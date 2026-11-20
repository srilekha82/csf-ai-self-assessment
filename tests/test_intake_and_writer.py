"""Run: .venv/bin/python -m unittest discover -s tests -v

The intake (numbers -> values), the shared options and the workbook writer. Everything is written to a temp dir."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import intake as IN  # noqa: E402
import config as OPT  # noqa: E402
import write_questionnaire as WQ  # noqa: E402
from config import AI_AREAS, AI_SCOPE_RULES  # noqa: E402


def args(**over):
    base = dict(replace=False, org="Acme Corp", domain="1", certs="2 3", ai_in_use="2", role="1",
                built_on_existing_model=None, given_to_others=None, ai_usage="1 3", ai_components="2", date="2026-10-14", runs_dir=None)
    base.update(over)
    return type("A", (), base)()


class Options(unittest.TestCase):
    def test_every_ai_area_is_reachable(self):
        # every AI area comes from a menu or ai_area_rules; automatic ones (always, any_ai) are never also on a menu.
        # A with-rule may add a menu item too (agents add MCP / tools, which can also be ticked).
        areas = {a["id"] for a in json.loads(AI_AREAS.read_text())["ai_areas"]}
        menu = {q["key"]: [o["value"] for o in q["options"]] for q in OPT.INTAKE_QUESTIONS}
        r = json.loads(AI_SCOPE_RULES.read_text())["ai_area_rules"]
        menus, auto = set(menu["ai_usage"]) | set(menu["ai_components"]), set(r["always"]) | set(r["any_ai"])
        added = {a for adds in list(r["with"].values()) + list(r["role"].values()) for a in adds}
        self.assertEqual(menus | auto | added, areas)
        self.assertFalse(menus & auto)
        self.assertTrue(set(r["role"]) <= set(menu["role"]))
        self.assertTrue(set(r["with"]) <= areas)

    def test_client_roles_cover_every_answer_and_only_known_roles(self):
        rules, qrules = json.loads(AI_SCOPE_RULES.read_text()), json.loads(OPT.AI_QUESTION_RULES.read_text())
        menu = {q["key"]: [o["value"] for o in q["options"]] for q in OPT.INTAKE_QUESTIONS}
        roles = {k: v for k, v in rules["client_roles"].items() if k != "description"}
        self.assertEqual(set(roles), set(menu["role"]) | {"none", "unsure"})
        self.assertTrue({r for v in roles.values() for r in v} <= set(qrules["roles"]))

    def test_every_domain_has_a_weight_key_and_every_cert_a_file(self):
        self.assertEqual(set(OPT.WEIGHT_KEY), set(OPT.DOMAINS))
        menu = [o["value"] for o in next(q for q in OPT.INTAKE_QUESTIONS if q["key"] == "certs")["options"]]
        self.assertEqual(set(OPT.CERT_FILES), set(menu) - {"none"})


class Intake(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def go(self, **over):
        a = args(runs_dir=str(self.tmp), **over)
        try:
            IN.write(a)
            return 0
        except SystemExit as e:
            return e.code

    def run_dir(self):
        return self.tmp / "Acme_Corp_2026-10-14"

    def usage(self):
        return json.loads((self.run_dir() / "ai_intake.json").read_text())

    def test_numbers_become_the_csf_and_ai_answers(self):
        self.assertEqual(self.go(), 0)
        intake = json.loads((self.run_dir() / "csf_intake.json").read_text())
        self.assertEqual((intake["domain"], intake["certs"]), ("finance", ["iso27001", "pci_dss"]))
        usage = self.usage()
        self.assertEqual(usage["ai_areas"], ["internal_process", "customer_facing", "invisible_usage", "input", "output",
                                             "mcp_tools"])
        self.assertEqual((usage["role"], usage["producer"]), ("consumer", None))
        self.assertEqual(set(usage), {"ai_in_use", "role", "producer", "ai_areas"})

    def test_no_ai_keeps_only_invisible_usage(self):
        self.assertEqual(self.go(ai_in_use="1", role=None, ai_usage=None, ai_components=None, certs="3"), 0)
        usage = self.usage()
        self.assertEqual(usage["ai_areas"], ["invisible_usage"])
        self.assertEqual((usage["role"], usage["producer"]), (None, None))

    def test_producer_and_agents_bring_their_areas(self):
        # build, built on an existing model, not given to others; agents and a hosted model
        self.assertEqual(self.go(role="2", built_on_existing_model="1", given_to_others="2", ai_usage="", ai_components="3 4"), 0)
        usage = self.usage()
        for area in ("model_building", "model", "test_tuning_data", "agent", "mcp_tools", "hosting"):
            self.assertIn(area, usage["ai_areas"])
        self.assertEqual(usage["producer"], {"built_on_existing_model": True, "given_to_others": False})
        self.assertEqual(usage["role"], "producer")

    def test_both_keeps_the_usage_areas_and_adds_the_producer_ones(self):
        self.assertEqual(self.go(role="3", built_on_existing_model="2", given_to_others="1"), 0)
        usage = self.usage()
        self.assertEqual(usage["role"], "both")
        self.assertTrue({"internal_process", "customer_facing", "model_building", "model"} <= set(usage["ai_areas"]))
        self.assertEqual(usage["producer"], {"built_on_existing_model": False, "given_to_others": True})

    def test_blank_menus_are_allowed(self):
        self.assertEqual(self.go(ai_usage="", ai_components=""), 0)
        usage = self.usage()
        self.assertEqual(usage["ai_areas"], ["invisible_usage", "input", "output"])
        self.assertEqual(usage["role"], "consumer")

    def test_bad_input_is_rejected_and_writes_nothing(self):
        for bad in (dict(domain="9"), dict(domain="x"), dict(domain="1 2"), dict(certs="1 2"), dict(certs=""),
                    dict(ai_usage="9"), dict(ai_components="1 7"), dict(role=None), dict(role="4"),
                    dict(built_on_existing_model="1"),                        # producer follow-up for a consumer
                    dict(role="2", built_on_existing_model=None, given_to_others="2"),  # follow-up missing for a producer
                    dict(ai_in_use="1"),                                      # questions answered without "some"
                    dict(ai_in_use="3", role=None, ai_usage=None, ai_components="1"),
                    dict(org="!!!"), dict(date="2026-13-01")):
            self.assertEqual(self.go(**bad), 1, bad)
            self.assertFalse(self.run_dir().exists(), bad)

    def test_an_existing_intake_is_not_overwritten_without_replace(self):
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.go(domain="2"), 1)
        self.assertEqual(json.loads((self.run_dir() / "csf_intake.json").read_text())["domain"], "finance")
        self.assertEqual(self.go(domain="2", replace=True), 0)
        self.assertEqual(json.loads((self.run_dir() / "csf_intake.json").read_text())["domain"], "healthcare")

    def test_downstream_scripts_find_domain_and_certs(self):
        self.go()
        self.assertEqual(OPT.load_csf_intake(self.run_dir())["certs"], ["iso27001", "pci_dss"])
        with self.assertRaises(SystemExit):
            OPT.load_csf_intake(self.tmp / "missing")


class SoaReadingRecord(unittest.TestCase):
    """compute_scope.py records the agent's SoA reading (soa_judgements.json) once, the first time it uses it."""

    def scope(self, *more):
        p = __import__("subprocess").run([sys.executable, str(ROOT / "scripts" / "compute_scope.py"), str(self.run), *more],
                                         capture_output=True, text=True)
        return p.returncode

    def test_the_reading_needs_a_model_and_is_recorded_once(self):
        runs = Path(tempfile.mkdtemp())
        IN.write(args(runs_dir=str(runs), certs="2", ai_in_use="1", role=None, ai_usage=None, ai_components=None))
        self.run = runs / "Acme_Corp_2026-10-14"
        (self.run / "soa_parsed.json").write_text(json.dumps([
            {"control_id": "Annex A Controls: 5.20", "control_id_raw": "5.20", "applicable": False,
             "applicable_raw": "No", "exclusion_reason": None, "implemented": None}]))
        self.assertEqual(self.scope(), 2)                                   # the exclusion needs an agent reading
        (self.run / "soa_judgements.json").write_text(json.dumps(
            {"Annex A Controls: 5.20": {"exclusion_class": "not_relevant", "reason": "No suppliers handle data."}}))
        self.assertEqual(self.scope(), 1)                                   # used for the first time: --model needed
        self.assertFalse((self.run / "csf_scope.json").exists())
        self.assertEqual(self.scope("--model", "test-model"), 0)
        records = list((self.run / "judgement_log").glob("*_soa_exclusions.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["model"], "test-model")
        self.assertEqual(self.scope(), 0)                                   # already recorded: no model, no new record
        self.assertEqual(len(list((self.run / "judgement_log").glob("*_soa_exclusions.json"))), 1)


class EvidenceLoop(unittest.TestCase):
    """record_csf_bank.py evidence: round 1, one revision, then a person; a person's decision is final."""

    def setUp(self):
        import record_csf_bank as RC
        self.RC, tmp = RC, Path(tempfile.mkdtemp())
        targets = list(RC.evidence_targets()) or ["PR.AA-03", "PR.AA-04"]
        self.a, self.b = sorted(targets)[:2] if len(targets) >= 2 else ("PR.AA-03", "PR.AA-04")
        core = json.loads(RC.CSF_CORE.read_text())
        others = {s["subcategory_id"]: "x" * 40 for s in core["subcategories"]
                  if s["subcategory_id"] not in (self.a, self.b)}
        (tmp / "evidence_prompts.json").write_text(json.dumps({"default": "d", "by_category": {}, "by_subcategory": others}))
        for name, value in (("EVIDENCE_PROMPTS", tmp / "evidence_prompts.json"), ("BANK_BUILD", tmp),
                            ("EVIDENCE_INPUT", tmp / "evidence_input.json"), ("EVIDENCE_REVISE", tmp / "evidence_revise.json"),
                            ("EVIDENCE_REVIEW", tmp / "evidence_review.json")):
            self.addCleanup(setattr, RC, name, getattr(RC, name))
            setattr(RC, name, value)
        self.tmp = tmp

    def record(self, prompts, verdicts, *more):
        (self.tmp / "p.json").write_text(json.dumps(prompts))
        (self.tmp / "v.json").write_text(json.dumps(verdicts))
        self.RC.evidence_record([str(self.tmp / "p.json"), "--review", str(self.tmp / "v.json"), "--model", "m", *more])

    def test_a_failure_is_revised_once_then_decided_by_a_person(self):
        good = "The latest record of this outcome, with the systems it covers and when it was last reviewed."
        self.RC.evidence_prepare()
        self.assertEqual(len(json.loads(self.RC.EVIDENCE_INPUT.read_text())["items"]), 2)
        self.record({self.a: good, self.b: good}, [{"subcategory_id": self.a, "verdict": "pass"},
                                                   {"subcategory_id": self.b, "verdict": "fail", "reason": "generic"}])
        self.assertEqual(list(self.RC.evidence_targets()), [self.b])
        with self.assertRaises(SystemExit):                       # the revision round is not finished
            self.RC.evidence_prepare()
        with self.assertRaises(SystemExit):                       # a revision must cover only the failed ones
            self.record({self.a: good}, [{"subcategory_id": self.a, "verdict": "pass"}], "--revision")
        self.record({self.b: good + " Revised."}, [{"subcategory_id": self.b, "verdict": "fail", "reason": "still"}],
                    "--revision")
        review = json.loads(self.RC.EVIDENCE_REVIEW.read_text())
        self.assertEqual([len(i["drafts"]) for i in review["items"]], [2])
        with self.assertRaises(SystemExit):                       # the person has not decided yet
            self.RC.evidence_reviewed()
        review["items"][0]["keep_category_line"] = True
        self.RC.EVIDENCE_REVIEW.write_text(json.dumps(review))
        self.RC.evidence_reviewed()
        doc = json.loads(self.RC.EVIDENCE_PROMPTS.read_text())
        self.assertEqual((doc["by_subcategory"][self.a], list(doc["category_line_kept"])), (good, [self.b]))
        self.assertEqual(self.RC.evidence_targets(), {})          # never asked again
        self.assertFalse(self.RC.EVIDENCE_REVIEW.exists())


class Metadata(unittest.TestCase):
    def test_a_refresh_updates_only_the_files_parsed(self):
        import parse_csf_source as PC
        from datetime import date
        path = Path(tempfile.mkdtemp()) / "metadata.json"
        old = {"last_refreshed": "2020-01-01", "is_placeholder": True, "record_count": None, "notes": "n"}
        path.write_text(json.dumps({"csf2_core.json": dict(old), "other.json": dict(old)}))
        PC.record_refresh(path, {"csf2_core.json": 106})
        doc = json.loads(path.read_text())
        self.assertEqual(doc["csf2_core.json"], {"last_refreshed": date.today().isoformat(), "is_placeholder": False,
                                                  "record_count": 106, "notes": "n"})
        self.assertEqual(doc["other.json"], old)
        self.assertIn("not recorded", PC.record_refresh(path.parent / "missing.json", {"x": 1}))


class CsetCsf2Set(unittest.TestCase):
    """CSET's own CSF 2.0 set (NCSF_V2) is replayed from the migrations and leads every subcategory in the bank."""
    SQL = [
        "INSERT INTO [dbo].[NEW_REQUIREMENT] ([Requirement_Id], [Requirement_Title], [Requirement_Text]) "
        "VALUES (10, N'ID.AM-01', N'Inventories of hardware are maintained')",
        "INSERT INTO [dbo].[NEW_REQUIREMENT] ([Requirement_Id], [Requirement_Title], [Requirement_Text]) "
        "VALUES (11, N'GV.OV-01', N'Outcomes are reviewed')",
        "INSERT INTO [dbo].[NEW_REQUIREMENT] ([Requirement_Id], [Requirement_Title], [Requirement_Text]) "
        "VALUES (12, N'ID.AM-1', N'CSF 1.1 numbering')",
        "INSERT INTO [dbo].[NEW_QUESTION] ([Question_Id], [Std_Ref], [Simple_Question]) "
        "VALUES (1, 'x', N'The organization maintains inventories of hardware (ID.AM-01).')",
        "INSERT INTO [dbo].[NEW_QUESTION] ([Question_Id], [Std_Ref], [Simple_Question]) VALUES (2, 'x', N'Old text?')",
        "INSERT INTO [dbo].[NEW_QUESTION] ([Question_Id], [Std_Ref], [Simple_Question]) VALUES (3, 'x', N'Gone?')",
        "UPDATE [dbo].[NEW_QUESTION] SET [Simple_Question]=N'Are outcomes reviewed (GV.OV-01)?' WHERE [Question_Id] = 2",
        "INSERT INTO [dbo].[REQUIREMENT_QUESTIONS_SETS] ([Question_Id], [Set_Name], [Requirement_Id]) "
        "VALUES (1, N'NCSF_V2', 12)",
        "UPDATE [dbo].[REQUIREMENT_QUESTIONS_SETS] SET [Requirement_Id]=10 WHERE [Question_Id] = 1 AND [Set_Name] = N'NCSF_V2'",
        "INSERT INTO [dbo].[REQUIREMENT_QUESTIONS_SETS] ([Question_Id], [Set_Name], [Requirement_Id]) "
        "VALUES (2, N'NCSF_V2', 11)",
        "INSERT INTO [dbo].[REQUIREMENT_QUESTIONS_SETS] ([Question_Id], [Set_Name], [Requirement_Id]) "
        "VALUES (3, N'NCSF_V2', 11)",
        "DELETE FROM [dbo].[REQUIREMENT_QUESTIONS_SETS] WHERE [Question_Id] = 3 AND [Set_Name] = N'NCSF_V2'",
        "INSERT INTO [dbo].[REQUIREMENT_QUESTIONS_SETS] ([Question_Id], [Set_Name], [Requirement_Id]) "
        "VALUES (3, N'NCSF_V1', 12)",
    ]

    def test_links_are_replayed_and_the_reference_suffix_dropped(self):
        import extract_cset_candidates as EX
        got = EX.extract_csf2_set(self.SQL)
        self.assertEqual(got, {
            "GV.OV-01": {"questions": [{"question_id": 2, "question_text": "Are outcomes reviewed?"}]},
            "ID.AM-01": {"questions": [{"question_id": 1, "question_text": "The organization maintains inventories of hardware."}]},
        })

    def test_the_csf2_question_leads_and_a_duplicate_maturity_question_is_dropped(self):
        import build_question_bank as BQ
        active = {s: {"subcategory_text": s} for s in ("GV.OV-01", "ID.AM-01", "RS.MA-02")}
        candidates = {"cset_commit": "c", "questions": {"7": {"question_text": "Are outcomes reviewed?"},
                                                        "8": {"question_text": "Is the board told?"}},
                      "csf2_set": {"GV.OV-01": {"questions": [{"question_id": 2, "question_text": "Are outcomes reviewed?"}]}}}
        routed = [{"qid": q, "subcategory_id": "GV.OV-01", "status": "accept", "decided_by": "schema",
                   "text": candidates["questions"][q]["question_text"]} for q in ("7", "8")]
        bank = BQ.build_bank("finance", routed, candidates, active, {}, 0)
        got = [(c["cset_question_id"], c.get("cset_set")) for c in bank["questions"]["GV.OV-01"]["candidates"]]
        self.assertEqual(got, [(2, "NCSF_V2"), (8, None)])
        self.assertEqual((bank["with_candidates"], bank["with_maturity_questions"], bank["empty"]), (1, 1, 2))


class CsfEvidencePrompts(unittest.TestCase):
    def test_a_subcategory_prompt_wins_over_the_category_line(self):
        import build_questions as BQ
        old = BQ.EVIDENCE
        try:
            BQ.EVIDENCE = {"default": "d", "by_category": {"PR.DS": "cat"}, "by_subcategory": {"PR.DS-11": "own"}}
            self.assertEqual((BQ.evidence_prompt("PR.DS-11"), BQ.evidence_prompt("PR.DS-01"), BQ.evidence_prompt("XX.YY-01")),
                             ("own", "cat", "d"))
        finally:
            BQ.EVIDENCE = old

    def test_the_writer_file_and_the_review_are_validated_together(self):
        import record_csf_bank as RC
        ok = "The backup schedule for critical data and the latest restore test result."
        self.assertEqual(RC.validate_evidence({"PR.DS-11": ok}, [{"subcategory_id": "PR.DS-11", "verdict": "pass"}],
                                              {"PR.DS-11"}), [])
        errs = RC.validate_evidence({"PR.DS-11": "short", "ZZ.ZZ-01": ok}, [{"subcategory_id": "PR.DS-11", "verdict": "fail"}],
                                    {"PR.DS-11"})
        self.assertTrue(any("ZZ.ZZ-01" in e for e in errs) and any("30 to 400" in e for e in errs)
                        and any("a fail needs a reason" in e or "exactly one verdict" in e for e in errs))


class Workbook(unittest.TestCase):
    def entries(self, function, sid, text, **extra):
        return [{"subcategory_id": sid, "function": function, "outcome": "o", "question_type": "full_discovery",
                 "questions": [{"question_text": text, "source_reference": "s"}], "evidence_prompt": "ep",
                 "confidence_flag": "", **extra}]

    def visible(self, wb):
        return [s.title for s in wb if s.sheet_state == "visible"]

    def write(self, framework, *files, out):
        argv = ["x", *map(str, files), str(out)] + (["--framework", framework] if framework != "csf" else [])
        sys.argv = argv
        WQ.main()

    def test_either_sheet_can_be_rewritten_without_losing_the_other(self):
        import openpyxl
        tmp = Path(tempfile.mkdtemp())
        csf, ai, out = tmp / "csf.json", tmp / "ai.json", tmp / "questionnaire.xlsx"
        csf.write_text(json.dumps(self.entries("GV", "GV.RM-01", "How is risk managed?")))
        ai.write_text(json.dumps(self.entries("GOVERN", "GOVERN 1.1", "How is AI governed?", bank="consumer")))
        self.write("ai", ai, out=out)       # AI first
        self.write("csf", csf, out=out)     # then CSF: used to wipe the AI sheet
        self.write("csf", csf, out=out)     # and a CSF re-run must keep it
        wb = openpyxl.load_workbook(out)
        self.assertEqual(self.visible(wb), ["CSF Questionnaire", "AI RMF Questionnaire"])
        self.assertEqual(wb["AI RMF Questionnaire"].max_row, 2)
        self.assertEqual(wb["CSF Questionnaire"].max_row, 2)

    def test_the_ai_system_inventory_sheet_shows_only_when_asked(self):
        import openpyxl
        from config import AI_QUESTION_RULES
        tmp = Path(tempfile.mkdtemp())
        ai, out = tmp / "ai.json", tmp / "questionnaire.xlsx"
        ai.write_text(json.dumps(self.entries("GOVERN", "GOVERN 1.1", "How is AI governed?", bank="foundation")))
        self.write("ai", ai, out=out)
        inv = json.loads(AI_QUESTION_RULES.read_text())["ai_system_inventory"]
        self.assertEqual(self.visible(openpyxl.load_workbook(out)), ["CSF Questionnaire", "AI RMF Questionnaire"])
        ai.write_text(json.dumps(self.entries("GOVERN", inv["subcategory"], "In the AI systems sheet, list ...",
                                              bank="foundation")))
        self.write("ai", ai, out=out)                                    # a re-run that asks it shows the sheet again
        wb = openpyxl.load_workbook(out)
        self.assertEqual(self.visible(wb), ["CSF Questionnaire", "AI RMF Questionnaire", inv["sheet"]])
        ws = wb[inv["sheet"]]
        hidden = [c.value for c in ws[2] if ws.column_dimensions[c.column_letter].hidden]
        self.assertEqual(hidden, [])                                      # no ai_intake.json: treated as unsure, all shown

    def area_columns_shown(self, usage):
        import openpyxl
        from config import AI_AREA_LABELS, AI_QUESTION_RULES
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ai_intake.json").write_text(json.dumps(usage))
        inv = json.loads(AI_QUESTION_RULES.read_text())["ai_system_inventory"]
        ai, out = tmp / "ai.json", tmp / "questionnaire.xlsx"
        ai.write_text(json.dumps(self.entries("GOVERN", inv["subcategory"], "In the AI systems sheet, list ...",
                                              bank="foundation")))
        self.write("ai", ai, out=out)
        ws = openpyxl.load_workbook(out)[inv["sheet"]]
        labels = json.loads(AI_AREA_LABELS.read_text())["labels"]
        return {c.value for c in ws[2] if c.value in labels.values() and not ws.column_dimensions[c.column_letter].hidden}

    def test_the_ai_systems_sheet_shows_only_the_clients_ai_areas(self):
        from config import AI_AREA_LABELS
        labels = json.loads(AI_AREA_LABELS.read_text())["labels"]
        some = {"ai_in_use": "some", "ai_areas": ["customer_facing", "invisible_usage"]}
        self.assertEqual(self.area_columns_shown(some), {labels["customer_facing"], labels["invisible_usage"]})
        self.assertEqual(self.area_columns_shown({"ai_in_use": "unsure", "ai_areas": ["invisible_usage"]}),
                         set(labels.values()))                            # unsure: all, to find out what AI it has

    def test_the_template_matches_the_data(self):
        """The questionnaire template is laid out by hand in Excel: fail if it drifts from the data it shows."""
        import openpyxl
        from config import AI_AREAS, AI_AREA_LABELS, AI_QUESTION_RULES, QUESTIONNAIRE_TEMPLATE
        wb = openpyxl.load_workbook(QUESTIONNAIRE_TEMPLATE)
        for framework, spec in WQ.FRAMEWORKS.items():
            heads = {c.value for c in wb[spec["sheet"]][1]}
            self.assertLessEqual(set(WQ.row_values(framework, {}, 0, {})) | {"Answer", "Evidence"}, heads, framework)
        inv = json.loads(AI_QUESTION_RULES.read_text())["ai_system_inventory"]
        labels = json.loads(AI_AREA_LABELS.read_text())["labels"]
        areas = [labels[a["id"]] for a in json.loads(AI_AREAS.read_text())["ai_areas"]]
        ws = wb[inv["sheet"]]
        self.assertEqual(ws["A1"].value, inv["instructions"])
        self.assertEqual([c.value for c in ws[2]], [inv["system_column"], *areas, *inv["criticality"]])
        from openpyxl.utils.cell import range_boundaries
        bounds = [(range_boundaries(str(dv.sqref)), dv) for dv in ws.data_validations.dataValidation]
        lists = {b[0]: dv.formula1.strip('"').split(",") for b, dv in bounds}
        self.assertEqual([lists[c] for c in range(2, 2 + len(areas))], [["Yes"]] * len(areas))
        self.assertEqual([lists[2 + len(areas) + i] for i in range(len(inv["criticality"]))],
                         list(inv["criticality"].values()))
        self.assertEqual({b[3] for b, _ in bounds}, {2 + inv["rows"]})

if __name__ == "__main__":
    unittest.main()
