"""
Checks and stores AI agent decisions on the CSF side. Nothing gets into the store without passing its checks.

Called by: /build-csf-bank (steps 4 and 5); /csf-questionnaire (step 3, `log`)
Input:     the agent's file (decisions, evidence lines, or the SoA reading)
Output:    data/csf/bank_build/cset_judgements.json, data/csf/evidence_prompts.json, or a record in the run
           folder; a write-once copy in judgement_log/

Usage: .venv/bin/python ./scripts/record_judgements.py <verdicts.json> [--pending PATH] [--model ID] [--session REF] [--cache-dir DIR]
       .venv/bin/python ./scripts/record_judgements.py evidence prepare
       .venv/bin/python ./scripts/record_judgements.py evidence <prompts.json> --review <verdicts.json> --model ID
       .venv/bin/python ./scripts/record_judgements.py log <run_dir> --step NAME --output FILE --model ID
                  [--prompt PATH] [--inputs FILE ...] [--session REF]

  <verdicts.json>  /build-csf-bank step 4: the agent's decisions on the pending CSET questions (which sectors a
                   question suits, a rewrite, whether it fits a subcategory), stored in
                   data/csf/bank_build/cset_judgements.json. Format and checks: validate().
  evidence         /build-csf-bank step 5: `prepare` writes the evidence writer's input; the second form stores the
                   evidence lines the evaluator passed in data/csf/evidence_prompts.json.
  log              /csf-questionnaire step 3: keeps a record of the agent's SoA reading in the run folder.

Each form checks the whole file and exits 1, storing nothing, if anything is wrong. Every recording also writes a
write-once record to judgement_log/ (who decided, with which prompt and inputs, and what they said). A stored decision
remembers the question text it was based on, so it is ignored if CSET later changes that question.
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
from audit import sha, run_log  # noqa: E402

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


def validate_check(patch: list, check, prev: tuple[list, list] | None = None) -> list[str]:
    """The checker's verdicts on a patch: one per patch entry, pass or fail (a fail with a reason); in round 2 an entry
    identical to the earlier patch that passed then must pass now."""
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
    if prev:
        old = {e["subcategory_id"]: e for e in prev[0]}
        passed = {v["subcategory_id"] for v in prev[1] if v.get("verdict") == "pass"}
        now = {e["subcategory_id"]: e for e in patch if isinstance(e, dict)}
        flipped = [v["subcategory_id"] for v in check if v.get("verdict") == "fail" and v["subcategory_id"] in passed
                   and now.get(v["subcategory_id"]) == old.get(v["subcategory_id"])]
        if flipped:
            errors.append(f"round 2 fails entries that are unchanged and passed round 1: {', '.join(flipped)}")
    return errors


def load_list(path: Path) -> list:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"[record_judgements] ERROR: cannot read {path} as JSON: {e}")


def log_run_step(argv: list[str]) -> None:
    """Record an agent step inside an engagement run (the SoA reading) through the shared recording contract."""
    parser = argparse.ArgumentParser(prog="record_judgements.py log")
    parser.add_argument("run_dir")
    parser.add_argument("--step", required=True, help="e.g. soa_exclusions")
    parser.add_argument("--output", required=True, help="the file the agent wrote (relative to run_dir)")
    parser.add_argument("--model", required=True, help="model id of the agent that made the judgements")
    parser.add_argument("--prompt", help="prompt file the agent followed, relative to the repo root")
    parser.add_argument("--inputs", nargs="*", default=[], help="files the agent was shown (relative to run_dir)")
    parser.add_argument("--session", help="session / run reference of the agent")
    a = parser.parse_args(argv)

    run_dir = Path(a.run_dir)
    if not run_dir.is_dir():
        sys.exit(f"[record_judgements] ERROR: run folder not found: {run_dir}")

    def rp(p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else run_dir / q

    out = rp(a.output)
    extra_inputs = [rp(p) for p in a.inputs]
    extra_record = {"inputs": [{"path": p, "sha": sha(rp(p))} for p in a.inputs], "output": {"path": a.output}}
    # an output another script validates on its next run (soa_judgements.json): recorded as submitted
    file, validate = out, lambda data: []
    store = lambda data: (out, f"logged step '{a.step}'")  # noqa: E731

    audit.record_agent_output(
        log_path=run_log(run_dir), log_dir=run_dir / "judgement_log", step=a.step, args={"prompt": a.prompt},
        file=file, validate=validate, store=store, model=a.model, session=a.session,
        prompts=[a.prompt] if a.prompt else [], extra_inputs=extra_inputs, extra_record=extra_record)


EVIDENCE_WRITER = "prompts/csf_evidence_writer.md"
EVIDENCE_MIN, EVIDENCE_MAX = 30, 400


def evidence_targets() -> dict[str, dict]:
    """Active CSF subcategories with no evidence prompt of their own yet: {id: {outcome, implementation_examples}}."""
    have = json.loads(EVIDENCE_PROMPTS.read_text()).get("by_subcategory", {})
    return {s["subcategory_id"]: {"outcome": s["subcategory_text"],
                                  "implementation_examples": s.get("implementation_examples") or []}
            for s in json.loads(CSF_CORE.read_text())["subcategories"]
            if not s["subcategory_text"].startswith("[Withdrawn") and s["subcategory_id"] not in have}


def validate_evidence(data, review) -> list[str]:
    """The writer's {subcategory: prompt} for subcategories without one, and the evaluator's verdicts, one per prompt."""
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object {subcategory: evidence prompt}"]
    targets = evidence_targets()
    errors = [f"{sid}: not a subcategory without an evidence prompt" for sid in data if sid not in targets]
    errors += [f"{sid}: the evidence prompt must be text of {EVIDENCE_MIN} to {EVIDENCE_MAX} characters"
               for sid, t in data.items() if not isinstance(t, str) or not EVIDENCE_MIN <= len(t.strip()) <= EVIDENCE_MAX]
    errors += validate_check([{"subcategory_id": sid} for sid in data], review)
    return errors


def record_evidence(argv: list[str]) -> None:
    """`evidence prepare`: the writer's input. `evidence <file> --review <file> --model ID`: store the passing prompts
    in evidence_prompts.json by_subcategory (a failed prompt is not stored; the category line stays)."""
    if argv[:1] == ["prepare"]:
        ev = audit.begin(BANK_BUILD / "audit.jsonl", "csf_evidence_prepare", {})
        items = [{"id": sid, **t} for sid, t in evidence_targets().items()]
        out = BANK_BUILD / "evidence_input.json"
        out.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
        ev.finish(inputs=[CSF_CORE, EVIDENCE_PROMPTS], outputs=[out], detail=f"{len(items)} subcategories without one")
        print(f"[record_judgements] wrote {out.relative_to(REPO_ROOT)}: {len(items)} subcategories without an evidence prompt")
        return
    parser = argparse.ArgumentParser(prog="record_judgements.py evidence")
    parser.add_argument("file", help="the writer's {subcategory: evidence prompt}")
    parser.add_argument("--review", required=True, help="the evaluator's verdicts (failed prompts are not stored)")
    parser.add_argument("--model", required=True, help="the writer's model id")
    parser.add_argument("--session", help="e.g. evaluator=<model id>")
    a = parser.parse_args(argv)
    review = load_list(Path(a.review))

    def store(data):
        failed = {v["subcategory_id"] for v in review if v["verdict"] == "fail"}
        doc = json.loads(EVIDENCE_PROMPTS.read_text())
        doc.setdefault("by_subcategory", {}).update({sid: t.strip() for sid, t in data.items() if sid not in failed})
        doc["by_subcategory"] = dict(sorted(doc["by_subcategory"].items()))
        EVIDENCE_PROMPTS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        return EVIDENCE_PROMPTS, (f"{len(data) - len(failed)} evidence prompts stored, {len(failed)} failed the check "
                                  f"(they keep the category line); {len(evidence_targets())} subcategories still without one")

    audit.record_agent_output(
        log_path=BANK_BUILD / "audit.jsonl", log_dir=BANK_BUILD / "judgement_log", step="csf_evidence",
        args={"file": a.file, "review": a.review}, file=a.file, validate=lambda d: validate_evidence(d, review),
        store=store, model=a.model, session=a.session, prompts=[EVIDENCE_WRITER, "prompts/csf_evidence_evaluator.md"],
        extra_inputs=[BANK_BUILD / "evidence_input.json", Path(a.review)], extra_record={"review": review})


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "log":
        return log_run_step(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "evidence":
        return record_evidence(sys.argv[2:])
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
        log_path=cache / "audit.jsonl", log_dir=cache / "judgement_log", step="record_judgements",
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
