"""
Usage: .venv/bin/python ./scripts/check_questionnaire.py <run_dir> [--framework csf|ai]

Checks that the questions picked for this run are the ones its intake and the question banks call for, before the
workbook is written. It judges nothing about wording: the questions were reviewed when the banks were built. It checks
every draft present in the run folder (or only one framework with --framework).

CSF (csf_questions_draft.json, against csf_scope.json, intake.json and csf_question_bank_used.json):
  - one entry per subcategory in scope that is not `skip`, none for the others, each with the scope's question type
  - every GOVERN (GV) entry is full_discovery; every confirmatory entry carries the LOW confidence flag
  - at least one non-blank question per entry, none repeated, no more than scope_rules.json max_questions for its type
  - every question is one of the bank's questions for that subcategory, CSET's own CSF 2.0 question is kept when the
    bank has it, and the generic fallback appears only when the bank has no question for it
  - no question is worded for a certification the organisation does not hold

AI RMF (ai_questions_draft_<bank>.json, against ai_usage.json and ai_question_bank_used_<bank>.json):
  - every question is in the bank under its subcategory, every question is full_discovery
  - it is asked of a role the client is asked as, needs only producer details the client has, and (area questions)
    covers only rows of the client's own AI areas
  - nothing is missing: each subcategory holds exactly the questions the bank gives this client

Exit 0 = all checks pass; exit 1 = problems listed (re-run the step that wrote the draft; do not edit drafts by hand).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from options import AI_QUESTION_BANKS, CERT_LABELS, load_intake  # noqa: E402
from paths import AI_SCOPE_RULES, SCOPE_RULES  # noqa: E402
from build_ai_questions import client_roles, pick  # noqa: E402
import audit  # noqa: E402

CSF_DRAFT = "csf_questions_draft.json"
DETAIL_WORDS = {"built_on_existing_model": "built on an existing model", "given_to_others": "given to others"}


def load(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def entry_problems(sid: str, questions) -> list[str]:
    """Problems any entry can have: no questions, a blank one, one asked twice."""
    if not isinstance(questions, list) or not questions:
        return [f"{sid}: no questions"]
    texts = [str(q.get("question_text", "")).strip() for q in questions]
    problems = [f"{sid}: a blank question" for t in texts if not t]
    problems += [f"{sid}: question asked twice: {t[:60]!r}" for t in sorted(set(texts)) if t and texts.count(t) > 1]
    return problems


def check_csf(run_dir: Path) -> list[str]:
    draft = load(run_dir / CSF_DRAFT)
    scope = load(run_dir / "csf_scope.json")
    bank = load(run_dir / "csf_question_bank_used.json")
    if draft is None or scope is None or bank is None:
        return ["CSF: csf_questions_draft.json, csf_scope.json and csf_question_bank_used.json must all exist "
                "(run /csf-questionnaire)"]
    certs = load_intake(run_dir)["certs"]
    max_questions = json.loads(SCOPE_RULES.read_text())["max_questions"]
    expected = {e["subcategory_id"]: e["question_type"] for e in scope if e["question_type"] != "skip"}
    got = {e["subcategory_id"]: e for e in draft}

    problems = [f"CSF {sid}: in scope ({qtype}) but missing" for sid, qtype in expected.items() if sid not in got]
    problems += [f"CSF {sid}: not in scope (or skip) but has questions" for sid in got if sid not in expected]
    not_held = [label for cert, label in CERT_LABELS.items() if cert not in certs]
    for sid, e in got.items():
        if sid not in expected:
            continue
        qtype, questions = e.get("question_type"), e.get("questions")
        problems += [f"CSF {p}" for p in entry_problems(sid, questions)]
        if qtype != expected[sid]:
            problems.append(f"CSF {sid}: question type {qtype}, scope says {expected[sid]}")
        if sid.startswith("GV.") and qtype != "full_discovery":
            problems.append(f"CSF {sid}: GOVERN must be full_discovery, not {qtype}")
        if qtype == "confirmatory" and not str(e.get("confidence_flag", "")).startswith("LOW"):
            problems.append(f"CSF {sid}: confirmatory without the LOW confidence flag")
        if not isinstance(questions, list):
            continue
        if qtype in max_questions and len(questions) > max_questions[qtype]:
            problems.append(f"CSF {sid}: {len(questions)} questions, at most {max_questions[qtype]} for {qtype}")
        candidates = bank["questions"].get(sid, {}).get("candidates", [])
        ids = {c.get("cset_question_id") for c in candidates}
        for q in questions:
            qid = q.get("cset_question_id")
            if qid is None and candidates:
                problems.append(f"CSF {sid}: generic fallback question although the bank has questions for it")
            elif qid is not None and qid not in ids:
                problems.append(f"CSF {sid}: question {qid} is not in the bank for this subcategory")
            text = str(q.get("question_text", ""))
            problems += [f"CSF {sid}: worded for {label}, which the organisation does not hold"
                         for label in not_held if f"Your {label}" in text]
        own = [c["cset_question_id"] for c in candidates if c.get("cset_set") == "NCSF_V2"]
        if own and own[0] not in {q.get("cset_question_id") for q in questions}:
            problems.append(f"CSF {sid}: CSET's own CSF 2.0 question ({own[0]}) is missing")
    return problems


def check_ai(run_dir: Path) -> list[str]:
    profile = load(run_dir / "ai_usage.json")
    if profile is None:
        return ["AI: ai_usage.json is missing (run the intake)"]
    roles = client_roles(profile, json.loads(AI_SCOPE_RULES.read_text()))
    flags = [f for f, v in (profile.get("producer") or {}).items() if v]
    areas = profile["ai_areas"]
    problems = []
    for name in AI_QUESTION_BANKS:
        draft = load(run_dir / f"ai_questions_draft_{name}.json")
        bank = load(run_dir / f"ai_question_bank_used_{name}.json")
        if draft is None or bank is None:
            problems.append(f"AI {name}: ai_questions_draft_{name}.json and ai_question_bank_used_{name}.json must "
                            "both exist (run /ai-questionnaire)")
            continue
        subs = bank["subcategories"]
        got = {e["subcategory_id"]: e for e in draft}
        for sid, e in got.items():
            rec = subs.get(sid)
            if rec is None:
                problems.append(f"AI {name} {sid}: not a subcategory of the {name} bank")
                continue
            problems += [f"AI {name} {p}" for p in entry_problems(sid, e.get("questions"))]
            if e.get("question_type") != "full_discovery":
                problems.append(f"AI {name} {sid}: question type {e.get('question_type')}, must be full_discovery")
            in_bank = {q["question_text"]: q for q in rec["questions"]}
            for q in e.get("questions") or []:
                b = in_bank.get(q.get("question_text"))
                if b is None:
                    problems.append(f"AI {name} {sid}: question not in the bank: {str(q.get('question_text'))[:60]!r}")
                    continue
                if not set(b["roles"]) & set(roles):
                    problems.append(f"AI {name} {sid}: question for {b['roles']}, client is asked as {roles}")
                if not set(b["producer_flags"]) <= set(flags):
                    problems.append(f"AI {name} {sid}: question is for a producer whose model is "
                                    f"{' and '.join(DETAIL_WORDS.get(f, f) for f in b['producer_flags'])}, "
                                    "which this organisation did not say")
                rows = q.get("rows") or []
                if name == "areas":
                    foreign = [r for r in rows if r not in b.get("rows", []) or rec["rows"][r]["area"] not in areas]
                    if not rows or foreign:
                        problems.append(f"AI {name} {sid}: question covers no row, or rows outside the client's AI "
                                        f"areas {foreign}")
                elif rows:
                    problems.append(f"AI {name} {sid}: a foundation question must cover no area rows")
        for sid, rec in subs.items():   # nothing missing: what the bank gives this client is all there
            want = {q["question_text"] for q, _ in pick(name, rec, roles, flags, areas)}
            have = {q.get("question_text") for q in (got.get(sid) or {}).get("questions") or []}
            if want - have:
                problems.append(f"AI {name} {sid}: {len(want - have)} question(s) the bank gives this client are missing")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--framework", choices=["csf", "ai"], help="check only this framework's drafts")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        sys.exit(f"[check_questionnaire] ERROR: run folder not found: {run_dir}")
    load_intake(run_dir)   # exits with a clear message when the intake is missing
    ev = audit.begin(audit.run_log(run_dir), "check_questionnaire", {"framework": args.framework})
    frameworks = [args.framework] if args.framework else [
        f for f, present in (("csf", (run_dir / CSF_DRAFT).is_file()),
                             ("ai", any((run_dir / f"ai_questions_draft_{b}.json").is_file()
                                        for b in AI_QUESTION_BANKS))) if present]
    if not frameworks:
        ev.fail("[check_questionnaire] ERROR: no drafts in the run folder (run /csf-questionnaire or /ai-questionnaire)")
    problems = []
    for f in frameworks:
        problems += check_csf(run_dir) if f == "csf" else check_ai(run_dir)
    if problems:
        print("\n".join(problems))
        print(f"\n[check_questionnaire] {len(problems)} problem(s) in {', '.join(frameworks)}: re-run the step that "
              "wrote the draft; do not edit drafts by hand.")
        ev.finish("rejected", detail=f"{len(problems)} problems", problems=problems)
        sys.exit(1)
    print(f"[check_questionnaire] {', '.join(frameworks)}: all checks pass")
    ev.finish(detail=f"{', '.join(frameworks)}: all checks pass")


if __name__ == "__main__":
    main()
