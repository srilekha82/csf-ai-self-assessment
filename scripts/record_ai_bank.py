"""
Checks and stores the AI agents' work in the AI RMF bank build.

Called by: /build-ai-bank (steps 3-7)
Input:     an agent's file (mapping, questions, evidence lines, impact notes or their review)
Output:    data/ai/mapping.json, data/ai/banks/, data/csf/ai_impact_notes.json; a write-once copy in
           data/ai/bank_build/judgement_log/

Usage: .venv/bin/python ./scripts/record_ai_bank.py <mode> ...
       (modes that store agent work also take --model ID [--session REF] [--prompt PATH ...])

Each mode checks the whole file and rejects it if anything is wrong (exit 1, nothing stored); otherwise it stores it,
keeps a write-once record in data/ai/bank_build/judgement_log/ and adds a run-log line. A line a person decided in a
review sheet is never overwritten by an agent.

Modes that store agent work (the full checks are in the function named, in ai_mapping.py, ai_questions.py or
ai_notes.py):
  mapping <file> [--review F]   one AI area's mapping -> data/ai/mapping.json                 (ai_mapping.validate_mapping)
  questions <areas|foundation> <file> [--replace-human]
                                questions for some subcategories -> data/ai/banks/...          (ai_questions.validate_questions)
  evidence <areas|foundation> <file> --review F
                                the evidence lines the evaluator passed -> that bank           (ai_questions.validate_evidence)
  notes <file>                  AI impact notes -> data/csf/ai_impact_notes.json              (ai_notes.validate_notes)
  notes-review <file>           the notes evaluator's findings -> the same file               (ai_notes.validate_notes_review)

Modes with no agent output:
  assemble --gen1 F --eval1 F [--gen2 F --eval2 F] --out F
                                combines the question writer's and checker's files into the file `questions` stores;
                                a subcategory still failing after the second round is marked needs_human_review.
  revalidate                    after a change to the mapping rules or to other AI areas, re-checks the recorded areas
                                against the current rules: areas that pass are marked current, the rest are listed.
                                An area whose own sources or AI area row changed must be re-drafted instead.

This file is only the command: it reads the mode and the file, then calls the checks and the store of
ai_mapping.py (the mapping), ai_questions.py (the question banks) or ai_notes.py (the impact notes).
Related: prepare_ai_bank.py writes the agents' input; ai_pilot.py records your approvals.

Terms (AI area, mapping row, foundation, impact, folded subcategory, required check, needs human review): see
docs/guide.md, Glossary. The full model: docs/ai-rmf-model.md.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import AI_AREAS, AI_BUILD, AI_MAPPING, AI_MAPPING_RULES  # noqa: E402
from ai_bank_common import DEFAULT_PROMPTS, load_inputs, load_json  # noqa: E402
from options import AI_QUESTION_BANKS  # noqa: E402
import audit  # noqa: E402
from ai_mapping import mapping_inputs, revalidate, store_mapping, validate_mapping  # noqa: E402
from ai_questions import (assemble, human_decided, question_context, store_evidence, store_questions,  # noqa: E402
                          validate_evidence, validate_questions)
from ai_notes import store_notes, store_notes_review, validate_notes, validate_notes_review  # noqa: E402


LOG_DIR = AI_BUILD / "judgement_log"


def record(mode: str, args) -> None:
    inp = load_inputs()
    if mode == "mapping":
        m = mapping_inputs(inp)
        review = load_json(Path(args.review), "review file") if getattr(args, "review", None) else None
        validate = lambda d: validate_mapping(d, inp, m, review)                # noqa: E731
        store_fn = lambda d: store_mapping(d, inp, m, review)                    # noqa: E731
        extra = {"review_file": args.review, "review": review}
        log_name = lambda d: f"mapping_{d.get('area', 'unknown')}" if isinstance(d, dict) else "mapping"  # noqa: E731
    else:
        review = load_json(Path(args.review), "review file") if getattr(args, "review", None) else None
        validate = {"questions": lambda d: (validate_questions(d, args.bank, inp, question_context(inp))
                                            + human_decided(d, args)),
                    "evidence": lambda d: validate_evidence(d, review, args.bank),
                    "notes": validate_notes, "notes-review": validate_notes_review}[mode]
        store = {"questions": store_questions, "evidence": store_evidence,
                 "notes": store_notes, "notes-review": store_notes_review}[mode]
        store_fn, extra = (lambda d: store(d, args, inp)), ({"review": review} if mode == "evidence" else None)
        log_name = f"{mode}_{args.bank}" if mode in ("questions", "evidence") else mode
    audit.record_agent_output(
        log_path=AI_BUILD / "audit.jsonl", log_dir=LOG_DIR, step=f"record_ai_bank_{mode}",
        args={"file": args.file, "bank": getattr(args, "bank", None)}, file=args.file,
        validate=validate, store=store_fn,
        model=args.model, session=args.session, prompts=args.prompt or DEFAULT_PROMPTS[mode],
        log_name=log_name, extra_record=extra)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    pa = sub.add_parser("assemble")
    for name in ("gen1", "eval1", "gen2", "eval2"):
        pa.add_argument(f"--{name}", required=name in ("gen1", "eval1"))
    pa.add_argument("--out", required=True)
    sub.add_parser("revalidate")

    for m in ("questions", "evidence", "notes", "notes-review", "mapping"):
        p = sub.add_parser(m)
        if m in ("questions", "evidence"):
            p.add_argument("bank", choices=AI_QUESTION_BANKS)
        if m == "questions":
            p.add_argument("--replace-human", action="store_true",
                           help="overwrite subcategories a person decided in the review sheet (only when they agreed)")
        p.add_argument("file")
        if m == "mapping":
            p.add_argument("--review", help="the evaluator's last list of failures (rows stored as needs_human_review)")
        if m == "evidence":
            p.add_argument("--review", required=True, help="the evidence evaluator's verdicts (failed prompts are not stored)")
        p.add_argument("--model", required=True, help="model id of the agent that produced the file")
        p.add_argument("--session")
        p.add_argument("--prompt", nargs="*", help="prompt file(s) the agent followed, relative to the repo root")
    args = ap.parse_args()

    if args.mode == "revalidate":
        inp = load_inputs()
        m = mapping_inputs(inp)
        ev = audit.begin(AI_BUILD / "audit.jsonl", "revalidate_mapping", {})
        _, lines, cleared = revalidate(inp, m)
        for ln in lines:
            print(f"[record_ai_bank] {ln}")
        line = f"revalidate: {cleared} areas checked against the current rules and stamped current; {len(lines)} problems"
        print(f"[record_ai_bank] {line}")
        ev.finish(inputs=[AI_AREAS, AI_MAPPING_RULES], outputs=[AI_MAPPING] if cleared else [], detail=line)
        sys.exit(1 if lines else 0)
    if args.mode == "assemble":
        ev = audit.begin(AI_BUILD / "audit.jsonl", "assemble_questions", {"gen1": args.gen1, "gen2": args.gen2})
        ins = [Path(p) for p in (args.gen1, args.eval1, args.gen2, args.eval2) if p]
        line = assemble(Path(args.gen1), Path(args.eval1), Path(args.gen2) if args.gen2 else None,
                        Path(args.eval2) if args.eval2 else None, Path(args.out))
        print(f"[record_ai_bank] {line}")
        ev.finish(inputs=ins, outputs=[Path(args.out)], detail=line)
        return
    record(args.mode, args)


if __name__ == "__main__":
    main()
