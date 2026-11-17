# /generate-questions

Makes one questionnaire (`questionnaire.xlsx`, a CSF sheet and an AI RMF sheet) for one organisation.

- **Who runs it:** anyone assessing an organisation.
- **Reads:** the intake answers you give, and the question banks already in the repo.
- **Writes:** a run folder `runs/<Org>_<date>/` with the intake, the picked questions and `questionnaire.xlsx`.
- **Files explained:** `docs/guide.md`, section "Runs".

Steps: intake → check the banks are recent enough (stops and names the bank to rebuild if not) → `/csf-questionnaire`
(CSF sheet) → `/ai-questionnaire` (AI RMF sheet). It never builds a bank: that is `/build-csf-bank` and `/build-ai-bank`.

Tools: Bash, Read, Skill. Working directory: repo root. Say little: the script summary lines, and anything you need
from the user.

## 1 — Intake (numbers, asked once)
`.venv/bin/python ./scripts/intake.py menu` prints every numbered menu. Ask the user the organisation name (free text),
then each menu one at a time, in order, and take the number(s) typed. Ask "Do you build AI, use AI, or both?", "How do
you use AI?" and "What does your AI include?" only if AI in use is option 2, and the two producer follow-ups only if the
role is Build or Both (the menu says so); the two "How / What" menus may be left blank. If the user asks what an option means, answer from `data/ai/ai_areas.json`
(each AI area's name and what it covers) and `data/ai/question_rules.json` (roles, and `producer_flags` for the two producer details). Then:

```bash
.venv/bin/python ./scripts/intake.py write --org "<name>" --domain N --certs "N N" --ai-in-use N \
    [--role N [--built-on-model N --given-to-others N] --ai-usage "N N" --ai-components "N N"] \
    --csf-assessment-done N --iso42001-held N
```

It maps the numbers to values, rejects anything not on a menu (exit 1: ask the user again for those questions only; if it
says the run folder already has an intake, ask whether to replace it and add `--replace`, knowing the old drafts are then
stale) and
prints the run folder (`runs/<Org>_<date>`) with `intake.json` and `ai_usage.json` in it. Use that folder for every
later step; nothing else needs the answers repeated.

## 2 — Check the banks are recent enough
`.venv/bin/python ./scripts/check_freshness.py --bank-age --run <run_dir>`

It checks only the build date of the banks this run uses (the CSF bank of the domain and the two AI RMF banks) against
the limits in `data/metadata.json` (`question_banks`). It needs no source files.

- Exit 0: go on.
- Exit 1: a bank is missing or too old. **Stop.** Show the user its lines and tell them to run the command each line
  names (`/build-csf-bank <domain>`, `/build-ai-bank`) first, then run `/generate-questions` again. Never build or
  rebuild a bank yourself here.

## 3 — CSF questions
Run `/csf-questionnaire <run_dir>` (Skill tool). It has its own STOP for the SoA question when ISO 27001 is held: wait for
the user's answer.

## 4 — AI RMF questions
Run `/ai-questionnaire <run_dir>`.

## Done
Tell the user: the run folder, the counts each step printed, and that `questionnaire.xlsx` (CSF sheet + AI RMF sheet)
is ready to send to the control owners. The answers filled into it go to Stage 2.
