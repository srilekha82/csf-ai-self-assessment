# TODO

## Stage 1: questionnaire — done
CSF and AI RMF banks built; `/generate-questions` writes one `questionnaire.xlsx` (CSF sheet + AI RMF sheet).

## Stage 2: answers → profile XLS — next
- Freeze the Stage 1 → Stage 2 contract first: questionnaire columns, question ids, answer format.
- Inputs: the ISO SoA, the org's documents (policies, AI governance document, operating records) and a knowledgeable
  person's answers.
- Test data: a generator of fictitious companies (`tests/generator/`), with outputs and their `truth.json` under
  `tests/fixtures/companies/<name>/`. The pipeline never imports it. Build one company end to end first.
- Answer flow: ingest documents with metadata, retrieve per question, extract cited claims, draft the answer or record
  "no evidence found", evaluator check, confidence computed by a script, confirmation by control owners.
- Scoring on the templates' 1–4 scale; the evidence kind (intent, design, operation, measurement) caps the level.
- Write the two profile XLS files (`templates/`). The AI RMF profile's Priority column comes from
  `scripts/ai_priority.py` (rules in `data/ai/severity_rules.json`, from the client's AI systems sheet).

## Stage 3: reports — rebuild after Stage 2
One report per profile XLS (CSF, AI RMF) and a page linking both, built from scratch.

## Script review
Goal: simpler, easier to maintain, understandable on a first read. 24 scripts.

**Reviewed and finalised (12):** `intake.py`, `config.py`, `audit.py`, `parse_soa.py`, `parse_csf_source.py`,
`parse_ai_rmf_sources.py`, `extract_cset_candidates.py`, `record_bank.py`, `check_bank_age.py`, `check_freshness.py`,
`write_questionnaire.py`, `sheet_io.py`. Also `ai_priority.py` (kept for Stage 2).

**Now: client run**
1. `check_questionnaire.py`
2. `compute_scope.py`
3. `build_questions.py` with `build_ai_questions.py`: decide whether they become one `pick_questions.py` (both pick a
   client's questions from a bank).

**Later: bank building, as one block, with `/build-csf-bank`, `/build-ai-bank` and their prompts**
- CSF: `build_question_bank.py`. Open: split `route_pairs` into "what does the question still need from the agent"
  and "route it"; drop `iso_mapping` from the banks (a copy of the crosswalk, never read).
- AI: `prepare_ai_bank.py`, `prepare_ai_notes.py`, `ai_bank_common.py`, `ai_mapping.py`, `ai_questions.py`,
  `ai_notes.py`. Open: fold `prepare_ai_notes.py` into `prepare_ai_bank.py` (both prepare an agent's input).
- Prompts: `ai_rmf_evidence_evaluator.md` still mentions the removed per-run reviewer; the GOVERN 1.2 question asked
  of AI in use "none" assumes an AI policy exists ("when an AI policy or procedure is written or revised ...").
- Descriptions that still name old scripts, updated when those files are next written: `data/ai/mapping_rules.json`
  (fingerprinted by the mapping approval: edit only with a re-approval), `data/ai/mapping.json`, the AI banks.

**After the reviews**
- Docs refactor: each fact in one place. A script's own header (what it does, Called by / Input / Output, how to run
  it) and the guide's diagrams (how the scripts fit together); the guide's step lists and tables point to them instead
  of repeating them.

## Parked
- Unit tests for each `compute_scope.py` state (today it is tested end to end, through `check_questionnaire.py`'s
  tests, and for its SoA judgement checks).
- With the prompt review: store review reasons in the AI banks as a list per question instead of one joined text
  (removes about 40 lines of splitting and joining in `ai_questions.py`).
