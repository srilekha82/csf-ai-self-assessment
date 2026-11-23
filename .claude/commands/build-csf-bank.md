# /build-csf-bank

Builds or refreshes the CSF 2.0 question banks, all six sectors together, from CISA's CSET.
No argument.

The questions come from CSET as they are; scripts pick them by sector with the rules in `data/csf/bank_rules.json`.
No agent is used. The Evidence Required line of the CSF sheet is NIST's implementation examples, read at client time.
Do not re-implement any parsing or picking inline.

Tools: Bash, Read. Working directory: repo root. Say little: the script summary lines and the final report.

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

## 4 — Report
Relay the build's summary line (questions and empty subcategories per sector, CSET commit). Do not re-read the bank
files unless the user asks.
