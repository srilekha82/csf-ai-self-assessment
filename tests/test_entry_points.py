"""Smoke test of the command lines: every script starts, and the ones a run can use without PDFs, CSET or an agent do
their job end to end in a temp folder. The other unit tests call functions directly, so they miss a command line that
breaks at start-up (a wrong module name, a file read on import). Everything is written to temp folders."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT)


class CommandLines(unittest.TestCase):
    def test_every_script_starts(self):
        for path in sorted(SCRIPTS.glob("*.py")):
            with self.subTest(script=path.name):
                if '__name__ == "__main__"' in path.read_text():
                    r = run(path, "--help")
                    self.assertEqual(r.returncode, 0, r.stderr[-800:])
                    self.assertIn("usage", r.stdout.lower())
                else:   # imported only: it must import cleanly on its own
                    r = run("-c", f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import {path.stem}")
                    self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_a_client_run_from_intake_to_workbook(self):
        runs = Path(tempfile.mkdtemp())
        r = run(SCRIPTS / "intake.py", "write", "--org", "Smoke", "--sector", "1", "--certs", "1", "--ai-in-use", "1",
                "--date", "2026-11-24", "--runs-dir", runs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run_dir = runs / "Smoke_2026-11-24"
        r = run(SCRIPTS / "compute_scope.py", run_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads((run_dir / "csf_scope.json").read_text()))
        draft = run_dir / "csf_questions_draft.json"
        draft.write_text(json.dumps([{"subcategory_id": "GV.OC-01", "function": "GV", "outcome": "o",
                                      "question_type": "full_discovery", "evidence_prompt": "e", "confidence_flag": "",
                                      "questions": [{"question_text": "How is the mission used?", "source_reference": "s"}]}]))
        r = run(SCRIPTS / "write_questionnaire.py", draft, run_dir / "questionnaire.xlsx")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((run_dir / "questionnaire.xlsx").is_file())

    def test_the_csf_bank_build_and_its_check(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "cset_candidates.json").write_text(json.dumps({"cset_commit": "abc", "questions": {}, "mappings": [],
                                                              "csf2_set": {}}))
        banks = tmp / "banks"
        r = run(SCRIPTS / "build_csf_bank.py", "--cache-dir", tmp, "--output-dir", banks)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run(SCRIPTS / "build_csf_bank.py", "--cache-dir", tmp, "--output-dir", banks, "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("identical", r.stdout)
        bank = next(banks.glob("question_bank_*.json"))
        bank.write_text(json.dumps(dict(json.loads(bank.read_text()), cset_commit="other")))
        r = run(SCRIPTS / "build_csf_bank.py", "--cache-dir", tmp, "--output-dir", banks, "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cset_commit", r.stdout)


if __name__ == "__main__":
    unittest.main()
