You write the evidence prompt for each NIST CSF 2.0 subcategory: one short line telling an assessor what to ask the
organisation to show for that outcome. It is shown to every client, in every sector, next to the subcategory's
questions. You judge from the input file the command names (`data/csf/bank_build/evidence_input.json`) and this file
only. Do not read the banks, the crosswalks or any other file.

## Input
`items`: per subcategory, its `id`, `outcome` and NIST's `implementation_examples` (what doing it well looks like).

## Write, for every item
One evidence prompt of 1 to 2 short sentences (at most 400 characters) that:
- names the concrete artefacts that would show this outcome is achieved: a named register, inventory, record, report,
  configuration, log extract, approval, contract clause, test result, procedure and its last use. Take them from the
  implementation examples (PR.DS-11 backups: the backup schedule for critical data, the latest restore test result,
  where the offline or offsite copies are kept), never from a neighbouring outcome;
- carries coverage and recency (which systems, sites, data, suppliers or teams it covers; the latest one), so the
  questions can stay short;
- never repeats the outcome as a question, never asks a yes / no, never names a vendor, product, sector or
  certification, never assumes the organisation has something (say "if any" where it may not). An event a well-run
  organisation may never have had (an incident, a finding, a breach notification) is always asked as "the latest
  one, if any"; prefer the artefact the practice itself produces over proof of an event. The implementation
  examples are options, not requirements: a specific mechanism taken from them (single sign-on, DNS filtering,
  automated containment, load balancing, supplier contract clauses, in-house software) is asked "if used" or
  "if any", never as something the organisation must have.

Do not write a prompt for a subcategory that is not in the input.

## Revision (when the command gives you `evidence_revise.json` instead)
Each item also has your earlier `draft` and the evaluator's `reason` for failing it. Write a new prompt for every item
that fixes what the reason names, by the same rules. Do not argue with the reason or repeat the draft unchanged.

## Output
One JSON object to the file the command names: subcategory id -> evidence prompt.

```json
{"PR.DS-11": "The backup schedule for critical data and the systems it covers, the latest restore test result, and where offline or offsite copies are kept."}
```

A script (`record_csf_bank.py evidence`) rejects the whole file on a subcategory that is not in your input, a missing
one in a revision, or a prompt shorter than 30 or longer than 400 characters.
