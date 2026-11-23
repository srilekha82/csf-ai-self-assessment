"""Data checks: the committed data, not the code. Run them at the end-to-end step, after the banks are (re)built:
    .venv/bin/python -m unittest discover -s tests -p "check_*.py"
They fail while a bank is missing or two data files disagree. The unit tests (test_*.py) must pass on every change.
check_picks.py, the other data check, runs typical clients through the client scripts on the committed banks."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_bank_age as BA  # noqa: E402
import config as OPT  # noqa: E402
import sheet_io as S  # noqa: E402
import write_questionnaire as WQ  # noqa: E402
from config import AI_AREAS, AI_AREAS_XLSX, AI_SCOPE_RULES  # noqa: E402


class Options(unittest.TestCase):
    """The intake menus, the AI area rules, the CSF scope rules and the certification files agree."""

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

    def test_every_sector_has_its_bumps_and_every_cert_a_file(self):
        bumps = json.loads(OPT.SCOPE_RULES.read_text())["sector_bumps"]
        self.assertEqual(set(bumps) - {"description"}, set(OPT.SECTORS))
        menu = [o["value"] for o in next(q for q in OPT.INTAKE_QUESTIONS if q["key"] == "certs")["options"]]
        self.assertEqual(set(OPT.CERT_FILES), set(menu) - {"none"})


class CommittedBanks(unittest.TestCase):
    def test_the_committed_banks_have_a_build_date_and_the_limits_exist(self):
        from config import METADATA, bank_path
        limits = json.loads(METADATA.read_text())["question_banks"]
        self.assertEqual(BA.bank_problems("finance", limits={"csf_max_age_days": 10**6, "ai_max_age_days": 10**6},
                                          csf_file=bank_path("finance")), [])
        self.assertTrue({"csf_max_age_days", "ai_max_age_days"} <= set(limits))


class AiAreasSpreadsheet(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.json, xlsx = self.tmp / "a.json", self.tmp / "a.xlsx"
        shutil.copy(AI_AREAS_XLSX, xlsx)
        S.import_sheet(S.load_spec("ai_areas"), xlsx, self.json, self.tmp / "audit.jsonl")

    def test_committed_json_is_the_import_of_the_committed_spreadsheet(self):
        committed = json.loads(AI_AREAS.read_text())
        self.assertEqual(committed["source_sha"], S.audit.sha(AI_AREAS_XLSX))
        self.assertEqual(json.loads(self.json.read_text())["ai_areas"], committed["ai_areas"])
        ids = [a["id"] for a in committed["ai_areas"]]
        self.assertEqual(len(ids), len(set(ids)))


class QuestionnaireTemplate(unittest.TestCase):
    """The questionnaire template is laid out by hand in Excel: fail if it drifts from the data it shows."""

    def test_the_template_matches_the_data(self):
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
