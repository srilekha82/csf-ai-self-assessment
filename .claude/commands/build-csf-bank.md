# /build-csf-bank

Builds or refreshes the CSF 2.0 question banks, all six sectors together, from CISA's CSET.
No argument.

The questions come from CSET as they are; scripts pick them by sector with the rules in `data/csf/bank_rules.json`.
No agent touches the questions. Do not re-implement any parsing or picking inline.

Tools: Bash, Read, Write, Agent. Working directory: repo root. Say little: the script summary lines and the final report.

Temporary files (evidence inputs, agent drafts, the person's evidence review) all go in
`data/csf/bank_build/work/` (gitignored). Delete that folder at the end of the build.

## 1 — CSET path
The CSET repo is `~/workstuff/cset` unless the user says otherwise (expand `~`).
If that folder does not exist, clone the public repo there (only the SQL folder, with full history; tell the user):
`mkdir -p ~/workstuff && git clone --filter=blob:none --sparse https://github.com/cisagov/cset.git ~/workstuff/cset && git -C ~/workstuff/cset sparse-checkout set CSETWebApi/CSETWeb_Api/CSETWebCore.UpgradeLibrary/VersionUpgrader/SQL`

## 1b — What is out of date
`.venv/bin/python ./scripts/check_freshness.py --csf` (add `--cset-path <cset_path>` if CSET is not in the default
place) prints the age of NIST's reference data (`csf2_core.json` and the ISO 27001 and PCI DSS crosswalks), then one
line for the CSF banks against CSET. Show the user both.

Reference data flagged stale or never refreshed: ask the user whether to refresh it before building. NIST blocks automated downloads, so they
download it: go to https://www.nist.gov/cyberframework/csf-20-informative-references, click "Download English (xlsx)",
save as `data/csf/source/csf2.xlsx`, and tell you. Then run `.venv/bin/python ./scripts/parse_csf_source.py --output ./data`;
it also records the refresh in `data/metadata.json`. If they decline, note it and continue. A banks line that says stale
means CSET changed since they were built; steps 2 and 3 rebuild them.

## 2 — Extract candidates (deterministic)
`.venv/bin/python ./scripts/extract_cset_candidates.py --cset-path <cset_path>`

Pulls the CSET repo, replays the SQL (reference INSERT minus DELETE, question INSERT / UPDATE / DELETE) and writes
`data/csf/bank_build/cset_candidates.json`. Same commit as stored: prints "up to date" and exits. Commit moved but no
`.sql` changed: only patches the stored commit. Otherwise it re-extracts. If it reports "could not update CSET repo",
relay the message and stop. Add `--force` only if the user asks.

## 3 — Build the banks
`.venv/bin/python ./scripts/build_csf_bank.py` writes all six `data/csf/banks/question_bank_<sector>.json`. Per
subcategory: CSET's own CSF 2.0 question, then the CSET questions linked to it from the sets for that sector.

## 4 — Evidence prompts (agents, then a person for what still fails)
Each CSF subcategory gets its own evidence prompt once: the "Evidence Required" line of the CSF sheet, the same for
every sector, stored in `data/csf/evidence_prompts.json` `by_subcategory`. The questions stay CSET's; only this line
is written. A subcategory is asked again only while nothing is decided for it.

1. `.venv/bin/python ./scripts/record_bank.py csf-evidence-prepare` writes `data/csf/bank_build/work/evidence_input.json`
   (subcategories with no evidence line decided, with NIST's implementation examples; it says how many). Nothing to do
   when it says 0.
2. **Writers** (fresh subagents, Sonnet, started together): follow `prompts/csf_evidence_writer.md` with that input, one
   for GV + ID and one for PR + DE + RS + RC; write `data/csf/bank_build/work/evidence_<part>.json`.
3. **Evaluators** (fresh subagents, Opus; they must not see the writer's prompt): follow
   `prompts/csf_evidence_evaluator.md` with the input and one writer's file; write `work/evidence_<part>_eval.json`.
4. Record each part: `.venv/bin/python ./scripts/record_bank.py csf-evidence data/csf/bank_build/work/evidence_<part>.json
   --review data/csf/bank_build/work/evidence_<part>_eval.json --model <writer model id> --session "evaluator=<model id>"`.
   Passing prompts are stored; failures go to `data/csf/bank_build/work/evidence_revise.json` with the evaluator's reason.
5. **Revision** (only if `evidence_revise.json` exists): one fresh writer revises every item in it (same prompt, its
   Revision section) into `work/evidence_revision.json`; one fresh evaluator checks it into
   `work/evidence_revision_eval.json`; record with the same command plus `--revision`. Passing prompts are stored;
   what fails again goes to `data/csf/bank_build/work/evidence_review.json`.
6. **A person** (only if `evidence_review.json` exists): **STOP.** Tell the user how many items it has and that each
   shows the outcome, NIST's examples and both drafts with why they failed. For each item they set `"prompt"` to their
   own line (30 to 400 characters) or `"keep_category_line": true`. When they say it is done, run
   `.venv/bin/python ./scripts/record_bank.py csf-evidence-reviewed`; if it exits 1, show what it lists and wait again.
   Their decisions are final: those subcategories are never asked again.

## 5 — Report
Relay the build's summary line (questions and empty subcategories per sector, CSET commit) and the evidence prompts
stored. Do not re-read the bank files unless the user asks.
