"""The client-run picker (pick_questions.py, both frameworks) gives each client exactly the questions its intake
calls for. Runs intake, scope and the picker (both frameworks) on the committed banks for typical clients, then checks every pick
with the rules below. The picker is fixed rules, so this is checked here, once per code change, not in every run.

CSF:    every subcategory in scope has questions and none outside it; the right question type; GOVERN always asked in
        full; "confirm with evidence" questions flagged LOW; no blank, repeated or extra questions; every question from
        the bank, with CSET's own CSF 2.0 question kept; nothing worded for a certification the organisation lacks.
AI RMF: every question is in the bank; each is for a role, producer details and AI areas the organisation has; nothing
        the bank gives this organisation is missing.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from config import AI_QUESTION_BANKS, AI_SCOPE_RULES, CERT_LABELS, SCOPE_RULES, load_csf_intake  # noqa: E402
from pick_questions import ai_client_roles, ai_questions_for  # noqa: E402

CSF_DRAFT = "csf_questions_draft.json"
DETAIL_WORDS = {"built_on_existing_model": "built on an existing model", "given_to_others": "given to others"}


def load(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def entry_problems(sid: str, questions) -> list[str]:
    """Problems any entry can have: no questions, a blank one, one asked twice."""
    if not isinstance(questions, list) or not questions:
        return [f"{sid}: no questions"]
    texts = [str(q.get("question_text", "")).strip() for q in questions]
    problems = [f"{sid}: a blank question" for t in texts if not t]
    problems += [f"{sid}: question asked twice: {t[:60]!r}" for t in sorted(set(texts)) if t and texts.count(t) > 1]
    return problems


def check_csf(run_dir: Path) -> list[str]:
    draft = load(run_dir / CSF_DRAFT)
    scope = load(run_dir / "csf_scope.json")
    bank = load(run_dir / "csf_question_bank_used.json")
    if draft is None or scope is None or bank is None:
        return ["CSF: csf_questions_draft.json, csf_scope.json and csf_question_bank_used.json must all exist "
                "(run /csf-questionnaire)"]
    certs = load_csf_intake(run_dir)["certs"]
    max_questions = json.loads(SCOPE_RULES.read_text())["max_questions"]
    expected = {e["subcategory_id"]: e["question_type"] for e in scope if e["question_type"] != "skip"}
    got = {e["subcategory_id"]: e for e in draft}

    problems = [f"CSF {sid}: in scope ({qtype}) but missing" for sid, qtype in expected.items() if sid not in got]
    problems += [f"CSF {sid}: not in scope (or skip) but has questions" for sid in got if sid not in expected]
    not_held = [label for cert, label in CERT_LABELS.items() if cert not in certs]
    for sid, e in got.items():
        if sid not in expected:
            continue
        qtype, questions = e.get("question_type"), e.get("questions")
        problems += [f"CSF {p}" for p in entry_problems(sid, questions)]
        if qtype != expected[sid]:
            problems.append(f"CSF {sid}: question type {qtype}, scope says {expected[sid]}")
        if sid.startswith("GV.") and qtype != "full_discovery":
            problems.append(f"CSF {sid}: GOVERN must be full_discovery, not {qtype}")
        if qtype == "confirmatory" and not str(e.get("confidence_flag", "")).startswith("LOW"):
            problems.append(f"CSF {sid}: confirmatory without the LOW confidence flag")
        if not isinstance(questions, list):
            continue
        if qtype in max_questions and len(questions) > max_questions[qtype]:
            problems.append(f"CSF {sid}: {len(questions)} questions, at most {max_questions[qtype]} for {qtype}")
        candidates = bank["questions"].get(sid, {}).get("candidates", [])
        ids = {c.get("cset_question_id") for c in candidates}
        for q in questions:
            qid = q.get("cset_question_id")
            if qid is None and candidates:
                problems.append(f"CSF {sid}: generic fallback question although the bank has questions for it")
            elif qid is not None and qid not in ids:
                problems.append(f"CSF {sid}: question {qid} is not in the bank for this subcategory")
            text = str(q.get("question_text", ""))
            problems += [f"CSF {sid}: worded for {label}, which the organisation does not hold"
                         for label in not_held if f"Your {label}" in text]
        own = [c["cset_question_id"] for c in candidates if c.get("cset_set") == "NCSF_V2"]
        if own and own[0] not in {q.get("cset_question_id") for q in questions}:
            problems.append(f"CSF {sid}: CSET's own CSF 2.0 question ({own[0]}) is missing")
    return problems


def check_ai(run_dir: Path) -> list[str]:
    profile = load(run_dir / "ai_intake.json")
    if profile is None:
        return ["AI: ai_intake.json is missing (run the intake)"]
    roles = ai_client_roles(profile, json.loads(AI_SCOPE_RULES.read_text()))
    flags = [f for f, v in (profile.get("producer") or {}).items() if v]
    areas = profile["ai_areas"]
    problems = []
    for name in AI_QUESTION_BANKS:
        draft = load(run_dir / f"ai_questions_draft_{name}.json")
        bank = load(run_dir / f"ai_question_bank_used_{name}.json")
        if draft is None or bank is None:
            problems.append(f"AI {name}: ai_questions_draft_{name}.json and ai_question_bank_used_{name}.json must "
                            "both exist (run /ai-questionnaire)")
            continue
        subs = bank["subcategories"]
        got = {e["subcategory_id"]: e for e in draft}
        for sid, e in got.items():
            rec = subs.get(sid)
            if rec is None:
                problems.append(f"AI {name} {sid}: not a subcategory of the {name} bank")
                continue
            problems += [f"AI {name} {p}" for p in entry_problems(sid, e.get("questions"))]
            if e.get("question_type") != "full_discovery":
                problems.append(f"AI {name} {sid}: question type {e.get('question_type')}, must be full_discovery")
            in_bank = {q["question_text"]: q for q in rec["questions"]}
            for q in e.get("questions") or []:
                b = in_bank.get(q.get("question_text"))
                if b is None:
                    problems.append(f"AI {name} {sid}: question not in the bank: {str(q.get('question_text'))[:60]!r}")
                    continue
                if not set(b["roles"]) & set(roles):
                    problems.append(f"AI {name} {sid}: question for {b['roles']}, client is asked as {roles}")
                if not set(b["producer_flags"]) <= set(flags):
                    problems.append(f"AI {name} {sid}: question is for a producer whose model is "
                                    f"{' and '.join(DETAIL_WORDS.get(f, f) for f in b['producer_flags'])}, "
                                    "which this organisation did not say")
                rows = q.get("rows") or []
                if name == "areas":
                    foreign = [r for r in rows if r not in b.get("rows", []) or rec["rows"][r]["area"] not in areas]
                    if not rows or foreign:
                        problems.append(f"AI {name} {sid}: question covers no row, or rows outside the client's AI "
                                        f"areas {foreign}")
                elif rows:
                    problems.append(f"AI {name} {sid}: a foundation question must cover no area rows")
        for sid, rec in subs.items():   # nothing missing: what the bank gives this client is all there
            want = {q["question_text"] for q, _ in ai_questions_for(name, rec, roles, flags, areas)}
            have = {q.get("question_text") for q in (got.get(sid) or {}).get("questions") or []}
            if want - have:
                problems.append(f"AI {name} {sid}: {len(want - have)} question(s) the bank gives this client are missing")
    return problems


def script(name, *args):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / name), *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, f"{name}: " + r.stdout + r.stderr
    return r


# Typical clients: intake answers as menu numbers (see data/common/intake_options.json), and an optional SoA.
CLIENTS = {
    "no_cert_no_ai":   ["--sector", "5", "--certs", "1", "--ai-in-use", "1"],
    "iso_unsure_ai":   ["--sector", "2", "--certs", "2", "--ai-in-use", "3"],
    "pci_ai_user":     ["--sector", "1", "--certs", "3", "--ai-in-use", "2", "--role", "1", "--ai-usage", "1 4",
                        "--ai-components", "1"],
    "iso_pci_builder": ["--sector", "4", "--certs", "2 3", "--ai-in-use", "2", "--role", "2",
                        "--built-on-existing-model", "1", "--given-to-others", "1", "--ai-components", "3 4"],
    "iso_soa_both":    ["--sector", "3", "--certs", "2", "--ai-in-use", "2", "--role", "3",
                        "--built-on-existing-model", "2", "--given-to-others", "2", "--ai-usage", "3",
                        "--ai-components", "2"],
}
SOA = [{"control_id": "Annex A Controls: 5.1", "control_id_raw": "5.1", "applicable": True, "applicable_raw": "Yes",
        "exclusion_reason": None, "implemented": True},
       {"control_id": "Annex A Controls: 5.20", "control_id_raw": "5.20", "applicable": False, "applicable_raw": "No",
        "exclusion_reason": None, "implemented": None}]


def make_run(runs: Path, name: str) -> Path:
    script("intake.py", "write", "--org", name, *CLIENTS[name], "--date", "2026-11-17", "--runs-dir", runs)
    run = runs / f"{name}_2026-11-17"
    scope = ["compute_scope.py", run]
    if name == "iso_soa_both":
        (run / "soa_parsed.json").write_text(json.dumps(SOA))
    script(*scope)
    script("pick_questions.py", run, "--framework", "csf")
    script("pick_questions.py", run, "--framework", "ai")
    return run


class Picks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.runs = {name: make_run(cls.tmp / "runs", name) for name in CLIENTS}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_every_client_gets_exactly_its_questions(self):
        for name, run in self.runs.items():
            with self.subTest(client=name):
                self.assertEqual(check_csf(run), [])
                self.assertEqual(check_ai(run), [])

    def test_the_clients_differ(self):
        # guard against a check that passes on anything: the five clients really get different questionnaires
        sizes = {n: sum(len(e["questions"]) for b in AI_QUESTION_BANKS
                        for e in json.loads((r / f"ai_questions_draft_{b}.json").read_text())) for n, r in self.runs.items()}
        self.assertEqual(len(set(sizes.values())), len(sizes), sizes)
        types = {json.dumps(sorted((e["subcategory_id"], e["question_type"])
                                   for e in json.loads((r / "csf_scope.json").read_text()))) for r in self.runs.values()}
        self.assertGreaterEqual(len(types), 4)

    def test_the_checks_catch_a_wrong_pick(self):
        # the checks themselves must fail on a broken draft
        run = Path(tempfile.mkdtemp()) / "run"
        shutil.copytree(self.runs["iso_pci_builder"], run)
        csf = json.loads((run / CSF_DRAFT).read_text())
        csf.pop(0)
        gv = next(e for e in csf if e["subcategory_id"].startswith("GV."))
        gv["question_type"] = "gap"
        (run / CSF_DRAFT).write_text(json.dumps(csf))
        text = "\n".join(check_csf(run))
        self.assertIn("in scope", text)
        self.assertIn("GOVERN must be full_discovery", text)
        ai = json.loads((run / "ai_questions_draft_foundation.json").read_text())
        ai[0]["questions"].pop()
        ai[1]["questions"][0]["question_text"] = "Made-up question?"
        (run / "ai_questions_draft_foundation.json").write_text(json.dumps(ai))
        text = "\n".join(check_ai(run))
        self.assertIn("are missing", text)
        self.assertIn("not in the bank", text)


if __name__ == "__main__":
    unittest.main()
