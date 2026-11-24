# csf-ai-self-assessment — full guide

The detail behind the short `README.md`: every command, script, data file and the glossary.

Stage 1 of an AI and cybersecurity assessment pipeline. Given an organisation's profile (sector, certifications, optional ISO 27001 SoA) it produces one questionnaire (`questionnaire.xlsx`) to send to control owners, with three sheets: a tailored NIST CSF 2.0 sheet, a NIST AI RMF 1.0 sheet scoped by how the org uses AI, and an External AI sheet every org gets (what AI outside it changes for a CSF outcome). The client sees one questionnaire; the tracks are internal. In Stage 2 the answers become profile XLS files (CSF profile, AI RMF profile). Rules for changing the repo are in `DESIGN_RULES.md`; `CLAUDE.md` is the short operating guide. Pipeline design: `docs/architecture.md`.

```
Question banks  →  Stage 1: Questionnaire  →  Stage 2: Answers        →  Stage 3: reports
(CSF and AI RMF    (this repo)                (later)                    (later)
 built)
```

## I want to…

| I want to… | Do this |
|---|---|
| Generate a questionnaire for a client | `/generate-questions`. It asks the intake once (numbered choices), checks the banks are recent enough (it stops if one is missing or too old, and never rebuilds), then runs the CSF and AI commands, and writes one `questionnaire.xlsx` (CSF, AI RMF and External AI sheets). |
| Generate only the CSF part, or only the AI part | On an existing run folder: `/csf-questionnaire` or `/ai-questionnaire`. Each checks its questions and writes its own sheet; either can run in any order. |
| See what the bank builds need to redo (maintainer) | `.venv/bin/python ./scripts/check_freshness.py --csf` (NIST's reference data and every CSF bank against CSET) or `--ai-bank` (each part of the AI RMF build against its sources). |
| Build or refresh the CSF banks | `/build-csf-bank` (all six sectors together). `/generate-questions` stops and names it when a bank is missing or too old. |
| Map the AI areas to the AI RMF (rarely: a new or changed AI area, rules or source) | `/ai-mapping`: one area at a time, pilot first; you review `mapping.xlsx` and accept (`record_bank.py ai-accept-mapping`). |
| Build or refresh the AI RMF question banks (foundation, areas) and the External AI bank | `/build-ai-bank` (does the mapping first if it is not accepted, and accepts it when every row passed): pilot first; after you accept the pilot (`record_bank.py ai-accept-pilot`) later rebuilds need no pilot until a question prompt changes. |
| Use a new Playbook, CIS guide or CSF download | Replace the file (`data/ai/source/` or `data/csf/source/csf2.xlsx`, links in `data/metadata.json`). The freshness check sees the change; rebuild with the commands above. |
| Change a rule, a menu, a limit or a prompt | See **Policy** below: which file, and what to run after. |
| Review the AI RMF mapping (right, wrong, missing) | `.venv/bin/python ./scripts/sheet_io.py export mapping`, open `data/ai/authoring/mapping.xlsx` (one line per AI area x subcategory, mapped or not, with the Playbook text; a Coverage sheet), edit, then `sheet_io.py import mapping`. Then accept it: `.venv/bin/python ./scripts/record_bank.py ai-accept-mapping`. |
| Review the AI RMF questions | `.venv/bin/python ./scripts/sheet_io.py export area_questions` (and `foundation_questions`), open `data/ai/authoring/questions_areas.xlsx` / `questions_foundation.xlsx` (one line per question: areas covered, who it is asked of, flag, question, Playbook actions, status), edit, then `sheet_io.py import area_questions`. Changed subcategories are stored as decided by a person and a later generator run does not overwrite them. |
| Review the External AI threats and questions | `.venv/bin/python ./scripts/sheet_io.py export external_questions`, open `data/ai/authoring/questions_external.xlsx` (one line per question: CSF subcategory, threat, question, CIS safeguards, status), edit, set Status pass for what you accept, then `sheet_io.py import external_questions`. Questions are written only for threats set pass. Changed subcategories are stored as decided by a person. |
| Check that nothing drifted (regression check, writes nothing) | CSF: `.venv/bin/python ./scripts/build_csf_bank.py --check` (a fresh build compared with the committed banks). AI: `.venv/bin/python ./scripts/record_bank.py ai-check` (the stored mapping and banks re-checked against the current rules). |
| See what happened in a run | `runs/<Org>_<date>/audit.jsonl` (timeline). For an AI bank build, also `judgement_log/` in `data/ai/bank_build/` (what each agent was shown and answered). |
| Change the code or add a stage | Read `DESIGN_RULES.md` first, then run the unit tests (`.venv/bin/python -m unittest discover -s tests`). After a bank rebuild, also the data checks (`-p "check_*.py"`). |

## Policy: what to change, and what to do after

Rules and wording live in data files, not code. Each file's own `description` says what it decides.

| To change | File (key) | Then |
|---|---|---|
| Which CSET question sets go to which sector; which questions are left out | `data/csf/bank_rules.json` (`sector_by_model`, `reject_flags`, `statement_only_text`) | `/build-csf-bank` (scripts only), then the data checks |
| Question type per state, questions per type, the certification sentences, the fallback question and evidence line, sector bumps, how the SoA is read | `data/csf/scope_rules.json` | Nothing: the next client run uses it |
| Intake menus, sectors, certifications, question-type order | `data/common/intake_options.json` | Nothing. A new sector also needs its `sector_bumps` entry and a bank (`/build-csf-bank`); a new certification needs its crosswalk (`parse_csf_source.py`) |
| How old a bank may be | `data/metadata.json` (`question_banks`) | Nothing |
| The AI areas (usage, components, impacts) | `data/ai/authoring/ai_areas.xlsx`, then `sheet_io.py import ai_areas` | `/build-ai-bank` (it re-drafts the changed area, rechecks the others without an agent, then rebuilds the questions of changed rows). Keep `area_client_labels.json` and the questionnaire template's AI systems sheet in step (data check) |
| Which CIS controls an AI area may cite, required checks, foundation subcategories, how much source text the drafter sees | `data/ai/mapping_rules.json` | `record_bank.py ai-revalidate` (no agent); re-draft only the areas it names (`/ai-mapping`) |
| Question roles, producer details, impacts, criticality frame, questions per foundation subcategory, text limits, the AI system inventory | `data/ai/question_rules.json` | `record_bank.py ai-check`: it lists stored questions that break the new rules; regenerate those (`/build-ai-bank`, `--ids`) |
| Which roles a client is asked as; which AI areas the intake answers give | `data/ai/scope_rules.json` | Nothing: the next client run uses it (data check: every AI area reachable) |
| The label a client sees for an AI area | `data/ai/area_client_labels.json` | Update the AI systems sheet of `templates/questionnaire_template.xlsx` to match (data check) |
| The generic AI evidence line (a question with none of its own) | `data/ai/evidence_prompts.json` | Nothing |
| Priority per AI RMF subcategory (Stage 2) | `data/ai/severity_rules.json` | Nothing yet |
| Expected counts and file names of the AI source PDFs | `data/ai/parse_config.json` | `parse_ai_rmf_sources.py --force` |
| Review sheet columns, allowed values and words | `data/common/sheet_specs.json` | `sheet_io.py export <sheet>` again |
| How the question generator or evaluator judges | `prompts/ai_rmf_question_generator.md`, `ai_rmf_question_evaluator.md` | A new pilot before the next question build (the acceptance goes stale) |
| How any other agent judges (mapping, evidence, notes) | the file in `prompts/` | Nothing: the next draft or run uses it |

## How it works

- **Scripts do the repetitive, deterministic work and never decide.** Parsing, joining, looking up, validating, formatting. This is what keeps agent token use low.
- **Agents do every judgement**, and see only the small set of items a script could not settle (a `pending` file, exit code 2).
- **Everything that happens in a run is audited.** Each script run and agent step appends one line to an `audit.jsonl` (who, what, inputs and outputs with hashes, how it ended). Agent judgements also get a full write-once record in `judgement_log/` (model, prompt hash, output snapshot). Any new script or stage should use the same helper, `scripts/audit.py`.
- **Policy and content live in data files, not code.** To change a rule or a wording, edit a JSON file.

## Setup

- Python 3. Create the project venv once: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (`openpyxl`, `pdfplumber`). Every command in this guide runs as `.venv/bin/python ./scripts/<script>.py`.
- GitHub Codespaces: `.devcontainer/devcontainer.json` creates the venv and installs the requirements when the codespace is created (Python 3.12, Node for the Claude Code CLI). The licensed sources in `data/ai/source/` are not in the repo; upload them to the codespace if you need to re-parse.
- The CIS companion guides are not in the repo (the Playbook is); see `data/ai/source/README.md`.
- A copy of the public CSET repo at `~/workstuff/cset`, only for building and checking the CSF banks (an assessment does
  not need it). `/build-csf-bank` clones it the first time it runs. To clone it yourself, take only the SQL folder with
  full history (the freshness check compares commits; ~370 MB):
  `mkdir -p ~/workstuff && git clone --filter=blob:none --sparse https://github.com/cisagov/cset.git ~/workstuff/cset && git -C ~/workstuff/cset sparse-checkout set CSETWebApi/CSETWeb_Api/CSETWebCore.UpgradeLibrary/VersionUpgrader/SQL`
- Run everything from the repo root, inside Claude Code.

## Commands

| Command | What it does |
|---|---|
| `/generate-questions` | The whole flow: intake (numbered choices) → bank age check (stops if a bank is missing or too old) → `/csf-questionnaire` → `/ai-questionnaire` → one `questionnaire.xlsx`. Stops at the SoA question and to confirm the SoA columns. Send the XLSX to control owners. |
| `/csf-questionnaire` | The CSF sheet for a run folder: SoA question (and confirming its columns), scope, questions from the bank, check, sheet. Writes `csf_scope.json`, `csf_questions_draft.json` and the CSF sheet of `questionnaire.xlsx`. |
| `/ai-questionnaire` | The AI RMF sheet for a run folder: picks the client's questions by role, producer details and AI areas from `ai_intake.json`, checks them, writes the sheet. Writes `ai_scope.json`, `ai_questions_draft_<foundation|areas>.json` and the AI RMF sheet of `questionnaire.xlsx`. |
| `/build-csf-bank` | Builds the six CSF question banks, all sectors together, from the CSET repo (occasional; reused by every engagement). |
| `/ai-mapping` | Maps each AI area to the AI RMF subcategories that check it, with the CIS safeguards that prove them (`data/ai/mapping.json`); you review and accept it. Rarely redone. |
| `/build-ai-bank` | Builds the two AI RMF question banks (foundation, areas) from the Playbook and CIS companion guides, from the accepted mapping, and the External AI questions from the threats you accepted (quarterly, or when a source changes). Pilot first, then full run. |

The intake is `scripts/intake.py`: it prints the numbered menus (from `data/common/intake_options.json`), turns the typed numbers into values, and writes `csf_intake.json` (org, sector, certs) and `ai_intake.json` in the run folder. Every later step reads those files.

**Not built yet:** Stage 2 (answers → the profile spreadsheets) and Stage 3 (reports). The AI RMF and External AI banks are built by `/build-ai-bank`, in `data/ai/banks/`.

### Building a bank (`/build-csf-bank`)

1. `extract_cset_candidates.py` replays the CSET SQL migrations into `cset_candidates.json` (skipped if CSET has not changed): CSET's own CSF 2.0 set (`NCSF_V2`, one question for each of the 106 subcategories) and the maturity-model questions (ACET, CPG, SSG…) CSET maps to CSF 2.0.
2. `build_csf_bank.py` writes all six `data/csf/banks/question_bank_<sector>.json` at once, with no agent: per subcategory, CSET's own CSF 2.0 question first, then the CSET questions linked to it from the sets for that sector (`data/csf/bank_rules.json` `sector_by_model`: ACET for finance, SSG IT for saas_cloud; an unlisted set goes to every sector). Questions CSET marks not answerable, or with no text, are left out; an SSG IT practice with no question text is shown as its CSET outcome text.
3. Nothing else is written: the "Evidence Required" line of the CSF sheet is NIST's implementation examples for the subcategory (`csf2_core.json`), word for word, read by `pick_questions.py` in a client run.

Sectors: `healthcare`, `finance`, `manufacturing_ot`, `saas_cloud`, `consulting`, `other`.

### Running an engagement (`/generate-questions`)

1. `intake.py` asks once, as numbered choices: org, sector, certs, the AI usage profile (AI in use none / some / unsure, then "How do you use AI?" and "What does your AI include?", which give the client's AI areas), and for an organisation that builds its own model the two producer details. It writes `csf_intake.json` (org, date, sector, certifications: the CSF sheet is picked from these) and `ai_intake.json` (the AI answers: the AI RMF sheet is picked from these); every later step reads them.
2. `check_bank_age.py --run <run>` checks the build date of the CSF bank of the sector and the two AI RMF banks against the limits in `data/metadata.json` (`question_banks`: CSF 365 days, AI 90). If a bank is missing or too old the run stops and names the command to rebuild it (`/build-csf-bank`, `/build-ai-bank`); a client run never rebuilds a bank. It needs no source files.
3. `/csf-questionnaire`: `parse_soa.py <run> <soa>` extracts the SoA and prints the sheet and columns it picked; the user confirms them (a wrong pick is corrected with `--sheet` / `--id-col` / ...). `compute_scope.py` gives each subcategory a type: `full_discovery`, `gap` (cert covers it, ask what goes beyond) or `confirmatory` (cert should cover it, ask for evidence); policy is in `data/csf/scope_rules.json`. When in doubt (a control the SoA excludes or whose entry cannot be read) it asks in full, with a note that the client may answer "Not applicable" with the reason. `pick_questions.py (--framework csf)` picks questions from the bank and words them for the certs held, producing `csf_questions_draft.json`.
4. `/ai-questionnaire`: see below.
5. Each command ends with `write_questionnaire.py`, which writes that framework's sheet of `questionnaire.xlsx` (each replaces only its own sheet). Questions are reviewed once, when the banks are built, never per run; the picking is fixed rules, checked by `tests/check_picks.py` (nothing missing, right question types and flags, every question from the bank, nothing for a role, AI area or certification the org does not have).

### AI RMF track

**Building the banks (`/build-ai-bank`):**
1. `check_freshness.py --ai-bank` compares the SHA-256 of the current source files with the hashes each output recorded about its inputs, one line per stage; all current means skip.
2. `parse_ai_rmf_sources.py` turns the Playbook and the three CIS guides into `ai_rmf_core.json` (the 4 functions with their Playbook descriptions, 72 subcategories, suggested actions) and `cis_ai_safeguards.json` (153 safeguards per guide, with the CIS text: local only, CC BY-NC-ND 4.0) plus `cis_ai_safeguard_ids.json` (the same without text: committed).
3. Mapping (`/ai-mapping`, or run by `/build-ai-bank` when not accepted; rarely redone; agents, `prompts/ai_rmf_mapping_drafter.md` and `ai_rmf_mapping_evaluator.md`): per AI area (`data/ai/ai_areas.json`), the MAP, MEASURE and MANAGE subcategories that check it and the CIS safeguards that prove them, recorded by `record_bank.py ai-mapping` against `data/ai/mapping_rules.json`, reviewed in `mapping.xlsx` and accepted (`record_bank.py ai-accept-mapping`).
4. Questions, generated and evaluated with subagents (`prompts/ai_rmf_question_generator.md`, `prompts/ai_rmf_question_evaluator.md`), two turns at most, into two banks: **foundation** (GOVERN and the 12 foundation subcategories, asked once for the organisation) and **areas** (one item per subcategory with every area's mapping row on it; a question may stand for several rows). Every question carries the roles it is asked of and any producer details it needs. `prepare_ai_bank.py batch <foundation|areas>` prepares each batch; `record_bank.py ai-assemble` and `ai-questions` store the result (every row asked once, or twice when its check holds two practices, per role its area allows). Pilot first; once the user accepts it (`record_bank.py ai-accept-pilot`, tied to the current generator and evaluator prompts) later rebuilds need no pilot.
5. External AI questions: per CSF subcategory NIST links to CIS Controls v8.1 (`data/csf/crosswalks/olir_cis_v81.json`), the threat a person decided (review sheet `questions_external.xlsx`) and the AI text of those safeguards (`prepare_ai_bank.py external`); an agent writes one or two questions (`prompts/ai_external_question_generator.md`), a second checks them (`prompts/ai_external_question_evaluator.md`); `record_bank.py ai-assemble --kind external` and `ai-external` store `data/ai/banks/question_bank_external.json`. The CIS safeguards are worked out by `ai_external.py`, never by an agent.

**Running an engagement (`/ai-questionnaire`, run by `/generate-questions` or alone):** `pick_questions.py (--framework ai)` picks the client's questions from both banks by filtering on `ai_intake.json`: roles (`scope_rules.json` `client_roles`), producer details and, for area questions, the client's AI areas. A question shared by several of the client's areas carries "This question covers: ..." naming them. Every question is `full_discovery`: it asks what is done for AI, so it never repeats the CSF sheet or ISO 27001. It writes one draft per bank. `write_questionnaire.py --framework ai` writes the AI RMF sheet of `questionnaire.xlsx`, plus an "AI systems" sheet where the client answers the inventory question (GOVERN 1.6) as a table: one row per system, which of the client's AI areas it involves, and its criticality. The layout comes from `templates/questionnaire_template.xlsx`.

## What is where

### Scripts

You run commands; each command runs its scripts in order. Scripts do the routine work and never make judgement calls:
where one is needed, an AI agent makes it and a script checks the answer before storing it.

How to read the diagrams: grey boxes are commands, blue are scripts, orange are AI agents, green is you, red is where
a run stops, and the rounded boxes are the files they read or write.

**Making a questionnaire** (`/generate-questions`)

```mermaid
flowchart TD
    GQ["/generate-questions"]:::cmd --> IN[intake.py]:::script
    IN --> INT([csf_intake.json]):::file
    IN --> USE([ai_intake.json]):::file
    INT --> AGE["check_bank_age.py<br/><small>also reads: the banks' build dates</small>"]:::script
    AGE -- "a bank is missing or too old" --> STOP["stop: run /build-csf-bank or /build-ai-bank first"]:::stop
    AGE -- ok --> CQ["/csf-questionnaire"]:::cmd
    AGE -- ok --> AQ["/ai-questionnaire"]:::cmd

    CQ -- "ISO 27001 held" --> SOA["parse_soa.py<br/><small>reads: the SoA Excel file</small>"]:::script --> SOAJ([soa_parsed.json]):::file
    SOAJ --> OK1["you: confirm the sheet and columns it picked"]:::you
    OK1 -- "a pick is wrong: run again naming the column" --> SOA
    OK1 -- right --> SC["compute_scope.py<br/><small>also reads: csf_intake.json</small>"]:::script
    CQ --> SC
    SC --> SCJ([csf_scope.json]):::file --> BQ["pick_questions.py --framework csf<br/><small>also reads: csf_intake.json, the CSF bank</small>"]:::script
    BQ --> CD([csf_questions_draft.json]):::file

    AQ --> BAQ["pick_questions.py --framework ai<br/><small>also reads: the AI RMF banks</small>"]:::script
    USE --> BAQ
    BAQ --> AD([ai_questions_draft_*.json]):::file

    CD --> WQ[write_questionnaire.py]:::script --> X([questionnaire.xlsx]):::file
    AD --> WQ

    classDef cmd fill:#e5e7eb,stroke:#6b7280,color:#111
    classDef script fill:#dbeafe,stroke:#2563eb,color:#111
    classDef agent fill:#ffedd5,stroke:#ea580c,color:#111
    classDef you fill:#dcfce7,stroke:#16a34a,color:#111
    classDef file fill:#f9fafb,stroke:#9ca3af,color:#111
    classDef stop fill:#fee2e2,stroke:#dc2626,color:#111
    classDef you fill:#dcfce7,stroke:#16a34a,color:#111
```

**Building the CSF banks** (`/build-csf-bank`, maintainer)

```mermaid
flowchart TD
    B["/build-csf-bank"]:::cmd --> PC["parse_csf_source.py<br/>(only when NIST's file is refreshed)"]:::script
    NIST([csf2.xlsx from NIST]):::file --> PC --> CORE([csf2_core.json, crosswalks]):::file
    B --> EX[extract_cset_candidates.py]:::script
    SQL([CSET SQL files]):::file --> EX --> CAND([cset_candidates.json]):::file --> BQB[build_csf_bank.py]:::script
    RULES([bank_rules.json]):::file --> BQB
    BQB --> BANK([question_bank_&lt;sector&gt;.json]):::file
    CORE --> BQB

    classDef cmd fill:#e5e7eb,stroke:#6b7280,color:#111
    classDef script fill:#dbeafe,stroke:#2563eb,color:#111
    classDef agent fill:#ffedd5,stroke:#ea580c,color:#111
    classDef you fill:#dcfce7,stroke:#16a34a,color:#111
    classDef file fill:#f9fafb,stroke:#9ca3af,color:#111
    classDef stop fill:#fee2e2,stroke:#dc2626,color:#111
```

**Building the AI RMF mapping and banks** (`/ai-mapping`, `/build-ai-bank`, maintainer)

```mermaid
flowchart TD
    B["/build-ai-bank"]:::cmd --> CF["check_freshness.py --ai-bank<br/>(what needs redoing)"]:::script
    SRC([data/ai/source/: Playbook, CIS guides]):::file --> CF
    CF --> PS[parse_ai_rmf_sources.py]:::script
    SRC --> PS --> CORE([ai_rmf_core.json, cis_ai_safeguards.json, cis_ai_safeguard_ids.json]):::file

    AMC["/ai-mapping"]:::cmd --> PM
    CORE --> PM["prepare_ai_bank.py mapping"]:::script --> AM["agents: mapping drafter + checker"]:::agent --> RM["record_bank.py ai-mapping<br/><small>checks and store: ai_mapping.py</small>"]:::script --> MAP([mapping.json]):::file
    MAP --> SM["sheet_io.py export mapping"]:::script --> U1["you: review, then record_bank.py ai-accept-mapping"]:::you

    U1 --> PB["prepare_ai_bank.py batch"]:::script
    MAP --> PB --> AQ["agents: question generator + checker"]:::agent --> RQ["record_bank.py ai-assemble + ai-questions<br/><small>checks and store: ai_questions.py</small>"]:::script --> BANKS([question_bank_ai_rmf_foundation.json, ..._areas.json]):::file
    BANKS --> SQ["sheet_io.py export area_questions, foundation_questions"]:::script --> U2["you: review the pilot, then record_bank.py ai-accept-pilot"]:::you

    BANKS --> PE["prepare_ai_bank.py evidence"]:::script --> AE["agents: evidence writer + checker"]:::agent --> RE["record_bank.py ai-evidence<br/><small>checks and store: ai_questions.py</small>"]:::script --> BANKS

    OLIR([olir_cis_v81.json: NIST's CSF to CIS links]):::file --> PX["prepare_ai_bank.py external"]:::script
    U3["you: accept each threat in questions_external.xlsx"]:::you --> PX
    CORE --> PX --> AX["agents: question generator + checker"]:::agent --> RX["record_bank.py ai-assemble --kind external + ai-external<br/><small>checks and store: ai_external.py</small>"]:::script --> EXT([question_bank_external.json]):::file
    EXT --> SX["sheet_io.py export external_questions"]:::script --> U3

    classDef cmd fill:#e5e7eb,stroke:#6b7280,color:#111
    classDef script fill:#dbeafe,stroke:#2563eb,color:#111
    classDef agent fill:#ffedd5,stroke:#ea580c,color:#111
    classDef you fill:#dcfce7,stroke:#16a34a,color:#111
    classDef file fill:#f9fafb,stroke:#9ca3af,color:#111
    classDef stop fill:#fee2e2,stroke:#dc2626,color:#111
```

`sheet_io.py import` takes your edits from any review spreadsheet back into the data (lines you change are never
overwritten by an agent). Each script's own file opens with a short explanation of what it does.

**Helpers** (used by the scripts above, never run directly): `config.py` (where every file lives, and the shared
lists: sectors, certifications, question types), `audit.py` (the run log), `ai_bank_common.py` (shared AI bank
helpers), `ai_mapping.py`, `ai_questions.py` and `ai_external.py` (the checks, storing and review sheets behind
`record_bank.py` and `sheet_io.py`, one file per kind of AI bank data), `ai_priority.py` (priorities for Stage 2; not used yet).

### Prompts (`prompts/`)

How the agents judge and write (AI bank build only; the CSF track uses no agent): `ai_rmf_mapping_drafter.md`, `ai_rmf_mapping_evaluator.md`, `ai_rmf_question_generator.md`, `ai_rmf_question_evaluator.md`, `ai_rmf_evidence_writer.md`, `ai_rmf_evidence_evaluator.md`, `ai_external_question_generator.md`, `ai_external_question_evaluator.md` (bank build). Commands (`.claude/commands/`) say what to run; prompts say how to judge.

### Data (`data/`)

Not written during an engagement; that output goes to `runs/`.

```
data/
├── metadata.json            source, last refresh and staleness threshold per file
├── tier_definitions.json    NIST Tier 1-4 (not used yet; needed to map answers to tiers)
├── common/
│   ├── intake_options.json  intake menus, sectors, certs, question types (shared by both tracks)
│   └── sheet_specs.json     columns and allowed values of every spreadsheet sheet_io.py converts
├── csf/
│   ├── source/csf2.xlsx     NIST CPRT export (refreshed about yearly)
│   ├── csf2_core.json       CSF 2.0 subcategories and examples
│   ├── scope_rules.json     state → question type, max questions per type, sector bumps, function order; how
│   │                        the SoA spreadsheet is read (soa_reading)
│   ├── bank_rules.json      how CSET questions are flagged and picked when a CSF bank is built: sector of each
│   │                        question set, reject flags, the text shown for a practice with no question
│   ├── crosswalks/          ISO 27001, PCI DSS and CIS Controls v8.1 mappings (from NIST's file)
│   ├── banks/               question_bank_<sector>.json
│   └── bank_build/          cset_candidates.json, audit.jsonl
├── audit.jsonl              data refresh and freshness checks (created on first run)
└── ai/
    ├── source/                 AI RMF Playbook (committed), CIS companion guides (not in the repo; see source/README.md)
    ├── parse_config.json       expected counts and file names for the parser
    ├── ai_rmf_core.json        4 functions (Playbook description) with their 72 subcategories + suggested actions (parsed)
    ├── cis_ai_safeguard_ids.json  safeguards of the three guides: ids, controls, IG (committed)
    ├── cis_ai_safeguards.json  the same with the CIS text (parsed, local only, not committed)
    ├── question_rules.json     question banks: roles, producer details, impacts, question counts, the AI systems sheet,
    │                           text length limits
    ├── area_client_labels.json what the client sees for each AI area (area id -> plain label)
    ├── authoring/ai_areas.xlsx  AI areas and their impact, decided by a person (sheet_io.py import -> ai_areas.json)
    ├── ai_areas.json           generated from authoring/ai_areas.xlsx; scripts read this
    ├── mapping_rules.json      candidate CIS controls per AI area, required checks, foundation subcategories
    ├── mapping.json            AI area x function -> subcategory, CIS safeguards, impact (record_bank.py ai-mapping)
    ├── authoring/mapping.xlsx  the mapping for review (sheet_io.py export mapping; edits back with import mapping)
    ├── authoring/questions_<areas|foundation|external>.xlsx  the question banks for review (sheet_io.py export
    │                           area_questions / foundation_questions / external_questions)
    ├── scope_rules.json        engagement policy: AI area rules for the intake, roles each client is asked as, notes
    ├── evidence_prompts.json   evidence hint per question (foundation, or by the impacts of the rows it covers)
    ├── banks/                  question_bank_ai_rmf_<foundation|areas>.json, question_bank_external.json
    └── bank_build/             mapping_accepted.json, pilot_accepted.json, audit.jsonl, judgement_log/ (write-once records of agent steps, committed), work/ (temporary)
```

### Runs (`runs/<Org>_<date>/`)

One folder per engagement. It holds client data, so keep it out of any shared repo.

| File | What |
|---|---|
| `inputs/soa_original.xlsx` | Client SoA (if provided) |
| `soa_parsed.json` | The parsed SoA |
| `csf_intake.json` | Org, date, sector, certifications (from `intake.py`; read by scope, question building and the freshness check) |
| `ai_intake.json` | The AI usage profile (AI in use, role, producer details, the client's AI areas), from the same intake |
| `csf_scope.json` | Question type per subcategory, with the reason and any note for the client |
| `ai_scope.json`, `ai_questions_draft_<bank>.json` | The AI RMF track for the run (scope, the picked questions per bank); the AI RMF sheet goes into `questionnaire.xlsx` |
| `csf_question_bank_used.json`, `csf_questions_draft.json` | Copy of the CSF bank used, the picked CSF questions |
| `ai_question_bank_used_<bank>.json` | Copies of the two AI RMF banks used |
| `external_questions_draft.json`, `external_question_bank_used.json` | The picked External AI questions, and a copy of the External AI bank used |
| `questionnaire.xlsx` | The deliverable workbook with the CSF, AI RMF and External AI sheets |
| `audit.jsonl` | Timeline of the whole run: every script and agent step, with status (`ok`, `pending`, `rejected`, `error`, `incomplete`), file hashes and the intake answers (sector, certs) |

### Tests

`tests/fixtures/` has `sample_soa.xlsx`. `templates/` has `questionnaire_template.xlsx`, the questionnaire layout each run copies and fills (change its look in Excel), and the two empty profile XLS files that Stage 2 fills (a copy per run, in the run folder, never committed): `csf_org_profile_template.xlsx` (NIST's CSF 2.0 Organizational Profile template, emptied; source in `data/metadata.json`: sheet "Current and Target Profile", 19 columns, the CSF ids and outcomes, NIST's column descriptions) and `ai_rmf_profile_template.xlsx` (sheet "AI RMF Profile", 11 columns, the AI RMF ids and outcomes). Both carry only headers, ids and outcome text; keep their cell colours (the framework colours). `.venv/bin/python -m unittest discover -s tests` runs the unit tests (`test_*.py`): the intake, the SoA reader, scope, both question pickers, the questionnaire writer, the bank build scripts and the review sheets, on their own inputs (stores redirected to a temp dir, so the tests never change `data/`). `-p "check_*.py"` runs the data checks on the committed data: typical clients picked from the committed banks (`check_picks.py`), the banks' build dates, and that the data files and the questionnaire template agree (`check_data.py`).

## Status

- **Stage 1 code is built.** The CSF banks are to be rebuilt from CISA's CSET (`/build-csf-bank`; every subcategory
  starts with CSET's own CSF 2.0 question). AI RMF: the sources are parsed (72 subcategories, 459 safeguards), the AI
  areas, intake and mapping are built, and both question banks (foundation, areas) are built and reviewed; the
  invisible usage area is to be re-mapped (outside AI moved to External AI). External AI: 29 threats wait for review
  in `questions_external.xlsx`; their questions are built by `/build-ai-bank` once accepted.
- The client run has been tested end to end with the scripts (tests and scratch runs); a run with a real organisation
  has not been done yet.
- Stage 2 (answers → profile spreadsheets) is next; Stage 3 (reports) after it (`TODO.md`).

## Glossary

| Term | Meaning |
|---|---|
| **Bank** | A frozen set of questions, built once and reused. CSF: one per sector, from CSET (candidate questions). AI RMF: two, foundation and areas, generated from the Playbook and CIS guides; they hold every possible question, each tagged with the roles it is asked of. A questionnaire picks from a bank; it never invents questions. |
| **AI area** | A way AI is used (internal process, code generation, customer-facing, vendor AI, model building, invisible usage) or a part of the AI ecosystem (input, output, test, tuning and evaluation data, model, source data, MCP / tools, agent, hosting). 14 in all, decided by a person in `data/ai/authoring/ai_areas.xlsx`. |
| **Mapping row** | One AI area x one AI RMF subcategory (MAP, MEASURE or MANAGE): why that subcategory matters for the area, its impact, and the CIS safeguards that can serve as evidence. Area questions are written per row. All rows together are the **mapping** (`data/ai/mapping.json`). |
| **Foundation** | GOVERN and 12 other subcategories about how the organisation runs AI risk management: asked once for the organisation, never per area. |
| **Question type** | Set per subcategory at engagement time. `full_discovery`: nothing is covered, ask everything. `gap`: a certification covers the standard part, ask what goes beyond it. `confirmatory`: a certification should cover it, ask for evidence. A subcategory is never skipped. Every AI RMF question is `full_discovery`: it asks about AI, so certifications change nothing there. |
| **Sector** | The client's industry; it picks the CSF bank: healthcare, finance, manufacturing_ot, saas_cloud, consulting, other. |
| **SoA** | The client's ISO 27001 Statement of Applicability. It sets CSF question types for ISO-mapped subcategories. |
| **AI in use** | `none`, `some` or `unsure`. `unsure` is asked as a consumer and as an org with no AI; the questions discover what AI is used. `none` gets the AI policy and shadow-AI questions only. |
| **Producer / consumer** | Consumer: uses AI built by others (a vendor model, an API, AI inside products). Producer: builds or tunes its own model, from scratch or on an existing model, for itself or to give to others. Each question is tagged with the roles it is for; an organisation can be both. |
| **Producer details** | Two follow-up answers for an organisation that builds its own model: is it built on an existing model (then it gets questions about that base model), and is it given to others (then it gets questions about releasing it). Stored as `producer_flags` in the data. |
| **Covers note** | "This question covers: ..." on an area question that stands for several of the client's areas, naming only the client's own areas. |
| **Impact** | What could go wrong if an AI area is handled badly: `process` (a business process or decision goes wrong), `data` (data exposed, leaked or poisoned), `access` (permissions or credentials abused), `assets` (model, code or infrastructure stolen or damaged), `people` (harm to individuals). Each AI area and mapping row carries one or more; they shape the evidence asked for. Defined in `data/ai/question_rules.json`. |
| **Folded subcategory** | A subcategory that would get the same question as another row of the same AI area, so it is merged into that row instead of getting its own. The row's question must cite it. |
| **Required check** | A subcategory the rules say certain AI areas must always map, for example an audit trail and incident response for every area (`data/ai/mapping_rules.json` `required_checks`). |
| **Candidate CIS safeguards** | The CIS safeguards an AI area is allowed to cite as evidence (`data/ai/mapping_rules.json` `area_cis`). |
| **Generator / evaluator** | In the bank build one agent writes (questions, mapping rows, evidence lines) and a second, separate agent checks the result. One revision round at most; what still fails goes to a person. |
| **Needs human review** | An item the evaluator still failed after the revision round. It is kept, marked `needs_human_review`, and a person decides it in the review sheet. |
| **Decided by a person** | A line you changed in a review sheet (`decided_by: human`). Later agent runs never overwrite it. |
| **Review sheet** | A spreadsheet in `data/ai/authoring/` for checking or editing the mapping, the questions or the External AI threats (`sheet_io.py export` / `import`). |
| **Pending file / exit 2** | A script that cannot settle an item writes a `pending_*.json` and exits 2; an agent decides it and a recording script stores the answer. |
| **Recording** | Validating an agent's output file as a whole, storing it, and writing a write-once log of who decided what. A bad file is rejected and nothing is stored. |
| **Pilot** | A first AI bank run on a few hand-picked subcategories, reviewed by a person. Accepting it (`record_bank.py ai-accept-pilot`) approves the question generator and evaluator prompts; while they are unchanged, later rebuilds run without asking. |
| **Stale / incomplete** | Freshness report words. Stale: built from sources that have since changed. Incomplete: not every subcategory is in the bank yet (AI areas bank: or a mapping row changed after its questions were written). |
| **Run folder** | `runs/<Org>_<date>/`: everything one engagement produced. It holds client data. |
| **Profile XLS (Stage 2)** | The spreadsheet built from the answered questionnaire, one for CSF and one for AI RMF, with maturity scores. Not built yet. |
| **CSET, OLIR, Playbook, CIS guides** | CSET: CISA's assessment tool whose SQL holds the CSF questions: its CSF 2.0 standard (`NCSF_V2`, one per subcategory) and maturity-model questions mapped to CSF 2.0. OLIR: NIST's mappings between frameworks (ISO 27001 and PCI DSS to CSF). Playbook: the AI RMF's suggested actions. CIS guides: the CIS Controls v8.1 AI companion guides (LLM, MCP, agents). |
