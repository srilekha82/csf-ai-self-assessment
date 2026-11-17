"""check_questionnaire.py on a real run (intake, scope and both pickers on the committed banks), then on broken drafts."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import check_questionnaire as CQ  # noqa: E402


def script(name, *args):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / name), *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


class CheckQuestionnaire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        # a financial org with PCI DSS that builds and uses AI: customer-facing, vendor AI, MCP tools
        script("intake.py", "write", "--org", "Testbank", "--domain", "1", "--certs", "3", "--ai-in-use", "2",
               "--role", "3", "--built-on-model", "1", "--given-to-others", "2", "--ai-usage", "3 4",
               "--ai-components", "2", "--csf-assessment-done", "1", "--iso42001-held", "2",
               "--date", "2026-11-17", "--runs-dir", cls.tmp / "runs")
        cls.clean = cls.tmp / "runs" / "Testbank_2026-11-17"
        for step in ("compute_scope.py", "build_questions.py", "build_ai_questions.py"):
            script(step, cls.clean)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def setUp(self):
        self.run = Path(tempfile.mkdtemp()) / "run"
        shutil.copytree(self.clean, self.run)

    def edit(self, name, change):
        path = self.run / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def problems(self, framework):
        return CQ.check_csf(self.run) if framework == "csf" else CQ.check_ai(self.run)

    def test_a_fresh_run_passes(self):
        self.assertEqual(self.problems("csf"), [])
        self.assertEqual(self.problems("ai"), [])

    def test_csf_missing_entry_wrong_type_and_missing_flag_are_caught(self):
        def change(d):
            d.pop(0)                                                  # a subcategory in scope disappears
            gv = next(e for e in d if e["subcategory_id"].startswith("GV."))
            gv["question_type"] = "gap"                               # GOVERN must be full_discovery
            conf = next(e for e in d if e["question_type"] == "confirmatory")
            conf["confidence_flag"] = ""                              # confirmatory must be flagged LOW
        self.edit("csf_questions_draft.json", change)
        text = "\n".join(self.problems("csf"))
        self.assertIn("in scope", text)
        self.assertIn("GOVERN must be full_discovery", text)
        self.assertIn("without the LOW confidence flag", text)

    def test_csf_question_not_in_bank_repeated_or_wrong_certification_is_caught(self):
        def change(d):
            e = next(e for e in d if len(e["questions"]) > 1)
            e["questions"][1] = dict(e["questions"][1], cset_question_id=999999999)
            e["questions"][0]["question_text"] = "Your ISO 27001 certification should cover this."
            e["questions"].append(dict(e["questions"][-1]))           # the last question, asked again
        self.edit("csf_questions_draft.json", change)
        text = "\n".join(self.problems("csf"))
        self.assertIn("not in the bank", text)
        self.assertIn("asked twice", text)
        self.assertIn("worded for ISO 27001", text)

    def test_ai_question_missing_or_not_in_bank_is_caught(self):
        def change(d):
            d[0]["questions"].pop()                                   # a question the bank gives the client is gone
            d[1]["questions"][0]["question_text"] = "Made-up question?"
        self.edit("ai_questions_draft_foundation.json", change)
        text = "\n".join(self.problems("ai"))
        self.assertIn("are missing", text)
        self.assertIn("not in the bank", text)

    def test_ai_question_for_an_area_the_client_does_not_have_is_caught(self):
        usage = json.loads((self.run / "ai_usage.json").read_text())
        usage["ai_areas"] = [a for a in usage["ai_areas"] if a != "customer_facing"]
        (self.run / "ai_usage.json").write_text(json.dumps(usage))   # the drafts still hold customer-facing rows
        self.assertIn("outside the client's AI areas", "\n".join(self.problems("ai")))

    def test_cli_exits_1_and_lists_problems(self):
        self.edit("csf_questions_draft.json", lambda d: d.pop(0))
        r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_questionnaire.py"), str(self.run)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("problem(s)", r.stdout)


if __name__ == "__main__":
    unittest.main()
