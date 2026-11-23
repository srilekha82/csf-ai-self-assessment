You map ONE AI area to the NIST AI RMF 1.0. You judge from `data/ai/bank_build/work/mapping_input_<area>.json` and this file
only. Do not read the Playbook or CIS PDFs, other data files, or any file from a client run.

## Input
- `area`: the AI area: `covers` (what is exposed, what can go wrong) and `impact` (what a failure hits: data, access,
  process, assets, people).
- `other_areas`: the rest of the AI areas, each mapped on its own.
- `functions` (MAP, MEASURE, MANAGE) and `function_definitions` (the Playbook's statement of each function).
- `foundation`: GOVERN and the subcategories listed with it, asked once for the organisation elsewhere. Never map them.
- `subcategories`: per function, each AI RMF subcategory with its outcome and some Playbook suggested actions.
- `cis_candidates`: the CIS safeguards you may cite.
- `rules`: `min_why_chars`, `required_checks`.

## Task
Go through every subcategory in `subcategories`, one by one, and decide whether it checks this area. Do not stop at
the obvious ones (security, privacy, logging, switching off): requirements, intended use, benefits, failing safely,
performance in real conditions and feedback from the people affected count as much. A later step writes the questions;
you decide only where they land.
- MAP: this area in the organisation's systems, processes, assets and data: its reach, components, suppliers, purpose,
  limits, risks and impacts.
- MEASURE: how the area's risks are tested, evaluated and monitored in use.
- MANAGE: how the area's risks are treated, how it is switched off, how incidents are handled and recorded.

## Rules
1. A row is one function + one subcategory of that function, never repeated. There is no target number of rows: a
   narrow area may need few, a broad one many.
2. Map a subcategory only if it checks this area's own practice: an assessor could ask how the organisation handles
   this area under that outcome. Leave it out when:
   - it belongs to another area (its `covers` in `other_areas`): model testing belongs to model building, not to the
     model as an asset;
   - its `why` would read the same for any area, or it is only important in general;
   - it would only fill a function, or repeat another row in other words;
   - it asks whether a policy, role or approval exists: that is GOVERN (granting a tool access is MANAGE, not
     GOVERN 2.1).

   A function with no fitting subcategory gets one `no_question` entry with a one-sentence reason.
3. Meet every entry in `required_checks`: a row on one of its `any_of` subcategories, and where it has `cis_control`,
   that row cites a safeguard of that control.
4. `cis_refs`: every safeguard from `cis_candidates` that supports the row (evidence an assessor would ask for), and no
   others; prefer the lowest IG that fits. Look through all the candidates: `[]` only when none supports it.
5. `impact`: the area's impacts this row protects (a privacy row on source data is `data`; a retrieval permissions row
   is `access`). Never one the area does not list.
6. `why`: one sentence on what this subcategory checks about this area.
7. `folded` (optional): another subcategory of this area that this row's question fully asks, merged instead of a
   second row, e.g. `"folded": ["MAP 2.2"]`. It gets no question of its own. When in doubt, write two rows.
8. Do not decide by sector, organisation size or how any client works. Never invent an id.

## Output
Write ONE JSON object to the file the command names:

```json
{
  "area": "mcp_tools",
  "rows": [
    {"function": "MAP", "subcategory": "MAP 4.1", "cis_refs": ["MCP-2.1"], "impact": ["access"],
     "why": "The MCP servers and tools the AI can call, inside and outside, are identified with what each can reach."},
    {"function": "MEASURE", "subcategory": "MEASURE 2.8", "cis_refs": ["MCP-8.2"], "impact": ["access"],
     "why": "Tool calls are logged with the credentials used, so actions can be traced and accounted for."}
  ],
  "no_question": [
    {"function": "MAP", "reason": "..."}
  ]
}
```

A script checks the whole file (ids, functions, candidates, impacts, required checks) and rejects it if anything is
wrong; nothing is stored until it passes.

## Revision turn
If you are given the evaluator's failures, return the complete corrected file: fix or remove each failing row, add a
row for each `missing` subcategory unless you are sure it does not check this area (it then stays flagged for the
person reviewing), and leave correct rows unchanged. `note` entries are for the person; you need not act on them. When
you remove a row and move its content into another, list the removed subcategory in that row's `folded`.
