# Architecture

How the parts fit together, for both frameworks. The tool runs in three stages, preceded by a bank-building step that
runs only when its sources change. Stage 1 is built; Stages 2 and 3 come later.

```
Bank building (occasional)  →  Stage 1: questionnaire  →  Stage 2: answers and scores  →  Stage 3: reports
built, reused by every run     built                       later                            later
```

## Bank building

Questions are prepared once, checked, and stored in banks that every assessment reuses. A bank is rebuilt only when a
source it was built from changes.

| | NIST CSF 2.0 | NIST AI RMF 1.0 |
|---|---|---|
| Source of the questions | CISA's [CSET](https://github.com/cisagov/cset): its own CSF 2.0 question set plus the maturity-model questions it maps to CSF, read from CSET's SQL files | The AI RMF Playbook's suggested actions. The CIS AI companion guides add the safeguards a question may cite as evidence. |
| How questions are made | Taken from CSET, never written. An AI agent only decides which sector each question suits and repairs wording. | Written by an AI agent, checked by a second agent, piloted and reviewed by a person |
| Banks | One per sector: `data/csf/banks/question_bank_<sector>.json` | Two: foundation (asked once per organisation) and areas (per AI area), in `data/ai/banks/` |
| Command | `/build-csf-bank` | `/build-ai-bank` |
| Rebuilt when | CSET changes a question | The Playbook or a CIS guide changes, or the mapping changes |

The AI RMF track needs one extra step first: a **mapping** that links each AI area to the AI RMF subcategories that
check it (`data/ai/mapping.json`, reviewed and accepted by a person). The full model is in
[AI RMF model](ai-rmf-model.md).

The AI RMF build also writes **AI impact notes** for the CSF side (`data/csf/ai_impact_notes.json`): a short note per CSF
subcategory on what AI changes there, so even an organisation with no AI of its own sees the AI threats it is exposed
to. Each note has two layers: an `exposure` note shown to every organisation, and a `use` note added only when AI is in
use (`mcp_agentic` for organisations with MCP tools or agents, `base_rag` for the rest). Stage 2 writes them into the
CSF profile's Considerations column.

## Stage 1: questionnaire (built)

One intake, two tailored sheets in one workbook.

| | CSF sheet | AI RMF sheet |
|---|---|---|
| Tailored by | Sector and certifications (ISO 27001, PCI DSS), plus the ISO 27001 Statement of Applicability if there is one | How the organisation uses AI: AI in use, role (uses or builds AI) and the AI areas ticked |
| How | Each subcategory gets a question type: `full_discovery`, `gap`, `confirmatory` or `skip`, depending on what the certifications already cover (`compute_scope.py`, `build_questions.py`) | Questions are filtered from the two banks by role and AI areas (`build_ai_questions.py`). All are `full_discovery`: they ask about AI, so certifications change nothing. |
| Command | `/csf-questionnaire` | `/ai-questionnaire` |

`/generate-questions` runs the whole stage: the intake (`intake.py`), a check that the banks are recent enough, then
the two sheets, which `write_questionnaire.py` writes into `runs/<Org>_<date>/questionnaire.xlsx`. The run
folder holds client data and is never committed.

## Stage 2 and Stage 3 (later)

Stage 2 will turn the answered questionnaire into two filled profile spreadsheets (`templates/`), one for CSF and
one for AI RMF, with maturity scores. Stage 3 will build reports from them. Both will be described here once they are
built.

## Key design principles

1. **The profile spreadsheet is the handoff.** Stage 2 writes it; reporting reads it. Its layout is fixed by the Stage 2
   writer.
2. **Questions come from banks, never written per assessment.** Banks are built from structured sources, checked, then
   frozen and reused.
3. **Every AI agent that writes is checked by another** that runs separately and sees only what it needs. Questions are
   reviewed once, when a bank is built; a client run only picks and checks them.
4. **Honest gaps.** An answer with no evidence must say so; a claim of coverage without a cited source is rejected.
5. **CIS safeguards show how to fix gaps, not how mature you are.** Maturity comes from the scores in the profile.
6. **Works for any organisation.** Nothing specific to one organisation is an input.

## Where it runs

Everything is in this repository and runs in Claude Code. Scripts do the deterministic work (`scripts/`); AI agents
judge or write only where a script cannot decide, following the instructions in `prompts/`. Rules for changing the code
are in `DESIGN_RULES.md`.
