# /csf-questionnaire

Picks the CSF 2.0 questions for one organisation and writes the CSF sheet of its questionnaire.

Argument: the run folder (`runs/<Org>_<date>`). Normally run by `/generate-questions`; run it alone only to redo
the CSF sheet of an existing run folder.

Tools: Bash, Read. Working directory: repo root. Say little: the script's summary line, and anything you need
from the user.

## 1 — Run folder
If no run folder was given: `ls runs/` and ask which one. It must contain `csf_intake.json`; if not, tell the user to run
`/generate-questions` (or `scripts/intake.py`) first and stop. Read `csf_intake.json` (a few lines) for the certifications.

## 2 — SoA (only when `certs` contains `iso27001`)
**STOP and ask, then wait for the answer; never assume it:** "Do you have your ISO 27001 Statement of Applicability
(SoA)? (yes / no)"

- yes: ask for the file path, then
  `.venv/bin/python ./scripts/parse_soa.py <run_dir> /path/to/soa.xlsx`
  It copies the SoA into `<run_dir>/inputs/` and writes `soa_parsed.json`, then prints which sheet, header row and
  columns it used (control ID, applicable, reason, implemented) and the counts. **STOP and show the user those picks;
  ask whether they are right.** If one is wrong, or it could not find a column (it lists the headers it saw), ask
  which sheet or header to use and run it again with `--sheet NAME`, `--id-col`, `--applicable-col`,
  `--reason-col` or `--implemented-col` followed by the header text. Never pick a column yourself.
- no: tell the user that the subcategories ISO 27001 relates to will be asked for evidence, marked LOW in the
  questionnaire, and that running it again with an SoA later gives a more precise scope.

## 3 — Scope
`.venv/bin/python ./scripts/compute_scope.py <run_dir>`

It writes `csf_scope.json` and prints the count per question type. The policy is in `data/csf/scope_rules.json`: do not
read it or re-apply it by hand. A control the SoA excludes, or whose entry cannot be read, makes its subcategories
asked in full, with a note telling the client they may answer "Not applicable" with the reason.

## 4 — Questions from the bank
`.venv/bin/python ./scripts/pick_questions.py <run_dir> --framework csf`

Picks candidates from `data/csf/banks/question_bank_<domain>.json` per subcategory and writes `csf_questions_draft.json` and
a snapshot `csf_question_bank_used.json`.

## 5 — Write the CSF sheet
`.venv/bin/python ./scripts/write_questionnaire.py <run_dir>/csf_questions_draft.json <run_dir>/questionnaire.xlsx`

It writes or replaces only the CSF sheet.

## Done
Tell the user: the run folder, the counts by type and how many subcategories used the generic fallback question (no bank
candidate).
