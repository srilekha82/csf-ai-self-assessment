"""
The External AI question bank: per CSF 2.0 subcategory that NIST links to CIS Controls v8.1, the threat AI outside the
organisation brings there (other people's agents, MCP clients, scrapers, AI-enabled attackers) and one or two questions
on how the organisation's practice has changed for it. Every organisation gets them, whether it uses AI or not. Checks
the generated questions before they are stored, says whether the bank is complete, and converts the bank to and from
its review spreadsheet.

Why:       the questions reach every client. A script checks what agents get wrong (known subcategories, one or two
           distinct questions, a person's decisions kept) before anything is stored, and works out the CIS safeguards
           of each subcategory from NIST's own references, so no agent writes them.
Called by: record_bank.py (ai-external, ai-assemble --kind external, ai-check, ai-confirm-current), prepare_ai_bank.py
           (external), sheet_io.py (the external_questions sheet), check_freshness.py (bank external)
Input:     data/ai/banks/question_bank_external.json, data/csf/crosswalks/olir_cis_v81.json (NIST's CSF -> CIS v8.1
           references), data/csf/csf2_core.json, data/ai/cis_ai_safeguard_ids.json, data/ai/question_rules.json
           (external_bank, text_limits)
Output:    data/ai/banks/question_bank_external.json

A bank entry: `threat` (decided by a person: what AI outside changes for this outcome), `cis_refs` (the AI companion
guide safeguards with AI guidance for the CIS safeguards NIST lists, e.g. "AGENT-8.11"; written by this script), and,
once generated, `questions` [{question_text}], `status`, `turns`, `review_reasons`, `decided_by`. An entry with no
questions yet is waiting for /build-ai-bank. The Evidence Required line a client sees is NIST's implementation examples
for the subcategory (read from csf2_core.json when the sheet is written), so the bank holds none.

Terms (needs human review, decided by a person): see docs/guide.md, Glossary.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (AI_BANK_EXTERNAL, AI_QUESTION_RULES, AI_SAFEGUARD_IDS, CSF_CIS_CROSSWALK, CSF_CORE,  # noqa: E402
                    SHEET_SPECS)
from ai_bank_common import load_json  # noqa: E402
import audit  # noqa: E402

SHEET_WORDS = json.loads(SHEET_SPECS.read_text())["review_words"]   # data/common/sheet_specs.json
WHOLE = SHEET_WORDS["whole_subcategory"]
# The evaluator's checks (prompts/ai_external_question_evaluator.md); in round 2 an unchanged question that passed
# round 1 may newly fail only check 6 (it now repeats a rewritten question).
EXTERNAL_CHECKS = [str(n) for n in range(1, 7)]
EXTERNAL_TURN_TWO_RECHECKS = {"6"}


def rules() -> dict:
    """question_rules.json external_bank (questions per subcategory, guides) and the text limits."""
    q = load_json(AI_QUESTION_RULES, "question_rules.json")
    return {**q["external_bank"], "min_chars": q["text_limits"]["min_chars"],
            "threat_min_chars": q["text_limits"]["note_min_chars"]}


def cis_links() -> dict[str, list[str]]:
    """{CSF subcategory: CIS v8.1 safeguard ids} from NIST's references (parse_csf_source.py)."""
    if not CSF_CIS_CROSSWALK.is_file():
        sys.exit(f"[ai_external] ERROR: {CSF_CIS_CROSSWALK} not found. Run parse_csf_source.py.")
    return load_json(CSF_CIS_CROSSWALK, CSF_CIS_CROSSWALK.name)["csf_to_controls"]


def outcomes() -> dict[str, dict]:
    """Active CSF 2.0 subcategories from csf2_core.json, by id."""
    return {s["subcategory_id"]: s for s in load_json(CSF_CORE, "csf2_core.json")["subcategories"]
            if s["subcategory_id"] and not s["subcategory_text"].startswith("[Withdrawn")}


def guide_refs(cis_ids: list[str], guides: list[str]) -> list[str]:
    """The companion guide safeguards ("<guide>-<CIS id>") with AI guidance for these CIS safeguards, guide by guide."""
    have = {r["id"] for r in load_json(AI_SAFEGUARD_IDS, AI_SAFEGUARD_IDS.name)["safeguards"] if r["has_ai_guidance"]}
    return [f"{g}-{c}" for g in guides for c in cis_ids if f"{g}-{c}" in have]


def load_bank(path: Path | None = None) -> dict:
    path = path or AI_BANK_EXTERNAL
    if not path.is_file():
        sys.exit(f"[ai_external] ERROR: {path} not found. The External AI bank starts from the threats a person "
                 "decided: add them in the review sheet (sheet_io.py import external_questions).")
    return load_json(path, path.name)


# ── agent output ────────────────────────────────────────────────────────────

def check_questions(sid: str, qs, r: dict) -> list[str]:
    if not isinstance(qs, list) or not r["questions"]["min"] <= len(qs) <= r["questions"]["max"]:
        return [f"{sid}: questions must be a list of {r['questions']['min']} to {r['questions']['max']}"]
    errors = []
    for n, q in enumerate(qs, 1):
        if not isinstance(q, dict) or set(q) != {"question_text"}:
            errors.append(f"{sid}#{n}: a question has exactly one field, question_text")
        elif not isinstance(q["question_text"], str) or len(q["question_text"].strip()) < r["min_chars"]:
            errors.append(f"{sid}#{n}: question_text shorter than {r['min_chars']} characters")
    texts = [str(q.get("question_text", "")).strip().lower() for q in qs if isinstance(q, dict)]
    if len(set(texts)) != len(texts):
        errors.append(f"{sid}: the same question_text twice")
    return errors


def validate_external(data, replace_human: bool = False) -> list[str]:
    """The assembled file (record_bank.py ai-assemble --kind external): {subcategory: {status, turns, questions,
    reasons}}. A subcategory must be in the bank with a threat; it gets questions_per_subcategory min to max distinct
    questions; needs_human_review carries the evaluator's reasons by question number. A subcategory a person decided
    in the review sheet is refused unless replace_human. Whether a question asks about the threat is the evaluator's
    job."""
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object keyed by CSF subcategory id"]
    bank, r, errors = load_bank()["subcategories"], rules(), []
    for sid, entry in data.items():
        if sid not in bank:
            errors.append(f"{sid}: not in the External AI bank (a subcategory starts with a threat a person decided)")
            continue
        if bank[sid].get("decided_by") == "human" and not replace_human:
            errors.append(f"{sid}: decided by a person in the review sheet; leave it out of the batch, or pass "
                          "--replace-human if the person agreed to regenerate it")
            continue
        if not isinstance(entry, dict) or entry.get("status") not in ("pass", "needs_human_review"):
            errors.append(f"{sid}: status must be 'pass' or 'needs_human_review'")
            continue
        if entry.get("turns") not in (1, 2):
            errors.append(f"{sid}: turns must be 1 or 2")
        reasons = entry.get("reasons", {})
        if entry["status"] == "needs_human_review" and not (
                isinstance(reasons, dict) and reasons and all(str(x).strip() for x in reasons.values())):
            errors.append(f"{sid}: needs_human_review requires the evaluator's reasons by question number")
        errors += check_questions(sid, entry.get("questions"), r)
    return errors


def store_external(data: dict, args, inp: dict) -> tuple[Path, str]:
    """Store checked questions (entries replaced per subcategory); returns (path, summary)."""
    bank = load_bank()
    for sid, entry in data.items():
        e = bank["subcategories"][sid]
        for k in ("review_reasons", "decided_by"):
            e.pop(k, None)
        e.update({"status": entry["status"], "turns": entry["turns"], "questions": entry["questions"],
                  **({"review_reasons": entry["reasons"]} if entry.get("reasons") else {})})
    bank.update(built_record(inp))
    write_bank(bank)
    subs = bank["subcategories"].values()
    review = sum(1 for e in subs if e.get("status") == "needs_human_review")
    waiting = sum(1 for e in subs if not e.get("questions"))
    return AI_BANK_EXTERNAL, (f"external bank: recorded {len(data)} subcategories; bank has "
                              f"{len(bank['subcategories']) - review - waiting} passed, {review} needing human review, "
                              f"{waiting} without questions")


def built_record(inp: dict) -> dict:
    """What a stored bank records about its sources: the build date, the CIS guides and NIST's CIS references."""
    return {"built_on": date.today().isoformat(),
            "guide_sha256_16": {g: s["sha256_16"] for g, s in inp["sg_doc"]["sources"].items()},
            "cis_links_sha256_16": audit.sha(CSF_CIS_CROSSWALK)}


def arrange(bank: dict) -> dict:
    """The bank with its entries in CSF order, each with the CIS safeguards worked out now (never by an agent)."""
    links, guides = cis_links(), rules()["guides"]
    for sid, e in bank["subcategories"].items():
        e["cis_refs"] = guide_refs(links.get(sid, []), guides)
    bank["subcategories"] = {sid: bank["subcategories"][sid] for sid in outcomes() if sid in bank["subcategories"]}
    return bank


def write_bank(bank: dict) -> None:
    AI_BANK_EXTERNAL.write_text(json.dumps(arrange(bank), indent=2, ensure_ascii=False))


# ── completeness and regression ─────────────────────────────────────────────

def entry_problems(sid: str, e: dict, links: dict, active: dict, r: dict) -> list[str]:
    """Problems of one stored entry that do not depend on its questions having been generated yet."""
    if sid not in active:
        return [f"{sid}: not an active CSF 2.0 subcategory"]
    if sid not in links:
        return [f"{sid}: NIST lists no CIS Controls v8.1 safeguard for it (External AI covers only those)"]
    if not isinstance(e.get("threat"), str) or len(e["threat"].strip()) < r["threat_min_chars"]:
        return [f"{sid}: threat must be at least {r['threat_min_chars']} characters"]
    return []


def bank_freshness(doc: dict) -> tuple[bool, str]:
    """(complete?, text) for the freshness check: every entry has questions and its CIS safeguards as they are now."""
    links, active, r = cis_links(), outcomes(), rules()
    subs = doc["subcategories"]
    bad = [p for sid, e in subs.items() for p in entry_problems(sid, e, links, active, r)]
    waiting = [sid for sid, e in subs.items() if not e.get("questions")]
    moved = [sid for sid, e in subs.items() if e.get("cis_refs") != guide_refs(links.get(sid, []), r["guides"])]
    if bad or waiting or moved:
        parts = (bad[:3] + ([f"{len(waiting)} of {len(subs)} subcategories without questions"] if waiting else [])
                 + ([f"CIS safeguards changed: {', '.join(moved)}"] if moved else []))
        return False, "incomplete (" + "; ".join(parts) + ")"
    review = sum(1 for e in subs.values() if e["status"] == "needs_human_review")
    return True, f"current ({len(subs)} subcategories, {review} need human review)"


def stored_bank_problems() -> list[str]:
    """The committed bank re-checked against the current rules (regression check). Writes nothing."""
    if not AI_BANK_EXTERNAL.is_file():
        return ["external bank: missing"]
    links, active, r = cis_links(), outcomes(), rules()
    problems = []
    for sid, e in load_bank()["subcategories"].items():
        problems += entry_problems(sid, e, links, active, r)
        if e.get("questions"):
            problems += check_questions(sid, e["questions"], r)
    return [f"external bank: {p}" for p in problems]


# ── review sheet ────────────────────────────────────────────────────────────

def sheet_rows(doc: dict) -> list[dict]:
    """One review-sheet line per question; a subcategory with no questions yet has one line with no question."""
    active, lines = outcomes(), []
    for sid, e in doc["subcategories"].items():
        base = {"subcategory": sid, "outcome": active.get(sid, {}).get("subcategory_text", ""), "threat": e["threat"],
                "cis_refs": e.get("cis_refs", []), "decided_by": e.get("decided_by", "agent")}
        reasons = e.get("review_reasons", {}) if e.get("status") == "needs_human_review" else {}
        for n, q in enumerate(e.get("questions") or [None], 1):
            own = "\n".join(filter(None, [reasons.get(str(n)), WHOLE + reasons["0"] if "0" in reasons else ""]))
            lines.append({**base, "q": str(n) if q else "", "question_text": q["question_text"] if q else "",
                          "status": "needs_human_review" if own else "pass", "review_reason": own})
    return lines


def from_sheet(lines: list[dict], doc: dict) -> tuple[dict, list[str], int]:
    """(new bank, problems, subcategories changed) from the review sheet. A person may edit a threat or a question, add
    or delete question lines, set Status, add a subcategory (one NIST links to CIS v8.1, with its threat; its questions
    may be left blank for /build-ai-bank to write) or drop one (delete all its lines). Every line of a subcategory carries
    the same threat. A changed subcategory is stored as decided_by human; clearing its questions leaves it for the
    next build."""
    from ai_questions import reason_from_lines
    links, active, r = cis_links(), outcomes(), rules()
    by_sub: dict[str, list[dict]] = {}
    for ln in lines:
        by_sub.setdefault(ln["subcategory"], []).append(ln)
    problems, new, changed = [], json.loads(json.dumps(doc)), []
    for sid, sub_lines in by_sub.items():
        threats = {str(ln["threat"] or "").strip() for ln in sub_lines}
        if len(threats) != 1:
            problems.append(f"{sid}: every line of a subcategory carries the same threat")
            continue
        threat = threats.pop()
        problems += entry_problems(sid, {"threat": threat}, links, active, r)
        asked = [ln for ln in sub_lines if str(ln["question_text"] or "").strip()]
        qs = [{"question_text": str(ln["question_text"]).strip()} for ln in asked]
        if qs:
            problems += check_questions(sid, qs, r)
        parts = reason_from_lines(asked)
        old = doc["subcategories"].get(sid)
        status = "needs_human_review" if parts else "pass"
        old_parts = old.get("review_reasons", {}) if old and old.get("status") == "needs_human_review" else {}
        if old and old["threat"] == threat and (old.get("questions") or []) == qs and (
                not qs or (old.get("status") == status and parts == old_parts)):
            continue
        e = {"threat": threat, "decided_by": "human"}
        if qs:
            e.update({"status": status, "turns": (old or {}).get("turns", 1), "questions": qs,
                      **({"review_reasons": parts} if parts else {})})
        new["subcategories"][sid] = e
        changed.append(sid)
    for sid in set(doc["subcategories"]) - set(by_sub):   # all its lines deleted: dropped
        new["subcategories"].pop(sid)
        changed.append(sid)
    if problems:
        return doc, problems, 0
    return arrange(new), [], len(changed)
