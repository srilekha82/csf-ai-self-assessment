"""
The CSF AI impact notes: a short note per CSF subcategory on what AI changes there. Checks the notes and the notes
checker's findings before they are stored, and converts the notes to and from their review spreadsheet.

Called by: record_bank.py (ai-notes, ai-notes-review), sheet_io.py (the impact notes sheet)
Input:     data/csf/ai_impact_notes.json, data/csf/csf2_core.json, the CIS safeguard data; the note length limit
           (data/ai/question_rules.json text_limits)
Output:    data/csf/ai_impact_notes.json

Terms (impact, needs human review, decided by a person): see docs/guide.md, Glossary.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import AI_BUILD, AI_CIS_CSF_XLSX, AI_QUESTION_RULES, CSF_CORE, CSF_IMPACT_NOTES  # noqa: E402
from ai_bank_common import load_json  # noqa: E402
import audit  # noqa: E402


NOTE_MIN_CHARS = json.loads(AI_QUESTION_RULES.read_text())["text_limits"]["note_min_chars"]
NOTE_KEYS = ("exposure", "base_rag", "mcp_agentic")   # the notes of one CSF subcategory; "use" = its use layer as a whole


def validate_notes_review(data) -> list[str]:
    """The notes evaluator's findings: [{subcategory_id, note (exposure, base_rag, mcp_agentic or use), reason}], on
    stored notes not yet reviewed (no status: new, or rewritten by the writer) and not decided by a person ([] = every
    unreviewed note passes). A note already reviewed keeps its verdict, as an unchanged question keeps its pass."""
    if not isinstance(data, list):
        return ["the file must be a JSON list of findings ([] if every note passes)"]
    notes = load_json(CSF_IMPACT_NOTES, "ai_impact_notes.json")["notes"] if CSF_IMPACT_NOTES.is_file() else {}
    errors = []
    for n, f in enumerate(data, 1):
        if not isinstance(f, dict) or set(f) != {"subcategory_id", "note", "reason"}:
            errors.append(f"finding {n}: fields must be exactly subcategory_id, note, reason")
            continue
        sid = f["subcategory_id"]
        if sid not in notes:
            errors.append(f"finding {n}: {sid} has no recorded notes")
        elif f["note"] not in NOTE_KEYS + ("use",) or (f["note"] in NOTE_KEYS[1:] and "use" not in notes[sid]) or \
                (f["note"] == "exposure" and "exposure" not in notes[sid]):
            errors.append(f"finding {n}: note must be use, or exposure / base_rag / mcp_agentic that {sid} has")
        elif notes[sid].get("decided_by") == "human":
            errors.append(f"finding {n}: {sid} was decided by a person in the review sheet")
        elif "status" in notes[sid]:
            errors.append(f"finding {n}: {sid} was already reviewed and has not been rewritten since")
        if not str(f.get("reason", "")).strip():
            errors.append(f"finding {n}: reason is empty")
    return errors


def notes_sheet_rows(doc: dict) -> list[dict]:
    """One review-sheet line per CSF subcategory with notes (sheet_io.py export impact_notes)."""
    outcome = {s["subcategory_id"]: s["subcategory_text"] for s in load_json(CSF_CORE, "csf2_core.json")["subcategories"]}
    return [{"subcategory": sid, "outcome": outcome.get(sid, ""), "exposure": v.get("exposure", ""),
             "base_rag": v.get("use", {}).get("base_rag", ""), "mcp_agentic": v.get("use", {}).get("mcp_agentic", ""),
             "status": v.get("status", "pass"), "review_reason": v.get("review_reason", ""),
             "decided_by": v.get("decided_by", "agent")} for sid, v in doc["notes"].items()]


def notes_from_sheet(lines: list[dict], doc: dict) -> tuple[dict, list[str], int]:
    """(new notes doc, problems, subcategories changed) from the review sheet. Notes come from the writer: the sheet may
    change them, clear the exposure note, clear or fill a use layer (both use notes or neither), and set Status, but
    not add a subcategory; clearing every note of a line drops its subcategory (no note). A changed subcategory is
    stored as decided_by human."""
    notes, problems, seen, changed = doc["notes"], [], set(), []
    new = json.loads(json.dumps(doc))
    for n, ln in enumerate(lines, 2):
        sid = ln["subcategory"]
        if sid not in notes or sid in seen:
            problems.append(f"row {n}: {sid} is not a recorded subcategory, or is listed twice (notes come from "
                            "/build-ai-bank, Step 7)")
            continue
        seen.add(sid)
        exposure = str(ln["exposure"] or "").strip()
        entry = {"exposure": exposure} if exposure else {}
        use = {k: str(ln[k] or "").strip() for k in NOTE_KEYS[1:]}
        if any(use.values()):
            entry["use"] = use
        if not entry:   # every note cleared: the subcategory has no note
            new["notes"].pop(sid, None)
            changed.append(sid)
            continue
        bad = validate_notes({sid: entry}, from_sheet=True)
        if not all(use.values()) and any(use.values()):
            bad.append(f"{sid}: give both use notes (model / RAG and tools / agents) or neither")
        problems += [f"row {n}: {b}" for b in bad]
        old = notes[sid]
        if bad or ({k: old[k] for k in ("exposure", "use") if k in old} == entry
                   and ln["status"] == old.get("status", "pass")):
            continue
        e = new["notes"][sid]
        e.pop("use", None)
        e.pop("exposure", None)
        e.update(entry, status=ln["status"], decided_by="human")
        if ln["status"] == "pass":
            e.pop("review_reason", None)
        else:
            e["review_reason"] = old.get("review_reason") or "flagged in the review sheet"
        changed.append(sid)
    if set(notes) - seen:
        problems.append(f"every subcategory keeps its notes; no line for {', '.join(sorted(set(notes) - seen))}")
    if problems:
        return doc, problems, 0
    return new, [], len(changed)


def validate_notes(data, from_sheet: bool = False) -> list[str]:
    """AI impact notes: {"PR.AA-05": {"exposure": "...", "use": {"base_rag": "...", "mcp_agentic": "..."}}}

    exposure (shown to every organisation) is optional: only where the safeguard text supports something real for an
    organisation with no AI (decided 2026-10-31); "exposure": null removes it. use (shown only when AI is in use) is
    added or removed the same way; an entry left with neither is dropped. A subcategory a person decided in the review
    sheet is refused. A rewritten note loses its review status and is reviewed again."""
    errors = []
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object keyed by CSF subcategory id"]
    csf = load_json(CSF_CORE, "csf2_core.json")["subcategories"]
    valid = {s["subcategory_id"] for s in csf if not s["subcategory_text"].startswith("[Withdrawn")}
    existing = load_json(CSF_IMPACT_NOTES, "ai_impact_notes.json")["notes"] if CSF_IMPACT_NOTES.is_file() else {}
    pending_path = AI_BUILD / "impact_pending.json"
    mapped = None
    if pending_path.is_file():
        mapped = {i["subcategory_id"] for i in load_json(pending_path, "impact_pending.json")["items"]}
    for sid, v in data.items():
        if sid not in valid:
            errors.append(f"{sid}: not an active CSF 2.0 subcategory")
            continue
        if mapped is not None and sid not in mapped:
            errors.append(f"{sid}: not in impact_pending.json (no mapped AI safeguard); notes are not invented for unmapped subcategories")
        if not isinstance(v, dict) or not set(v) <= {"exposure", "use"}:
            errors.append(f"{sid}: fields must be exposure and/or use")
            continue
        if not from_sheet and existing.get(sid, {}).get("decided_by") == "human" and \
                v != {k: existing[sid].get(k) for k in v}:
            errors.append(f"{sid}: decided by a person in the review sheet (sheet_io.py import impact_notes); not "
                          "overwritten")
        if v.get("exposure") is not None:   # exposure: null removes it (nothing real to say to an org with no AI)
            if not isinstance(v["exposure"], str) or len(v["exposure"].strip()) < NOTE_MIN_CHARS:
                errors.append(f"{sid}: exposure must be a note of at least {NOTE_MIN_CHARS} characters")
        if "use" in v and v["use"] is not None:   # use: null removes the use layer (a revision that finds none needed)
            u = v["use"]
            if not isinstance(u, dict) or set(u) != {"base_rag", "mcp_agentic"} or any(
                    not isinstance(t, str) or len(t.strip()) < NOTE_MIN_CHARS for t in u.values()):
                errors.append(f"{sid}: use must have base_rag and mcp_agentic notes of at least {NOTE_MIN_CHARS} characters")
    return errors


def store_notes_review(data: list, args, inp: dict) -> tuple[Path, str]:
    """Give every note not yet reviewed (and not decided by a person) its status; returns (path, summary)."""
    store_doc = load_json(CSF_IMPACT_NOTES, "ai_impact_notes.json")
    flagged: dict[str, list[str]] = {}
    for f in data:
        flagged.setdefault(f["subcategory_id"], []).append(f"{f['note']}: {str(f['reason']).strip()}")
    for sid, v in store_doc["notes"].items():
        if v.get("decided_by") == "human" or "status" in v:
            continue
        v["status"] = "needs_human_review" if sid in flagged else "pass"
        v.pop("review_reason", None)
        if sid in flagged:
            v["review_reason"] = "; ".join(flagged[sid])[:500]
    CSF_IMPACT_NOTES.write_text(json.dumps(store_doc, indent=2, ensure_ascii=False))
    review = sum(1 for v in store_doc["notes"].values() if v.get("status") == "needs_human_review")
    return CSF_IMPACT_NOTES, (f"notes reviewed: {len(flagged)} newly flagged; {review} of "
                              f"{len(store_doc['notes'])} subcategories need human review")


def store_notes(data: dict, args, inp: dict) -> tuple[Path, str]:
    """Store AI impact notes (null removes one; a rewritten note is reviewed again); returns (path, summary)."""
    today = date.today().isoformat()
    store_doc = load_json(CSF_IMPACT_NOTES, "ai_impact_notes.json") if CSF_IMPACT_NOTES.is_file() else {"notes": {}}
    for sid, v in data.items():
        e = store_doc["notes"].setdefault(sid, {})
        e.update(v)
        for k in ("exposure", "use"):   # null removes a note
            if k in e and e[k] is None:
                del e[k]
        for k in ("status", "review_reason", "decided_by"):   # rewritten by an agent: to be reviewed again
            e.pop(k, None)
    store_doc["notes"] = dict(sorted((sid, e) for sid, e in store_doc["notes"].items()
                                     if "exposure" in e or "use" in e))   # an entry with no note is dropped
    store_doc.update({
        "description": ("AI-world notes per CSF 2.0 subcategory. `exposure` (where there is something real to say to an "
                        "org with no AI) is shown to every org; `use` only when AI is "
                        "in use (mcp_agentic when the client's AI areas include MCP / tools or agents, else base_rag). "
                        "Written by an agent from the CIS MCP and agents companion guides joined to CSF via the official "
                        "CIS v8.1 -> CSF 2.0 mapping, then reviewed. The Stage 2 XLS writer selects from the intake (AI in "
                        "use, AI areas)."),
        "judged_on": today,
        "sources_sha256_16": {"cis_csf": audit.sha(AI_CIS_CSF_XLSX),
                              **{g: inp["sg_doc"]["sources"][g]["sha256_16"] for g in ("MCP", "AGENT")}}})
    CSF_IMPACT_NOTES.write_text(json.dumps(store_doc, indent=2, ensure_ascii=False))
    with_use = sum(1 for v in store_doc["notes"].values() if "use" in v)
    return CSF_IMPACT_NOTES, f"{len(store_doc['notes'])} subcategories with notes, {with_use} with a use layer"
