# Design rules for csf-ai-self-assessment

Read this when you change the design: add or change a script, prompt, command or data file, or add a track or stage. It is
not needed to run the flows (`CLAUDE.md` covers that). `docs/guide.md` explains the flow and the file layout.

## Design rules (apply to every script, prompt and command)
1. **Scripts never decide.** They parse, join, look up, validate, format, hash and write. A script that cannot settle an
   item writes a `pending_*.json` and exits 2; it never guesses. Judgement goes to an agent.
2. **Agents see only the pending items,** as compact JSON a script prepared. Never hand an agent a PDF, a full bank or a
   crosswalk. Parse sources into JSON first.
3. **Agents return patches, not full lists.** Output tokens are the expensive ones. The agent returns only the entries it
   changed (or only new entries); a script validates and merges them.
4. **A recording script is the only door for agent output.** The agent hands in a file; the script validates the WHOLE
   file, rejects it if anything is wrong (exit 1, nothing stored), otherwise stores it and writes a write-once record
   (model, prompt hash, input hash, output snapshot). The contract lives once, in `audit.record_agent_output`; a recording
   script supplies only its validator and its store. CSF: `record_judgements.py`. AI RMF: `record_ai_bank.py`
   (mapping, questions, notes), and `record_judgements.py log --base --patch` for patch steps.
5. **Everything is audited.** Every script calls `scripts/audit.py` (`begin`, then `finish` / `fail` / `pending`), which
   appends to the folder's `audit.jsonl`. Do not invent another logging scheme. Use `audit.write_once_record` for
   write-once records.
6. **Policy and content live in data files, not code.** Max questions per type, scope rules, categories, definitions,
   evidence hints, expected counts: `data/csf/*.json`, `data/ai/*.json`; facts both tracks share (intake menus, domains,
   certifications, question types) in `data/common/intake_options.json`. Changing a rule means editing JSON. Keep each
   constant in one place only: scripts import shared facts from `scripts/options.py` (which reads those files) and
   paths from `scripts/paths.py`; a script never defines its own copy of a domain list, function order or bank name.
7. **Every agent that writes is checked by another, in a fresh context** (a subagent with only the files it needs):
   questions, notes, mapping rows, and the questionnaire reviewers' rewrites (`prompts/assessor_rewrite_checker.md`).
   The same loop everywhere: a verdict on every item, fail when unsure; one revision turn on the failures; round 2
   judges only what changed (an unchanged item keeps its pass, and the recording script enforces it); two turns at
   most; what still fails goes to a person (a review sheet, or a LOW flag in the questionnaire), whose decisions are
   never overwritten. An assessor is never the same conversation that generated the draft. (Decided 2026-10-31.)
8. **Few scripts, small files, one job each.** Reuse by importing a shared helper when the logic is the same; do not
   copy it, and do not merge scripts that do different jobs. Add a script only for a genuinely new deterministic job, and
   do not split one job across scripts unless a step can pause for an agent. Add a command only for a repeated step.
9. **Handoff by files.** Each stage reads and writes a validated file and passes paths, not content. Print one summary
   line on success; keep detail in a file read only on failure. The intake is saved by `scripts/intake.py` as
   `intake.json` and `ai_usage.json` in the run folder; later steps read those files and never ask or pass the answers
   again. The intake is asked as numbered choices; the script, not the agent, turns numbers into values.
10. **Prompts and docs stand alone.** A prompt carries its own rules; it does not point to a design document. Shared
    definitions (AI areas in `data/ai/ai_areas.json`; roles, producer flags and impacts in `data/ai/question_rules.json`)
    reach agents through the files scripts prepare.

## CSF track
- **CSF questions come from CSET only; they are never generated** (decided 2026-11-02). CSF is a mature practice: the
  bank holds CSET's own CSF 2.0 set (`NCSF_V2`, one question per subcategory, first) and the maturity-model questions
  CSET maps to CSF 2.0 (practice detail). A gap is closed by reading more of CSET, not by writing questions. The
  questionnaire reviewer may reword a CSET question or remove an off-topic one, never add one or drop the CSF 2.0
  question (`record_judgements.py` rejects it). Evidence prompts are not questions: each subcategory gets one, written
  once from NIST's implementation examples and checked by an evaluator. The AI RMF track builds on CSF, not beside it.

## AI RMF track

In one line: **how an organisation uses AI decides which AI RMF questions it gets.** The questions come from two
pre-built banks; a script filters them for each client. The full model (AI areas → attack areas → AI RMF function →
subcategory) is in `AI_RMF_Mapping_Sheet_Design.md`.

### What decides the questions
- **How AI is used, not sector or certifications.** Sector never changes which questions are asked. It only sets a
  minimum priority for findings (healthcare and manufacturing / OT, where loss of life is possible) and appears in the
  report.
- **The intake asks it once.** `intake.py` writes it to `runs/<Org>_<date>/ai_usage.json` (with `intake.json` for org,
  domain and certifications). Every later step (CSF, AI RMF, the XLS writer) reads these files. It holds:
  - AI in use: `none`, `some` or `unsure`
  - role: `consumer`, `producer` or `both`; for a producer, whether the model is built on an existing model and whether
    it is given to others
  - the client's **AI areas**: ticked in two intake menus, plus automatic ones (`scope_rules.json` `ai_area_rules`). The
    list of AI areas is decided by a person in `data/ai/authoring/ai_areas.xlsx`.
  - engagement flags: CSF assessment done, ISO 27001 held (worked out from the certifications, never asked twice), ISO
    42001 held
- **What each answer to "AI in use" gets:**

  | AI in use | Asked as |
  |---|---|
  | `some` | the role(s) they gave, filtered by their AI areas |
  | `unsure` | a consumer and an org with no AI: the questions find out what AI is used (`scope_rules.json` `client_roles`) |
  | `none` | only questions tagged `none` (AI policy, shadow-AI discovery) and the "invisible AI usage" area |

  The AI RMF profile XLS always has all 72 subcategories, whatever is asked.
- **One questionnaire.** `/generate-questions` asks the intake once and writes one `questionnaire.xlsx` with a CSF sheet
  and an AI RMF sheet. The client never sees a separate AI deliverable. In Stage 2 the two sheets become two profile XLS
  files.

### The two banks
- **Foundation bank:** questions asked once for the whole organisation: GOVERN, plus the subcategories listed in
  `mapping_rules.json` `foundation.subcategories`.
- **Areas bank:** questions per mapping row (one AI area × one MAP, MEASURE or MANAGE subcategory). One question may
  cover several rows of the same subcategory; it then names no single area.
- **Each question is tagged** with the roles it is asked of (`none` / `consumer` / `producer`) and any producer flags
  (`question_rules.json`). `record_ai_bank.py questions` checks every row is asked once per role its area allows (twice
  at most, when the row covers two practices).
- **Selection only filters.** `build_ai_questions.py` picks by role, producer flags and AI areas. It never ranks or
  rewrites. Area questions are asked once, scaled to the most critical systems, never once per AI system.
- **Every AI question is `full_discovery`; there is no gap rule** (decided 2026-10-29). Each question is about AI, so it
  never repeats what the CSF sheet or ISO 27001 covers, and the SoA and engagement flags change nothing. A client may
  cite a general control as evidence; the assessor checks that it actually reaches the AI. ISO 42001 is not used until
  its crosswalk is verified.

### Writing questions
- **Ask about practice, not boxes.** How, who, how often, what evidence; never "do you have a policy". A policy is asked
  as practice: where it is kept and how people learn about it.
- **Sources:** the AI RMF Playbook says what good looks like (including fairness, bias and explainability, which come
  from the Playbook only). The three CIS companion guides give safeguards a question may cite as evidence, never
  question text. The CIS → CSF mapping is used only for the AI impact notes. OWASP LLM Top 10 is not a source.
- **Read CIS safeguard IDs as text.** The CIS xlsx files store them as numbers, so 4.10 becomes 4.1. The guide tables
  also drop IDs: rebuild them from the control number and row order.

### Rebuilding the banks
- **Rebuild only when something it was built from changed:** a bank is missing or incomplete, or a source file changed
  (CSF: the CSET migration SQL; AI: the Playbook, the CIS guides, the CIS → CSF mapping). Editing a prompt or
  `question_rules.json` only marks the stage stale; it never starts a rebuild.
- **How staleness is checked:** each output records the SHA-256 of the files it was built from. `check_freshness.py
  --ai-bank` compares them with the files on disk. A stage is current only if it exists, matches the sources and is
  complete (the areas bank covers the mapping rows as they are now). There is no separate stamp to update.
- **The pilot is the one human gate.** `ai_pilot.py accept` stores the hashes of the generator and evaluator prompts.
  Only while those match may a missing or incomplete bank be rebuilt without asking.
- **At the start of a run**, `check_freshness.py --all` reports CSF and AI together. The CSF bank is stale when the CSET
  SQL changed upstream (it runs `git fetch` and reports a failure rather than hiding it). It only states facts; the
  calling command decides what to rebuild.

### Other
- **AI impact notes** (`data/csf/ai_impact_notes.json`, one per CSF subcategory) add AI context to the CSF profile, in
  two layers:
  - `exposure`: shown to every organisation
  - `use`: shown only when AI is in use (`mcp_agentic` when the client has MCP / tools or agents, else `base_rag`)

  Notes are written only for CSF subcategories with a mapped CIS safeguard; the rest are listed, never invented. The
  Stage 2 XLS writer puts them in the CSF profile's Considerations column (not built yet).
- **Profile XLS schemas are fixed by the Stage 2 writer** (AI RMF: 11 columns; CSF: 19 columns on "Current and Target
  Profile"); reporting reads them as they are.
