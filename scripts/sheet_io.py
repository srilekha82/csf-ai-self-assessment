"""
Lets you review and edit the AI bank data in Excel instead of JSON files: it turns the data into
spreadsheets, and reads your edits back after checking them.

Why:       a person reviews the AI mapping, questions and notes far more easily in a spreadsheet than in JSON. This
           keeps the sheet you edit and the JSON the scripts use in step, and checks every edit before it is stored.
Called by: /ai-mapping and /build-ai-bank (after each step that a person reviews)
Input:     export: data/ai/ JSON (AI areas, mapping, both banks, impact notes); import: your edited spreadsheet
Output:    export: spreadsheets in data/ai/authoring/; import: the updated JSON

Usage: .venv/bin/python ./scripts/sheet_io.py export <sheet> [--xlsx PATH] [--json PATH] [--force]
       .venv/bin/python ./scripts/sheet_io.py import <sheet> [--xlsx PATH] [--json PATH]

  export   JSON -> spreadsheet (in data/ai/authoring/), with drop-down lists and a "Read me" sheet.
  import   spreadsheet -> JSON. Checks the whole sheet first; if anything is wrong it lists the problems, exits 1 and
           changes nothing. Lines you changed are stored as decided by a person, and later agent runs do not
           overwrite them.

Sheets:
  ai_areas                the list of AI areas. Here the spreadsheet is the decision; the JSON is made from it.
  mapping                 which AI RMF subcategories apply to each AI area (data/ai/mapping.json): one line per
                          area x subcategory, mapped or not, plus a Coverage sheet.
  area_questions,         the two AI RMF question banks, one line per question. Lines may be edited, added or
  foundation_questions    deleted; subcategories cannot be added or dropped here.
  impact_notes            the CSF AI impact notes (data/csf/ai_impact_notes.json), one line per CSF subcategory.

Each sheet's columns and allowed values are in data/common/sheet_specs.json (column types: id, text, enum, list,
codes, bool). Scripts never read the spreadsheets, only the JSON.

Safety: export refuses to overwrite a spreadsheet with edits that were never imported (and, for ai_areas, at all)
unless --force. Each import stores the spreadsheet's fingerprint; that is how the freshness check spots a sheet edited
but not imported (sheet_status()).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
import audit  # noqa: E402

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
YES, NO = {"yes", "y", "true"}, {"no", "n", "false"}
README_SHEET = "Read me"


# ── the spec ────────────────────────────────────────────────────────────────

def load_spec(name: str, specs_path: Path | None = None) -> dict:
    specs = json.loads(Path(specs_path or config.SHEET_SPECS).read_text())["sheets"]
    if name not in specs:
        sys.exit(f"[sheet_io] ERROR: no sheet {name!r} in sheet_specs.json (known: {sorted(specs)})")
    return dict(specs[name], name=name)


def default_paths(spec: dict) -> tuple[Path, Path, Path]:
    """(xlsx, json, audit log) from the constants the spec names in config.py."""
    return getattr(paths, spec["xlsx"]), getattr(paths, spec["json"]), getattr(paths, spec["audit"]) / "audit.jsonl"


def json_columns(spec: dict) -> list[dict]:
    return [c for c in spec["columns"] if c.get("in_json", True)]


# ── cells ───────────────────────────────────────────────────────────────────

def parse_cell(col: dict, raw) -> tuple[object, list[str]]:
    """(value, problems) for one cell. Blank optional cells become "" (text), [] (list) or None (bool)."""
    text = "" if raw is None else str(raw).strip()
    t = col["type"]
    if not text:
        if col.get("required"):
            return None, ["is required"]
        return ([] if t in ("list", "codes") else None if t == "bool" else ""), []
    if t == "id":
        return text, ([] if ID_RE.match(text) else ["must be lowercase letters, digits and _ (starting with a letter)"])
    if t == "text":
        return text, []
    if t == "enum":
        v = text.lower()
        return v, ([] if v in col["allowed"] else [f"{text!r} is not one of {col['allowed']}"])
    if t == "list":
        vals = []
        for v in (v.strip().lower() for v in text.split(",")):
            if v and v not in vals:
                vals.append(v)
        bad = [v for v in vals if col.get("allowed") and v not in col["allowed"]]
        return vals, ([f"{bad} not in {col['allowed']}"] if bad else [])
    if t == "codes":
        vals = []
        for v in (v.strip() for v in text.split(",")):
            if v and v not in vals:
                vals.append(v)
        return vals, []
    if t == "bool":
        v = text.lower()
        if v in YES or v in NO:
            return v in YES, []
        return None, [f"{text!r} must be yes or no"]
    raise AssertionError(f"unknown column type {t}")


def cell_text(col: dict, value) -> str:
    if col["type"] == "bool":
        return "" if value is None else ("yes" if value else "no")
    if col["type"] in ("list", "codes"):
        return ", ".join(value or [])
    return "" if value is None else str(value)


# ── import ──────────────────────────────────────────────────────────────────

def read_sheet(spec: dict, xlsx: Path) -> tuple[list[dict], list[str]]:
    """(rows, problems) from the spreadsheet; rows are dicts keyed by column key (all columns)."""
    try:
        wb = openpyxl.load_workbook(xlsx, data_only=True)
    except (OSError, ValueError, KeyError) as e:
        return [], [f"cannot open {xlsx}: {e}"]
    if spec["sheet"] not in wb.sheetnames:
        return [], [f"no sheet named {spec['sheet']!r} (sheets: {wb.sheetnames})"]
    rows = list(wb[spec["sheet"]].iter_rows(values_only=True))
    headers = [str(h).strip() if h is not None else "" for h in (rows[0] if rows else [])]
    want = [c["header"] for c in spec["columns"]]
    missing = [h for h in want if h not in headers]
    extra = [h for h in headers if h and h not in want]
    if missing or extra:
        return [], [f"headers must be {want}; missing {missing}, unexpected {extra}"]
    idx = {h: headers.index(h) for h in want}
    out, problems, seen = [], [], {}
    for n, row in enumerate(rows[1:], start=2):
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        rec = {}
        for c in spec["columns"]:
            raw = row[idx[c["header"]]] if idx[c["header"]] < len(row) else None
            value, errs = parse_cell(c, raw)
            problems += [f"row {n}, {c['header']}: {e}" for e in errs]
            rec[c["key"]] = value
        key = rec.get(spec["key"]) if spec["key"] else None   # no single key (mapping): its converter checks repeats
        if key and key in seen:
            problems.append(f"row {n}: {spec['key']} {key!r} already used in row {seen[key]}")
        elif key:
            seen[key] = n
        out.append(rec)
    if not out and not problems:
        problems.append("the sheet has no rows")
    return out, problems


def import_sheet(spec: dict, xlsx: Path, json_path: Path, log: Path) -> str:
    ev = audit.begin(log, f"sheet_io_import_{spec['name']}", {"xlsx": str(xlsx), "json": str(json_path)}, actor="human")
    if not xlsx.is_file():
        ev.fail(f"[sheet_io] ERROR: {xlsx} not found.")
    rows, problems = read_sheet(spec, xlsx)
    if problems:
        ev.reject(problems, xlsx.name, [xlsx], status="rejected")
    if spec.get("shape") == "mapping":
        return import_mapping(spec, xlsx, json_path, ev, rows)
    if spec.get("shape") == "questions":
        return import_questions(spec, xlsx, json_path, ev, rows)
    if spec.get("shape") == "notes":
        return import_notes(xlsx, json_path, ev, rows)
    keep = [c["key"] for c in json_columns(spec)]
    doc = {"description": spec["json_description"], "source": _rel(xlsx), "source_sha": audit.sha(xlsx),
           "generated_by": f"scripts/sheet_io.py import {spec['name']}",
           spec["list_key"]: [{k: r[k] for k in keep} for r in rows]}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    line = f"{len(rows)} {spec['list_key']} from {xlsx.name} -> {_rel(json_path)}"
    print(f"[sheet_io] {line}")
    ev.finish(inputs=[xlsx], outputs=[json_path], detail=line)
    return line


def mapping_context():
    """ai_mapping.py (the mapping's converter and validator) with the reference data it needs. Imported only for the
    mapping sheet, so ai_areas works without the AI RMF build files."""
    import ai_mapping as M
    from ai_bank_common import load_inputs
    inp = load_inputs()
    return M, inp, M.mapping_inputs(inp)


def import_mapping(spec: dict, xlsx: Path, json_path: Path, ev, rows: list[dict]) -> str:
    if not json_path.is_file():
        ev.fail(f"[sheet_io] ERROR: {json_path} not found; draft an area first (/ai-mapping)")
    M, inp, m = mapping_context()
    doc, problems, changed = M.mapping_from_sheet(rows, json.loads(json_path.read_text()), inp, m)
    if problems:
        ev.reject(problems, xlsx.name, [xlsx], status="rejected")
    doc["source_sha"] = audit.sha(xlsx)
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    line = (f"{len(rows)} lines from {xlsx.name}, {changed} changed (decided_by human) -> {_rel(json_path)}; "
            f"{len(M.mapping_coverage(doc, inp, m['rules'])[1])} subcategories not reached yet")
    print(f"[sheet_io] {line}")
    ev.finish(inputs=[xlsx], outputs=[json_path], detail=line)
    return line


def import_questions(spec: dict, xlsx: Path, json_path: Path, ev, rows: list[dict]) -> str:
    if not json_path.is_file():
        ev.fail(f"[sheet_io] ERROR: {json_path} not found; record questions first (/build-ai-bank, Step 4)")
    from ai_bank_common import load_inputs
    from ai_questions import questions_from_sheet
    doc, problems, changed = questions_from_sheet(spec["bank"], rows, json.loads(json_path.read_text()), load_inputs())
    if problems:
        ev.reject(problems, xlsx.name, [xlsx], status="rejected")
    doc["source_sha"] = audit.sha(xlsx)
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    line = (f"{len(rows)} questions from {xlsx.name}, {changed} subcategories changed (decided_by human) -> "
            f"{_rel(json_path)}; {sum(1 for e in doc['subcategories'].values() if e['status'] != 'pass')} subcategories need human "
            f"review")
    print(f"[sheet_io] {line}")
    ev.finish(inputs=[xlsx], outputs=[json_path], detail=line)
    return line


def import_notes(xlsx: Path, json_path: Path, ev, rows: list[dict]) -> str:
    if not json_path.is_file():
        ev.fail(f"[sheet_io] ERROR: {json_path} not found; record notes first (/build-ai-bank, Step 6)")
    from ai_notes import notes_from_sheet
    doc, problems, changed = notes_from_sheet(rows, json.loads(json_path.read_text()))
    if problems:
        ev.reject(problems, xlsx.name, [xlsx], status="rejected")
    doc["source_sha"] = audit.sha(xlsx)
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    review = sum(1 for v in doc["notes"].values() if v.get("status") == "needs_human_review")
    line = (f"{len(rows)} subcategories from {xlsx.name}, {changed} changed (decided_by human) -> {_rel(json_path)}; "
            f"{review} need human review")
    print(f"[sheet_io] {line}")
    ev.finish(inputs=[xlsx], outputs=[json_path], detail=line)
    return line


# ── export ──────────────────────────────────────────────────────────────────

def write_xlsx(spec: dict, rows: list[dict], xlsx: Path, extra: dict[str, list[list]] | None = None) -> None:
    """Write the spreadsheet: one row per record (missing columns blank), dropdowns, a Read me sheet, and any extra
    read-only sheets ({title: rows of cells, header first})."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = spec["sheet"]
    fill, font = PatternFill("solid", fgColor="1A56DB"), Font(bold=True, color="FFFFFF")
    for i, c in enumerate(spec["columns"], 1):
        cell = ws.cell(row=1, column=i, value=c["header"])
        cell.fill, cell.font, cell.alignment = fill, font, Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = c.get("width", 20)
    for r, rec in enumerate(rows, 2):
        for i, c in enumerate(spec["columns"], 1):
            cell = ws.cell(row=r, column=i, value=cell_text(c, rec.get(c["key"])))
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if rec.get("_comments", {}).get(c["key"]):   # a note on the cell (hover), not part of the value
                cell.comment = Comment(rec["_comments"][c["key"]], "sheet_io")
    last = max(len(rows) + 1, 2) + 200  # room for new rows
    for i, c in enumerate(spec["columns"], 1):
        choices = c["allowed"] if c["type"] == "enum" else ["yes", "no"] if c["type"] == "bool" else None
        if choices:
            dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=not c.get("required"))
            col = get_column_letter(i)
            dv.add(f"{col}2:{col}{last}")
            ws.add_data_validation(dv)
    ws.freeze_panes = spec.get("freeze", "C2")
    ws.auto_filter.ref = f"A1:{get_column_letter(len(spec['columns']))}{max(len(rows) + 1, 2)}"

    for title, cells in (extra or {}).items():
        xs = wb.create_sheet(title)
        for r, values in enumerate(cells, 1):
            for i, v in enumerate(values, 1):
                cell = xs.cell(row=r, column=i, value=v)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if r == 1:
                    cell.fill, cell.font = fill, font
        for i in range(1, len(cells[0]) + 1 if cells else 1):
            xs.column_dimensions[get_column_letter(i)].width = 60 if i == 3 else 14
        xs.freeze_panes = "D2"
        xs.auto_filter.ref = f"A1:{get_column_letter(len(cells[0]) if cells else 1)}{max(len(cells), 2)}"

    rd = wb.create_sheet(README_SHEET)
    for n, line in enumerate(spec.get("readme", []), 1):
        rd.cell(row=n, column=1, value=line)
    start = len(spec.get("readme", [])) + 2
    for i, h in enumerate(("Column", "Type", "Required", "Allowed values", "In JSON", "Help"), 1):
        cell = rd.cell(row=start, column=i, value=h)
        cell.fill, cell.font = fill, font
    for n, c in enumerate(spec["columns"], start + 1):
        allowed = ", ".join(c["allowed"]) if c.get("allowed") else "yes, no" if c["type"] == "bool" else ""
        for i, v in enumerate((c["header"], c["type"], "yes" if c.get("required") else "no", allowed,
                               "yes" if c.get("in_json", True) else "no", c.get("help", "")), 1):
            rd.cell(row=n, column=i, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate((22, 10, 10, 40, 9, 80), 1):
        rd.column_dimensions[get_column_letter(i)].width = w
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx)


def export_sheet(spec: dict, xlsx: Path, json_path: Path, log: Path, force: bool = False) -> str:
    ev = audit.begin(log, f"sheet_io_export_{spec['name']}", {"xlsx": str(xlsx), "json": str(json_path), "force": force})
    if not json_path.is_file():
        ev.fail(f"[sheet_io] ERROR: {json_path} not found; nothing to export")
    doc = json.loads(json_path.read_text())
    if xlsx.is_file() and not force:
        if audit.sha(xlsx) != doc.get("source_sha"):
            ev.fail(f"[sheet_io] ERROR: {xlsx} has edits that were never imported (its hash differs from the JSON's). "
                    f"Run sheet_io.py import {spec['name']} first, or pass --force to overwrite them.")
        if spec.get("decision", "spreadsheet") == "spreadsheet" and len(json_columns(spec)) < len(spec["columns"]):
            ev.fail(f"[sheet_io] ERROR: {xlsx} is the decision and holds columns the JSON does not keep; exporting "
                    "would blank them. Edit the spreadsheet instead, or pass --force to rebuild it from the JSON.")
    if spec.get("shape") == "mapping":
        M, inp, m = mapping_context()
        rows, coverage = M.mapping_sheet_rows(doc, inp, m)
        write_xlsx(spec, rows, xlsx, {"Coverage": coverage})
    elif spec.get("shape") == "questions":
        from ai_bank_common import load_inputs
        from ai_questions import question_sheet_rows
        rows = question_sheet_rows(spec["bank"], doc, load_inputs())
        write_xlsx(spec, rows, xlsx)
    elif spec.get("shape") == "notes":
        from ai_notes import notes_sheet_rows
        rows = notes_sheet_rows(doc)
        write_xlsx(spec, rows, xlsx)
    else:
        rows = doc[spec["list_key"]]
        write_xlsx(spec, rows, xlsx)
    ev.finish(inputs=[json_path], outputs=[xlsx], detail=f"exported {len(rows)} rows")
    return import_sheet(spec, xlsx, json_path, log)  # records the new file's hash, and proves the round trip


# ── freshness ───────────────────────────────────────────────────────────────

def sheet_status(name: str, xlsx: Path, json_path: Path) -> tuple[bool, str]:
    """(current?, text) for check_freshness.py: the JSON exists and was imported from the spreadsheet as it is now."""
    if not json_path.is_file():
        return False, f"missing (run sheet_io.py import {name})"
    if not xlsx.is_file():
        return False, "spreadsheet missing"
    if json.loads(json_path.read_text()).get("source_sha") != audit.sha(xlsx):
        return False, f"stale (spreadsheet edited since the last import: run sheet_io.py import {name})"
    return True, "current"


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(config.REPO_ROOT))
    except ValueError:
        return str(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["import", "export"])
    ap.add_argument("sheet", help="a sheet name from data/common/sheet_specs.json, e.g. ai_areas")
    ap.add_argument("--xlsx", help="spreadsheet path (default: from the spec)")
    ap.add_argument("--json", help="JSON path (default: from the spec)")
    ap.add_argument("--force", action="store_true", help="export: overwrite the spreadsheet anyway")
    args = ap.parse_args()

    spec = load_spec(args.sheet)
    xlsx, json_path, log = default_paths(spec)
    xlsx, json_path = Path(args.xlsx or xlsx), Path(args.json or json_path)
    if args.mode == "import":
        import_sheet(spec, xlsx, json_path, log)
    else:
        export_sheet(spec, xlsx, json_path, log, args.force)


if __name__ == "__main__":
    main()
