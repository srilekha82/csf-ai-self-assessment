# AI RMF assessment model and mapping

The model the AI RMF track is built on: **how AI is used and what the AI is made of (AI areas) -> what a failure
there harms (impacts) -> questions per AI RMF function -> maturity per AI RMF subcategory**. Start every design
discussion from this page.

## 1. AI areas: the decision, in a spreadsheet
`data/ai/authoring/ai_areas.xlsx` is written by a person and is the decision. `scripts/sheet_io.py import ai_areas`
checks it and writes `data/ai/ai_areas.json`, which scripts and agents read. Columns: ID, AI area, Kind, Applies to,
Impact, What it covers, Example question (spreadsheet only).

| AI area | Kind | Applies to | Impact |
|---|---|---|---|
| Internal process | usage | both | process, data |
| Code generation (AI-specific part only; secure development is assessed by the CSF) | usage | both | assets, data |
| Customer-facing application | usage | both | process, data, people |
| Vendor AI (vendors and products running AI on the org's data: Jira, Slack, ServiceNow, GitHub, RPA) | usage | both | data |
| Model building (owning a model, built from scratch or on an existing one: purpose and design, evaluation before use, the base model, release to others) | usage | producer | assets |
| Invisible AI usage (unapproved inside, or others' agents, MCP clients and scrapers reaching in) | usage | both | data, access |
| Input | component | both | data |
| Output (wrong answers that are then trusted: steered by an attacker, or simply inaccurate, inconsistent or drifting) | component | both | process, people |
| Test, tuning and evaluation data (including the harness reliability is measured with, and feedback reused for tuning) | component | producer | data, assets |
| Model (as IP) | component | producer | assets |
| Source data (RAG / knowledge graph; includes data classification) | component | both | data, access |
| MCP / tools (hosted inside or used from outside; an outside server is also a supplier) | component | both | access, process, data |
| Agent | component | both | access, process, data |
| Hosting (a model the org hosts, as a producer or for a proof of concept) | component | both | assets |

- **Kind:** usage is a way AI is used (or used around the organisation); component is a part of the AI ecosystem.
- **Impact** is what a failure harms: **data** (exposed, leaked, poisoned), **access** (permissions and credentials
  used or abused), **process** (a business process or decision goes wrong), **assets** (model, code or infrastructure
  stolen, damaged or taken down), **people** (harm to individuals from what the AI says or decides). People harm is set
  where AI output reaches people directly (customer-facing, output); for agents, MCP tools and the model it is
  secondary and not listed. Defined in `data/ai/question_rules.json` `impacts`.
- GOVERN is the foundation and is not mapped to AI areas (section 3).
- General security (CSF, ISO 27001) is not asked again: every AI question asks what is done for the AI area or for AI
  in the organisation (section 7).

## 2. Intake: the client's AI areas
The intake asks only what the organisation has; every control is assessed by the questions.
- AI in use: none / some / unsure.
- "Do you build AI, use AI, or both?" (consumer / producer / both). Build or both brings the producer areas (model
  building, model, test / tuning / evaluation data) and two producer details: "Is your model built on an existing
  model?" (turns on the base-model questions, e.g. GOVERN 6.1, MANAGE 3.2) and "Do you give the model to others?"
  (turns on the release questions: clients, partners, an API, devices, open weights).
- "How do you use AI?" (pick all): internal process, code generation, customer-facing application, vendor AI.
- "What does your AI include?" (pick all): RAG / knowledge graph, MCP / tools, agents, a model you host.

`intake.py` writes the client's areas to `ai_intake.json` (`ai_areas`): the ones ticked, plus the automatic ones in
`data/ai/scope_rules.json` `ai_area_rules`:
- always (even with no AI in use): invisible AI usage
- any AI in use: input, output
- role producer or both: model building, model, test / tuning / evaluation data; agents add MCP / tools.

`ai_intake.json` holds `role`, `producer` (`built_on_existing_model`, `given_to_others`; null for a consumer) and
`ai_areas`. Question selection reads these (section 7).

## 3. Controls: GOVERN is the foundation; MAP, MEASURE and MANAGE are asked per AI area
The Playbook's own statement of each function (parsed into `data/ai/ai_rmf_core.json` `functions[].description`) is
the guide:

| Function | Playbook statement | What it is here |
|---|---|---|
| GOVERN | Policies, processes, procedures and practices across the organization related to the mapping, measuring and managing of AI risks are in place, transparent, and implemented effectively. | **Foundation**: how the organisation works with AI (policies, roles, inventory, culture, third parties). It defines how MAP, MEASURE and MANAGE are done. Not mapped to an area. |
| MAP | Context is established and understood. | **Context**: the AI areas applied to the organisation's systems, processes, assets and data; reach, components, purpose, risks and impacts. |
| MEASURE | Appropriate methods and metrics are identified and applied. | **Operations, checking**: the area's risks tested, evaluated and monitored (security, reliability, safety, fairness, privacy). |
| MANAGE | AI risks based on assessments and other analytical output from the Map and Measure functions are prioritized, responded to, and managed. | **Operations, responding**: risks prioritised and treated (access control, encryption, separation), switched off, incidents responded to, rectified and recorded. |

- **Foundation: all 19 GOVERN subcategories**, asked once for the organisation, not through an AI area. A GOVERN
  question does not depend on which AI areas the client has. Its questions are written per subcategory in the bank
  build and picked at engagement time by role: none, consumer, producer (both = consumer and producer; a producer
  detail where needed, e.g. GOVERN 6.1 when built on an existing model). `foundation` in `data/ai/mapping_rules.json`.
- **Foundation: 12 MAP, MEASURE and MANAGE subcategories** about how the organisation runs AI risk management, where
  every area would give the same answer: MAP 1.3 (mission), MAP 1.5 (risk tolerance), MAP 3.4 (proficiency and
  training), MEASURE 1.1 (choosing the risks and metrics to measure), MEASURE 1.2 (are the metrics and controls still
  effective), MEASURE 3.1 (tracking new risks), MEASURE 3.2 (tracking risks that are hard to measure), MEASURE 4.1
  (measurement feedback), MANAGE 1.2 (risks prioritised), MANAGE 1.3 (responses planned), MANAGE 1.4 (accepted
  residual risks) and MANAGE 2.1 (resources). They keep their AI RMF id, are asked once for the organisation like
  GOVERN, are left out of the drafter's input and the mapping review sheet, and the recording script rejects them as
  area rows (`foundation.subcategories`). Per area on purpose: MAP 1.1 (purpose), MANAGE 1.1 (go / no-go), MAP 1.2
  (who is involved and whether they can spot bias depends on the area), MAP 1.4 (business value, asked with the area's
  impact) and MEASURE 4.3 (performance and drift of a model).
- **A question = one AI area x one mapped function**, landing on one AI RMF subcategory. The function is not in the AI
  area sheet: a script crosses every area with MAP, MEASURE and MANAGE and the drafter fills each pair (or marks it "no
  question" with a reason). The recording script rejects a GOVERN row. The AI RMF has no "protect" function: access
  control and encryption are risk treatments (MANAGE) and are checked in MEASURE 2.7. Audit trails sit in MEASURE 2.8
  and MANAGE 4.1.

Sample, AI area "Source data (RAG / knowledge graph)":
| Function | Subcategory | CIS safeguards (lowest IG) | Impact |
|---|---|---|---|
| MAP | MAP 4.1 data sources and rights | LLM-3.1 (IG1) | data |
| MEASURE | MEASURE 2.10 privacy | LLM-3.7 (IG2), LLM-3.14 (IG3) | data |
| MEASURE | MEASURE 2.7 security | LLM-3.3 (IG1), LLM-3.12 (IG2) | access |
| MANAGE | MANAGE 2.4 disengage | LLM-3.3 (IG1) | access |

### Required checks
Some checks must exist for every AI area they apply to, so they cannot depend on the drafter remembering them. They are
in `data/ai/mapping_rules.json` `required_checks`, and the recording script rejects a mapping that misses one (for
example "agent: no audit-trail row").

| Check | For | Must have a row on | Citing |
|---|---|---|---|
| Audit trail | every AI area | MEASURE 2.8 or MANAGE 4.1 | a CIS control 8 (audit log) safeguard |
| Incident response | every AI area | MANAGE 2.3 or MANAGE 4.3 | CIS control 17 where linked |
| Reliability: accuracy and consistency | Output | MEASURE 2.5 | Playbook practices; CIS where linked |
| Reliability: monitored in use | Output | MEASURE 2.4 or MANAGE 4.1 | Playbook practices; CIS where linked |
| Reliability: test sets and harness documented | Output | MEASURE 2.1 | Playbook practices; CIS where linked |

Reliability (accuracy, consistency, drift, bias in answers) is checked at Output for consumers and producers alike:
components are the nouns that fail, usage areas the verbs, and wrong answers are where an unreliable model does harm.
Reliability under attack (prompt injection, poisoned answers) is part of Output and Source data and is checked in
MEASURE 2.7 like other security. The harness as data to protect is the Test, tuning and evaluation data area. The
inventory is not a per-area check: it is GOVERN 1.6, foundation, asked once. CIS controls 1 and 2 stay candidates in
every area for MAP rows on the area's components.

## 4. Severity: priority of findings (does not change which questions are asked)
For Stage 2: `scripts/ai_priority.py` with `data/ai/severity_rules.json` gives each subcategory a priority (High /
Medium / Low) for the profile's Priority column.
- **A system's criticality** comes from the client's AI systems sheet (below): the highest level among its answers.
  Financial loss: under USD 100k Low, 100k to 500k Medium, over 500k High. Reputational damage: none Low, local
  Medium, public or regulatory High. Possible harm to people: yes High. A blank answer counts High: not being able to
  answer is itself a gap.
- **Area subcategories** take the highest criticality among the systems marked with an AI area whose row (or a row
  that folds it) reaches the subcategory. **Foundation subcategories** take the highest system overall. An area no
  system is marked with, or no inventory at all, is High.
- **Domain floor:** in healthcare and manufacturing / OT loss of life is possible, so subcategories reached through a
  row with a people impact, and MEASURE 2.6 (safety), are always High.
- In AI RMF harm terms (NIST AI 100-1, section 1.1, Figure 1): financial and reputational loss is **Organization**,
  loss of life and harm to individuals is **People**, supply chain and environment is **Ecosystem** (not used).
- Data classification is not an input yet.

### Per AI system, without repeating questions
Assessing per AI system (GOVERN 1.6 inventory, MAP 1.1 context per system) does not mean asking every area question
once per system. The areas already describe what systems are made of, so:
- **Inventory in the foundation (GOVERN 1.6):** one question lists the client's AI systems, each with its AI areas and
  its criticality. It is the only per-system question, answered in its own "AI systems" sheet of the questionnaire:
  one row per system, a Yes column per AI area by its client label (only the client's own areas are shown; all of them
  for AI in use "unsure"), and a drop-down per criticality band (`question_rules.json` `ai_system_inventory`). The
  question only points to the sheet. AI in use "none" is not asked it, so the sheet is hidden.
- **Area questions are asked once per area x subcategory**, proportionate to criticality: "for your
  highest-criticality AI systems, ...".
- **Maturity (GOVERN 1.3, risk management proportionate to risk):** low = no difference between systems; middle =
  practices differ by criticality on paper; high = practices differ by criticality and are evidenced for the
  high-criticality systems.
- **Severity:** a gap on an area used by a high-criticality system ranks higher than the same gap elsewhere.

## 5. The mapping
Rows per AI area: AI RMF function -> subcategory, the CIS safeguards that can serve as evidence, impact, why. There is
no row count: an area gets a row for every subcategory that really checks it (each at most once), and the evaluator
fails padding.
- Answers are scored per AI RMF subcategory (the 72-row profile), like CSET questions mapping to CSF subcategories. AI
  areas and impacts are report views on top; nothing counts twice. How answers become scores is Stage 2.
- Coverage: 31 subcategories are foundation (19 GOVERN and 12 others); the other 41 are reached by area rows or folds.
  Today the mapping has 14 areas and 208 rows and reaches all 72. A subcategory no area reaches is allowed and listed
  (the Coverage sheet, and the `mapping` line of `check_freshness.py --ai-bank`).
- An area's candidate CIS safeguards come from the guides and controls listed for it in `mapping_rules.json`
  `area_cis` (plus `always_cis_controls`). 28 of the 41 area subcategories have at least one CIS safeguard on a row;
  the rest rely on Playbook practices alone.

## 6. Pipeline
1. AI areas spreadsheet (person) -> `sheet_io.py import ai_areas` -> `ai_areas.json`.
2. `prepare_ai_bank.py mapping --area ID` crosses the area with MAP, MEASURE and MANAGE and prepares a compact input:
   the area, the other areas of the sheet (id, name, applies to, covers) so the agents can leave out what belongs to
   another area, the Playbook definition of each function, the subcategories of each mapped function with suggested
   actions, and the candidate CIS safeguards.
3. The drafter agent goes through every MAP, MEASURE and MANAGE subcategory and writes a row for each that checks the
   area: subcategory, safeguards (from the candidates; empty only when none fits), impact, why. One area at a time.
4. The evaluator agent (fresh context) goes through every subcategory too and returns findings only, each with a kind:
   `row` (a row fails), `missing` (a subcategory that should be a row, named), `note` (a remark that does not block,
   e.g. the area's impacts look too narrow; the person decides the areas). One revision turn.
5. `record_ai_bank.py mapping` (checks in `ai_mapping.py`) validates the whole file (ids, safeguards from the
   candidates, impacts belong to the area, required checks met, every function has rows or a reason), stores the
   mapping JSON and a write-once record.
6. The mapping goes to a spreadsheet for review (`sheet_io.py export mapping` -> `data/ai/authoring/mapping.xlsx`): one
   line per AI area x MAP, MEASURE or MANAGE subcategory, mapped or not, with the Playbook outcome and safeguard titles,
   so missing subcategories are visible, plus a Coverage sheet (subcategory x area). The person edits; `import mapping`
   checks every area like agent output and stores changed lines as `decided_by: human`. A failed row and a `missing`
   line show Status needs_human_review with the evaluator's note; a `missing` line is decided by mapping it or by
   setting Status to pass (stored once per area, so it does not flag the area's other rows).
   **Folds:** when the drafter merges two subcategories into one row, the row lists the other in `folded`. The sheet
   shows it as a note on the Why cell of both lines and in an editable "Folded into this row" column; clearing a
   subcategory there unfolds it. A folded subcategory counts as reached: it is asked and scored through the row it is
   folded into, so a fold is allowed only when that row's question fully asks the folded outcome. A row with folds
   cannot be set to Mapped = no until its folds are mapped on their own lines.
7. Approval (person): `ai_pilot.py accept-mapping`, tied to a fingerprint of the mapping's content; the `mapping` line
   of `check_freshness.py --ai-bank` reports it. A re-drafted area keeps the person's decisions, and the merged area is
   checked against the rules again before it is stored. **A change is a delta:** an area is re-drafted only when its
   own row in the AI areas sheet or the sources change; when only the mapping rules or other areas change,
   `record_ai_bank.py revalidate` checks every recorded area against the current rules (no agent), marks the ones that
   pass current and lists the problems of the rest.
8. Questions (generator, evaluator) -> the foundation and area banks (section 7).

Regeneration is per subcategory: an area subcategory whose mapping rows changed is shown incomplete by the freshness
check.

## 7. Questions: two banks of every possible question; selection is a filter
- **The bank is every possible question, not a questionnaire.** `question_bank_ai_rmf_foundation.json`: per foundation
  subcategory (GOVERN and the 12), 1 to 4 questions from the Playbook. `question_bank_ai_rmf_areas.json`: per
  subcategory with mapping rows, the questions for those rows. Every question carries `roles` (`none`, `consumer`,
  `producer`) and the producer details it needs (`producer_flags` in the data: `built_on_existing_model`,
  `given_to_others`), defined in `data/ai/question_rules.json`.
- **Area questions.** Each mapping row is asked by one question per role its area allows (the area's applies to, plus
  `none` for invisible AI usage, which every client gets), or by two when its why holds two different practices
  (`question_rules.json` `row_questions`). A question asks the core of the row's why: one practice, details only as
  "for example", no purpose clauses, at most one short follow-up. Proportionate to criticality ("for your
  highest-criticality AI systems, ..."), optional for code generation, vendor AI, model building, model,
  test / tuning / evaluation data and invisible AI usage (`criticality_frame_optional`), never once per AI system. A
  row with folded subcategories also asks their outcomes. One question per role only where good practice differs (a
  producer controls training, a consumer only what it accepts); a producer detail only when the whole row applies
  only to producers with it.
- **Similar rows share one question, no cap.** The generator's batch is one item per subcategory with every area's row
  on it, so it writes one question for rows that would get the same question and lists their row ids. A shared
  question names no area and must read correctly for each area alone; the questionnaire shows "This question covers:
  <the client's areas>" (`scope_rules.json` `covers_note`), and the one answer counts for every row it covers. Rows
  share only when they check the same single practice; the shared question does not add up each row's details.
- **Client labels** (`data/ai/area_client_labels.json`): area id -> the plain label the client sees (covers note, Area
  column, the GOVERN 1.6 inventory sheet). Ids and names stay for experts, agents and scripts; a label is client text
  only and never makes the mapping or a bank stale.
- **Foundation questions.** 1 to 4 per subcategory, plus one asked of producers only where their practice really
  differs (e.g. GOVERN 1.2: standards for training their own models); a consumer is never asked more than 4. At least
  one consumer and one producer question without producer details per subcategory (both are scored on all 72). `none`
  only for the AI policy and shadow-AI discovery. A policy is asked as practice: where it is kept and how the people it
  applies to come to know it and its changes, never whether it exists. GOVERN 1.6 is the AI system inventory (section
  4).
- **Evaluator consistency:** the evaluator writes a verdict on every check of every question, not only failures, and
  quotes the start of the question each verdict is for, so a verdict cannot land on the wrong question. Round 2 gets
  round 1's questions and verdicts; an unchanged question that passed keeps its pass except on checks 6 and 7 (clash or
  duplicate with a rewrite). `record_ai_bank.py assemble` rejects a file that breaks either. When the person overrides
  the evaluator because of what a mapping row says, the row's why is edited to match, so later runs agree.
- **Recording** (`record_ai_bank.py questions`, checks in `ai_questions.py`) checks coverage mechanically (rows, roles,
  producer details, safeguards of the covered rows, folds cited, foundation count and roles); the evaluator judges
  quality, sharing and audience. Each area entry stores a fingerprint of the rows it was written for and each row's area
  and impact (for the covers note and the evidence prompt).
- **Evidence lines.** Each bank question may carry its own `evidence_prompt`, written once by an evidence writer and
  checked by an evidence evaluator (`/build-ai-bank` Step 6b, `record_ai_bank.py evidence`). A prompt the evaluator
  fails is not stored and there is no revision turn: the question keeps the generic line of
  `data/ai/evidence_prompts.json`. Editable in the question review sheets (a blank cell keeps the bank's prompt).
- **Selection** (`build_ai_questions.py`): roles from `scope_rules.json` `client_roles` (none -> none; unsure -> none,
  consumer; consumer; producer; both -> consumer and producer), producer details from the intake, and for area
  questions the client's AI areas. Nothing is ranked, capped or rewritten. Questions are reviewed once, when the bank is
  built; a client run only picks them, and `check_questionnaire.py` checks the picks against the intake and the banks
  before the sheet is written.
- **Scoring** (several areas on one subcategory) is decided in Stage 2; every question keeps its subcategory and rows.
- **No gap rule.** Every question asks how something is done for AI: for the area ("for your AI agents ...") or for AI
  in the organisation, never general security (the evaluator fails a question that would read the same with the AI
  subject removed). So it never repeats what the CSF sheet or ISO 27001 assesses, and an ISO control the client
  excluded in its SoA leaves no hole: every AI question is `full_discovery` for every client. A client may cite a
  general control as evidence; the assessor checks whether it reaches the AI (are agent actions in the log, not only
  human logins). Holding ISO 27001 does not mean a control is applied, and the questions are AI-specific anyway.
- **Review sheets** (`sheet_io.py export / import area_questions`, `foundation_questions` ->
  `data/ai/authoring/questions_<areas|foundation>.xlsx`): one line per question (areas covered, asked of, producer
  details, question, Playbook actions, safeguards, status). Lines may be edited, added or deleted; subcategories come
  from generation. Import checks the whole bank with the recording validator and stores changed subcategories as
  `decided_by: human`; agent output is refused for them unless `--replace-human`. The freshness check shows a sheet
  edited but not imported.
