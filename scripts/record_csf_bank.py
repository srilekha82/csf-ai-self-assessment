"""
The only door for AI agent output when the CSF banks are built: it checks an agent's file and stores it only if
everything passes. Nothing gets into a store without passing its checks.

Called by: /build-csf-bank (steps 4 and 5)
Input:     the agent's file: decisions on CSET questions, or evidence prompts with the evaluator's verdicts
Output:    data/csf/bank_build/cset_judgements.json or data/csf/evidence_prompts.json; a write-once record of each
           recording in data/csf/bank_build/judgement_log/ (who decided, with which prompt and inputs, what they said)

Usage: .venv/bin/python ./scripts/record_csf_bank.py <verdicts.json> [--pending PATH] [--model ID] [--session REF]
       .venv/bin/python ./scripts/record_csf_bank.py evidence prepare
       .venv/bin/python ./scripts/record_csf_bank.py evidence <prompts.json> --review <verdicts.json> --model ID [--revision]
       .venv/bin/python ./scripts/record_csf_bank.py evidence reviewed

  <verdicts.json>  step 4: the agent's decisions on the CSET questions build_question_bank.py could not place (which
                   sectors a question suits, a rewrite of a statement or cut-off text, whether it fits a subcategory),
                   stored in cset_judgements.json. A decision remembers the question text it was based on, so it is
                   redone only if CSET changes that question. Format and checks: validate().
  evidence         step 5: each subcategory's own evidence prompt (the "Evidence Required" line of the CSF sheet),
                   the same loop as every agent that writes (DESIGN_RULES rule 7):
                     prepare           writes evidence_input.json: the subcategories with no evidence line decided
                     <file> --review   round 1: stores what passed; what failed goes to evidence_revise.json with
                                       the evaluator's reason
                     ... --revision    round 2, the revised prompts: stores what passed; what failed again goes to
                                       evidence_review.json
                     reviewed          a person has filled evidence_review.json (their own prompt, or
                                       keep_category_line): stored as final, never asked again

Each form checks the whole file and exits 1, storing nothing, if anything is wrong.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_question_bank import REWRITE_FLAGS, text_hash  # noqa: E402
from options import DOMAINS  # noqa: E402
from paths import BANK_BUILD, CSF_CORE, EVIDENCE_PROMPTS, REPO_ROOT  # noqa: E402
import audit  # noqa: E402
from audit import sha  # noqa: E402

JUDGE_PROMPT = REPO_ROOT / "prompts" / "question_bank_judge.md"


VALID_DOMAINS = set(DOMAINS) | {"all"}


def validate(verdicts: dict, candidates: dict, valid_subs: set[str]) -> list[str]:
    """The agent's decisions on pending CSET questions (verdicts.json):
        {"<qid>": {"domains": ["finance", "other"],          # any of the six sectors, or ["all"]   (optional)
                   "rewrite": "Question text ..." | null,    # for statement-only practices; null = cannot be asked
                   "fit": {"GV.SC-04": {"verdict": "accept" | "reject", "reason": "..."}},          (optional)
                   "reason": "one sentence"}}
    Returns the problems; an empty list means the file can be stored."""
    errors = []
    mapped = {}
    for m in candidates["mappings"]:
        mapped.setdefault(str(m["qid"]), set()).add(m["subcategory_id"])

    for qid, v in verdicts.items():
        q = candidates["questions"].get(qid)
        if q is None:
            errors.append(f"{qid}: unknown question id")
            continue
        if not isinstance(v, dict) or not (v.keys() & {"domains", "rewrite", "fit"}):
            errors.append(f"{qid}: needs at least one of domains / rewrite / fit")
            continue
        if "domains" in v:
            d = v["domains"]
            if not isinstance(d, list) or not d or not set(d) <= VALID_DOMAINS:
                errors.append(f"{qid}: domains must be a non-empty list from {sorted(VALID_DOMAINS)}")
        if "rewrite" in v and v["rewrite"] is not None:
            if not isinstance(v["rewrite"], str) or len(v["rewrite"].strip()) < 20:
                errors.append(f"{qid}: rewrite must be a question of at least 20 characters, or null")
            elif not (REWRITE_FLAGS & set(q["flags"])):
                errors.append(f"{qid}: rewrite given but the question is neither statement-only nor truncated")
        for sub, fv in v.get("fit", {}).items():
            if sub not in mapped.get(qid, set()) or sub not in valid_subs:
                errors.append(f"{qid}: {sub} is not an active subcategory this question maps to")
            if not isinstance(fv, dict) or fv.get("verdict") not in ("accept", "reject"):
                errors.append(f"{qid}/{sub}: verdict must be accept or reject")
            elif not str(fv.get("reason", "")).strip():
                errors.append(f"{qid}/{sub}: a reason is required")
        if not str(v.get("reason", "")).strip() and "domains" in v:
            errors.append(f"{qid}: a reason is required with domains")
    return errors


def validate_check(patch: list, check) -> list[str]:
    """The evaluator's verdicts on a patch: exactly one per patch entry, pass or fail (a fail with a reason)."""
    if not isinstance(check, list) or not all(isinstance(v, dict) for v in check):
        return ["the check file must be a JSON list of verdicts"]
    ids = [e.get("subcategory_id") for e in patch if isinstance(e, dict)]
    got = [v.get("subcategory_id") for v in check]
    errors = [] if sorted(got) == sorted(ids) else [f"the check needs exactly one verdict per patch entry "
                                                     f"(missing {sorted(set(ids) - set(got))}, extra or repeated "
                                                     f"{sorted({g for g in got if g not in ids or got.count(g) > 1})})"]
    for v in check:
        if v.get("verdict") not in ("pass", "fail") or (v["verdict"] == "fail" and not str(v.get("reason", "")).strip()):
            errors.append(f"{v.get('subcategory_id')}: verdict must be pass or fail, and a fail needs a reason")
    return errors


def load_list(path: Path) -> list:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"[record_csf_bank] ERROR: cannot read {path} as JSON: {e}")


EVIDENCE_WRITER = "prompts/csf_evidence_writer.md"
EVIDENCE_EVALUATOR = "prompts/csf_evidence_evaluator.md"
EVIDENCE_MIN, EVIDENCE_MAX = 30, 400
EVIDENCE_INPUT = BANK_BUILD / "evidence_input.json"     # round 1: the writers' input
EVIDENCE_REVISE = BANK_BUILD / "evidence_revise.json"   # round 2: what failed round 1, with the evaluator's reason
EVIDENCE_REVIEW = BANK_BUILD / "evidence_review.json"   # what failed both rounds: a person decides


def evidence_targets() -> dict[str, dict]:
    """Active CSF subcategories with no evidence line decided yet (none of their own, and a person has not chosen to
    keep the category line): {id: {outcome, implementation_examples}}."""
    doc = json.loads(EVIDENCE_PROMPTS.read_text())
    decided = set(doc.get("by_subcategory", {})) | set(doc.get("category_line_kept", {}))
    return {s["subcategory_id"]: {"outcome": s["subcategory_text"],
                                  "implementation_examples": s.get("implementation_examples") or []}
            for s in json.loads(CSF_CORE.read_text())["subcategories"]
            if not s["subcategory_text"].startswith("[Withdrawn") and s["subcategory_id"] not in decided}


def prompt_problems(data: dict) -> list[str]:
    return [f"{sid}: the evidence prompt must be text of {EVIDENCE_MIN} to {EVIDENCE_MAX} characters"
            for sid, t in data.items() if not isinstance(t, str) or not EVIDENCE_MIN <= len(t.strip()) <= EVIDENCE_MAX]


def validate_evidence(data, review, allowed: set[str]) -> list[str]:
    """The writer's {subcategory: prompt} and the evaluator's verdicts, one per prompt. Round 1: only subcategories
    without an evidence line; round 2: exactly the ones that failed round 1."""
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object {subcategory: evidence prompt}"]
    errors = [f"{sid}: not a subcategory this round writes for" for sid in data if sid not in allowed]
    errors += prompt_problems(data)
    errors += validate_check([{"subcategory_id": sid} for sid in data], review)
    return errors


def store_prompts(prompts: dict) -> None:
    doc = json.loads(EVIDENCE_PROMPTS.read_text())
    doc.setdefault("by_subcategory", {}).update({sid: t.strip() for sid, t in prompts.items()})
    doc["by_subcategory"] = dict(sorted(doc["by_subcategory"].items()))
    EVIDENCE_PROMPTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.is_file() else default


def evidence_prepare() -> None:
    """Round 1 input: the subcategories without an evidence line. Refused while an earlier round is unfinished."""
    for f, what in ((EVIDENCE_REVISE, "the revision round"), (EVIDENCE_REVIEW, "the review by a person")):
        if f.is_file():
            sys.exit(f"[record_csf_bank] ERROR: {f.name} exists: finish {what} first.")
    ev = audit.begin(BANK_BUILD / "audit.jsonl", "csf_evidence_prepare", {})
    items = [{"id": sid, **t} for sid, t in evidence_targets().items()]
    EVIDENCE_INPUT.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
    ev.finish(inputs=[CSF_CORE, EVIDENCE_PROMPTS], outputs=[EVIDENCE_INPUT], detail=f"{len(items)} subcategories")
    print(f"[record_csf_bank] wrote {EVIDENCE_INPUT.name}: {len(items)} subcategories without an "
          "evidence line")


def evidence_record(argv: list[str]) -> None:
    """Store the prompts that passed. Round 1: failures go to evidence_revise.json for one revision. Round 2
    (--revision): failures go to evidence_review.json for a person."""
    parser = argparse.ArgumentParser(prog="record_csf_bank.py evidence")
    parser.add_argument("file", help="the writer's {subcategory: evidence prompt}")
    parser.add_argument("--review", required=True, help="the evaluator's verdicts")
    parser.add_argument("--revision", action="store_true", help="round 2: the revised prompts of evidence_revise.json")
    parser.add_argument("--model", required=True, help="the writer's model id")
    parser.add_argument("--session", help="e.g. evaluator=<model id>")
    a = parser.parse_args(argv)
    review = load_list(Path(a.review))
    revise = read_json(EVIDENCE_REVISE, {"items": []})["items"]
    if a.revision and not revise:
        sys.exit(f"[record_csf_bank] ERROR: --revision, but {EVIDENCE_REVISE.name} has nothing to revise")
    allowed = {i["id"] for i in revise} if a.revision else set(evidence_targets())

    def validate(data):
        errors = validate_evidence(data, review, allowed)
        if a.revision and not errors and set(data) != allowed:
            errors.append(f"revise every failed prompt: missing {sorted(allowed - set(data))}")
        return errors

    def store(data):
        reasons = {v["subcategory_id"]: v.get("reason", "") for v in review if v["verdict"] == "fail"}
        store_prompts({sid: t for sid, t in data.items() if sid not in reasons})
        targets = evidence_targets()
        if a.revision:
            earlier = {i["id"]: i for i in revise}
            items = [{"id": sid, "outcome": earlier[sid]["outcome"],
                      "implementation_examples": earlier[sid]["implementation_examples"],
                      "drafts": [{"text": earlier[sid]["draft"], "failed_because": earlier[sid]["reason"]},
                                 {"text": data[sid], "failed_because": reasons[sid]}],
                      "prompt": None, "keep_category_line": False}
                     for sid in sorted(reasons)]
            EVIDENCE_REVISE.unlink()
            if items:
                EVIDENCE_REVIEW.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
            nxt = f"{len(items)} for a person in {EVIDENCE_REVIEW.name}" if items else "nothing left for a person"
        else:
            items = revise + [{"id": sid, **targets[sid], "draft": data[sid], "reason": reasons[sid]}
                              for sid in sorted(reasons)]
            if items:
                EVIDENCE_REVISE.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
            nxt = f"{len(items)} to revise in {EVIDENCE_REVISE.name}"
        return EVIDENCE_PROMPTS, f"{len(data) - len(reasons)} evidence prompts stored, {len(reasons)} failed; {nxt}"

    audit.record_agent_output(
        log_path=BANK_BUILD / "audit.jsonl", log_dir=BANK_BUILD / "judgement_log",
        step="csf_evidence_revision" if a.revision else "csf_evidence", args={"file": a.file, "review": a.review},
        file=a.file, validate=validate, store=store, model=a.model, session=a.session,
        prompts=[EVIDENCE_WRITER, EVIDENCE_EVALUATOR],
        extra_inputs=[EVIDENCE_REVISE if a.revision else EVIDENCE_INPUT, Path(a.review)], extra_record={"review": review})


def validate_review(data) -> list[str]:
    """A person's decisions in evidence_review.json: each item has either its own `prompt` (30 to 400 characters) or
    `keep_category_line` true, not both."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return ["evidence_review.json must hold {\"items\": [...]}"]
    errors = []
    for i in items:
        own, keep = i.get("prompt"), i.get("keep_category_line") is True
        if bool(own) == keep:
            errors.append(f"{i.get('id')}: give either a prompt or keep_category_line: true")
        elif own:
            errors += prompt_problems({i.get("id"): own})
    return errors


def evidence_reviewed() -> None:
    """Store a person's decisions from evidence_review.json. They are final: a later build never asks again for a
    subcategory with its own prompt or with the category line kept."""
    if not EVIDENCE_REVIEW.is_file():
        sys.exit(f"[record_csf_bank] ERROR: {EVIDENCE_REVIEW.name} not found: nothing to review")

    def store(data):
        items = data["items"]
        store_prompts({i["id"]: i["prompt"] for i in items if i.get("prompt")})
        doc = json.loads(EVIDENCE_PROMPTS.read_text())
        kept = doc.setdefault("category_line_kept", {})
        kept.update({i["id"]: "decided by a person after two failed drafts" for i in items if not i.get("prompt")})
        doc["category_line_kept"] = dict(sorted(kept.items()))
        EVIDENCE_PROMPTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        EVIDENCE_REVIEW.unlink()
        n_own = sum(1 for i in items if i.get("prompt"))
        return EVIDENCE_PROMPTS, f"{n_own} prompts written by a person, {len(items) - n_own} keep the category line"

    audit.record_agent_output(
        log_path=BANK_BUILD / "audit.jsonl", log_dir=BANK_BUILD / "judgement_log", step="csf_evidence_review",
        args={}, file=EVIDENCE_REVIEW, validate=validate_review, store=store, model="person", decided_by="person")


def main():
    if sys.argv[1:3] == ["evidence", "prepare"]:
        return evidence_prepare()
    if sys.argv[1:3] == ["evidence", "reviewed"]:
        return evidence_reviewed()
    if sys.argv[1:2] == ["evidence"]:
        return evidence_record(sys.argv[2:])
    parser = argparse.ArgumentParser()
    parser.add_argument("verdicts")
    parser.add_argument("--pending", help="the pending_judgements file the agent was shown")
    parser.add_argument("--model", help="model id of the agent that made the verdicts")
    parser.add_argument("--session", help="session / run reference of the agent")
    parser.add_argument("--cache-dir", default=str(BANK_BUILD))
    args = parser.parse_args()

    cache = Path(args.cache_dir)
    candidates = json.loads((cache / "cset_candidates.json").read_text())
    csf_core = json.loads(CSF_CORE.read_text())
    valid_subs = {s["subcategory_id"] for s in csf_core["subcategories"]
                  if not s["subcategory_text"].startswith("[Withdrawn")}
    store_path = cache / "cset_judgements.json"

    def store(verdicts):
        store = json.loads(store_path.read_text()) if store_path.exists() else {"questions": {}}
        for qid, v in verdicts.items():
            entry = store["questions"].setdefault(qid, {})
            if entry.get("text_hash") != text_hash(candidates["questions"][qid]):
                entry.clear()  # stale verdicts for a changed question are dropped
            entry.update({k: val for k, val in v.items() if k in ("domains", "rewrite", "reason")})
            if "fit" in v:
                entry.setdefault("fit", {}).update(v["fit"])
            entry.update({"text_hash": text_hash(candidates["questions"][qid]),
                          "judged_on": date.today().isoformat(), "decided_by": "agent"})
        store_path.write_text(json.dumps(store, indent=2, ensure_ascii=False))
        return store_path, f"recorded {len(verdicts)} questions ({len(store['questions'])} judged in total)"

    audit.record_agent_output(
        log_path=cache / "audit.jsonl", log_dir=cache / "judgement_log", step="record_csf_bank",
        args={"verdicts": args.verdicts}, file=args.verdicts,
        validate=lambda verdicts: validate(verdicts, candidates, valid_subs), store=store,
        model=args.model, session=args.session, prompts=[str(JUDGE_PROMPT.relative_to(REPO_ROOT))],
        log_name=lambda verdicts: f"{len(verdicts)}q",
        extra_inputs=[args.pending] if args.pending else [],
        extra_record={"cset_commit": candidates["cset_commit"], "pending_file": args.pending,
                      "pending_sha": sha(Path(args.pending)) if args.pending else None},
        snapshot_key="verdicts")


if __name__ == "__main__":
    main()
