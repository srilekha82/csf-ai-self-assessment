# /ai-questionnaire

Picks the AI RMF 1.0 questions for one organisation and writes the AI RMF sheet of its questionnaire.

- **Who runs it:** normally `/generate-questions`, which first checks the banks are recent enough. Run it alone only
  on an existing run folder, to redo the AI RMF sheet.
- **Argument:** the run folder (`runs/<Org>_<date>`).
- **Reads:** `ai_intake.json` (how the organisation uses AI) and the two AI RMF banks (`data/ai/banks/`).
- **Writes:** `ai_scope.json` (what was picked per subcategory, and why), `ai_questions_draft_<bank>.json` (the picked
  questions, one file per bank), `ai_question_bank_used_<bank>.json` (copies of the banks used), and the AI RMF sheet
  of `questionnaire.xlsx`.
- **Files explained:** `docs/guide.md`, section "Runs".

Scripts decide everything here; there is no agent judgement in this command.

Tools: Bash, Read. Working directory: repo root. Say little: the script's summary line, and anything you need from the
user.

## 1 — Run folder
If no run folder was given: `ls runs/` and ask which one. It must contain `ai_intake.json`; if not, tell the user to run
`/generate-questions` (or `scripts/intake.py`) first and stop.

## 2 — Scope and questions
`.venv/bin/python ./scripts/pick_questions.py <run_dir> --framework ai`

Picks the client's questions from the banks by their role, producer details and AI areas (policy in
`data/ai/scope_rules.json`: do not read it or re-apply it by hand) and writes `ai_scope.json`,
`ai_questions_draft_<bank>.json` and a snapshot `ai_question_bank_used_<bank>.json`. A question shared by several of
the client's areas carries a note naming them. Subcategories with no question for this client are left out (they do
not apply). Every AI question is full discovery: they ask what is done for AI, so a CSF assessment or ISO 27001
changes nothing here. Exit 1 lists what is wrong with `ai_intake.json`: tell the user, fix it with them
(re-run `scripts/intake.py` for a new intake) and run again.

## 3 — Write the AI RMF sheet
`.venv/bin/python ./scripts/write_questionnaire.py <run_dir>/ai_questions_draft_foundation.json <run_dir>/ai_questions_draft_areas.json <run_dir>/questionnaire.xlsx --framework ai`

It fills only the AI RMF sheet, and shows the AI systems sheet with the client's own AI areas when the inventory
question is asked (it stays hidden otherwise).

## Done
Tell the user: the run folder and the counts per bank (subcategories, questions).
