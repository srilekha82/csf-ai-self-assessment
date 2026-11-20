# /build-csf-bank

Builds or refreshes the CSF 2.0 question banks, all six sectors together, from CISA's CSET.

- **Who runs it:** the maintainer, when a bank is missing or too old, or when CSET changes. Not part of a client run.
- **Argument:** none. The six sector banks are always built together, from the same CSET collection and agent
  judgements, so they share one record of what they were built from.
- **Reads:** a local copy of the CSET repository (its SQL files) and `data/csf/csf2_core.json`.
- **Writes:** `data/csf/banks/question_bank_<sector>.json` for every sector: per CSF subcategory, CSET's own CSF 2.0 question first,
  then the maturity-model questions CSET maps to it. Working files go to `data/csf/bank_build/`.
- **Files explained:** `docs/guide.md`, sections "Building a bank" and "Data".

Scripts do everything the CSET schema decides; an agent step (Step 4) judges only what the schema cannot (the sector
of generic questions, rewording statement-only practices as questions, loose subcategory mappings). Do not
re-implement any parsing or routing inline.

Tools: Bash, Read, Write, Agent. Working directory: repo root. Say little: the script summary lines and the final report.

## 1 — CSET path
The CSET repo is `~/workstuff/cset` unless the user says otherwise (expand `~`).
If that folder does not exist, clone the public repo there (only the SQL folder, with full history; tell the user):
`mkdir -p ~/workstuff && git clone --filter=blob:none --sparse https://github.com/cisagov/cset.git ~/workstuff/cset && git -C ~/workstuff/cset sparse-checkout set CSETWebApi/CSETWeb_Api/CSETWebCore.UpgradeLibrary/VersionUpgrader/SQL`

## 1b — What is out of date
`.venv/bin/python ./scripts/check_freshness.py --csf` (add `--cset-path <cset_path>` if CSET is not in the default
place) prints the age of NIST's reference data (`csf2_core.json` and the ISO 27001 and PCI DSS crosswalks), then one
line for the CSF banks against CSET. Show the user both.

Reference data flagged stale or seed: ask the user whether to refresh it before building. NIST blocks automated downloads, so they
download it: go to https://www.nist.gov/cyberframework/csf-20-informative-references, click "Download English (xlsx)",
save as `data/csf/source/csf2.xlsx`, and tell you. Then run `.venv/bin/python ./scripts/parse_crosswalk.py --output ./data`;
it also records the refresh in `data/metadata.json`. If they decline, note it and continue. A banks line that says stale
means CSET changed since they were built; steps 2 and 3 rebuild them.

## 2 — Extract candidates (deterministic)
`.venv/bin/python ./scripts/extract_cset_candidates.py --cset-path <cset_path>`

Pulls the CSET repo, replays the SQL (reference INSERT minus DELETE, question INSERT / UPDATE / DELETE) and writes
`data/csf/bank_build/cset_candidates.json`. Same commit as stored: prints "up to date" and exits. Commit moved but no
`.sql` changed: only patches the stored commit. Otherwise it re-extracts. If it reports "could not update CSET repo",
relay the message and stop. Add `--force` only if the user asks.

## 3 — Build the bank (deterministic routing)
`.venv/bin/python ./scripts/build_question_bank.py`

- **Exit 0**: all six banks written. Go to Step 5.
- **Exit 2**: some candidates need a judgement. It wrote `data/csf/bank_build/pending_judgements.json` (each question
  once, whatever the sector) and no bank. Go to Step 4.

## 4 — Judge the pending questions (agent)
`prompts/question_bank_judge.md` is your complete instruction for this step.

1. Read `data/csf/bank_build/pending_judgements.json`; work through `items` in batches of about 25.
2. For each item write only the verdicts it `needs`, in the format the prompt defines, all into
   `data/csf/bank_build/verdicts.json`.
3. Save them (your model id):
   ```bash
   .venv/bin/python ./scripts/record_judgements.py data/csf/bank_build/verdicts.json \
       --pending data/csf/bank_build/pending_judgements.json --model <model id>
   ```
   If it lists problems, fix those entries and run it again; nothing is saved until it passes.
4. Run Step 3 again: it should now exit 0.

Verdicts are stored in `data/csf/bank_build/cset_judgements.json` and reused by every domain and every later build; they
are redone only for questions CSET has changed. Each recording also writes a write-once record to
`data/csf/bank_build/judgement_log/`. Delete `verdicts.json` once recorded.

## 5 — Evidence prompts (agents; once, only subcategories without one)
Each CSF subcategory gets its own evidence prompt once (domain-independent, stored in `data/csf/evidence_prompts.json`
`by_subcategory`), so every client gets a specific line rather than the generic category line. The questions stay CSET's; only the evidence line is written.

1. `.venv/bin/python ./scripts/record_judgements.py evidence prepare` writes `data/csf/bank_build/evidence_input.json`
   (subcategories with no prompt of their own, with NIST's implementation examples; it says how many). Nothing to do
   when it says 0.
2. **Writers** (fresh subagents, Sonnet, started together): follow `prompts/csf_evidence_writer.md` with that input, one
   for GV + ID and one for PR + DE + RS + RC; write `data/csf/bank_build/work/evidence_<part>.json`.
3. **Evaluators** (fresh subagents, Opus; they must not see the writer's prompt): follow
   `prompts/csf_evidence_evaluator.md` with the input and one writer's file; write `work/evidence_<part>_eval.json`.
4. Record each part: `.venv/bin/python ./scripts/record_judgements.py evidence data/csf/bank_build/work/evidence_<part>.json
   --review data/csf/bank_build/work/evidence_<part>_eval.json --model <writer model id> --session "evaluator=<model id>"`.
   A failed prompt is not stored (the subcategory keeps its category line);
   one pass, no revision turn. Delete the work and input files.

## 6 — Report
Relay the script output: subcategories with candidates (and how many have maturity-model questions), empty ones, the routing counts (accept/schema, accept/agent,
reject/schema, reject/agent), how many questions the agent judged, and the evidence prompts stored. Do not re-read the bank file unless the user asks.
