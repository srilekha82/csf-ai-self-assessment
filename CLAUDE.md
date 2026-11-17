# csf-ai-self-assessment

Stage 1 of the assessment pipeline: one questionnaire (CSF 2.0 sheet + AI RMF 1.0 sheet) for a client. `docs/guide.md`
has the flow and file layout. **Before changing a script, prompt, command or data file, or adding a stage, read
`DESIGN_RULES.md`.** You do not need it to run the flows below.

## Running
- Always use the venv: `.venv/bin/python ./scripts/<script>.py` (create: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Run from the repo root.
- Tests: `.venv/bin/python -m unittest discover -s tests` (stores are redirected to a temp dir; keep it that way).

## What to run
- **Generate questions:** `/generate-questions` (one numbered intake, CSF + AI RMF, one `questionnaire.xlsx`). Parts on an
  existing run folder: `/csf-questionnaire` (CSF sheet), `/ai-questionnaire` (AI RMF sheet).
- **Build or refresh the AI RMF banks:** `/build-ai-bank` (pilot first). CSF banks: `/build-csf-bank`.
- **Questions about how something works or what a term means:** answer from `docs/guide.md` (it has an "I want to…" table
  and a glossary).
- **Maturity XLS (Stage 2):** the XLS writer and answer session are not built yet.

## Never
- Commit `runs/` or copy it into `data/`: it holds client data.
- Commit CIS text. The CIS guide PDFs (`data/ai/source/`) and the text parsed from them
  (`data/ai/cis_ai_safeguards.json`) stay on your machine; the CIS licence does not allow sharing them. The repo keeps
  only `cis_ai_safeguard_ids.json` (IDs, no text).
