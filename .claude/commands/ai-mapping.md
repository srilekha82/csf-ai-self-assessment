# /ai-mapping

Maps each AI area (`data/ai/ai_areas.json`) to the AI RMF subcategories of MAP, MEASURE and MANAGE that check it, with
the CIS safeguards that prove them, for you to review and accept. Run rarely: once per area, and again only for an area
whose row, the mapping rules or a source changed. `/build-ai-bank` needs the mapping accepted.
Argument: an AI area id, or none (the areas the gate below names).

Scripts prepare, validate and record; agents draft and check through `scripts/record_bank.py ai-mapping`, which rejects
a whole file if anything is wrong. Do not re-implement any parsing or validation inline.

Tools: Bash, Read, Write, Agent. Working directory: repo root. Say little: the script summary lines and the final report.
Replace `<model id>` with the model id of the agent that produced the file.

Temporary files go in `data/ai/bank_build/work/` (gitignored). Delete that folder at the end.

## 1 — What needs doing
`.venv/bin/python ./scripts/check_freshness.py --ai-bank`: read its `parse`, `ai areas` and `mapping` lines.
- `parse` not current: `.venv/bin/python ./scripts/parse_ai_rmf_sources.py` (`sources: missing`: point to
  `data/ai/source/README.md` and stop).
- `ai areas` edited but not imported: `.venv/bin/python ./scripts/sheet_io.py import ai_areas`.
- Rules or another area's row changed: `.venv/bin/python ./scripts/record_bank.py ai-revalidate` (no agent); it names
  the areas to re-draft.

## 2 — Draft each area (one at a time: the areas the gate names, or for a new mapping a pilot on the area the user
names first)

Area `<a>`. Pass subagents paths, not content.

1. `.venv/bin/python ./scripts/prepare_ai_bank.py mapping --area <a>` → `work/mapping_input_<a>.json`.
2. **Drafter** (fresh subagent): `prompts/ai_rmf_mapping_drafter.md` with the input → `work/mapping_<a>_draft1.json`.
3. **Evaluator** (fresh subagent, never sees the drafter's prompt): `prompts/ai_rmf_mapping_evaluator.md` with the input
   and the draft → `work/mapping_<a>_eval1.json`.
4. Only if it has `row` or `missing` findings: a fresh drafter revises (input, draft1, eval1 → complete `draft2`), a fresh
   evaluator checks it (→ `eval2`). Two turns at most.
5. Record the last pair; if it lists problems, send them back to the drafter and record again:
   ```bash
   .venv/bin/python ./scripts/record_bank.py ai-mapping data/ai/bank_build/work/mapping_<a>_draft<N>.json \
       --review data/ai/bank_build/work/mapping_<a>_eval<N>.json --model <drafter model id> --session "evaluator=<model id>"
   ```
6. `.venv/bin/python ./scripts/sheet_io.py export mapping`. If it refuses (sheet edits not imported), ask the user to run
   `sheet_io.py import mapping` first.

Then **stop** (after the pilot area, or after the areas the gate named). Show the recorded rows, what the evaluator
failed, missing rows, notes and unreached subcategories, and point the user to `data/ai/authoring/mapping.xlsx`.

## 3 — Accept
When every area is recorded and reviewed (nothing needs human review, edits imported), the user runs
`.venv/bin/python ./scripts/record_bank.py ai-accept-mapping` (it refuses while anything needs a person). Re-drafting an area later keeps the user's decisions.
