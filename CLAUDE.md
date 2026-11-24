# csf-ai-self-assessment

Stage 1 of the assessment pipeline: one questionnaire (CSF 2.0, AI RMF 1.0 and External AI sheets) for a client. `docs/guide.md`
has the flow and file layout. **Before changing a script, prompt, command or data file, or adding a stage, read
`DESIGN_RULES.md`.** You do not need it to run the flows below.

## Running
- Always use the venv: `.venv/bin/python ./scripts/<script>.py` (create: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Run from the repo root.
- Unit tests (every change; they must pass): `.venv/bin/python -m unittest discover -s tests` (`test_*.py`; their own
  inputs, stores redirected to a temp dir; keep it that way). The AI tests read a frozen copy of the AI rules, areas
  and mapping (`tests/fixtures/ai/`, set up by `tests/ai_fixture.py`), so changing the real data does not break them.
  Run them before opening a pull request. GitHub Actions also runs them on every pull request and push to main by
  itself (`.github/workflows/unit-tests.yml`): never trigger or wait for it.
- Data checks (the committed banks and data files; at the end-to-end run, after a rebuild):
  `.venv/bin/python -m unittest discover -s tests -p "check_*.py"`.

## What to run
- **Generate questions:** `/generate-questions` (one numbered intake, CSF + AI RMF + External AI, one
  `questionnaire.xlsx`). Parts on an existing run folder: `/csf-questionnaire` (CSF sheet), `/ai-questionnaire` (AI RMF
  and External AI sheets).
- **Build or refresh the AI banks (AI RMF and External AI):** `/build-ai-bank` (pilot first; it needs the AI mapping accepted:
  `/ai-mapping` drafts it and you review and accept it, rarely redone). CSF banks: `/build-csf-bank`.
- **Questions about how something works or what a term means:** answer from `docs/guide.md` (it has an "I want to…" table
  and a glossary).
- **Maturity XLS (Stage 2):** the XLS writer and answer session are not built yet.

## Never
- Commit `runs/` or copy it into `data/`: it holds client data.
- Commit CIS text. The CIS guide PDFs (`data/ai/source/`) and the text parsed from them
  (`data/ai/cis_ai_safeguards.json`) stay on your machine; the CIS licence does not allow sharing them. The repo keeps
  only `cis_ai_safeguard_ids.json` (IDs, no text).
