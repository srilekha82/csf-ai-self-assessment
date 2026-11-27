"""
The AI RMF mapping: which AI RMF subcategories apply to each AI area, and why. Checks a drafted area before it is
stored, keeps what a person decided, says whether each area is up to date, converts the mapping to and from its
review spreadsheet, and records your approval of the whole mapping (mapping_accepted.json, with a fingerprint: change
the mapping and it must be approved again).

Why:       the mapping decides which AI RMF subcategories each AI area is asked about. A drafted area is checked
           against the rules (ids, candidate safeguards, required checks) before it is stored, a person's
           decisions are kept, and each area says when it is out of date, so only that area is redrafted.
Called by: record_bank.py (ai-mapping, ai-revalidate, ai-accept-mapping), sheet_io.py (the mapping sheet),
           check_freshness.py (mapping status)
Input:     data/ai/mapping.json, data/ai/ai_areas.json, data/ai/mapping_rules.json, the parsed AI RMF and CIS data
Output:    data/ai/mapping.json

Terms (AI area, mapping row, required check, needs human review): see docs/guide.md, Glossary.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (AI_AREAS, AI_CORE, AI_MAPPING, AI_MAPPING_ACCEPTED, AI_MAPPING_RULES, AI_MAPPING_XLSX,  # noqa: E402
                    AI_SAFEGUARDS, AI_SAFEGUARD_IDS, SHEET_SPECS)
from ai_bank_common import foundation_subcategories, load_json  # noqa: E402
import audit  # noqa: E402



DRAFT_FIELDS = ("function", "subcategory", "cis_refs", "why", "also_covers")   # a row as the drafter writes it
SHEET_WORDS = json.loads(SHEET_SPECS.read_text())["review_words"]   # data/common/sheet_specs.json


def draft_of(area_id: str, rows: list, no_question: list) -> dict:
    """An area as the drafter hands it in (the stored rows without status, decided_by or review_reason)."""
    return {"area": area_id, "no_question": no_question,
            "rows": [{k: r[k] for k in DRAFT_FIELDS if k in r} for r in rows]}


# ── mapping_rules.json: what each AI area may cite and must check ──────────────────────────────────────────────

def always_controls(rules: dict) -> list[int]:
    return sorted(int(n) for n in rules["always_cis_controls"]["controls"])


def check_mapping_rules(rules: dict, inp: dict) -> list[str]:
    """Problems in mapping_rules.json against the parsed CIS guides: every control number of an area (its own and the
    always ones) must exist in each guide the area uses; the always controls' names must match the guides' titles; a
    required check's cis_control must be an always control (so every area can cite it); every AI RMF function is either
    mapped per area (functions) or foundation, never both; a required check names subcategories of mapped functions;
    a foundation subcategory is a real subcategory of a mapped function and no required check names it."""
    controls = inp["sg_doc"]["controls"]   # keyed "<guide>-<number>"
    errors = []
    mapped, foundation = rules["functions"], rules["foundation"]["functions"]
    core_fns = [f["id"] for f in inp["core"]["functions"]]
    if set(mapped) & set(foundation) or sorted(mapped + foundation) != sorted(core_fns):
        errors.append(f"functions {mapped} and foundation {foundation} must split the AI RMF functions {core_fns} between them")
    extra = rules["foundation"]["subcategories"]
    bad = [s for s in extra if s not in inp["subs"] or inp["subs"][s]["function"] not in mapped]
    if bad:
        errors.append(f"foundation subcategories {bad}: must be subcategories of a mapped function ({mapped})")
    for check in rules["required_checks"]:
        bad = [s for s in check["any_of"] if s not in inp["subs"] or inp["subs"][s]["function"] not in mapped]
        if bad:
            errors.append(f"required check {check['name']!r}: {bad} are not subcategories of a mapped function")
        if set(check["any_of"]) & set(extra):
            errors.append(f"required check {check['name']!r}: names foundation subcategories {sorted(set(check['any_of']) & set(extra))}")
    for n, name in rules["always_cis_controls"]["controls"].items():
        for g in {g for k, v in rules["area_cis"].items() if k != "description" for g in v["guides"]}:
            c = controls.get(f"{g}-{n}")
            if c is None:
                errors.append(f"always_cis_controls {n}: no control {n} in the {g} guide")
            elif c["title"].strip().lower() != name.strip().lower():
                errors.append(f"always_cis_controls {n}: named {name!r}, but the {g} guide calls it {c['title']!r}")
    for area, v in rules["area_cis"].items():
        if area == "description":
            continue
        for g in v["guides"]:
            missing = [n for n in v["controls"] if f"{g}-{n}" not in controls]
            if missing:
                errors.append(f"area_cis {area}: controls {missing} are not in the {g} guide")
    for check in rules["required_checks"]:
        if "cis_control" in check and check["cis_control"] not in always_controls(rules):
            errors.append(f"required check {check['name']!r}: cis_control {check['cis_control']} is not an always control")
    return errors


def area_rules(rules: dict, area_id: str) -> dict:
    """The mapping_rules.json entries that apply to one AI area: its candidate CIS controls and guides, its required checks."""
    cis = rules["area_cis"].get(area_id)
    if cis is None:
        sys.exit(f"[ai_bank] ERROR: AI area {area_id!r} has no entry in mapping_rules.json area_cis")
    return {"controls": sorted(set(cis["controls"]) | set(always_controls(rules))), "guides": cis["guides"],
            "required_checks": [c for c in rules["required_checks"] if c["areas"] == "all" or area_id in c["areas"]]}


def area_candidates(inp: dict, rules: dict, area_id: str) -> list[dict]:
    """The CIS safeguards a mapping row of this AI area may cite: its controls (plus the always ones) in its guides."""
    r = area_rules(rules, area_id)
    return [inp["safeguards"][s["id"]] for s in inp["sg_doc"]["safeguards"]
            if s["guide"] in r["guides"] and s["control"] in r["controls"]]


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
         "rows": [{"function": "MEASURE", "subcategory": "MEASURE 2.8", "cis_refs": ["MCP-8.2"], "why": "..."}],
         "no_question": [{"function": "MAP", "reason": "..."}]}

    Rejected unless: the area is in ai_areas.json; each row's function is MAP, MEASURE or MANAGE (GOVERN is the
    foundation, asked once for the organisation, never per area); each subcategory exists and belongs to that
    function; cis_refs come from the area's candidates (mapping_rules.json area_cis); every row has a why; an optional
    `also_covers` note names other AI RMF subcategories the row's practice also covers (a comment: it is not a row,
    and it is not counted or scored); every function has rows or a no_question reason (not both); no function +
    subcategory twice; every required check that applies to the area is met.

    --review is the evaluator's last list [{"kind", "function", "subcategory", "reason"}]: "row" (default) fails a
    row, stored as needs_human_review; "missing" names a subcategory that should be a row, stored in the area's
    `missing` list for human review; "note" is a remark that never blocks, stored in the area's `notes`. Rows a person
    decided (decided_by human, removed_by_human) are merged in and the result is checked again before storing."""
    if not isinstance(data, dict) or set(data) - {"area", "rows", "no_question"} or "area" not in data:
        return ["the file must be an object with area, rows and no_question"]
    area_id = data["area"]
    if area_id not in m["areas"]:
        return [f"unknown AI area {area_id!r} (not in ai_areas.json)"]
    rules = m["rules"]
    rows, skips = data.get("rows", []), data.get("no_question", [])
    if not isinstance(rows, list) or not isinstance(skips, list):
        return ["rows and no_question must be lists"]
    allowed = {s["id"] for s in area_candidates(inp, rules, area_id)}
    errors, seen = [], set()
    for n, r in enumerate(rows, 1):
        tag = str(r.get("subcategory")) if isinstance(r, dict) else f"row {n}"
        if not isinstance(r, dict) or not {"function", "subcategory", "cis_refs", "why"} <= set(r) <= \
                {"function", "subcategory", "cis_refs", "why", "also_covers"}:
            errors.append(f"{tag}: fields must be function, subcategory, cis_refs, why (and optional also_covers)")
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
        if len(str(r["why"]).strip()) < rules["min_why_chars"]:
            errors.append(f"{tag}: why must say in a sentence why this subcategory checks this area")
    errors += also_covers_problems(rows, inp)
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
                elif kind == "missing" and (key in seen or key[1] in rules["foundation"]["subcategories"]):
                    errors.append(f"review entry {f!r}: missing must name a subcategory that is not a row and not "
                                  "foundation")
    return errors


def also_covers_problems(rows: list, inp: dict) -> list[str]:
    """`also_covers` (optional on a row): a note naming other AI RMF subcategories whose practice this row also covers.
    Only the ids are checked: real subcategories, other than the row's own."""
    errors = []
    for r in rows:
        if not isinstance(r, dict) or "also_covers" not in r:
            continue
        ids = r["also_covers"]
        if not isinstance(ids, list) or [x for x in ids if x not in inp["subs"] or x == r.get("subcategory")]:
            errors.append(f"{r.get('subcategory')}: also_covers must list other AI RMF subcategory ids")
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
    merged = draft_of(data["area"], rows, no_question)
    problems = validate_mapping(merged, inp, m, None) if kept else []
    if problems:   # a person's earlier decision no longer fits the current rules: they decide, not the script
        print("[record_bank] ERROR: merged with the rows a person decided, the area breaks the rules; nothing "
              "stored. Fix those lines in mapping.xlsx (sheet_io.py import mapping), then record again:\n  - "
              + "\n  - ".join(problems), file=sys.stderr)
        sys.exit(1)
    own = {r["subcategory"] for r in rows}
    missing = [x for x in missing if x["subcategory"] not in own and x["subcategory"] not in removed]
    doc.pop("description", None)
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
    out.sort(key=lambda r: list(inp["subs"]).index(r["subcategory"]))
    fns = {r["function"] for r in out}
    kept = len(human) + sum(1 for r in rows if r["subcategory"] in removed)
    return out, [q for q in no_question if q["function"] not in fns], kept, removed


def mapping_input_hashes(inp: dict, area_id: str) -> dict:
    """What a recorded area was built from: its own row of the AI areas sheet (`area`), the whole sheet and the rules
    (both reach the drafter: other areas' scope, candidates, foundation), and the sources. The areas are hashed as the
    drafter sees them, without their impact."""
    areas = load_json(AI_AREAS, "ai_areas.json")["ai_areas"]
    row = next((a for a in areas if a["id"] == area_id), None)
    return {"area": audit.json_sha(drafter_view(row)),
            "ai_areas": audit.json_sha([drafter_view(a) for a in areas]), "rules": audit.sha(AI_MAPPING_RULES),
            "playbook": inp["core"]["source_sha256_16"],
            "guides": {g: s["sha256_16"] for g, s in inp["sg_doc"]["sources"].items()}}


def drafter_view(area: dict | None) -> dict | None:
    """What the drafter sees of an AI area: everything but its impact (what a failure harms, used for priority), so an
    impact change does not make the mapping stale."""
    return {k: v for k, v in area.items() if k != "impact"} if area else area


def mapping_freshness(entry: dict, area_id: str, inp: dict) -> str:
    """current, recheck (only the rules or other areas changed: `revalidate` can clear it without an agent) or redraft
    (the area's own row or the sources changed). An entry recorded before the area hash existed can only be rechecked
    if the whole AI areas sheet is unchanged."""
    rec, now = entry.get("inputs") or {}, mapping_input_hashes(inp, area_id)
    if rec == now:
        return "current"
    used = area_rules(load_json(AI_MAPPING_RULES, "mapping_rules.json"), area_id)["guides"]   # the guides it cites
    if rec.get("playbook") != now["playbook"] or \
            any((rec.get("guides") or {}).get(g) != now["guides"].get(g) for g in used):
        return "redraft"
    if rec.get("area", None if rec.get("ai_areas") == now["ai_areas"] else "unknown") not in (None, now["area"]):
        return "redraft"
    return "recheck"


def stored_mapping_problems(inp: dict, m: dict) -> list[str]:
    """Every recorded area re-checked with validate_mapping against the current rules (regression check). Writes nothing."""
    doc = load_json(AI_MAPPING, "mapping.json") if AI_MAPPING.is_file() else {"areas": {}}
    return [f"mapping {a}: {p}" for a, e in doc["areas"].items()
            for p in validate_mapping(draft_of(a, e["rows"], e.get("no_question", [])), inp, m, None)]


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
        problems = validate_mapping(draft_of(area_id, entry["rows"], entry.get("no_question", [])), inp, m, None)
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
    """(subcategories reached by an area row or the foundation, the ones not reached, in AI RMF order). An also_covers
    note is a comment and does not count."""
    reached = {r["subcategory"] for a in doc.get("areas", {}).values() for r in a["rows"]}
    reached |= set(foundation_subcategories(rules, inp))
    return reached, [s for s in inp["subs"] if s not in reached]


ROW_FIELDS = ("cis_refs", "why", "status", "also_covers")   # what a person can change on a row in the sheet


def mapping_sheet_rows(doc: dict, inp: dict, m: dict) -> tuple[list[dict], list[list[str]]]:
    """(the Mapping sheet lines, the Coverage sheet as rows of cells). Script only: the outcomes are looked up, nothing
    is decided. Mapping: one line per row, plus one per subcategory the evaluator says is missing (no Why yet) or
    left a note on; in AI RMF order within each area. Coverage: every subcategory x every area."""
    order = list(inp["subs"])
    lines = []
    for area_id, entry in doc.get("areas", {}).items():
        by_sub = {r["subcategory"]: r for r in entry["rows"]}
        missing = {x["subcategory"]: x["reason"] for x in entry.get("missing", [])}
        notes = {}
        for x in entry.get("notes", []):
            notes.setdefault(x["subcategory"], []).append(x["reason"])
        for sid in sorted(set(by_sub) | set(missing) | set(notes), key=order.index):
            r = by_sub.get(sid)
            lines.append({
                "area": area_id, "subcategory": sid, "outcome": inp["subs"][sid]["outcome"],
                "why": r["why"] if r else "", "cis_refs": r["cis_refs"] if r else [],
                "also_covers": r.get("also_covers", []) if r else [],
                "status": r["status"] if r else "needs_human_review" if sid in missing else "",
                "review_reason": " ".join(filter(None, [
                    r.get("review_reason", "") if r else "",
                    SHEET_WORDS["missing"] + missing[sid] if sid in missing else "",
                    *[SHEET_WORDS["note"] + t for t in notes.get(sid, [])]])),
            })
    drafted = doc.get("areas", {})
    reach = {(a, r["subcategory"]) for a in drafted for r in drafted[a]["rows"]}
    also = {}
    for a in drafted:
        for r in drafted[a]["rows"]:
            for x in r.get("also_covers", []):
                also.setdefault((a, x), []).append(r["subcategory"])
    foundation = set(foundation_subcategories(m["rules"], inp))
    coverage = [[*SHEET_WORDS["coverage_headers"],
                 *[a if a in drafted else SHEET_WORDS["not_drafted"].format(a) for a in m["areas"]]]]
    for s in inp["subs"].values():   # all 72, in AI RMF order; every AI area as a column
        if s["subcategory_id"] in foundation:
            coverage.append([s["function"], s["subcategory_id"], s["outcome"], SHEET_WORDS["foundation"],
                             *["" for _ in m["areas"]]])
            continue
        key = s["subcategory_id"]
        cells = [SHEET_WORDS["row_cell"] if (a, key) in reach else
                 SHEET_WORDS["also_cell"].format(", ".join(also[(a, key)])) if (a, key) in also else ""
                 for a in m["areas"]]
        coverage.append([s["function"], key, s["outcome"], sum(1 for a in m["areas"] if (a, key) in reach), *cells])
    return lines, coverage


def mapping_from_sheet(lines: list[dict], doc: dict, inp: dict, m: dict) -> tuple[dict, list[str], int]:
    """(the mapping with the person's edits, problems, rows changed). A line with a Why is a row; a line without one is
    not (a missing line stays to decide until its Status is pass or the line is deleted). A recorded row whose line
    is deleted or has no Why is removed. Every area is checked with the same validator as agent output; a changed or
    new row is decided_by human, an unchanged one keeps what was recorded."""
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
    problems += [f"{a}: no lines in the sheet; an area keeps at least its rows (re-draft it with /ai-mapping instead)"
                 for a in areas if areas[a]["rows"] and a not in sheet]
    new_doc = json.loads(json.dumps(doc))
    for area_id, subs in sheet.items():
        recorded = {r["subcategory"]: r for r in areas[area_id]["rows"]}
        removed = set(areas[area_id].get("removed_by_human", []))
        missing = {x["subcategory"]: x for x in areas[area_id].get("missing", [])}
        rows = []
        for sid in recorded:
            if sid not in subs or not subs[sid]["why"]:
                changed += 1
                removed.add(sid)
        for sid in list(missing):
            if sid not in subs or (not subs[sid]["why"] and subs[sid]["status"] != "needs_human_review"):
                changed += 1   # the person decided the evaluator's missing row is not needed
                missing.pop(sid)
        for sid, ln in subs.items():
            if not ln["why"]:
                continue
            if missing.pop(sid, None):
                changed += 1
            removed.discard(sid)
            new = {"function": ln["function"], "subcategory": sid, "cis_refs": ln["cis_refs"], "why": ln["why"],
                   "status": ln["status"] or "pass", **({"also_covers": ln["also_covers"]} if ln["also_covers"] else {})}
            old = recorded.get(sid)
            if old and all(new.get(k, []) == (str(old[k]).strip() if k == "why" else old.get(k, [])) for k in ROW_FIELDS):
                rows.append(old)
            else:
                changed += 1
                rows.append({**new, "decided_by": "human"})
        rows.sort(key=lambda r: list(inp["subs"]).index(r["subcategory"]))
        with_rows = {r["function"] for r in rows}
        draft = draft_of(area_id, rows, [q for q in areas[area_id].get("no_question", []) if q["function"] not in with_rows])
        problems += [f"{area_id}: {e}" for e in validate_mapping(draft, inp, m, None)]
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
    return audit.json_sha(keep)


def mapping_problems(doc: dict | None) -> tuple[list[str], list[str]]:
    """(what stops the mapping from being accepted, subcategories no area reaches)."""
    if doc is None:
        return ["missing (draft the areas: /ai-mapping)"], []
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
        problems.append(f"{missing} missing rows to decide (lines without a Why and Status needs_human_review in "
                        f"{AI_MAPPING_XLSX.name}: write a Why to map them, or set Status to pass)")
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
