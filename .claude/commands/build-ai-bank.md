# /build-ai-bank

Builds or refreshes the AI RMF mapping, the two AI RMF question banks and the CSF AI impact notes.

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

One line per stage (parse, bank foundation, bank areas, notes, pilot, ai areas, mapping): `current`, `missing`, `stale`
or `incomplete`. A
stage is current only if it was built from the exact source files on disk (each output records the SHA-256 of its inputs).

- Exit 0: everything is current and complete. Tell the user and stop, unless they ask to force a rebuild.
- Exit 1 with `sources: missing ...`: point to `data/ai/source/README.md` and stop.
- Exit 1 otherwise: do only the stages that are not current, in the order below; a stale stage makes the ones after it
  stale too. Tell the user which stages you will run.

## Step 2 — Parse the sources

```bash
.venv/bin/python ./scripts/parse_ai_rmf_sources.py
```

Writes `data/ai/ai_rmf_core.json` (the 4 functions with their Playbook descriptions, and their 72 subcategories with
suggested actions) and
`data/ai/cis_ai_safeguards.json` (the safeguards of the three guides, with their CIS text: local only, never
committed) and `data/ai/cis_ai_safeguard_ids.json` (the same without the text: committed). It fails, writing nothing,
if a count is off. It reads nothing and says "up to date" when the outputs were made from these exact PDFs and the
local CIS text file exists (`--force` reads them anyway: only after editing `data/ai/parse_config.json`).
Agents read these files, never the PDFs.

## Steps 3 and 4 — Mapping (one AI area at a time, only when the user asks; the first run is a pilot on the area they name)

Work files: `data/ai/bank_build/work/`, area `<a>`. Pass subagents paths, not content.

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

After the pilot: **stop.** Show the recorded rows, what the evaluator failed, missing rows, notes and unreached
subcategories, and point the user to `data/ai/authoring/mapping.xlsx`.

- Rules or another area's row changed: `.venv/bin/python ./scripts/record_bank.py ai-revalidate` (no agent); re-draft
  only the areas it names.
- All areas recorded and reviewed (nothing needs human review, edits imported): the user runs
  `.venv/bin/python ./scripts/record_bank.py ai-accept-mapping`.

## Step 5 — Questions (subagents; needs the mapping accepted as it is now)

Two banks, built the same way: **foundation** (GOVERN and the 12 foundation subcategories of
`data/ai/mapping_rules.json`; questions per subcategory from the Playbook, each tagged with the roles it is asked of:
none, consumer, producer) and **areas** (one item per subcategory with every AI area's mapping row on it; each row is
asked once per role its area allows, or twice when its check holds two practices, and rows that would get the same
question share one). Use Sonnet
(`model: "sonnet"`) for the generator and Opus (`model: "opus"`) for the evaluator (a Sonnet evaluator misses wrong
citations and duplicates).

Ask the user: **pilot** (a few subcategories the user agrees to, then stop for review) or **full** (all subcategories
not yet recorded, one AI RMF function per batch).

### Pilot
Propose about 6 subcategories and show them to the user before running (wait for confirmation):
- two foundation: one GOVERN policy subcategory (e.g. GOVERN 1.2) and GOVERN 1.6 (the AI system inventory)
- one area subcategory with many areas (e.g. MEASURE 2.8, the audit trail: tests sharing)
- one with producer-only areas and a producer detail (e.g. a MANAGE row on model_building about releases)
- one with a folded subcategory (e.g. MAP 3.2 on internal_process folds MAP 5.1)
- one MAP subcategory on usage areas (e.g. MAP 1.4)

### The loop (per batch: the pilot's ids of one bank, or one AI RMF function in a full run)
1. Prepare the batch input:
   ```bash
   .venv/bin/python ./scripts/prepare_ai_bank.py batch <foundation|areas> --ids "<ID>" ... --tag <tag>   # pilot
   .venv/bin/python ./scripts/prepare_ai_bank.py batch <foundation|areas> --function MEASURE --missing    # full
   ```
   It writes `data/ai/bank_build/work/batch_<bank>_<tag>.json`.
2. **Generator** (a fresh subagent via the Agent tool, Sonnet): tell it to follow
   `prompts/ai_rmf_question_generator.md` with the batch file as input and to write its output to `work/<tag>_gen1.json`.
   Pass paths, not content.
3. **Evaluator** (another fresh subagent, Opus): tell it to follow `prompts/ai_rmf_question_evaluator.md` with the
   batch file and `work/<tag>_gen1.json`, and to write its verdicts (every check of every question, and a `complete`
   verdict per subcategory) to `work/<tag>_eval1.json`. It must not see the generator's prompt.
4. If `eval1` fails anything: a fresh generator subagent revises only those subcategories (inputs: the batch file,
   `gen1`, `eval1`; output `work/<tag>_gen2.json` with the COMPLETE question list of each failing subcategory), then a
   fresh evaluator checks `gen2` into `work/<tag>_eval2.json`, given also `gen1` and `eval1` (round 2: unchanged
   questions that passed keep their verdicts, except checks 6 and 7). Two turns at most.
5. Assemble and record (the script marks a subcategory `needs_human_review` if it still fails after turn 2; it rejects
   an evaluator file without a verdict on every check of every question, or a round 2 file that fails an unchanged
   question that passed round 1 on a check other than 6 and 7: send it back to the evaluator):
   ```bash
   .venv/bin/python ./scripts/record_bank.py ai-assemble --gen1 work/... --eval1 work/... [--gen2 ... --eval2 ...] --out data/ai/bank_build/work/<tag>_record.json
   .venv/bin/python ./scripts/record_bank.py ai-questions <foundation|areas> data/ai/bank_build/work/<tag>_record.json \
       --model <generator model id> --session "evaluator=<evaluator model id>"
   ```
   If `questions` lists problems (a row not asked, or asked more than twice, for a role; a role the area does not allow; a
   safeguard not of the row; a fold not cited; a foundation subcategory without a consumer or producer question), send
   them back to the generator and repeat; nothing is stored until it passes. A subcategory the user decided in the
   review sheet is refused: leave it out of the batch, or add `--replace-human` only if the user agreed.
6. Refresh the review sheet of that bank: `.venv/bin/python ./scripts/sheet_io.py export area_questions` (or
   `foundation_questions`); it refuses if the sheet has edits not yet imported: ask the user to import them first.

### After the pilot: stop
Do not continue to a full run on your own. Report to the user: how many subcategories passed on turn 1 and turn 2, how
many need human review, and token use per batch if you can see it. Show 2 or 3 PASSING questions as well as the
failures (include a shared question and its rows), so passes get reviewed too. Run the evaluator once on a file with 3
deliberately weak, checkbox-style questions added to a copy of one subcategory (never recorded) and report whether it
caught them. Point the user to the review sheets (`data/ai/authoring/questions_areas.xlsx`,
`questions_foundation.xlsx`); the user cannot easily edit spreadsheets, so take their decisions in chat, apply them to
the sheet and run `sheet_io.py import area_questions` / `foundation_questions`. The user tunes the generator and
evaluator prompts from this, then runs `/build-ai-bank` again for the full run.

When the user says the pilot is good, record it:
```bash
.venv/bin/python ./scripts/record_bank.py ai-accept-pilot --note "<what the user said>"
```
The acceptance is tied to the current generator and evaluator prompts. From then on `/generate-questions` rebuilds a
missing or incomplete AI bank on its own, like a CSF bank. If either prompt is edited later the acceptance goes stale
and a new pilot is needed before the next rebuild.

### Full run
Use `prepare_ai_bank.py batch <bank> --function <MAP|MEASURE|MANAGE|GOVERN> --missing` so each batch holds only
subcategories not yet recorded (split a function with `--ids` if the batch is large), and run the loop per batch. At
the end show the user a random sample of 5 passing subcategories to spot-check.

## Step 6 — Check completeness

```bash
.venv/bin/python ./scripts/check_freshness.py --ai-bank
```

Both `bank foundation` and `bank areas` must show `current`. `incomplete` lists what is missing, or the area
subcategories whose mapping rows changed after their questions were written: go back to Step 5 (`--missing`, or
`--ids` for the changed ones).

### Step 6b — Evidence prompts (agents; only questions without one)
Each bank question gets its own evidence prompt once, so every client gets a specific line rather than a generic one.
Per bank (`foundation`, then `areas`):

1. `.venv/bin/python ./scripts/prepare_ai_bank.py evidence <bank>` writes
   `data/ai/bank_build/work/evidence_input_<bank>.json` (only questions with no evidence prompt; it says how many).
   Nothing to do when it says 0.
2. **Writer** (a fresh subagent, Sonnet): follow `prompts/ai_rmf_evidence_writer.md` with that input; write
   `work/evidence_<bank>.json`. For the area bank, split by function (MAP, MEASURE, MANAGE) if the input is large.
3. **Evaluator** (a fresh subagent, Opus; it must not see the writer's prompt): follow
   `prompts/ai_rmf_evidence_evaluator.md` with the input and the writer's file; write `work/evidence_<bank>_eval.json`.
4. Record: `.venv/bin/python ./scripts/record_bank.py ai-evidence <bank> data/ai/bank_build/work/evidence_<bank>.json
   --review data/ai/bank_build/work/evidence_<bank>_eval.json --model <writer model id> --session "evaluator=<model id>"`.
   A failed prompt is not stored (the question keeps the generic line from `data/ai/evidence_prompts.json`; review
   it in the questions sheet); one pass, no revision turn. Then refresh the review sheet
   (`sheet_io.py export area_questions` / `foundation_questions`).

## Step 7 — AI impact notes (agent; skip if sources are unchanged and notes exist)

Notes for orgs reached by external agents or AI-enabled attackers, and where AI use changes the reading.

```bash
.venv/bin/python ./scripts/prepare_ai_notes.py
```

It joins the CIS → CSF 2.0 mapping to the MCP and agents guide safeguards and writes
`data/ai/bank_build/work/impact_pending.json` (about 48 CSF subcategories; the unmapped ones are listed, not guessed). Read
`prompts/ai_impact_notes_writer.md` and that file. Run the two layers in order, each as a patch file, each recorded:

1. Layer 1 (exposure, only where the safeguard text supports something real for an org with no AI): write
   `data/ai/bank_build/work/notes_layer1.json`, then
   `.venv/bin/python ./scripts/record_bank.py ai-notes data/ai/bank_build/work/notes_layer1.json --model <model id>`
2. Layer 2 (use): write `data/ai/bank_build/work/notes_layer2.json` for the subset where use changes the reading, then
   the same command with that file.

Fix-and-rerun on problems. A note a person decided in the review sheet is refused; leave it out of the patch.

3. Review (a fresh subagent, Opus, `model: "opus"`; it must not see the writer's prompt): follow
   `prompts/ai_impact_notes_evaluator.md` with `impact_pending.json` and `data/csf/ai_impact_notes.json`, writing the
   flagged notes to `data/ai/bank_build/work/notes_review1.json`, then
   `.venv/bin/python ./scripts/record_bank.py ai-notes-review data/ai/bank_build/work/notes_review1.json --model <model id>`
   (every note not yet reviewed and not decided by a person gets status pass or needs_human_review).
   If notes were flagged: a fresh writer (Sonnet) follows the writer prompt's "Revision turn" with
   `impact_pending.json` and the notes file, writes `data/ai/bank_build/work/notes_revision.json` (every flagged
   subcategory, complete), recorded with `record_bank.py ai-notes` (a rewritten note loses its status); then a fresh
   evaluator reviews again into `notes_review2.json`, recorded with `notes-review`: it judges only the rewritten notes,
   the others keep their verdict. Two turns at most; what still fails goes to the user in the review sheet.
4. Refresh the review sheet: `.venv/bin/python ./scripts/sheet_io.py export impact_notes`
   (`data/ai/authoring/impact_notes.xlsx`; the user decides flagged notes in chat, Claude applies them and runs
   `sheet_io.py import impact_notes`).

## Step 8 — Report

Tell the user: what was rebuilt or skipped, the gate output, counts (passed, needs human review), notes count, and
what is left to do. List any subcategory that needs human review with its reason (read it from the bank file only
for those).
