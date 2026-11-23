"""
Builds the six CSF question banks, one per sector, from the CSET questions linked to CSF 2.0. No agent, no judgement:
every question and every link is CSET's, and fixed rules decide which sector gets which question.

Why:       a client should get CSET's own questions for their sector, the same every time the bank is rebuilt from the
           same CSET commit. Certifications are not applied here; a client run applies them (compute_scope.py).
Called by: /build-csf-bank (step 3)
Input:     data/csf/bank_build/cset_candidates.json (extract_cset_candidates.py), data/csf/csf2_core.json, the rules in
           data/csf/bank_rules.json
Output:    data/csf/banks/question_bank_<sector>.json for every sector

Usage: .venv/bin/python ./scripts/build_csf_bank.py [--output-dir DIR] [--cache-dir DIR]

Per CSF subcategory, in this order:
  1. CSET's own CSF 2.0 question (the NCSF_V2 set), in every sector.
  2. The other CSET questions CSET links to it, from a set for this sector (bank_rules.json sector_by_model, e.g. ACET
     for finance) or a set listed for no sector (every sector). A question with a reject flag (CSET marks it not
     answerable, or it has no text) is left out. A practice with no question text (statement_only) is shown as its
     CSET outcome text. The same wording twice in a subcategory is kept once.
The banks are always built together, from the same CSET collection, so they share one record of what they were built
from (check_freshness.py --csf checks it).

This file also holds the evidence prompt steps of /build-csf-bank (step 4; record_bank.py csf-evidence-*):
  validate_evidence / store_evidence     round 1 of the evidence prompts (the Evidence Required line of the CSF
                                         sheet) -> data/csf/evidence_prompts.json; failures -> evidence_revise.json
                  ... / store_revision   round 2, the revised prompts; failures -> evidence_review.json
  validate_review / store_review         a person's decisions in evidence_review.json, final
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (BANK_BUILD, BANK_WORK, CSF_BANKS, CSF_BANK_RULES, CSF_CORE, CSF_FUNCTION_ORDER,  # noqa: E402
                     DOMAINS, EVIDENCE_PROMPTS, bank_path)
import audit  # noqa: E402

BANK_RULES = json.loads(CSF_BANK_RULES.read_text())   # data/csf/bank_rules.json
REJECT_FLAGS = set(BANK_RULES["reject_flags"])
STATEMENT_FIELD = BANK_RULES["statement_only_text"]["field"]
SECTOR_BY_MODEL = {k: v for k, v in BANK_RULES["sector_by_model"].items() if k != "description"}
CSF2_SET = "NCSF_V2"  # CSET's CSF 2.0 standard (cset_candidates.json `csf2_set`), first in every subcategory


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def question_text(q: dict) -> str:
    """CSET's question text; for a practice with none, CSET's own text of the field bank_rules.json names."""
    text = q["question_text"] or (q.get("practice") or {}).get(STATEMENT_FIELD) or ""
    return " ".join(text.split())


def for_sector(q: dict, sector: str) -> bool:
    """A set listed in sector_by_model is for that sector only; any other set is for every sector."""
    return SECTOR_BY_MODEL.get(q.get("model_name"), sector) == sector and not REJECT_FLAGS & set(q["flags"])


def build_bank(sector: str, candidates: dict, active: dict[str, dict]) -> dict:
    by_sub: dict[str, list[dict]] = {sid: [] for sid in active}
    seen: dict[str, set[str]] = {sid: set() for sid in active}

    def add(sid: str, entry: dict) -> None:
        key = norm(entry["question_text"])
        if sid in active and key and key not in seen[sid]:
            seen[sid].add(key)
            by_sub[sid].append(entry)

    for sid, entry in candidates.get("csf2_set", {}).items():
        for q in entry["questions"]:
            add(sid, {"cset_question_id": q["question_id"], "cset_set": CSF2_SET, "question_text": q["question_text"],
                      "model_name": CSF2_SET})
    links = sorted(((int(m["qid"]), m["subcategory_id"]) for m in candidates["mappings"]))
    for qid, sid in links:
        q = candidates["questions"].get(str(qid))
        if q is None or not for_sector(q, sector):
            continue
        add(sid, {"cset_question_id": qid, "question_text": question_text(q), "model_name": q.get("model_name"),
                  "category": q.get("category"), "sub_category": q.get("sub_category"),
                  "text_from": STATEMENT_FIELD if not q["question_text"] else "question"})

    ordered = sorted(active, key=lambda s: (CSF_FUNCTION_ORDER.get(s[:2], 9), s))
    return {"sector": sector, "cset_commit": candidates["cset_commit"], "built_on": date.today().isoformat(),
            "inputs_sha": bank_inputs_sha(),
            "questions": {sid: {"subcategory_text": active[sid]["subcategory_text"], "candidates": by_sub[sid]}
                          for sid in ordered}}


def bank_inputs_sha() -> dict:
    """Hashes of the local inputs a bank is built from besides CSET (check_freshness compares them)."""
    return {"bank_rules": audit.sha(CSF_BANK_RULES), "csf2_core": audit.sha(CSF_CORE)}


# ── Evidence prompts: the Evidence Required line of the CSF sheet (record_bank.py csf-evidence-*) ─────────────
# Round 1 (writers, evaluators) -> one revision of what failed -> what fails again goes to a person (rule 7).

EVIDENCE_WRITER = "prompts/csf_evidence_writer.md"
EVIDENCE_EVALUATOR = "prompts/csf_evidence_evaluator.md"
EVIDENCE_MIN, EVIDENCE_MAX = 30, 400
EVIDENCE_INPUT = BANK_WORK / "evidence_input.json"     # round 1: the writers' input
EVIDENCE_REVISE = BANK_WORK / "evidence_revise.json"   # round 2: what failed round 1, with the evaluator's reason
EVIDENCE_REVIEW = BANK_WORK / "evidence_review.json"   # what failed both rounds: a person decides


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


def load_list(path: Path) -> list:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"[build_csf_bank] ERROR: cannot read {path} as JSON: {e}")


def evidence_prepare() -> None:
    """Round 1 input: the subcategories without an evidence line. Refused while an earlier round is unfinished."""
    for f, what in ((EVIDENCE_REVISE, "the revision round"), (EVIDENCE_REVIEW, "the review by a person")):
        if f.is_file():
            sys.exit(f"[build_csf_bank] ERROR: {f.name} exists: finish {what} first.")
    ev = audit.begin(BANK_BUILD / "audit.jsonl", "csf_evidence_prepare", {})
    items = [{"id": sid, **t} for sid, t in evidence_targets().items()]
    EVIDENCE_INPUT.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_INPUT.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
    ev.finish(inputs=[CSF_CORE, EVIDENCE_PROMPTS], outputs=[EVIDENCE_INPUT], detail=f"{len(items)} subcategories")
    print(f"[build_csf_bank] wrote {EVIDENCE_INPUT.name}: {len(items)} subcategories without an "
          "evidence line")


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


def store_evidence(data: dict, review: list) -> tuple[Path, str]:
    """Round 1: store what passed; what failed goes to evidence_revise.json with the evaluator's reason."""
    reasons = {v["subcategory_id"]: v.get("reason", "") for v in review if v["verdict"] == "fail"}
    store_prompts({sid: t for sid, t in data.items() if sid not in reasons})
    targets = evidence_targets()
    items = load_json(EVIDENCE_REVISE, {"items": []})["items"] + [
        {"id": sid, **targets[sid], "draft": data[sid], "reason": reasons[sid]} for sid in sorted(reasons)]
    if items:
        EVIDENCE_REVISE.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False))
    return EVIDENCE_PROMPTS, (f"{len(data) - len(reasons)} evidence prompts stored, {len(reasons)} failed; "
                              f"{len(items)} to revise in {EVIDENCE_REVISE.name}")


def store_revision(data: dict, review: list, revise: list) -> tuple[Path, str]:
    """Round 2: store what passed; what failed again goes to evidence_review.json, with both drafts, for a person."""
    reasons = {v["subcategory_id"]: v.get("reason", "") for v in review if v["verdict"] == "fail"}
    store_prompts({sid: t for sid, t in data.items() if sid not in reasons})
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
    return EVIDENCE_PROMPTS, f"{len(data) - len(reasons)} evidence prompts stored, {len(reasons)} failed; {nxt}"


def record_evidence(file: str, review_file: str, revision: bool, model: str, session: str | None) -> None:
    """Round 1, or with revision=True round 2 (exactly the prompts that failed round 1)."""
    review = load_list(Path(review_file))
    revise = load_json(EVIDENCE_REVISE, {"items": []})["items"]
    if revision and not revise:
        sys.exit(f"[build_csf_bank] ERROR: a revision, but {EVIDENCE_REVISE.name} has nothing to revise")
    allowed = {i["id"] for i in revise} if revision else set(evidence_targets())

    def validate(data):
        errors = validate_evidence(data, review, allowed)
        if revision and not errors and set(data) != allowed:
            errors.append(f"revise every failed prompt: missing {sorted(allowed - set(data))}")
        return errors

    audit.record_agent_output(
        log_path=BANK_BUILD / "audit.jsonl", log_dir=BANK_BUILD / "judgement_log",
        step="csf_evidence_revision" if revision else "csf_evidence", args={"file": file, "review": review_file},
        file=file, validate=validate,
        store=(lambda d: store_revision(d, review, revise)) if revision else (lambda d: store_evidence(d, review)),
        model=model, session=session, prompts=[EVIDENCE_WRITER, EVIDENCE_EVALUATOR],
        extra_inputs=[EVIDENCE_REVISE if revision else EVIDENCE_INPUT, Path(review_file)], extra_record={"review": review})


def store_review(data: dict) -> tuple[Path, str]:
    """A person's decisions, final: their own prompt, or keep the category line (never asked again)."""
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


def record_review() -> None:
    if not EVIDENCE_REVIEW.is_file():
        sys.exit(f"[build_csf_bank] ERROR: {EVIDENCE_REVIEW.name} not found: nothing to review")
    audit.record_agent_output(
        log_path=BANK_BUILD / "audit.jsonl", log_dir=BANK_BUILD / "judgement_log", step="csf_evidence_review",
        args={}, file=EVIDENCE_REVIEW, validate=validate_review, store=store_review, model="human", decided_by="human")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(CSF_BANKS))
    parser.add_argument("--cache-dir", default=str(BANK_BUILD))
    args = parser.parse_args()

    cache, out_dir = Path(args.cache_dir), Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = audit.begin(cache / "audit.jsonl", "build_csf_bank", {})
    candidates = load_json(cache / "cset_candidates.json")
    if candidates is None:
        ev.fail("[build_csf_bank] ERROR: cset_candidates.json not found. Run scripts/extract_cset_candidates.py first.")
    active = {s["subcategory_id"]: s for s in load_json(CSF_CORE)["subcategories"]
              if not s["subcategory_text"].startswith("[Withdrawn")}

    paths, details = [], []
    for sector in DOMAINS:
        bank = build_bank(sector, candidates, active)
        path = bank_path(sector, out_dir)
        path.write_text(json.dumps(bank, indent=2, ensure_ascii=False))
        paths.append(path)
        n = sum(len(v["candidates"]) for v in bank["questions"].values())
        empty = sum(1 for v in bank["questions"].values() if not v["candidates"])
        details.append(f"{sector}: {n} questions, {empty} subcategories empty")
    print("[build_csf_bank] " + "; ".join(details) + f" (CSET {candidates['cset_commit'][:7]})")
    ev.finish(inputs=[cache / "cset_candidates.json", CSF_CORE, CSF_BANK_RULES], outputs=paths,
              detail="; ".join(details), cset_commit=candidates["cset_commit"])


if __name__ == "__main__":
    main()
