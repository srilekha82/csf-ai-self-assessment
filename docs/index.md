# csf-ai-self-assessment

A self-assessment for cybersecurity and AI. You answer a short intake about your organisation, and the tool builds one
questionnaire (`questionnaire.xlsx`) with two sheets:

- **NIST CSF 2.0**: cybersecurity, tailored to your sector and the certifications you hold.
- **NIST AI RMF 1.0**: AI risk, tailored to how you use AI.

Setup and the quick start are in the [README](https://github.com/srilekha82/csf-ai-self-assessment#readme).

## The idea

The tool never writes questions on the fly. Questions are prepared once, checked, and stored in **question banks**.
Each assessment then **picks** the questions that fit the organisation.

```
Intake  →  pick from the banks  →  questionnaire.xlsx  →  answers (Stage 2)  →  maturity scores and reports (later)
```

- **CSF sheet.** The questions come from CISA's free assessment tool [CSET](https://github.com/cisagov/cset), one bank
  per sector. Your certifications decide how each question is asked: where ISO 27001 already covers something, you are
  asked to show evidence or what you do beyond it, instead of starting from scratch.
- **AI RMF sheet.** No ready-made question set exists, so the banks were generated from the NIST AI RMF Playbook, checked
  by a second AI agent and reviewed by a person. What you are asked depends on **how you use AI**, not on your sector.

### How the AI RMF sheet is tailored

The AI RMF has 72 **subcategories**: outcome statements grouped under four functions. GOVERN is about the organisation
as a whole; MAP, MEASURE and MANAGE are about specific AI systems.

The tool links them to **AI areas**: 14 ways AI is used or built.
- 6 usage areas: internal processes, code generation, customer-facing applications, vendor AI, model building,
  invisible (shadow) AI.
- 8 component areas: input, output, test and tuning data, the model, source data, MCP tools, agents, hosting.

From that:
1. **Every organisation using AI** gets the **foundation** questions: GOVERN, plus 12 other subcategories asked once
   for the organisation.
2. **Each AI area you tick in the intake** adds the MAP, MEASURE and MANAGE questions mapped to that area.
3. **Your role** decides which version of a question you see: you use AI (consumer), you build it (producer), or both.

## A small example

A bank runs a chatbot that answers customers. In the intake it ticks *"AI your customers or the public talk to or get
answers from"*. That is the **customer-facing** AI area.

| Step | What it is | Example |
|---|---|---|
| AI RMF statement | The official outcome, from NIST | **MEASURE 2.4:** "The functionality and behavior of the AI system and its components are monitored when in production." |
| Mapping row | What that statement means for this AI area | *Customer-facing × MEASURE 2.4:* production behaviour is monitored for abuse patterns, unusual answers and high-impact answers, with alerts. |
| Question | What the client is asked | "For your highest-criticality AI systems, how is the AI's behaviour with the public monitored in production, for example for abuse patterns or unusual answers? Who gets the alerts?" |
| Evidence asked for | What proves the answer | The monitoring rules and alert routing, the named alert recipients, and an extract from the latest monitoring review or alert. |
| Where it comes from | Sources behind the question | AI RMF Playbook, MEASURE 2.4 suggested actions 3 and 4; CIS LLM companion guide, safeguard 8.11 (Control 8, audit log management) |

The same bank also gets a foundation question for every AI user, for example for **GOVERN 1.1** (legal and regulatory
requirements):
> "Where are the legal and regulatory requirements that apply to your use or building of AI kept, and how do the people
> they apply to learn of them and of changes?"

On the CSF sheet, a question comes straight from CSET, for example for **GV.OC-01**:
> "Is the organizational Mission understood and does it inform cybersecurity risk management?"

The questions ask how something is done, by whom and with what proof, not just "do you have a policy?".

## Where each part lives

| Part | Where | What it is |
|---|---|---|
| Intake menus | `data/common/intake_options.json` | Sectors, certifications, AI usage choices |
| Intake answers | `runs/<Org>_<date>/csf_intake.json`, `ai_intake.json` | One folder per assessment. Holds client data, never committed. |
| CSF framework | `data/csf/csf2_core.json` | The 106 CSF 2.0 subcategories, from NIST |
| CSF question banks | `data/csf/banks/question_bank_<sector>.json` | CSET questions per subcategory, one file per sector |
| CSF tailoring rules | `data/csf/scope_rules.json`, `data/csf/crosswalks/` | How certifications change each question; the ISO 27001 and PCI DSS mappings to CSF |
| AI RMF framework | `data/ai/ai_rmf_core.json` | The 72 AI RMF subcategories and the Playbook's suggested actions |
| AI areas | `data/ai/authoring/ai_areas.xlsx` → `data/ai/ai_areas.json` | The 14 AI areas. A person decides them in the spreadsheet. |
| Mapping | `data/ai/mapping.json` (review copy: `data/ai/authoring/mapping.xlsx`) | Which AI RMF subcategories apply to each AI area, and why |
| AI RMF question banks | `data/ai/banks/` | Foundation questions and area questions |
| CIS safeguards | `data/ai/cis_ai_safeguard_ids.json` | CIS safeguard IDs a question may cite as evidence (IDs only, no CIS text) |
| Scripts | `scripts/` | Do the deterministic work: intake, picking questions, writing the workbook |
| AI agent instructions | `prompts/` | How each AI agent judges or writes when the banks are built |
| Commands | `.claude/commands/` | The steps you run in Claude Code, such as `/generate-questions` |
| Templates | `templates/` | The questionnaire layout each run fills in, and the empty CSF and AI RMF profile spreadsheets that Stage 2 will fill |
| Tests | `tests/` | Checks for the scripts |

## More detail

| Page | Read it to… |
|---|---|
| [Guide](guide.md) | run the tool: every command, script and data file, and a glossary |
| [Architecture](architecture.md) | see how the stages fit together: bank building, questionnaire, answers, reports |
| [AI RMF model](ai-rmf-model.md) | go deeper on the AI RMF design: AI areas, mapping, severity, question banks |

Rules for changing the code are in
[DESIGN_RULES.md](https://github.com/srilekha82/csf-ai-self-assessment/blob/main/DESIGN_RULES.md).
