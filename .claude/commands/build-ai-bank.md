# /build-ai-bank

Builds or refreshes the two AI RMF question banks and the CSF AI impact notes, from an accepted mapping
(`/ai-mapping`).

Scripts parse, prepare, validate, record and decide nothing; agents judge, and hand every result in through
`scripts/record_bank.py` (its `ai-…` modes), which rejects a whole file if anything is wrong. The judging rules are in the prompts
named in each step. Do not re-implement any parsing or validation inline.

Use your tools (Bash, Read, Write, Agent). Working directory: repo root. Say little: the script summary lines and the final report.

Replace `<model id>` in the record commands with the model id of the agent that produced the file.

Temporary files (prepared inputs, agent drafts and verdicts) all go in `data/ai/bank_build/work/` (gitignored).
Delete that folder at the end of the build.

---

## Step 1 — Freshness gate

```bash
.venv/bin/python ./scripts/check_freshness.py --ai-bank
```

One line per stage (parse, bank foundation, bank areas, notes, pilot, ai areas, mapping; the last two are done in
Step 2): `current`, `missing`, `stale`
or `incomplete`. A
stage is current only if it was built from the exact source files on disk (each output records the SHA-256 of its inputs).

- Exit 0: everything is current and complete. Run `.venv/bin/python ./scripts/record_bank.py ai-confirm-current`
  (no agent: it re-stamps both banks' build date, as a CSF rebuild does, so a client run's age check passes), tell the
  user and stop, unless they ask to force a rebuild.
- Exit 1 with `sources: missing ...`: point to `data/ai/source/README.md` and stop.
- Exit 1 otherwise: do only the stages that are not current, in the order below; a stale stage makes the ones after it
  stale too. Tell the user which stages you will run.

## Step 2 — Mapping

If the `mapping` line of Step 1 is not `accepted`, do the mapping here without asking the user: follow
`.claude/commands/ai-mapping.md` steps 1 and 2 for the areas the gate names (no pilot stop), then
`.venv/bin/python ./scripts/record_bank.py ai-accept-mapping --by-build`. It accepts only when every row passed its
evaluator and nothing is left for a person; if it refuses, stop and show the user what it lists (rows to review in
`data/ai/authoring/mapping.xlsx`).

## Step 3 — Parse the sources

```bash
.venv/bin/python ./scripts/parse_ai_rmf_sources.py
```

It reads the Playbook and CIS PDFs into `data/ai/ai_rmf_core.json` and the CIS safeguard files, which agents read
instead of the PDFs. It skips itself when the PDFs are unchanged (`--force` only after editing
`data/ai/parse_config.json`).

## Step 4 — Questions (only when the gate shows a bank `missing` or `incomplete`)

Two banks: **foundation** (GOVERN and the other foundation subcategories, asked once per organisation) and **areas**
(per subcategory, every AI area's mapping row on it). Pass subagents paths, not content.

**Pilot or full.** If the gate's `pilot` line is not `accepted` (no pilot yet, or a question prompt changed): pilot.
Propose about 6 subcategories and wait for the user's yes: GOVERN 1.2 and GOVERN 1.6 (foundation); one area
subcategory with many areas (e.g. MEASURE 2.8); one with a producer detail; one with a folded subcategory; one MAP
subcategory on usage areas. Otherwise: full, one batch per AI RMF function, `--missing` (only what is not recorded),
or `--ids` for the subcategories the gate lists as changed.

The loop, per batch (`<b>` = `foundation` or `areas`, `<t>` = batch tag):
1. `.venv/bin/python ./scripts/prepare_ai_bank.py batch <b> (--ids ... | --function <F> --missing) --tag <t>`
   → `work/batch_<b>_<t>.json`.
2. **Generator** (fresh subagent): `prompts/ai_rmf_question_generator.md` with the batch → `work/<t>_gen1.json`.
3. **Evaluator** (fresh subagent, never sees the generator's prompt): `prompts/ai_rmf_question_evaluator.md` with the
   batch and gen1 → `work/<t>_eval1.json`.
4. Only if eval1 fails anything: a fresh generator revises the failing subcategories (batch, gen1, eval1 → `gen2`), a
   fresh evaluator checks it (batch, gen1, eval1, gen2 → `eval2`). Two turns at most.
5. Record; if a command lists problems, send them back (evaluator file problems to the evaluator, question problems to
   the generator) and record again:
   ```bash
   .venv/bin/python ./scripts/record_bank.py ai-assemble --gen1 data/ai/bank_build/work/<t>_gen1.json \
       --eval1 data/ai/bank_build/work/<t>_eval1.json [--gen2 ... --eval2 ...] --out data/ai/bank_build/work/<t>_record.json
   .venv/bin/python ./scripts/record_bank.py ai-questions <b> data/ai/bank_build/work/<t>_record.json \
       --model <generator model id> --session "evaluator=<evaluator model id>"
   ```
   A subcategory the user decided in the review sheet is refused: leave it out, or add `--replace-human` only if the
   user agreed.
6. `.venv/bin/python ./scripts/sheet_io.py export area_questions` (or `foundation_questions`). If it refuses (sheet edits
   not imported), ask the user to run `sheet_io.py import area_questions` / `foundation_questions` first.

**After a pilot: stop.** Report turn 1 and turn 2 passes and what needs human review; show 2 or 3 passing questions
(one shared) as well as the failures. Point the user to `data/ai/authoring/questions_areas.xlsx` and
`questions_foundation.xlsx`; take their decisions in chat, apply them to the sheet and import it. When the user says
the pilot is good: `.venv/bin/python ./scripts/record_bank.py ai-accept-pilot --note "<what the user said>"`.

**After a full run:** show the user 5 random passing subcategories to spot-check.

## Step 5 — Complete?

`.venv/bin/python ./scripts/check_freshness.py --ai-bank`: `bank foundation` and `bank areas` must be `current`.
`incomplete` names what is missing or changed: back to Step 4 for those.

### Step 5b — Evidence lines (only questions without one)
Per bank (`foundation`, then `areas`):
1. `.venv/bin/python ./scripts/prepare_ai_bank.py evidence <b>` → `work/evidence_input_<b>.json`. It says how many;
   nothing to do at 0.
2. **Writer** (fresh subagent): `prompts/ai_rmf_evidence_writer.md` with the input → `work/evidence_<b>.json` (split
   the area bank by function if the input is large).
3. **Evaluator** (fresh subagent, never sees the writer's prompt): `prompts/ai_rmf_evidence_evaluator.md` with the input
   and the writer's file → `work/evidence_<b>_eval.json`.
4. `.venv/bin/python ./scripts/record_bank.py ai-evidence <b> data/ai/bank_build/work/evidence_<b>.json \
   --review data/ai/bank_build/work/evidence_<b>_eval.json --model <writer model id> --session "evaluator=<model id>"`.
   One pass: a failed line is not stored (the question keeps its generic line). Then export the bank's review sheet.

## Step 6 — AI impact notes (only when the gate's `notes` line is not current)

`.venv/bin/python ./scripts/prepare_ai_notes.py` → `work/impact_pending.json` (the CSF subcategories CIS maps to the
MCP and agents guides). Follow `prompts/ai_impact_notes_writer.md`; record each patch with
`.venv/bin/python ./scripts/record_bank.py ai-notes <file> --model <model id>` and send back what it lists:
1. Layer 1, exposure → `work/notes_layer1.json`.
2. Layer 2, use → `work/notes_layer2.json`.
3. **Evaluator** (fresh subagent, never sees the writer's prompt): `prompts/ai_impact_notes_evaluator.md` with
   `impact_pending.json` and `data/csf/ai_impact_notes.json` → `work/notes_review1.json`, recorded with
   `record_bank.py ai-notes-review data/ai/bank_build/work/notes_review1.json --model <model id>`.
4. Only if notes were flagged: a fresh writer revises them (the prompt's "Revision turn") → `work/notes_revision.json`,
   recorded with `ai-notes`; a fresh evaluator reviews the rewritten ones → `notes_review2.json`. Two turns at most.
5. `.venv/bin/python ./scripts/sheet_io.py export impact_notes`; the user decides flagged notes in chat, you apply them
   and run `sheet_io.py import impact_notes`.

A note a person decided in the review sheet is refused: leave it out of the patch.

## Step 7 — Report

Tell the user what was rebuilt or skipped, the counts (passed, needs human review), and what is left to do. List each
subcategory that needs human review with its reason (read it from the bank file only for those).
