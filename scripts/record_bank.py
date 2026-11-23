"""
Saves the agents' work, and your approvals, while the question banks are built. It is the only way anything an agent
writes gets into the banks: every file is checked first, and a file with any problem is refused as a whole.

Why:       agents make mistakes. Checking everything they hand in at one place keeps a wrong or partial answer out of
           the banks, and the copy it keeps of who decided what lets you trace any bank line back to its decision.
Called by: /build-csf-bank (steps 4 and 5) and /build-ai-bank (steps 3 to 7); never in a client run
Input:     a file an agent wrote (with the evaluator's verdicts, where there is one), or your approval
Output:    the bank file each mode names, plus a permanent record of what was saved (see below)

Usage: .venv/bin/python ./scripts/record_bank.py <mode> <file> [options]     (--help lists the modes)
       Modes that save an agent's file also take --model <model id> [--session <ref>].

What every mode does
  1. Check   the whole file against the rules (the check function named below). Any problem: it lists them, saves
             nothing and exits 1, so the agent can fix the file and hand it in again.
  2. Save    the file into its bank file. A line a person decided is never overwritten by an agent.
  3. Record  a write-once copy in judgement_log/ (data/csf/bank_build/ or data/ai/bank_build/): who decided, with
             which prompt and inputs, and exactly what they handed in. Plus one line in that folder's audit.jsonl.

CSF banks (/build-csf-bank; the checks are in build_csf_bank.py)
  csf-cset <verdicts.json> [--pending F]    the agent's decisions on CSET questions the build could not place
                                            (sector, rewording, fit) -> cset_judgements.json   check: validate_cset
  csf-evidence-prepare                      writes the evidence writers' input: subcategories with no evidence line
  csf-evidence <file> --review F            round 1: passed lines -> evidence_prompts.json; failed ones are kept
                                            for one revision                                   check: validate_evidence
  csf-evidence <file> --review F --revision round 2: passed lines saved; lines that fail again go to you
  csf-evidence-reviewed                     your choice for each of those (your own line, or keep the category line);
                                            final                                              check: validate_review

AI RMF banks (/build-ai-bank; the checks are in ai_mapping.py, ai_questions.py, ai_notes.py)
  ai-mapping <file> [--review F]            one AI area's mapping rows -> mapping.json         check: validate_mapping
  ai-revalidate                             after a rules change, re-checks the saved areas (no agent); lists the
                                            ones to redraft
  ai-accept-mapping [--note T]              you approve the mapping as it is now (it must be approved again if it
                                            changes)
  ai-assemble --gen1 F --eval1 F [--gen2 F --eval2 F] --out F
                                            joins the question writer's and checker's files (up to two rounds) into
                                            one file for ai-questions; what still fails is marked for your review
  ai-questions <foundation|areas> <file>    questions for some subcategories -> that bank      check: validate_questions
               [--replace-human]            (--replace-human: only when you agreed to replace your own edits)
  ai-accept-pilot [--note T]                you approve the pilot questions (a new pilot is needed if the question
                                            prompts change)
  ai-evidence <foundation|areas> <file> --review F
                                            evidence lines the evaluator passed -> that bank   check: validate_evidence
  ai-notes <file>                           AI impact notes for the CSF sheet -> ai_impact_notes.json
                                                                                               check: validate_notes
  ai-notes-review <file>                    the notes evaluator's findings -> the same file
                                                                                        check: validate_notes_review

Related: prepare_ai_bank.py writes the AI agents' input; check_freshness.py reads the two approvals.
Terms (AI area, mapping row, foundation, impact notes): docs/guide.md, Glossary.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (AI_AREAS, AI_BUILD, AI_MAPPING, AI_MAPPING_ACCEPTED, AI_MAPPING_RULES, AI_PILOT,  # noqa: E402
                    AI_QUESTION_BANKS, REPO_ROOT)
from ai_bank_common import DEFAULT_PROMPTS, load_inputs, load_json  # noqa: E402
import audit  # noqa: E402
import build_csf_bank as csf  # noqa: E402
from ai_mapping import accept_mapping, mapping_inputs, revalidate, store_mapping, validate_mapping  # noqa: E402
from ai_questions import (accept_pilot, assemble, human_decided, question_context, store_evidence,  # noqa: E402
                          store_questions, validate_evidence, validate_questions)
from ai_notes import store_notes, store_notes_review, validate_notes, validate_notes_review  # noqa: E402

AI_LOG_DIR = AI_BUILD / "judgement_log"


def record_ai(mode: str, args) -> None:
    """One AI RMF recording: the mode's check and store, through audit.record_agent_output."""
    inp = load_inputs()
    review = load_json(Path(args.review), "review file") if getattr(args, "review", None) else None
    if mode == "mapping":
        m = mapping_inputs(inp)
        validate = lambda d: validate_mapping(d, inp, m, review)                # noqa: E731
        store_fn = lambda d: store_mapping(d, inp, m, review)                    # noqa: E731
        extra = {"review_file": args.review, "review": review}
        log_name = lambda d: f"mapping_{d.get('area', 'unknown')}" if isinstance(d, dict) else "mapping"  # noqa: E731
    else:
        validate = {"questions": lambda d: (validate_questions(d, args.bank, inp, question_context(inp))
                                            + human_decided(d, args)),
                    "evidence": lambda d: validate_evidence(d, review, args.bank),
                    "notes": validate_notes, "notes-review": validate_notes_review}[mode]
        store = {"questions": store_questions, "evidence": store_evidence,
                 "notes": store_notes, "notes-review": store_notes_review}[mode]
        store_fn, extra = (lambda d: store(d, args, inp)), ({"review": review} if mode == "evidence" else None)
        log_name = f"{mode}_{args.bank}" if mode in ("questions", "evidence") else mode
    audit.record_agent_output(
        log_path=AI_BUILD / "audit.jsonl", log_dir=AI_LOG_DIR, step=f"ai_{mode}",
        args={"file": args.file, "bank": getattr(args, "bank", None)}, file=args.file,
        validate=validate, store=store_fn, model=args.model, session=args.session, prompts=DEFAULT_PROMPTS[mode],
        log_name=log_name, extra_record=extra)


def run_step(step: str, args: dict, inputs: list, outputs: list, do, actor: str = "script") -> None:
    """A mode with no agent output (prepare, assemble, revalidate, your approvals): run it, print and log one line."""
    ev = audit.begin(AI_BUILD / "audit.jsonl" if step.startswith("ai") else csf.BANK_BUILD / "audit.jsonl",
                     step, args, actor=actor)
    line, failed = do()
    print(f"[record_bank] {line}")
    ev.finish(inputs=inputs, outputs=outputs, detail=line)
    if failed:
        sys.exit(1)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    def agent_args(p):
        p.add_argument("--model", required=True, help="model id of the agent that produced the file")
        p.add_argument("--session", help="session reference, e.g. evaluator=<model id>")

    p = sub.add_parser("csf-cset")
    p.add_argument("file")
    p.add_argument("--pending", help="the pending_judgements file the agent was shown")
    agent_args(p)
    sub.add_parser("csf-evidence-prepare")
    p = sub.add_parser("csf-evidence")
    p.add_argument("file")
    p.add_argument("--review", required=True, help="the evaluator's verdicts")
    p.add_argument("--revision", action="store_true", help="round 2: the revised prompts of evidence_revise.json")
    agent_args(p)
    sub.add_parser("csf-evidence-reviewed")

    for m in ("mapping", "questions", "evidence", "notes", "notes-review"):
        p = sub.add_parser(f"ai-{m}")
        if m in ("questions", "evidence"):
            p.add_argument("bank", choices=AI_QUESTION_BANKS)
        p.add_argument("file")
        if m == "questions":
            p.add_argument("--replace-human", action="store_true",
                           help="overwrite subcategories a person decided in the review sheet (only when they agreed)")
        if m == "mapping":
            p.add_argument("--review", help="the evaluator's last list of failures (rows stored as needs_human_review)")
        if m == "evidence":
            p.add_argument("--review", required=True, help="the evidence evaluator's verdicts")
        agent_args(p)
    p = sub.add_parser("ai-assemble")
    for name in ("gen1", "eval1", "gen2", "eval2"):
        p.add_argument(f"--{name}", required=name in ("gen1", "eval1"))
    p.add_argument("--out", required=True)
    sub.add_parser("ai-revalidate")
    for m in ("ai-accept-mapping", "ai-accept-pilot"):
        sub.add_parser(m).add_argument("--note")
    return ap


def main():
    args = parser().parse_args()
    mode = args.mode
    if mode == "csf-cset":
        csf.record_cset(args.file, args.pending, args.model, args.session)
    elif mode == "csf-evidence-prepare":
        csf.evidence_prepare()
    elif mode == "csf-evidence":
        csf.record_evidence(args.file, args.review, args.revision, args.model, args.session)
    elif mode == "csf-evidence-reviewed":
        csf.record_review()
    elif mode == "ai-assemble":
        files = [Path(p) if p else None for p in (args.gen1, args.eval1, args.gen2, args.eval2)]
        run_step("ai_assemble_questions", {"gen1": args.gen1, "gen2": args.gen2}, [f for f in files if f],
                 [Path(args.out)], lambda: (assemble(*files, Path(args.out)), False))
    elif mode == "ai-revalidate":
        def do():
            inp = load_inputs()
            _, lines, cleared = revalidate(inp, mapping_inputs(inp))
            for ln in lines:
                print(f"[record_bank] {ln}")
            return (f"revalidate: {cleared} areas checked against the current rules and stamped current; "
                    f"{len(lines)} problems"), bool(lines)
        run_step("ai_revalidate_mapping", {}, [AI_AREAS, AI_MAPPING_RULES], [AI_MAPPING], do)
    elif mode == "ai-accept-mapping":
        run_step("ai_accept_mapping", {"note": args.note}, [AI_MAPPING], [AI_MAPPING_ACCEPTED],
                 lambda: (accept_mapping(args.note), False), actor="human")
    elif mode == "ai-accept-pilot":
        run_step("ai_accept_pilot", {"note": args.note}, [REPO_ROOT / p for p in DEFAULT_PROMPTS["questions"]],
                 [AI_PILOT], lambda: (accept_pilot(args.note), False), actor="human")
    else:
        record_ai(mode.removeprefix("ai-"), args)


if __name__ == "__main__":
    main()
