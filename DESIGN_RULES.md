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
   script supplies only its validator and its store. Both bank builds: `record_bank.py` (one mode per kind of agent
   output; the checks live next to the data they guard: `build_csf_bank.py` for CSF, `ai_mapping.py`,
   `ai_questions.py`, `ai_notes.py` for AI RMF). A client run has no agent output: its scope and picks are fixed rules,
   and where a rule cannot be sure (an SoA exclusion) it asks in full rather than ask an agent.
5. **Everything is audited.** Every script calls `scripts/audit.py` (`begin`, then `finish` / `fail` / `pending`), which
   appends to the folder's `audit.jsonl`. Do not invent another logging scheme. Use `audit.write_once_record` for
   write-once records.
6. **Policy and content live in data files, not code.** Max questions per type, scope rules, categories, definitions,
   evidence hints, expected counts: `data/csf/*.json`, `data/ai/*.json`; facts both tracks share (intake menus, domains,
   certifications, question types) in `data/common/intake_options.json`. Changing a rule means editing JSON. Keep each
   constant in one place only: scripts import shared facts (read from those files) and paths from `scripts/config.py`;
   a script never defines its own copy of a domain list, function order or bank name.
   **Spreadsheet layouts live in `templates/`, not in code.** The questionnaire's sheets, headers, colours, widths and
   drop-downs are `templates/questionnaire_template.xlsx`, edited in Excel; `write_questionnaire.py` copies it into the
   run folder and only fills rows, writing each value under its header by name. Per client it only hides: the AI
   systems sheet when the inventory question (GOVERN 1.6) is not asked (AI in use "none"), and the AI area columns the
   client did not tick (all are shown for AI in use "unsure"). A test fails if the template no longer matches the data
   it shows (AI area labels, criticality bands, question headers).
7. **Every agent that writes is checked by another, in a fresh context** (a subagent with only the files it needs):
   questions, notes, mapping rows. The same loop everywhere: a verdict on every item, fail when unsure; one revision
   turn on the failures; round 2 judges only what changed (an unchanged item keeps its pass, and the recording script
   enforces it); two turns at most; what still fails goes to a person (a review sheet), whose decisions are never
   overwritten. An evaluator is never the same conversation that generated the draft.
   **Questions are reviewed once, when a bank is built, never per client run.** A client run only picks from the banks
   by fixed rules, so the picks are verified by tests (`tests/test_picks.py`, typical clients against the committed
   banks), not on every run. Never edit a run's drafts by hand: re-run the step that wrote them.
   **A client run never builds or rebuilds a bank.** It checks only the banks' age (`check_bank_age.py`,
   limits in `data/metadata.json`) and stops if one is missing or too old, naming the build command to run.
8. **Few scripts, small files, one job each.** Reuse by importing a shared helper when the logic is the same; do not
   copy it, and do not merge scripts that do different jobs. Add a script only for a genuinely new deterministic job, and
   do not split one job across scripts unless a step can pause for an agent. Add a command only for a repeated step.
9. **Handoff by files.** Each stage reads and writes a validated file and passes paths, not content. Print one summary
   line on success; keep detail in a file read only on failure. The intake is saved by `scripts/intake.py` as
   `csf_intake.json` and `ai_intake.json` in the run folder; later steps read those files and never ask or pass the answers
   again. The intake is asked as numbered choices; the script, not the agent, turns numbers into values.
   Temporary files (prepared inputs, agent drafts, verdicts) go in a gitignored `work/` folder
   (`data/ai/bank_build/work/`) and are deleted when the build ends; a client run's whole folder is gitignored.
   Only kept inputs, approvals and results are committed.
10. **Prompts and docs stand alone.** A prompt carries its own rules; it does not point to a design document. Shared
    definitions (AI areas in `data/ai/ai_areas.json`; roles, producer details and impacts in `data/ai/question_rules.json`)
    reach agents through the files scripts prepare.

## CSF track
- **CSF questions come from CSET only; they are never generated.** CSF is a mature practice: the
  bank holds CSET's own CSF 2.0 set (`NCSF_V2`, one question per subcategory, first) and the maturity-model questions
  CSET maps to CSF 2.0 (practice detail). A gap is closed by reading more of CSET, not by writing questions. A
  client run never rewords them; CSET's own CSF 2.0 question is always kept (`tests/test_picks.py` checks it).
  Only if the bank has no question for a subcategory does a client run ask the fixed fallback in `scope_rules.json`
  (built from NIST's outcome text); the run's summary counts these.
  The Evidence Required line is NIST's implementation examples for the subcategory, word for word; no agent
  writes it. The AI RMF track builds on CSF, not beside it.

## AI RMF track
How it works, with a small example (AI area → AI RMF statement → question): `docs/index.md`; the full model:
`docs/ai-rmf-model.md`. The rules:
- **Scope comes from how AI is used, never sector or certifications.** Sector only sets the minimum priority of findings.
- **Selection only filters** (role, producer details, AI areas). `pick_questions.py (--framework ai)` never ranks or rewrites.
- **Every AI question is `full_discovery`; there is no gap rule.** AI questions never repeat what the
  CSF sheet or ISO 27001 covers.
- **Ask about practice, not checkboxes** (how, who, how often, what evidence). A policy is asked as practice: where it
  is kept and how people learn about it.
- **Sources:** the Playbook sets what good looks like (fairness, bias and explainability come from it only); CIS guides
  give evidence only, never question text; the CIS → CSF mapping is used only for the AI impact notes. OWASP LLM Top 10
  is not a source.
- **Read CIS safeguard IDs as text.** The CIS xlsx stores them as numbers, so 4.10 becomes 4.1. The guide tables drop
  IDs: rebuild them from the control number and row order.
- **The maintainer rebuilds a bank when a source it was built from changed, or when it passes its age limit.** Editing a
  prompt only marks it stale. The pilot (`record_bank.py ai-accept-pilot`) is the one human gate.
- **AI impact notes only for CSF subcategories with a mapped CIS safeguard;** never invented.
- **Profile XLS schemas are fixed by the Stage 2 writer;** reporting reads them as they are.
