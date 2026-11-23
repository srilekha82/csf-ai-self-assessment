"""
Builds the six CSF question banks, one per sector, together from the collected CSET questions.

Why:       CSET links many maturity-model questions to each CSF subcategory, but some are for one sector only, cut off,
           or only loosely linked. Fixed rules settle most of them; an agent is asked only about the rest, once, and its
           decisions are kept, so every rebuild gives the same banks.
Called by: /build-csf-bank (step 3)
Input:     data/csf/bank_build/cset_candidates.json and cset_judgements.json (earlier agent decisions); the routing
           rules in data/csf/bank_rules.json
Output:    data/csf/banks/question_bank_<sector>.json for every sector, or work/pending_judgements.json (exit 2)

Usage: .venv/bin/python ./scripts/build_csf_bank.py [--fanout-threshold N] [--allow-pending] [--output-dir DIR]
                                                 [--cache-dir DIR]

The banks are always built together, from the same CSET collection and agent judgements, so they share one record of
what they were built from (check_freshness.py --csf checks it).

Each subcategory starts with CSET's own CSF 2.0 question (every sector). Each other CSET question is then:
  rejected   not answerable, empty, or already judged unfit or not for this sector
  accepted   its source model is for this sector (e.g. ACET for finance), or an earlier decision covers it
  pending    needs an agent: sector unclear, text to (re)write, or linked to many subcategories
             (--fanout-threshold; default in data/csf/bank_rules.json)

Exit 2 if anything is pending in any sector: it writes one pending_judgements.json (each question once, whatever
the sector) and no bank. An agent decides them (prompts/question_bank_judge.md), record_bank.py csf-cset stores the
decisions, then run it again. Decisions are tied to the question's text, so they are redone only if CSET changes the
question. --allow-pending writes the banks anyway, leaving pending questions out.

This file also holds the checks and stores record_bank.py uses for the CSF bank build (sections at the end):
  validate_cset / store_cset             the agent's decisions on pending CSET questions -> cset_judgements.json
  validate_evidence / store_evidence     round 1 of the evidence prompts (the Evidence Required line of the CSF
                                         sheet) -> data/csf/evidence_prompts.json; failures -> evidence_revise.json
                  ... / store_revision   round 2, the revised prompts; failures -> evidence_review.json
  validate_review / store_review         a person's decisions in evidence_review.json, final
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (BANK_BUILD, BANK_WORK, CROSSWALK_DIRS, CSF_BANKS, CSF_BANK_RULES, CSF_CORE, CSF_FUNCTION_ORDER,  # noqa: E402
                     DOMAINS, EVIDENCE_PROMPTS, bank_path)
import audit  # noqa: E402

BANK_RULES = json.loads(CSF_BANK_RULES.read_text())   # the routing policy: data/csf/bank_rules.json
REJECT_FLAGS = set(BANK_RULES["reject_flags"])
CSF2_SET = "NCSF_V2"  # CSET's CSF 2.0 standard (cset_candidates.json `csf2_set`), first candidate everywhere
# Questions whose text must be (re)written by the agent: a practice statement with no question,
# or a question CSET left cut off mid-sentence.
REWRITE_FLAGS = set(BANK_RULES["rewrite_flags"])

# Source models that are specific to one sector. Everything else is treated as generic.
SECTOR_BY_MODEL = {k: v for k, v in BANK_RULES["sector_by_model"].items() if k != "description"}


def text_hash(q: dict) -> str:
    """Hash of what a judgement was based on; a judgement is stale if CSET changes it."""
    basis = json.dumps([q["question_text"], q.get("practice", {})], sort_keys=True)
    return hashlib.sha1(basis.encode()).hexdigest()[:10]


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def route_pairs(domain: str, candidates: dict, judgements: dict, active: dict[str, dict],
                fanout_threshold: int) -> tuple[list[dict], dict[str, dict]]:
    """
    Route every (question, active subcategory) pair for one domain.
    Returns (routed_pairs, pending_by_qid).
    """
    questions = candidates["questions"]
    subs_of: dict[str, list[str]] = {}
    for m in candidates["mappings"]:
        if m["subcategory_id"] in active:
            subs_of.setdefault(str(m["qid"]), []).append(m["subcategory_id"])

    routed, pending = [], {}

    def need(qid: str, kind: str, sub: str | None = None):
        item = pending.setdefault(qid, {"needs": [], "fit_subcategories": []})
        if kind not in item["needs"]:
            item["needs"].append(kind)
        if sub and sub not in item["fit_subcategories"]:
            item["fit_subcategories"].append(sub)

    for qid, subs in subs_of.items():
        q = questions.get(qid)
        if q is None:
            continue
        j = judgements.get("questions", {}).get(qid)
        if j and j.get("text_hash") != text_hash(q):
            j = None  # CSET changed this question since it was judged

        def emit(sub, status, decided_by, reason, text=None):
            routed.append({"qid": qid, "subcategory_id": sub, "status": status,
                           "decided_by": decided_by, "reason": reason, "text": text})

        if REJECT_FLAGS & set(q["flags"]):
            for s in subs:
                emit(s, "reject", "schema", f"flags: {sorted(REJECT_FLAGS & set(q['flags']))}")
            continue

        # domain
        sector = SECTOR_BY_MODEL.get(q.get("model_name"))
        domain_by = "schema" if sector == domain else None
        if domain_by is None and j and "domains" in j:
            if domain not in j["domains"] and "all" not in j["domains"]:
                for s in subs:
                    emit(s, "reject", "agent", f"not suited to {domain}: {j.get('reason', '')}")
                continue
            domain_by = "agent"

        # Collect everything this question needs in one go, so the agent is asked once.
        fanout = len(subs)
        needs_rewrite = bool(REWRITE_FLAGS & set(q["flags"])) and not (j and "rewrite" in j)
        fit_missing = [s for s in subs if fanout >= fanout_threshold
                       and (j or {}).get("fit", {}).get(s) is None]
        if domain_by is None:
            need(qid, "domains")
        if needs_rewrite:
            need(qid, "rewrite")
        for s in fit_missing:
            need(qid, "fit", s)
        if qid in pending:
            for s in subs:
                emit(s, "pending", None, "needs judgement")
            continue

        text = q["question_text"]
        if REWRITE_FLAGS & set(q["flags"]):
            if not j["rewrite"]:
                for s in subs:
                    emit(s, "reject", "agent", "agent: cannot be asked as a question")
                continue
            text = j["rewrite"]

        for s in subs:
            if fanout >= fanout_threshold:
                verdict = j["fit"][s]
                if verdict["verdict"] == "reject":
                    emit(s, "reject", "agent", f"does not fit {s}: {verdict.get('reason', '')}")
                else:
                    emit(s, "accept", "agent", "fit confirmed", text)
            else:
                emit(s, "accept", domain_by, "domain match" if domain_by == "schema" else "agent domain verdict", text)
    return routed, pending


def bank_inputs_sha(cache: Path) -> dict:
    """Hashes of the local inputs a bank is built from besides CSET (check_freshness compares them)."""
    return {"cset_judgements": audit.sha(cache / "cset_judgements.json"), "csf2_core": audit.sha(CSF_CORE)}


def build_pending_file(pending: dict, candidates: dict, active: dict[str, dict]) -> dict:
    items = []
    for qid, p in sorted(pending.items(), key=lambda kv: int(kv[0])):
        q = candidates["questions"][qid]
        mapped = [m["subcategory_id"] for m in candidates["mappings"]
                  if str(m["qid"]) == qid and m["subcategory_id"] in active]
        items.append({
            "qid": qid,
            "needs": p["needs"],
            "model_name": q.get("model_name"),
            "category": q.get("category"),
            "sub_category": q.get("sub_category"),
            "question_text": q["question_text"],
            "practice": q.get("practice", {}),
            "mapped_subcategories": [{"id": s, "outcome": active[s]["subcategory_text"]} for s in sorted(mapped)],
            "check_fit_for": sorted(p["fit_subcategories"]),
        })
    return {"cset_commit": candidates["cset_commit"], "count": len(items), "items": items}


def build_bank(domain: str, routed: list[dict], candidates: dict, active: dict[str, dict],
               iso_lookup: dict, pending_count: int) -> dict:
    by_sub: dict[str, list[dict]] = {}
    seen: dict[str, set[str]] = {}
    # CSET's own CSF 2.0 question comes first in every subcategory (it is the subcategory, for every domain);
    # the maturity-model questions CSET maps to it follow as practice detail.
    for sid, entry in candidates.get("csf2_set", {}).items():
        if sid not in active:
            continue
        for q in entry["questions"]:
            seen.setdefault(sid, set()).add(norm(q["question_text"]))
            by_sub.setdefault(sid, []).append({
                "cset_question_id": q["question_id"],
                "cset_set": CSF2_SET,
                "question_text": q["question_text"],
                "category": None,
                "sub_category": None,
                "model_name": CSF2_SET,
                "decided_by": "schema",
                "reworded": False,
            })
    for r in sorted(routed, key=lambda r: int(r["qid"])):
        if r["status"] != "accept":
            continue
        text = r["text"]
        key = norm(text)
        if key in seen.setdefault(r["subcategory_id"], set()):
            continue  # same wording already offered for this subcategory
        seen[r["subcategory_id"]].add(key)
        q = candidates["questions"][r["qid"]]
        by_sub.setdefault(r["subcategory_id"], []).append({
            "cset_question_id": int(r["qid"]),
            "question_text": text,
            "category": q.get("category"),
            "sub_category": q.get("sub_category"),
            "model_name": q.get("model_name"),
            "decided_by": r["decided_by"],
            "reworded": text != q["question_text"],
        })

    ordered = sorted(active, key=lambda s: (CSF_FUNCTION_ORDER.get(s[:2], 9), s))
    questions = {
        sid: {
            "subcategory_text": active[sid]["subcategory_text"],
            "iso_mapping": iso_lookup.get(sid, []),
            "candidates": by_sub.get(sid, []),
        }
        for sid in ordered
    }
    with_candidates = sum(1 for v in questions.values() if v["candidates"])
    with_maturity = sum(1 for v in questions.values() if any(c.get("cset_set") != CSF2_SET for c in v["candidates"]))
    return {
        "domain": domain,
        "cset_commit": candidates["cset_commit"],
        "built_on": date.today().isoformat(),
        "total_subcategories": len(questions),
        "with_candidates": with_candidates,
        "empty": len(questions) - with_candidates,
        "with_maturity_questions": with_maturity,
        "pending_judgements": pending_count,
        "questions": questions,
    }


# ── The agent's decisions on CSET questions: checked and stored by record_bank.py csf-cset ─────────────────────

JUDGE_PROMPT = "prompts/question_bank_judge.md"
VALID_DOMAINS = set(DOMAINS) | {"all"}


def validate_cset(verdicts: dict, candidates: dict, valid_subs: set[str]) -> list[str]:
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


def store_cset(verdicts: dict, candidates: dict, store_path: Path) -> tuple[Path, str]:
    """Add the decisions to cset_judgements.json. A decision is tied to the question text it was made on (text_hash):
    when CSET changes the question, its earlier decisions are dropped."""
    store = json.loads(store_path.read_text()) if store_path.exists() else {"questions": {}}
    for qid, v in verdicts.items():
        entry = store["questions"].setdefault(qid, {})
        if entry.get("text_hash") != text_hash(candidates["questions"][qid]):
            entry.clear()
        entry.update({k: val for k, val in v.items() if k in ("domains", "rewrite", "reason")})
        if "fit" in v:
            entry.setdefault("fit", {}).update(v["fit"])
        entry.update({"text_hash": text_hash(candidates["questions"][qid]),
                      "judged_on": date.today().isoformat(), "decided_by": "agent"})
    store_path.write_text(json.dumps(store, indent=2, ensure_ascii=False))
    return store_path, f"recorded {len(verdicts)} questions ({len(store['questions'])} judged in total)"


def record_cset(file: str, pending: str | None, model: str, session: str | None, cache: Path | None = None) -> None:
    cache = cache or BANK_BUILD
    candidates = json.loads((cache / "cset_candidates.json").read_text())
    valid_subs = {s["subcategory_id"] for s in json.loads(CSF_CORE.read_text())["subcategories"]
                  if not s["subcategory_text"].startswith("[Withdrawn")}
    audit.record_agent_output(
        log_path=cache / "audit.jsonl", log_dir=cache / "judgement_log", step="csf_cset", args={"verdicts": file},
        file=file, validate=lambda d: validate_cset(d, candidates, valid_subs),
        store=lambda d: store_cset(d, candidates, cache / "cset_judgements.json"),
        model=model, session=session, prompts=[JUDGE_PROMPT], log_name=lambda d: f"{len(d)}q",
        extra_inputs=[pending] if pending else [],
        extra_record={"cset_commit": candidates["cset_commit"], "pending_file": pending,
                      "pending_sha": audit.sha(Path(pending)) if pending else None},
        snapshot_key="verdicts")


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


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.is_file() else default


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
    items = read_json(EVIDENCE_REVISE, {"items": []})["items"] + [
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
    revise = read_json(EVIDENCE_REVISE, {"items": []})["items"]
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
    parser.add_argument("--fanout-threshold", type=int, default=BANK_RULES["fanout_threshold"]["value"])
    parser.add_argument("--allow-pending", action="store_true")
    parser.add_argument("--output-dir", default=str(CSF_BANKS))
    parser.add_argument("--cache-dir", default=str(BANK_BUILD))
    args = parser.parse_args()

    cache, out_dir = Path(args.cache_dir), Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = audit.begin(cache / "audit.jsonl", "build_csf_bank",
                     {"fanout_threshold": args.fanout_threshold, "allow_pending": args.allow_pending})
    candidates = load_json(cache / "cset_candidates.json")
    if candidates is None:
        ev.fail("[build_csf_bank] ERROR: cset_candidates.json not found. Run scripts/extract_cset_candidates.py first.")
    judgements = load_json(cache / "cset_judgements.json", {"questions": {}})

    csf_core = load_json(CSF_CORE)
    active = {s["subcategory_id"]: s for s in csf_core["subcategories"]
              if not s["subcategory_text"].startswith("[Withdrawn")}
    olir_iso = load_json(CROSSWALK_DIRS["olir_iso27001.json"] / "olir_iso27001.json")
    iso_lookup = olir_iso["csf_to_controls"]
    build_inputs = [cache / "cset_candidates.json", cache / "cset_judgements.json", CSF_CORE]

    # Route every sector first: the banks are built together, from the same CSET collection and judgements.
    routed, pending = {}, {}
    for domain in DOMAINS:
        routed[domain], domain_pending = route_pairs(domain, candidates, judgements, active, args.fanout_threshold)
        for qid, p in domain_pending.items():         # one question needs one judgement, whatever the sector
            item = pending.setdefault(qid, {"needs": [], "fit_subcategories": []})
            item["needs"] += [n for n in p["needs"] if n not in item["needs"]]
            item["fit_subcategories"] += [s for s in p["fit_subcategories"] if s not in item["fit_subcategories"]]

    pending_path = cache / "work" / "pending_judgements.json"
    if pending:
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(json.dumps(build_pending_file(pending, candidates, active), indent=2, ensure_ascii=False))
        print(f"{len(pending)} questions need a judgement → {pending_path}")
        if not args.allow_pending:
            ev.finish("pending", build_inputs, [pending_path], detail=f"{len(pending)} questions need an agent judgement; "
                      "no bank written", cset_commit=candidates["cset_commit"])
            sys.exit(2)
    else:
        pending_path.unlink(missing_ok=True)

    paths, details = [], []
    for domain in DOMAINS:
        n_pending = sum(1 for r in routed[domain] if r["status"] == "pending")
        bank = build_bank(domain, routed[domain], candidates, active, iso_lookup, n_pending)
        bank["inputs_sha"] = bank_inputs_sha(cache)
        path = bank_path(domain, out_dir)
        path.write_text(json.dumps(bank, indent=2, ensure_ascii=False))
        paths.append(path)
        by = {}
        for r in routed[domain]:
            by[(r["status"], r["decided_by"])] = by.get((r["status"], r["decided_by"]), 0) + 1
        routing = ", ".join(f"{s}/{d or '-'}: {n}" for (s, d), n in sorted(by.items(), key=str))
        print(f"Built: {path}\n  Subcategories: {bank['total_subcategories']}, with candidates: {bank['with_candidates']} "
              f"(maturity-model questions in {bank['with_maturity_questions']}), empty: {bank['empty']}\n"
              f"  Routing: {routing}")
        details.append(f"{domain}: {bank['with_candidates']} of {bank['total_subcategories']} with candidates")
    print(f"CSET commit: {candidates['cset_commit']}")
    ev.finish(inputs=build_inputs, outputs=paths, detail="; ".join(details), cset_commit=candidates["cset_commit"])


if __name__ == "__main__":
    main()
