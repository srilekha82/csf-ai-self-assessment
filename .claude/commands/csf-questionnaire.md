# /csf-questionnaire — CSF 2.0 questions for an engagement

Argument: the run folder (`runs/<Org>_<date>`, created by `/generate-questions` or `scripts/intake.py`). Reads its
`intake.json`; writes `csf_scope.json`, `csf_questions_draft.json` and the CSF sheet of `questionnaire.xlsx`. Uses the
CSF bank for the domain in the repo (built by `/build-csf-bank`).

Tools: Bash, Read, Write. Working directory: repo root. Say little: the script's summary line, and anything you need
from the user.

## 1 — Run folder
If no run folder was given: `ls runs/` and ask which one. It must contain `intake.json`; if not, tell the user to run
`/generate-questions` (or `scripts/intake.py`) first and stop. Read `intake.json` (a few lines) for the certifications.

## 2 — SoA (only when `certs` contains `iso27001`)
**STOP and ask, then wait for the answer; never assume it:** "Do you have your ISO 27001 Statement of Applicability
(SoA)? (yes / no)"

- yes: ask for the file path, then
  `.venv/bin/python ./scripts/parse_soa.py <run_dir> /path/to/soa.xlsx`
  It copies the SoA into `<run_dir>/inputs/` and writes `soa_parsed.json`. If it cannot find the ID or applicability
  column it lists the headers it saw: show them and ask which columns to use; do not guess.
- no: tell the user all ISO-mapped subcategories will be `confirmatory` with `confidence: LOW`, and that re-running
  with an SoA later gives a more precise scope.

## 3 — Scope
`.venv/bin/python ./scripts/compute_scope.py <run_dir>`

It writes `csf_scope.json` and prints the count per question type. The policy is in `data/csf/scope_rules.json`: do not
read it or re-apply it by hand.

- **Exit 2**: it needs your reading of some SoA controls and wrote `<run_dir>/soa_pending.json`. Read that file and
  `prompts/soa_exclusion_judge.md`, judge only from what they contain, write `<run_dir>/soa_judgements.json` in the
  format the prompt gives, and run the same command again. If it then exits 1 it lists what is wrong with
  `soa_judgements.json`: fix those entries and re-run. Once `csf_scope.json` is written, log the reading (your model id):
  ```bash
  .venv/bin/python ./scripts/record_judgements.py log <run_dir> --step soa_exclusions \
      --output soa_judgements.json --inputs soa_pending.json --prompt prompts/soa_exclusion_judge.md --model <model id>
  ```
- Exit 0: nothing more.

## 4 — Questions from the bank
`.venv/bin/python ./scripts/build_questions.py <run_dir>`

Picks candidates from `data/csf/banks/question_bank_<domain>.json` per subcategory and writes `csf_questions_draft.json` and
a snapshot `csf_question_bank_used.json`.

## 5 — Check and write the CSF sheet
`.venv/bin/python ./scripts/check_questionnaire.py <run_dir> --framework csf`

It checks the picked questions against the scope and the bank (nothing missing, right question types and flags, every
question from the bank, none worded for a certification the org does not hold). Exit 1 lists the problems: show them
to the user and stop; never edit the draft by hand. Exit 0:

`.venv/bin/python ./scripts/write_questionnaire.py <run_dir>/csf_questions_draft.json <run_dir>/questionnaire.xlsx`

It writes or replaces only the CSF sheet.

## Done
Tell the user: the run folder, the counts by type and how many subcategories used the generic fallback question (no bank
candidate).
