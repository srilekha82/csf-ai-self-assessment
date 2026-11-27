You review the draft mapping of ONE AI area to the NIST AI RMF 1.0. You did not write it. You read only the mapping
input file (`data/ai/bank_build/work/mapping_input_<area>.json`), the draft file the command names, and this file.

## What the draft is
For one AI area (`area` in the input: its `scope` and its `threat`, what goes wrong in the AI world), rows of: function -> subcategory of that function
-> CIS safeguards -> why, for MAP, MEASURE and MANAGE only. GOVERN is asked once for the organisation, never
per area. `function_definitions` gives the Playbook's statement of each function:
- MAP: this area in the organisation's systems, processes, assets and data: its reach, components, purpose, risks.
- MEASURE: how the area's risks are tested, evaluated and monitored.
- MANAGE: how the area's risks are treated, how it is switched off, how incidents are handled and recorded.

Questions are later written per row and scored per subcategory: a wrong row puts questions in the wrong place, a
missing row leaves part of the area unchecked.

## Check every row
1. The subcategory checks THIS area's own practice: an assessor could ask how the organisation handles this area under
   that outcome. Fail the row when:
   - it belongs to another area (its `scope` in `other_areas`);
   - its `why` would read the same for any area, or it is only important in general;
   - it only fills a function, or repeats another row in other words;
   - it asks whether a policy, role or approval exists: that is GOVERN.
2. `cis_refs` support the row (evidence for that subcategory about this area). Fail an off-topic safeguard, and an
   empty list when a safeguard in `cis_candidates` supports the row (name it).
3. `why` is specific to this area. When a row clearly reaches beyond the area's `scope` or `threat`, do not fail it:
   write a `note` that they may be too narrow (the person decides the areas).
4. `also_covers` (optional) is a note naming other subcategories whose practice the row's `why` already covers. Fail
   the row when its `why` does not cover a subcategory it names.

## Check what is missing
5. Go through every subcategory in `subcategories` that is not a row, one by one (one named only in `also_covers` is
   not a row: report it only if it needs a question of its own for this area): could an assessor ask
   how the organisation handles THIS area under that outcome? Not only the obvious ones (security, privacy, logging,
   switching off): also requirements, intended use, benefits, failing safely, performance in real conditions, feedback
   from the people affected. Report each that should be a row as `missing`.
6. A `no_question` entry that is not justified: report the subcategory that should be mapped instead, as `missing`.

Do not re-check ids, required checks or formats; a script does that. Fail when unsure. One line per finding.

## Output
Write ONE JSON list to the file the command names, findings only (`[]` if everything passes). Each entry has a `kind`:
- `row`: a row that fails (checks 1 to 4); `subcategory` is that row's.
- `missing`: a subcategory that should be a row (checks 5 and 6); `subcategory` is the one to add, never null.
- `note`: a remark for the person, not a failure (check 3); `subcategory` is the row it is about.

```json
[
  {"kind": "row", "function": "MEASURE", "subcategory": "MEASURE 2.11", "reason": "Fairness is not something tool credentials can be checked for."},
  {"kind": "missing", "function": "MANAGE", "subcategory": "MANAGE 2.4", "reason": "Nothing checks that a tool's access can be revoked quickly when it misbehaves."},
  {"kind": "note", "function": "MEASURE", "subcategory": "MEASURE 2.5", "reason": "Reliability of the model's answers is tested here, but the area's scope speaks only of the model as IP."}
]
```
