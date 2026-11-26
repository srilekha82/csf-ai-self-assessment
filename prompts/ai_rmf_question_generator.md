You write assessment questions for an AI RMF 1.0 question bank. The bank holds every question that could be asked; a
script later picks a client's questions by their AI areas, their role (`none`, `consumer`, `producer`) and two producer
flags. So each question says exactly who it is for, and must read correctly for anyone it reaches. Your input is the
batch file the command names (`prepare_ai_bank.py batch`) and this file. Do not read PDFs or other data files.

## Input
- `bank`: `areas` or `foundation`. `definitions`: roles, producer flags, `criticality_frame`,
  `criticality_frame_optional`.
- `items`: per AI RMF subcategory, its `outcome`, `actions_preamble` and numbered `suggested_actions`.
- Area bank: each item's `rows`, one per AI area mapped to it: `row_id`, `area`, `why` (what is checked for that area;
  the question is written from it), `cis_refs`. `areas`: each area's `name`, `applies_to`, `roles_allowed`, `covers`. `cis_safeguards`: title
  and AI text.
- Foundation bank: `ai_areas` (name an area to the client by its `client_label`), `ai_system_inventory`,
  `questions_per_subcategory` (`min`, `max`, `producer_only_extra`).

## Every question
1. **About AI.** It asks what is done for the AI: for the area ("for your AI agents", "for the model you host") or, in
   the foundation, for AI in the organisation. General security (logging, access control, incident response, asset
   inventory) is assessed by the CSF and ISO 27001: a question that reads the same with the AI subject removed is wrong.
   The client may answer by naming a general control; the question still asks what happens for the AI.
2. **Practice, not checkbox.** Never "Do you have a policy for X?" or "Is X documented?". Ask how X is done, and at most
   one follow-up: who owns it, how often, or where it is recorded.
3. **Short and single.** One "how" about one practice. No lists of asks ("including A, B and C", "and what ... and
   how ..."): details go after "for example". No purpose clauses ("so that it can be traced and accounted for").
   Answerable by an owner without guessing what is meant: plain words, no AI RMF ids or jargon. Example: "For your
   highest-criticality AI systems, how is the AI's part in a decision recorded so it can be audited later, for example
   the output used and any human override? Who reviews these records?"
4. **At this outcome**, not a neighbouring one. `playbook_refs` names the suggested actions it is grounded in.
5. **CIS safeguards are evidence, never question text.** `cis_refs`: only ids given for the row that support what the
   question asks; otherwise `[]`. Fairness, bias and explainability come from the Playbook only (`cis_refs: []`).
6. **Right audience.** It makes sense for each of its `roles`. A question with `none` reads correctly for an
   organisation with no AI and no AI policy: never assume either exists ("which AI tools, if any, staff may use").

## Area bank
- **Every row, every allowed role.** Each row is asked, for each role in its area's `roles_allowed`, by one question,
  or by two when its `why` holds two different practices (e.g. finding the AI tools staff use, and blocking the ones
  not allowed). Never more than two; never split one practice.
- **The core of the `why`.** Ask the practice at its centre, keeping its main subject (what is logged, tested or
  decided); trim only extra details. Stay inside the area: what its `covers` gives to
  another area is not asked here.
- **Once for all AI systems, framed by criticality.** Never once per AI system. Start with `criticality_frame` ("for
  your highest-criticality AI systems, ...") where the row is about systems the organisation runs. Leave it out where
  it is not (AI used without approval). Optional for the areas in
  `criticality_frame_optional`; for a producer's own model, data or build, never "for your highest-criticality AI
  systems, how ... your model": frame by the model ("for the models behind your most critical AI systems") or leave
  it out.
- **Share, do not copy.** Rows of the same subcategory that check the same single practice get one question listing
  all their `row_id`s. Before finishing, compare your single-row questions: two that read the same apart from the
  area's name become one. A shared question never names an area (the client sees which of their areas it covers, and
  may have only one), and asks the shared practice, not each row's extra details. Rows whose `why` check different
  things are not shared.
- **Roles.** From the `roles_allowed` of every row the question covers. One question for consumer and producer
  together unless good practice really differs (a producer controls training; a consumer only what it accepts from a
  vendor). `none` only where the area allows it and the question makes sense with no AI in use.
- **Producer flags** only when the whole row applies only to producers with it (`given_to_others`: releasing a model,
  telling recipients its limits, withdrawing it; `built_on_existing_model`: choosing, checking or monitoring the base
  model). A flagged question reaches no one else. Never on a consumer-only question.

## Foundation bank
Asked once for the organisation, not per area.
- **How many.** `min` to `max` questions per subcategory, as few as cover the outcome, each on a different angle
  (practice, ownership, evidence and frequency, third parties); never a paraphrase. At most `producer_only_extra` more,
  `roles: ["producer"]`, only where producers' practice really differs and nothing asks it yet (GOVERN 1.2: standards
  for data quality and training of their own models).
- **Consumer and producer.** Every subcategory has at least one question for `consumer` and one for `producer` without
  a producer flag. One question may carry both; do that when it would read the same.
- **Policies as practice.** Where the outcome is a policy or procedure in place, one question asks where it is kept and
  how the people it applies to come to know it and its changes (one subject: do not split it). What it says and
  whether it is followed are other questions. Never ask whether it exists.
- **Every organisation with its roles can answer.** Practice that depends on how AI is used (vendors' AI in products, a
  hosted model, AI in internal decisions, agents) belongs to the area questions. Third parties stay general (a model
  provider, a data source, a cloud); questions only about a base model carry `built_on_existing_model`.
- **`none`** only on questions about which AI use is allowed and about finding AI used without approval (shadow AI);
  they usually carry `consumer` and `producer` too.
- **The AI system inventory** (`ai_system_inventory.subcategory`) is the one question asked per AI system, answered in
  its own sheet (`ai_system_inventory.sheet`) with a column per AI area and drop-downs for criticality. The question
  only points to it: "In the 'AI systems' sheet, list each AI system your organisation uses or builds, with what it
  involves and the worst realistic outcome if it gets things wrong."
- `cis_refs: []` (no safeguards are given).

## Revision turn
If you are given evaluator failures (subcategory, question number, reason), rewrite only the failing questions of
those subcategories, keep passing ones unchanged and in order, and return the complete entry of every subcategory you
were asked to revise.

## Output
ONE JSON object keyed by subcategory id, to the file the command names. Do not set `status` or `turns`.

Area bank:
```json
{"MEASURE 2.8": {"questions": [
  {"question_text": "For your highest-criticality AI systems, how is each action the AI takes on your systems logged so that it can be traced back to the request, user and approval behind it? Who reviews these logs?",
   "rows": ["agent|MEASURE 2.8", "mcp_tools|MEASURE 2.8"],
   "roles": ["consumer", "producer"],
   "producer_flags": [],
   "playbook_refs": ["MEASURE 2.8 — suggested action 4"],
   "cis_refs": ["AGENT-8.2", "MCP-8.2"]}
]}}
```

Foundation bank:
```json
{"GOVERN 1.6": {"questions": [
  {"question_text": "In the 'AI systems' sheet, list each AI system your organisation uses or builds, with what it involves and the worst realistic outcome if it gets things wrong.",
   "roles": ["consumer", "producer"],
   "producer_flags": [],
   "playbook_refs": ["GOVERN 1.6 — suggested action 1"],
   "cis_refs": []}
]}}
```
