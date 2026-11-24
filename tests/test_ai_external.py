"""Run: .venv/bin/python -m unittest discover -s tests -v

The External AI bank (scripts/ai_external.py): recording questions, assembling verdicts, the review sheet, completeness
and the writer's input. The bank is redirected to a temp dir; NIST's CSF -> CIS references and the CSF outcomes are
the real (read-only) reference files."""

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_fixture  # noqa: E402,F401  (the frozen AI data: tests/fixtures/ai/)
import ai_external as X  # noqa: E402
import prepare_ai_bank as P  # noqa: E402
from ai_bank_modules import R  # noqa: E402

THREAT = "Outside agents can sign in and call services on behalf of users at machine speed."
Q = "How do you tell when a sign-in comes from an automated agent acting for a user, and who reviews the limits?"


class ExternalBank(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, X, "AI_BANK_EXTERNAL", X.AI_BANK_EXTERNAL)
        R.AI_BANK_EXTERNAL = self.tmp / "external.json"
        R.AI_BUILD, R.AI_LOG_DIR = self.tmp / "build", self.tmp / "build" / "log"
        R.AI_BUILD.mkdir()
        self.inp = R.load_inputs()
        X.write_bank({"bank": "external", "subcategories": {"PR.AA-05": {"threat": THREAT},
                                                             "DE.AE-02": {"threat": THREAT + " Logs look routine."}}})

    def bank(self):
        return json.loads(X.AI_BANK_EXTERNAL.read_text())["subcategories"]

    def record(self, data, replace_human=False):
        f = self.tmp / "in.json"
        f.write_text(json.dumps(data))
        a = argparse.Namespace(file=str(f), model="test-model", session=None, replace_human=replace_human)
        try:
            R.record_ai("external", a)
            return 0
        except SystemExit as e:
            return e.code

    def entry(self, *texts, status="pass", **extra):
        return {"status": status, "turns": 1, "questions": [{"question_text": t} for t in texts], **extra}

    def test_cis_refs_and_order_come_from_nists_references(self):
        bank = self.bank()
        self.assertEqual(list(bank), ["PR.AA-05", "DE.AE-02"])                 # CSF order (PROTECT before DETECT)
        links = X.cis_links()
        self.assertEqual({r.split("-", 1)[1] for r in bank["DE.AE-02"]["cis_refs"]}, set(links["DE.AE-02"]))
        self.assertTrue(all(r.split("-")[0] in ("LLM", "MCP", "AGENT") for r in bank["PR.AA-05"]["cis_refs"]))

    def test_record(self):
        bad = {"unknown subcategory": {"GV.OC-01": self.entry(Q)},
               "three questions": {"PR.AA-05": self.entry(Q, Q + " (2)", Q + " (3)")},
               "no questions": {"PR.AA-05": self.entry()},
               "short": {"PR.AA-05": self.entry("How?")},
               "same twice": {"PR.AA-05": self.entry(Q, Q)},
               "extra field": {"PR.AA-05": {**self.entry(), "questions": [{"question_text": Q, "cis_refs": []}]}},
               "review without reasons": {"PR.AA-05": self.entry(Q, status="needs_human_review")},
               "turns": {"PR.AA-05": {**self.entry(Q), "turns": 3}}}
        for name, data in bad.items():
            self.assertEqual(self.record(data), 1, name)
        self.assertNotIn("questions", self.bank()["PR.AA-05"])                  # nothing stored
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q, Q + " Who owns it?")}), 0)
        self.assertEqual(self.record({"DE.AE-02": self.entry(Q, status="needs_human_review",
                                                             reasons={"1": "check 2: not the threat"})}), 0)
        bank = self.bank()
        self.assertEqual(len(bank["PR.AA-05"]["questions"]), 2)
        self.assertEqual(bank["DE.AE-02"]["review_reasons"], {"1": "check 2: not the threat"})
        self.assertTrue(bank["PR.AA-05"]["cis_refs"])
        doc = json.loads(X.AI_BANK_EXTERNAL.read_text())
        self.assertEqual(doc["guide_sha256_16"], {g: s["sha256_16"] for g, s in self.inp["sg_doc"]["sources"].items()})
        self.assertTrue(doc["built_on"] and doc["cis_links_sha256_16"])
        self.assertEqual(X.bank_freshness(doc)[0], True)
        self.assertEqual(X.stored_bank_problems(), [])

    def test_a_persons_decision_is_kept(self):
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 0)
        doc = json.loads(X.AI_BANK_EXTERNAL.read_text())
        doc["subcategories"]["PR.AA-05"]["decided_by"] = "human"
        X.AI_BANK_EXTERNAL.write_text(json.dumps(doc))
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 1)
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}, replace_human=True), 0)
        self.assertNotIn("decided_by", self.bank()["PR.AA-05"])

    def test_a_threat_needing_review_gets_questions_only_once_a_person_accepts_it(self):
        doc = json.loads(X.AI_BANK_EXTERNAL.read_text())
        doc["subcategories"]["PR.AA-05"].update({"status": "needs_human_review", "review_reasons": {"0": "check it"}})
        X.AI_BANK_EXTERNAL.write_text(json.dumps(doc))
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 1)          # not accepted yet
        lines = X.sheet_rows(doc)
        line = next(ln for ln in lines if ln["subcategory"] == "PR.AA-05")
        self.assertEqual((line["status"], line["review_reason"]), ("needs_human_review", "Whole subcategory: check it"))
        self.assertEqual(X.from_sheet(lines, doc)[1:], ([], 0))                # unchanged: still to review
        accepted = [dict(ln, status="pass") if ln is line else ln for ln in lines]
        new, problems, changed = X.from_sheet(accepted, doc)
        self.assertEqual((problems, changed), ([], 1))
        self.assertEqual(new["subcategories"]["PR.AA-05"]["status"], "pass")
        self.assertNotIn("review_reasons", new["subcategories"]["PR.AA-05"])
        X.AI_BANK_EXTERNAL.write_text(json.dumps(new))
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 0)          # accepted: questions may be written

    def test_completeness(self):
        doc = json.loads(X.AI_BANK_EXTERNAL.read_text())
        ok, text = X.bank_freshness(doc)
        self.assertFalse(ok)
        self.assertIn("2 of 2 subcategories without questions", text)
        doc["subcategories"]["PR.AA-05"]["cis_refs"] = []                   # NIST's references moved since
        self.assertIn("CIS safeguards changed: PR.AA-05", X.bank_freshness(doc)[1])

    def test_assemble_uses_the_external_checks(self):
        g1 = {"PR.AA-05": {"questions": [{"question_text": Q}]}}

        def verdicts(checks):
            return [{"subcategory_id": "PR.AA-05", "question_number": 1, "starts_with": Q[:30],
                     "checks": {c: "pass" for c in checks}, "reasons": {}},
                    {"subcategory_id": "PR.AA-05", "question_number": 0, "checks": {"complete": "pass"}, "reasons": {}}]
        def w(name, d):
            (self.tmp / name).write_text(json.dumps(d))
            return self.tmp / name
        out, gen1 = self.tmp / "record.json", w("g1.json", g1)
        with self.assertRaises(SystemExit):                                  # the AI RMF evaluator's nine checks
            R.assemble(gen1, w("e9.json", verdicts([str(n) for n in range(1, 10)])), None, None, out,
                       checks=X.EXTERNAL_CHECKS, rechecks=X.EXTERNAL_TURN_TWO_RECHECKS)
        R.assemble(gen1, w("e6.json", verdicts(X.EXTERNAL_CHECKS)), None, None, out,
                   checks=X.EXTERNAL_CHECKS, rechecks=X.EXTERNAL_TURN_TWO_RECHECKS)
        self.assertEqual(json.loads(out.read_text())["PR.AA-05"]["status"], "pass")
        self.assertEqual(self.record(json.loads(out.read_text())), 0)

    def test_review_sheet(self):
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 0)
        doc = json.loads(X.AI_BANK_EXTERNAL.read_text())
        lines = X.sheet_rows(doc)
        self.assertEqual([(ln["subcategory"], ln["q"]) for ln in lines], [("PR.AA-05", "1"), ("DE.AE-02", "")])
        self.assertEqual(X.from_sheet(lines, doc)[1:], ([], 0))                # unchanged round trip
        edit = lambda **kw: [dict(ln, **kw) if ln["subcategory"] == "PR.AA-05" else ln for ln in lines]  # noqa: E731
        new, problems, changed = X.from_sheet(edit(question_text=Q + " Where is it recorded?"), doc)
        self.assertEqual((problems, changed), ([], 1))
        self.assertEqual(new["subcategories"]["PR.AA-05"]["decided_by"], "human")
        added = lines + [dict(lines[0], subcategory="PR.AA-01", threat=THREAT, question_text="")]
        new, problems, changed = X.from_sheet(added, doc)                    # a new subcategory, questions to come
        self.assertEqual((problems, changed), ([], 1))
        self.assertTrue(new["subcategories"]["PR.AA-01"]["cis_refs"])
        self.assertNotIn("questions", new["subcategories"]["PR.AA-01"])
        bad = {"not linked to CIS by NIST": lines + [dict(lines[0], subcategory="GV.OC-01")],
               "two threats": lines + [dict(lines[1], threat="another threat that is long enough to pass")],
               "short threat": edit(threat="short")}
        for name, rows in bad.items():
            self.assertTrue(X.from_sheet(rows, doc)[1], name)
        new, problems, changed = X.from_sheet([ln for ln in lines if ln["subcategory"] != "DE.AE-02"], doc)
        self.assertEqual((problems, changed, list(new["subcategories"])), ([], 1, ["PR.AA-05"]))   # dropped

    def test_writer_input(self):
        self.inp["has_text"] = True   # the CIS text is local only; the input's structure is what is checked
        P.AI_WORK = self.tmp / "work"
        self.assertEqual(self.record({"PR.AA-05": self.entry(Q)}), 0)
        out = P.prepare_external(self.inp, [], missing_only=True, everything=False)
        doc = json.loads(out.read_text())
        self.assertEqual([i["subcategory_id"] for i in doc["items"]], ["DE.AE-02"])   # only the one without questions
        item = doc["items"][0]
        self.assertEqual(item["threat"], THREAT + " Logs look routine.")
        self.assertTrue(item["implementation_examples"] and item["outcome"])
        self.assertEqual([s["id"] for s in item["cis_safeguards"]], self.bank()["DE.AE-02"]["cis_refs"])
        self.assertEqual(doc["questions_per_subcategory"], {"min": 1, "max": 2})
        with self.assertRaises(SystemExit):
            P.prepare_external(self.inp, ["GV.OC-01"], False, False)


if __name__ == "__main__":
    unittest.main()
