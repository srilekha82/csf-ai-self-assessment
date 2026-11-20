"""
The AI RMF mapping: which AI RMF subcategories apply to each AI area, and why. Checks a drafted area before it is
stored, keeps what a person decided, says whether each area is up to date, converts the mapping to and from its
review spreadsheet, and records your approval of the whole mapping (mapping_accepted.json, with a fingerprint: change
the mapping and it must be approved again).

Called by: record_bank.py (ai-mapping, ai-revalidate, ai-accept-mapping), sheet_io.py (the mapping sheet),
           check_freshness.py (mapping status)
Input:     data/ai/mapping.json, data/ai/ai_areas.json, data/ai/mapping_rules.json, the parsed AI RMF and CIS data
Output:    data/ai/mapping.json

Terms (AI area, mapping row, folded subcategory, required check, needs human review): see docs/guide.md, Glossary.
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (AI_AREAS, AI_CORE, AI_MAPPING, AI_MAPPING_ACCEPTED, AI_MAPPING_RULES, AI_MAPPING_XLSX,  # noqa: E402
                    AI_SAFEGUARDS, AI_SAFEGUARD_IDS)
from ai_bank_common import (area_candidates, area_rules, check_mapping_rules, foundation_subcategories,  # noqa: E402
                            load_json)
import audit  # noqa: E402


def mapping_inputs(inp: dict) -> dict:
    """The AI areas and the mapping rules, for the mapping validator and store."""
    for p, how in ((AI_AREAS, "sheet_io.py import ai_areas"), (AI_MAPPING_RULES, "data/ai/mapping_rules.json")):
        if not p.is_file():
            sys.exit(f"[record_bank] ERROR: {p} not found ({how})")
    rules = load_json(AI_MAPPING_RULES, "mapping_rules.json")
    problems = check_mapping_rules(rules, inp)
    if problems:
        sys.exit("[record_bank] ERROR: mapping_rules.json does not match the CIS guides:\n  - " + "\n  - ".join(problems))
    return {"areas": {a["id"]: a for a in load_json(AI_AREAS, "ai_areas.json")["ai_areas"]}, "rules": rules}


def validate_mapping(data, inp, m: dict, review) -> list[str]:
    """One AI area's mapping (the drafter's file, after the evaluator's turn):
        {"area": "mcp_tools",
         "rows": [{"function": "MEASURE", "subcategory": "MEASURE 2.8", "cis_refs": ["MCP-8.2"],
                   "impact": ["access"], "why": "..."}],
         "no_question": [{"function": "MAP", "reason": "..."}]}

    Rejected unless: the area is in ai_areas.json; each row's function is MAP, MEASURE or MANAGE (GOVERN is the
    foundation, asked once for the organisation, never per area); each subcategory exists and belongs to that
    function; cis_refs come from the area's candidates (mapping_rules.json area_cis); impact is a non-empty subset of
    the area's impact; every row has a why; an optional `folded` list names mapped subcategories with no row of their
    own, each folded once; every function has rows or a no_question reason (not both); no function + subcategory
    twice; every required check that applies to the area is met.

    --review is the evaluator's last list [{"kind", "function", "subcategory", "reason"}]: "row" (default) fails a
    row, stored as needs_human_review; "missing" names a subcategory that should be a row, stored in the area's
    `missing` list for human review; "note" is a remark that never blocks, stored in the area's `notes`. Rows a person
    decided (decided_by human, removed_by_human) are merged in and the result is checked again before storing."""
    if not isinstance(data, dict) or set(data) - {"area", "rows", "no_question"} or "area" not in data:
        return ["the file must be an object with area, rows and no_question"]
    area_id = data["area"]
    if area_id not in m["areas"]:
        return [f"unknown AI area {area_id!r} (not in ai_areas.json)"]
    rules, area = m["rules"], m["areas"][area_id]
    rows, skips = data.get("rows", []), data.get("no_question", [])
    if not isinstance(rows, list) or not isinstance(skips, list):
        return ["rows and no_question must be lists"]
    allowed = {s["id"] for s in area_candidates(inp, rules, area_id)}
    errors, seen = [], set()
    for n, r in enumerate(rows, 1):
        tag = f"row {n}"
        if not isinstance(r, dict) or not {"function", "subcategory", "cis_refs", "impact", "why"} <= set(r) <= \
                {"function", "subcategory", "cis_refs", "impact", "why", "folded"}:
            errors.append(f"{tag}: fields must be function, subcategory, cis_refs, impact, why (and optional folded)")
            continue
        sub = inp["subs"].get(r["subcategory"])
        if r["function"] in rules["foundation"]["functions"]:
            errors.append(f"{tag}: {r['function']} is foundation (asked once for the organisation), not mapped to an AI area")
        elif r["function"] not in rules["functions"]:
            errors.append(f"{tag}: function must be one of {rules['functions']}")
        elif sub is None:
            errors.append(f"{tag}: {r['subcategory']!r} is not an AI RMF subcategory")
        elif sub["function"] != r["function"]:
            errors.append(f"{tag}: {r['subcategory']} belongs to {sub['function']}, not {r['function']}")
        elif r["subcategory"] in rules["foundation"]["subcategories"]:
            errors.append(f"{tag}: {r['subcategory']} is foundation (asked once for the organisation), not mapped to an AI area")
        if (r["function"], r["subcategory"]) in seen:
            errors.append(f"{tag}: {r['function']} / {r['subcategory']} appears twice")
        seen.add((r["function"], r["subcategory"]))
        if not isinstance(r["cis_refs"], list) or [g for g in r["cis_refs"] if g not in allowed]:
            errors.append(f"{tag}: cis_refs must come from this area's candidates; not allowed: "
                          f"{[g for g in r['cis_refs'] if g not in allowed] if isinstance(r['cis_refs'], list) else r['cis_refs']}")
        if not isinstance(r["impact"], list) or not r["impact"] or not set(r["impact"]) <= set(area["impact"]):
            errors.append(f"{tag}: impact must be one or more of the area's impacts {area['impact']}")
        if len(str(r["why"]).strip()) < rules["min_why_chars"]:
            errors.append(f"{tag}: why must say in a sentence why this subcategory checks this area")
    errors += folded_problems(rows, inp, rules)
    with_rows = {r.get("function") for r in rows if isinstance(r, dict)}
    for s in skips:
        if not isinstance(s, dict) or s.get("function") not in rules["functions"] or \
                len(str(s.get("reason", "")).strip()) < rules["min_why_chars"]:
            errors.append(f"no_question {s!r}: needs a function and a reason")
        elif s["function"] in with_rows:
            errors.append(f"{s['function']}: has rows and a no_question entry; keep one")
    missing = [f for f in rules["functions"] if f not in with_rows and f not in {s.get("function") for s in skips
                                                                                if isinstance(s, dict)}]
    if missing:
        errors.append(f"functions with neither rows nor a no_question reason: {missing}")
    for check in area_rules(rules, area_id)["required_checks"]:
        hits = [r for r in rows if isinstance(r, dict) and r.get("subcategory") in check["any_of"]]
        if "cis_control" in check:
            hits = [r for r in hits if any(g in inp["safeguards"] and inp["safeguards"][g]["control"] == check["cis_control"]
                                           for g in r.get("cis_refs") or [])]
        if not hits:
            extra = f" citing a CIS control {check['cis_control']} safeguard" if "cis_control" in check else ""
            errors.append(f"required check '{check['name']}' missing: needs a row on {' or '.join(check['any_of'])}{extra}")
    if review is not None:
        if not isinstance(review, list):
            errors.append("the review file must be a list of failures")
        else:
            folded = {sid for r in rows if isinstance(r, dict) for sid in r.get("folded") or []}
            for f in review:
                kind = f.get("kind", "row") if isinstance(f, dict) else None
                key = (f.get("function"), f.get("subcategory")) if isinstance(f, dict) else None
                sub = inp["subs"].get(key[1]) if key else None
                if key is None or kind not in REVIEW_KINDS or not str(f.get("reason", "")).strip():
                    errors.append(f"review entry {f!r}: needs kind ({', '.join(REVIEW_KINDS)}), function, subcategory "
                                  "and reason")
                elif sub is None or sub["function"] != key[0]:
                    errors.append(f"review entry {f!r}: subcategory must be a subcategory of the function")
                elif kind == "row" and key not in seen:
                    errors.append(f"review entry {f!r}: no such row in the mapping (use kind missing for a subcategory "
                                  "that should be a row)")
                elif kind == "missing" and (key in seen or key[1] in folded
                                            or key[1] in rules["foundation"]["subcategories"]):
                    errors.append(f"review entry {f!r}: missing must name a subcategory that is not a row, not folded "
                                  "and not foundation (fail the row it is folded into instead)")
    return errors


def folded_problems(rows: list, inp: dict, rules: dict) -> list[str]:
    """`folded` (optional on a row): subcategories whose content this row also covers, because the drafter merged them
    into it. Each must be a mapped-function subcategory that is not foundation, not a row of its own, folded once."""
    rows = [r for r in rows if isinstance(r, dict)]
    own, errors, where = {r.get("subcategory") for r in rows}, [], {}
    for n, r in enumerate(rows, 1):
        folded = r.get("folded", [])
        if not isinstance(folded, list):
            errors.append(f"row {n}: folded must be a list of subcategory ids")
            continue
        for sid in folded:
            sub = inp["subs"].get(sid)
            if sub is None or sub["function"] not in rules["functions"] or sid in rules["foundation"]["subcategories"]:
                errors.append(f"row {n}: folded {sid!r} is not a MAP, MEASURE or MANAGE subcategory an area can map")
            elif sid in own:
                errors.append(f"row {n}: folded {sid} is also a row of its own; keep one")
            elif sid in where:
                errors.append(f"row {n}: folded {sid} is already folded into {where[sid]}")
            else:
                where[sid] = r.get("subcategory")
    return errors


REVIEW_KINDS = ("row", "missing", "note")


def store_mapping(data, inp, m: dict, review) -> tuple[Path, str]:
    failing, missing, notes = {}, [], []
    for f in review or []:
        entry = {"function": f["function"], "subcategory": f["subcategory"], "reason": str(f["reason"]).strip()[:500]}
        kind = f.get("kind", "row")
        if kind == "row":
            failing.setdefault((f["function"], f["subcategory"]), []).append(entry["reason"])
        else:
            (missing if kind == "missing" else notes).append(entry)
    rows = []
    for r in data["rows"]:
        why = failing.get((r["function"], r["subcategory"]))
        rows.append({**r, "status": "needs_human_review" if why else "pass", "decided_by": "agent",
                     **({"review_reason": "; ".join(why)[:500]} if why else {})})
    doc = load_json(AI_MAPPING, "mapping.json") if AI_MAPPING.is_file() else {"areas": {}}
    rows, no_question, kept, removed = keep_human_decisions(rows, data.get("no_question", []),
                                                           doc["areas"].get(data["area"]), inp)
    merged = {"area": data["area"], "no_question": no_question,
              "rows": [{k: r[k] for k in ("function", "subcategory", "cis_refs", "impact", "why", "folded") if k in r}
                       for r in rows]}
    problems = validate_mapping(merged, inp, m, None) if kept else []
    if problems:   # a person's earlier decision no longer fits the current rules: they decide, not the script
        print("[record_bank] ERROR: merged with the rows a person decided, the area breaks the rules; nothing "
              "stored. Fix those lines in mapping.xlsx (sheet_io.py import mapping), then record again:\n  - "
              + "\n  - ".join(problems), file=sys.stderr)
        sys.exit(1)
    own = {r["subcategory"] for r in rows}
    missing = [x for x in missing if x["subcategory"] not in own and x["subcategory"] not in removed]
    doc["description"] = ("AI RMF mapping: per AI area, rows of AI RMF function -> subcategory, CIS safeguards that prove "
                          "it, impact. Drafted and evaluated by agents (prompts/ai_rmf_mapping_*.md), recorded by "
                          "record_bank.py ai-mapping, reviewed by a person. Model: docs/ai-rmf-model.md.")
    doc["areas"][data["area"]] = {
        "recorded_on": date.today().isoformat(), "inputs": mapping_input_hashes(inp, data["area"]),
        "rows": rows, "no_question": no_question, **({"missing": missing} if missing else {}),
        **({"notes": notes} if notes else {}), **({"removed_by_human": removed} if removed else {})}
    doc["areas"] = {a: doc["areas"][a] for a in m["areas"] if a in doc["areas"]}   # ai_areas.json order
    AI_MAPPING.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    review_n = sum(1 for r in rows if r["status"] != "pass")
    reached, unreached = mapping_coverage(doc, inp, m["rules"])
    return AI_MAPPING, (f"{data['area']}: {len(rows)} rows ({review_n} need human review"
                        + (f"; {len(missing)} missing rows to decide" if missing else "")
                        + (f"; {len(notes)} evaluator notes" if notes else "")
                        + (f"; {kept} human decisions kept" if kept else "") + "); mapping has "
                        f"{len(doc['areas'])} of {len(m['areas'])} areas, {len(unreached)} subcategories not reached yet")


def keep_human_decisions(rows: list, no_question: list, prev: dict | None, inp: dict) -> tuple[list, list, int, list]:
    """A re-drafted area keeps what a person decided in the review sheet: rows decided_by human replace the agent's row
    on the same subcategory (or are added), and subcategories the person removed (removed_by_human) stay removed.
    Returns (rows, no_question, human decisions kept, removed list)."""
    if not prev:
        return rows, no_question, 0, []
    human = {r["subcategory"]: r for r in prev["rows"] if r.get("decided_by") == "human"}
    removed = [sid for sid in prev.get("removed_by_human", []) if sid not in human]
    out = [r for r in rows if r["subcategory"] not in human and r["subcategory"] not in removed] + list(human.values())
    for i, r in enumerate(out):   # a subcategory the person decided is no longer folded into an agent row
        if set(r.get("folded", [])) & set(human):
            out[i] = {k: v for k, v in r.items() if k != "folded"}
            if [f for f in r["folded"] if f not in human]:
                out[i]["folded"] = [f for f in r["folded"] if f not in human]
    out.sort(key=lambda r: list(inp["subs"]).index(r["subcategory"]))
    fns = {r["function"] for r in out}
    kept = len(human) + sum(1 for r in rows if r["subcategory"] in removed)
    return out, [q for q in no_question if q["function"] not in fns], kept, removed


def mapping_input_hashes(inp: dict, area_id: str) -> dict:
    """What a recorded area was built from: its own row of the AI areas sheet (`area`), the whole sheet and the rules
    (both reach the drafter: other areas' covers, candidates, foundation), and the sources."""
    row = next((a for a in load_json(AI_AREAS, "ai_areas.json")["ai_areas"] if a["id"] == area_id), None)
    return {"area": hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
            "ai_areas": audit.sha(AI_AREAS), "rules": audit.sha(AI_MAPPING_RULES),
            "playbook": inp["core"]["source_sha256_16"],
            "guides": {g: s["sha256_16"] for g, s in inp["sg_doc"]["sources"].items()}}


def mapping_freshness(entry: dict, area_id: str, inp: dict) -> str:
    """current, recheck (only the rules or other areas changed: `revalidate` can clear it without an agent) or redraft
    (the area's own row or the sources changed). An entry recorded before the area hash existed can only be rechecked
    if the whole AI areas sheet is unchanged."""
    rec, now = entry.get("inputs") or {}, mapping_input_hashes(inp, area_id)
    if rec == now:
        return "current"
    if rec.get("playbook") != now["playbook"] or rec.get("guides") != now["guides"]:
        return "redraft"
    if rec.get("area", None if rec.get("ai_areas") == now["ai_areas"] else "unknown") not in (None, now["area"]):
        return "redraft"
    return "recheck"


def revalidate(inp: dict, m: dict) -> tuple[dict, list[str], int]:
    """(the mapping, one line per area that is not current, areas stamped current). Checks only; decides nothing: the
    recorded rows are kept as they are, and an area that breaks the current rules stays stale."""
    doc = load_json(AI_MAPPING, "mapping.json") if AI_MAPPING.is_file() else {"areas": {}}
    lines, cleared = [], 0
    foundation = set(m["rules"]["foundation"]["subcategories"])
    for area_id, entry in doc["areas"].items():
        state = mapping_freshness(entry, area_id, inp)
        if state == "current":
            continue
        if state == "redraft":
            lines.append(f"{area_id}: its own row in the AI areas sheet or the sources changed; re-draft it")
            continue
        draft = {"area": area_id, "no_question": entry.get("no_question", []),
                 "rows": [{k: r[k] for k in ("function", "subcategory", "cis_refs", "impact", "why", "folded") if k in r}
                          for r in entry["rows"]]}
        problems = validate_mapping(draft, inp, m, None)
        if problems:
            lines += [f"{area_id}: {p}" for p in problems]
            continue
        if entry.get("missing"):   # a missing finding on a subcategory that is now foundation no longer applies
            entry["missing"] = [x for x in entry["missing"] if x["subcategory"] not in foundation]
            if not entry["missing"]:
                del entry["missing"]
        entry["inputs"] = mapping_input_hashes(inp, area_id)
        cleared += 1
    if cleared:
        AI_MAPPING.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return doc, lines, cleared


def mapping_coverage(doc: dict, inp: dict, rules: dict) -> tuple[set, list]:
    """(subcategories reached by an area row, a fold or the foundation, the ones not reached, in AI RMF order). A folded
    subcategory is reached: it is asked and scored through the row it is folded into."""
    reached = {s for a in doc.get("areas", {}).values() for r in a["rows"] for s in [r["subcategory"], *r.get("folded", [])]}
    reached |= set(foundation_subcategories(rules, inp))
    return reached, [s for s in inp["subs"] if s not in reached]


ROW_FIELDS = ("cis_refs", "impact", "why", "status", "folded")   # what a person can change on a row in the sheet


def mapping_sheet_rows(doc: dict, inp: dict, m: dict) -> tuple[list[dict], list[list[str]]]:
    """(one line per recorded area x mapped-function subcategory, the Coverage sheet as rows of cells). Script only:
    the outcome and safeguard titles are looked up, nothing is decided."""
    mapped_subs = [s for s in inp["subs"].values() if s["function"] in m["rules"]["functions"]
                   and s["subcategory_id"] not in m["rules"]["foundation"]["subcategories"]]
    lines = []
    for area_id, entry in doc.get("areas", {}).items():
        by_sub = {r["subcategory"]: r for r in entry["rows"]}
        into = {f: r["subcategory"] for r in entry["rows"] for f in r.get("folded", [])}
        missing = {x["subcategory"]: x["reason"] for x in entry.get("missing", [])}
        notes = {}
        for x in entry.get("notes", []):
            notes.setdefault(x["subcategory"], []).append(x["reason"])
        for s in mapped_subs:
            r = by_sub.get(s["subcategory_id"])
            refs = r["cis_refs"] if r else []
            note = ("Also covers " + ", ".join(r["folded"]) + " (folded into this row by the drafter)."
                    if r and r.get("folded") else
                    f"Folded into {into[s['subcategory_id']]}: that row covers this subcategory's content."
                    if s["subcategory_id"] in into else "")
            lines.append({
                **({"_comments": {"why": note}} if note else {}),
                "area": area_id, "area_name": m["areas"].get(area_id, {}).get("name", ""), "function": s["function"],
                "subcategory": s["subcategory_id"], "outcome": s["outcome"], "mapped": bool(r),
                "why": r["why"] if r else "", "cis_refs": refs,
                "impact": r["impact"] if r else [],
                "status": r["status"] if r else "needs_human_review" if s["subcategory_id"] in missing else "",
                "review_reason": " ".join(filter(None, [
                    r.get("review_reason", "") if r else "",
                    f"Missing: {missing[s['subcategory_id']]}" if s["subcategory_id"] in missing else "",
                    *[f"Note: {t}" for t in notes.get(s["subcategory_id"], [])]])),
                "decided_by": r["decided_by"] if r else "", "folded": r.get("folded", []) if r else [],
            })
    drafted = doc.get("areas", {})
    reach = {(a, r["subcategory"]) for a in drafted for r in drafted[a]["rows"]}
    folds = {(a, f): r["subcategory"] for a in drafted for r in drafted[a]["rows"] for f in r.get("folded", [])}
    foundation = set(foundation_subcategories(m["rules"], inp))
    coverage = [["Function", "Subcategory", "What it means (Playbook outcome)", "Areas reaching it",
                 *[a if a in drafted else f"{a} (not drafted)" for a in m["areas"]]]]
    for s in inp["subs"].values():   # all 72, in AI RMF order; every AI area as a column
        if s["subcategory_id"] in foundation:
            coverage.append([s["function"], s["subcategory_id"], s["outcome"], "foundation (asked once, by role)",
                             *["" for _ in m["areas"]]])
            continue
        cells = ["yes" if (a, s["subcategory_id"]) in reach else f"folded into {folds[(a, s['subcategory_id'])]}"
                 if (a, s["subcategory_id"]) in folds else "" for a in m["areas"]]
        coverage.append([s["function"], s["subcategory_id"], s["outcome"], sum(1 for c in cells if c), *cells])
    return lines, coverage


def mapping_from_sheet(lines: list[dict], doc: dict, inp: dict, m: dict) -> tuple[dict, list[str], int]:
    """(the mapping with the person's edits, problems, rows changed). Every edited area is checked with the same
    validator as agent output; a changed or new row is decided_by human, an unchanged one keeps what was recorded."""
    problems, changed = [], 0
    areas = doc.get("areas", {})
    sheet: dict[str, dict[str, dict]] = {}
    for n, ln in enumerate(lines, 2):
        sub = inp["subs"].get(ln["subcategory"])
        if ln["area"] not in areas:
            problems.append(f"row {n}: AI area {ln['area']!r} has no recorded mapping (draft it first)")
        elif sub is None or sub["function"] not in m["rules"]["functions"]:
            problems.append(f"row {n}: {ln['subcategory']!r} is not a MAP, MEASURE or MANAGE subcategory")
        elif ln["subcategory"] in m["rules"]["foundation"]["subcategories"]:
            problems.append(f"row {n}: {ln['subcategory']} is foundation (asked once for the organisation), not per area")
        elif ln["subcategory"] in sheet.setdefault(ln["area"], {}):
            problems.append(f"row {n}: {ln['area']} / {ln['subcategory']} appears twice")
        else:
            sheet[ln["area"]][ln["subcategory"]] = dict(ln, function=sub["function"], line=n)
    new_doc = json.loads(json.dumps(doc))
    for area_id, subs in sheet.items():
        recorded = {r["subcategory"]: r for r in areas[area_id]["rows"]}
        problems += [f"{area_id} / {sid}: the line is missing from the sheet; set Mapped to no instead of deleting it"
                     for sid in recorded if sid not in subs]
        rows, removed = [], set(areas[area_id].get("removed_by_human", []))
        missing = {x["subcategory"]: x for x in areas[area_id].get("missing", [])}
        for sid, ln in subs.items():
            if not ln["mapped"]:
                if sid in recorded:
                    changed += 1
                    removed.add(sid)
                    if ln["folded"]:
                        problems.append(f"{area_id}: sheet row {ln['line']} ({sid}): {', '.join(ln['folded'])} "
                                        "folded into it would be lost; clear 'Folded into this row' (or map them on their "
                                        "own lines) before setting Mapped to no")
                elif sid in missing and ln["status"] != "needs_human_review":
                    changed += 1   # the person decided the evaluator's missing row is not needed
                    missing.pop(sid)
                continue
            if missing.pop(sid, None):
                changed += 1
            removed.discard(sid)
            new = {"function": ln["function"], "subcategory": sid, "cis_refs": ln["cis_refs"], "impact": ln["impact"],
                   "why": ln["why"], "status": ln["status"] or "pass"}
            if ln["folded"]:
                new["folded"] = ln["folded"]
            old = recorded.get(sid)
            if old and all(new.get(k, []) == (str(old[k]).strip() if k == "why" else old.get(k, [])) for k in ROW_FIELDS):
                rows.append(old)
            else:
                changed += 1
                rows.append({**new, "decided_by": "human"})
        rows.sort(key=lambda r: list(inp["subs"]).index(r["subcategory"]))
        own = {r["subcategory"] for r in rows}
        for i, r in enumerate(rows):   # a subcategory the person maps on its own is no longer folded into another row
            if set(r.get("folded", [])) & own:
                rows[i] = {k: v for k, v in r.items() if k != "folded"}
                if [f for f in r["folded"] if f not in own]:
                    rows[i]["folded"] = [f for f in r["folded"] if f not in own]
        with_rows = {r["function"] for r in rows}
        draft = {"area": area_id, "rows": [{k: r[k] for k in ("function", "subcategory", "cis_refs", "impact", "why",
                                                              "folded") if k in r} for r in rows],
                 "no_question": [q for q in areas[area_id].get("no_question", []) if q["function"] not in with_rows]}
        at = {f"row {k}:": f"sheet row {subs[r['subcategory']]['line']} ({r['subcategory']}):"
              for k, r in enumerate(rows, 1)}
        problems += [f"{area_id}: " + next((e.replace(a, b, 1) for a, b in at.items() if e.startswith(a + " ")), e)
                     for e in validate_mapping(draft, inp, m, None)]
        new_doc["areas"][area_id].update(rows=rows, no_question=draft["no_question"])
        new_doc["areas"][area_id].pop("missing", None)
        if missing:
            new_doc["areas"][area_id]["missing"] = list(missing.values())
        new_doc["areas"][area_id].pop("removed_by_human", None)
        if removed:
            new_doc["areas"][area_id]["removed_by_human"] = sorted(removed, key=list(inp["subs"]).index)
    return new_doc, problems, changed


# ── Your approval of the mapping ────────────────────────────────────────────

def mapping_hash(doc: dict) -> str:
    """Hash of what the mapping decides (rows, no_question, removals per area); not the sheet hash or dates."""
    keep = {a: {k: e.get(k) for k in ("rows", "no_question", "removed_by_human")} for a, e in doc["areas"].items()}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def mapping_problems(doc: dict | None) -> tuple[list[str], list[str]]:
    """(what stops the mapping from being accepted, subcategories no area reaches)."""
    if doc is None:
        return ["missing (draft the areas: /build-ai-bank, Mapping)"], []
    if not (AI_CORE.is_file() and (AI_SAFEGUARDS.is_file() or AI_SAFEGUARD_IDS.is_file())):
        return ["cannot check (run parse_ai_rmf_sources.py first)"], []
    from ai_bank_common import load_inputs
    from sheet_io import sheet_status
    inp = load_inputs()
    m = mapping_inputs(inp)
    problems = []
    missing = [a for a in m["areas"] if a not in doc["areas"]]
    if missing:
        problems.append(f"incomplete ({len(doc['areas'])} of {len(m['areas'])} AI areas; missing: {', '.join(missing)})")
    state = {a: mapping_freshness(e, a, inp) for a, e in doc["areas"].items()}
    redraft = [a for a, s in state.items() if s == "redraft"]
    recheck = [a for a, s in state.items() if s == "recheck"]
    if redraft:
        problems.append(f"stale, re-draft (the area's own row in the AI areas sheet or the sources changed: "
                        f"{', '.join(redraft)})")
    if recheck:
        problems.append(f"to recheck (the mapping rules or other AI areas changed; record_bank.py ai-revalidate, no "
                        f"agent needed: {', '.join(recheck)})")
    review = sum(1 for e in doc["areas"].values() for r in e["rows"] if r.get("status") != "pass")
    if review:
        problems.append(f"{review} rows need human review (Status in {AI_MAPPING_XLSX.name})")
    missing = sum(len(e.get("missing", [])) for e in doc["areas"].values())
    if missing:
        problems.append(f"{missing} missing rows to decide (Mapped = no lines with Status needs_human_review in "
                        f"{AI_MAPPING_XLSX.name}: map them, or set Status to pass)")
    if AI_MAPPING_XLSX.is_file() and not sheet_status("mapping", AI_MAPPING_XLSX, AI_MAPPING)[0]:
        problems.append(f"{AI_MAPPING_XLSX.name} edited but not imported (sheet_io.py import mapping)")
    return problems, mapping_coverage(doc, inp, m["rules"])[1]


def mapping_status(mapping_file: Path | None = None, accepted_file: Path | None = None) -> tuple[bool, str]:
    """(current?, text) for the `mapping` stage: complete, current, reviewed and accepted as it is now."""
    mapping_file, accepted_file = mapping_file or AI_MAPPING, accepted_file or AI_MAPPING_ACCEPTED
    doc = json.loads(mapping_file.read_text()) if mapping_file.is_file() else None
    problems, unreached = mapping_problems(doc)
    tail = f"; {len(unreached)} subcategories reached by no area" if doc else ""
    if problems:
        return False, "; ".join(problems) + tail
    accepted = json.loads(accepted_file.read_text()) if accepted_file.is_file() else None
    if accepted is None:
        return False, f"not accepted (review {AI_MAPPING_XLSX.name}, then record_bank.py ai-accept-mapping){tail}"
    if accepted["mapping_sha"] != mapping_hash(doc):
        return False, f"changed since accepted on {accepted['accepted_on']} (accept again){tail}"
    return True, f"accepted {accepted['accepted_on']} ({len(doc['areas'])} areas{tail})"


def accept_mapping(note: str | None) -> str:
    """Record that the user accepted the mapping as it is now."""
    doc = json.loads(AI_MAPPING.read_text()) if AI_MAPPING.is_file() else None
    problems, unreached = mapping_problems(doc)
    if problems:
        sys.exit("[record_bank] ERROR: the mapping cannot be accepted yet:\n  - " + "\n  - ".join(problems))
    rows = sum(len(e["rows"]) for e in doc["areas"].values())
    AI_MAPPING_ACCEPTED.write_text(json.dumps({
        "accepted_on": date.today().isoformat(), "note": note, "areas": len(doc["areas"]), "rows": rows,
        "unreached": unreached, "mapping_sha": mapping_hash(doc)}, indent=2, ensure_ascii=False))
    return (f"mapping accepted ({len(doc['areas'])} areas, {rows} rows"
            + (f"; reached by no area: {', '.join(unreached)}" if unreached else "") + ")")
