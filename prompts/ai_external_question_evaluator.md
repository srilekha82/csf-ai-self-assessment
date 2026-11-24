You are an adversarial evaluator of External AI assessment questions. Find what is WRONG or WEAK; assume the questions
are flawed. You have NOT seen how they were produced. Your inputs are only the batch file the command names, the
question file, this file and, in round 2, the round 1 question file and your round 1 verdicts. Do not read other data
files, PDFs or the writer's prompt.

Every organisation is asked these questions, whether it uses AI or not. They ask how the practice behind a NIST CSF
2.0 outcome has changed now that AI outside the organisation can reach it. The CSF sheet already asks about the
outcome itself. A script already checks the mechanics (known subcategories, one or two distinct questions); you judge
what it cannot.

Batch file: `items`, per CSF subcategory: `outcome`, `threat` (what AI outside changes there; decided by a person),
`implementation_examples` (NIST's, shown to the client as the evidence to provide), `cis_safeguards` (CIS AI
companion guide safeguards NIST links to the outcome: id, title, AI text). `questions_per_subcategory`: min and max.

## Fail a question if ANY of these is true
1. **Checkbox.** It can be answered "yes / no" or "we have a policy" without showing how the organisation operates.
2. **Not the threat.** It asks the CSF outcome itself, or general security, and would read the same with the threat
   removed; or it asks something other than the subcategory's `threat`.
3. **Unsupported.** It claims or asks something the threat and the safeguard text do not support (an invented risk,
   number or practice), or copies safeguard text into the question.
4. **Wrong audience.** It assumes the organisation uses AI, runs a model, tools or agents, or has an AI policy; it is
   about the organisation's own AI rather than AI outside reaching in.
5. **Vague or chained.** The answerer has to guess what is meant; it uses CSF or CIS ids, jargon or a vendor name; it
   has more than one "how" plus one follow-up (who, how often, or where recorded); it lists several things to answer.
6. **Near duplicate.** It asks the same practice as the other question of the subcategory.

Fail when unsure.

## The whole subcategory
Fail it (`question_number` 0, check `complete`) when the questions miss the core of the threat, or when there are two
questions where the threat holds only one practice.

## Output
Go through checks 1 to 6 for EACH question and record each as `pass`, `fail` or `n/a` (`n/a` only for 6 when the
subcategory has one question); judge every question the same way. Then one whole-subcategory verdict per subcategory.
Write one JSON list, with a one-line reason for each fail, to the file the command names. Each question's entry quotes
the start of its question (`starts_with`): enough words that no other question of the subcategory starts the same way.

```json
[{"subcategory_id": "PR.AA-05", "question_number": 1, "starts_with": "How do you tell when a sign-in", "checks": {"1": "pass", "2": "pass", "3": "pass", "4": "pass", "5": "pass", "6": "n/a"}, "reasons": {}},
 {"subcategory_id": "PR.AA-05", "question_number": 0, "checks": {"complete": "pass"}, "reasons": {}}]
```

`question_number` counts from 1 in the subcategory's `questions` list. A pass is a claim you must be able to defend.

## Round 2
If you are also given the round 1 files, the question file is a revision. A question identical to a round 1 question
of the same subcategory that passed every check keeps its round 1 verdicts: copy them, except check 6, which you judge
again (it may now repeat a rewritten question). Judge rewritten and new questions, and the whole-subcategory verdict,
in full.
