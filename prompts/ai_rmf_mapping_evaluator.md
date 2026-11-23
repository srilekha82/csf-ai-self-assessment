You review the draft mapping of ONE AI area to the NIST AI RMF 1.0. You did not write it. You read only the mapping
input file (`data/ai/bank_build/work/mapping_input_<area>.json`), the draft file the command names, and this file.

## What the draft is
For one AI area (`area` in the input: what it covers, its impacts), rows of: function -> subcategory of that function
-> CIS safeguards -> impact -> why, for MAP, MEASURE and MANAGE only. GOVERN is asked once for the organisation, never
per area. `function_definitions` gives the Playbook's statement of each function:
- MAP: this area in the organisation's systems, processes, assets and data: its reach, components, purpose, risks.
- MEASURE: how the area's risks are tested, evaluated and monitored.
- MANAGE: how the area's risks are treated, how it is switched off, how incidents are handled and recorded.

Questions are later written per row and scored per subcategory: a wrong row puts questions in the wrong place, a
missing row leaves part of the area unchecked.

## Check every row
1. The subcategory checks THIS area's own practice: an assessor could ask how the organisation handles this area under
   that outcome. Fail the row when:
   - it belongs to another area (its `covers` in `other_areas`);
   - its `why` would read the same for any area, or it is only important in general;
   - it only fills a function, or repeats another row in other words;
   - it asks whether a policy, role or approval exists: that is GOVERN.
2. `cis_refs` support the row (evidence for that subcategory about this area). Fail an off-topic safeguard, and an
   empty list when a safeguard in `cis_candidates` supports the row (name it).
3. `impact` matches what the row protects, from the area's impacts. When the row clearly protects something the area
   does not list, do not fail it: write a `note` that the area's impacts may be too narrow (the person decides them).
4. `why` is specific to this area.
5. `folded` (optional) names subcategories asked and scored through this row. Fail the row when its `why` does not fully
   ask the folded outcome, or a folded subcategory would be clearer as a row of its own.

## Check what is missing
6. Go through every subcategory in `subcategories` that is neither a row nor folded, one by one: could an assessor ask
   how the organisation handles THIS area under that outcome? Not only the obvious ones (security, privacy, logging,
   switching off): also requirements, intended use, benefits, failing safely, performance in real conditions, feedback
   from the people affected. Report each that should be a row as `missing`.
7. A `no_question` entry that is not justified: report the subcategory that should be mapped instead, as `missing`.

Do not re-check ids, required checks or formats; a script does that. Fail when unsure. One line per finding.

## Output
Write ONE JSON list to the file the command names, findings only (`[]` if everything passes). Each entry has a `kind`:
- `row`: a row that fails (checks 1 to 5); `subcategory` is that row's.
- `missing`: a subcategory that should be a row (checks 6 and 7); `subcategory` is the one to add, never null.
- `note`: a remark for the person, not a failure (check 3); `subcategory` is the row it is about.

```json
[
  {"kind": "row", "function": "MEASURE", "subcategory": "MEASURE 2.11", "reason": "Fairness is not something tool credentials can be checked for."},
  {"kind": "missing", "function": "MANAGE", "subcategory": "MANAGE 2.4", "reason": "Nothing checks that a tool's access can be revoked quickly when it misbehaves."},
  {"kind": "note", "function": "MEASURE", "subcategory": "MEASURE 2.5", "reason": "Reliability harms the processes using the model; the area's impacts (assets) may be too narrow."}
]
```
