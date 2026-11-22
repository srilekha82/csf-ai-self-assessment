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
- Write the two profile XLS files (`templates/`).

## Stage 3: reports — rebuild after Stage 2
One report per profile XLS (CSF, AI RMF) and a page linking both, built from scratch.

## For the reviews
- Prompt review: the GOVERN 1.2 question asked of AI in use "none" assumes an AI policy exists ("when an AI policy or
  procedure is written or revised ..."); an organisation with no AI may have none.
- Docs refactor: each fact in one place. A script's own header (what it does, Called by / Input / Output, how to run
  it) and the guide's diagrams (how the scripts fit together); the guide's step lists and tables point to them instead
  of repeating them.

## Parked
- Unit tests for each `compute_scope.py` state (today it is tested end to end, through `tests/test_picks.py`'s five
  typical clients, and for its SoA judgement checks).
- With the prompt review: store review reasons in the AI banks as a list per question instead of one joined text
  (removes about 40 lines of splitting and joining in `ai_questions.py`).
