"""
Reads the organisation's ISO 27001 Statement of Applicability (an Excel file) into the run folder. It only
copies what is there; anything it can't read for certain is left empty.

Called by: /csf-questionnaire (step 2), when ISO 27001 is held
Input:     the SoA Excel file the user gives; the words for finding its sheet and columns (data/csf/scope_rules.json
           soa_reading)
Output:    <run_dir>/inputs/soa_original.<ext> (a copy) and <run_dir>/soa_parsed.json

Usage: .venv/bin/python ./scripts/parse_soa.py <run_dir> <soa_path> [--sheet NAME] [--id-col HEADER]
             [--applicable-col HEADER] [--reason-col HEADER] [--implemented-col HEADER]

It prints the sheet, header row and columns it picked, for the user to confirm. A pick that is wrong is corrected by
naming the sheet or the column's header text with the options above.

soa_parsed.json has one entry per control: control_id (e.g. "Annex A Controls: 5.1"), control_id_raw (as written),
applicable (true / false / null), applicable_raw, exclusion_reason, implemented (true / false, or null when there is
no such column or value).

Exit 1, writing nothing, if it can't find the control ID or applicability column (it lists the headers it saw), finds
no controls, or finds a control twice. IDs stored as numbers lose a trailing zero (5.10 -> 5.1); they are rebuilt from
row order.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent))
from paths import SCOPE_RULES  # noqa: E402
import audit  # noqa: E402

RULES = json.loads(SCOPE_RULES.read_text())["soa_reading"]   # the words used to find sheet, header row and columns
COLUMNS = ("id", "applicable", "reason", "implemented")


ANNEX_A_RANGE = re.compile(r"^([5-9]|[1-9]\d)\.\d")   # 5.x – 99.x → Annex A
MANDATORY_CLAUSE_RANGE = re.compile(r"^([4])\.")        # 4.x → Mandatory Clause

APPLICABLE_YES, APPLICABLE_NO = set(RULES["applicable_yes"]), set(RULES["applicable_no"])
IMPLEMENTED_YES, IMPLEMENTED_NO = set(RULES["implemented_yes"]), set(RULES["implemented_no"])


def normalize_control_id(raw: str) -> str:
    """Map SoA control ID to the format used in olir_iso27001.json control_to_csf keys."""
    raw = raw.strip()
    if ANNEX_A_RANGE.match(raw):
        return f"Annex A Controls: {raw}"
    if MANDATORY_CLAUSE_RANGE.match(raw):
        return f"Mandatory Clause: {raw}"
    return raw


def find_controls_sheet(wb):
    """The sheet that holds the controls: the first whose name has a sheet_name_words word, else the first without a
    skip_sheet_words word, else the active sheet (soa_reading in data/csf/scope_rules.json)."""
    for name in wb.sheetnames:
        if any(w in name.lower() for w in RULES["sheet_name_words"]):
            return wb[name]
    for name in wb.sheetnames:
        if not any(s in name.lower() for s in RULES["skip_sheet_words"]):
            return wb[name]
    return wb.active


def find_header_row(rows):
    """Index of the first of the top header_scan_rows rows with a header_row_words word in a cell, else 0."""
    for i, row in enumerate(rows[:RULES["header_scan_rows"]]):
        norm = [str(c).strip().lower().replace("\n", " ") if c else "" for c in row]
        if any(w in c for c in norm for w in RULES["header_row_words"]):
            return i
    return 0


def col_index(headers, candidates, avoid=()):
    """Index of the first header equal to a candidate, else of the first one containing a candidate and none of the
    `avoid` words (so "control" does not pick "control title" over the id column)."""
    for cand in candidates:
        for i, h in enumerate(headers):
            if h == cand:
                return i
    for cand in candidates:
        for i, h in enumerate(headers):
            if cand in h and not any(a in h for a in avoid):
                return i
    return None


DOTTED = re.compile(r"^(\d+)\.(\d+)$")


def control_id_text(cell, prev: tuple[int, int] | None) -> str:
    """The control id as written. Excel stores an id typed as 5.10 as the number 5.1, so a numeric id whose minor part
    goes backwards within its theme (5.9 then 5.1) is read as the next one with its lost zero (5.10)."""
    if isinstance(cell, bool) or not isinstance(cell, (int, float)):
        return str(cell).strip()
    text = str(cell)
    m = DOTTED.match(text)
    if m and prev and int(m.group(1)) == prev[0] and int(m.group(2)) <= prev[1] < int(m.group(2) + "0"):
        return f"{m.group(1)}.{m.group(2)}0"
    return text


def read_flag(cell, yes: set, no: set):
    """True / False for a known yes/no word, None for blank or anything else."""
    if cell is None:
        return None
    s = str(cell).strip().lower()
    if s in yes:
        return True
    if s in no:
        return False
    return None


def pick_columns(headers: list[str], given: dict) -> tuple[dict, list[str]]:
    """{role: column index or None} for id, applicable, reason, implemented. A column named on the command line is
    found by its header (exact, any case); otherwise by the soa_reading words. Returns the problems with named ones."""
    picked, problems = {}, []
    for role in COLUMNS:
        if given.get(role):
            want = given[role].strip().lower().replace("\n", " ")
            picked[role] = headers.index(want) if want in headers else None
            if picked[role] is None:
                problems.append(f"--{role}-col '{given[role]}' is not a header")
        else:
            spec = RULES["columns"][role]
            picked[role] = col_index(headers, spec["match"], avoid=spec.get("avoid", ()))
    return picked, problems


def main():
    ap = argparse.ArgumentParser(description="Read an ISO 27001 SoA spreadsheet into the run folder.")
    ap.add_argument("run_dir")
    ap.add_argument("soa_path")
    ap.add_argument("--sheet", help="the sheet with the controls, by name (default: found by its name)")
    for role in COLUMNS:
        ap.add_argument(f"--{role}-col", help=f"the {role} column, by its header text (default: found by words)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    soa_path = Path(args.soa_path)
    given = {role: getattr(args, f"{role}_col") for role in COLUMNS}
    ev = audit.begin(audit.run_log(run_dir), "parse_soa",
                     {"soa": str(soa_path), "sheet": args.sheet, **{f"{r}_col": v for r, v in given.items() if v}})
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    copied = inputs_dir / f"soa_original{soa_path.suffix}"
    shutil.copy2(soa_path, copied)

    wb = openpyxl.load_workbook(copied, data_only=True)
    if args.sheet and args.sheet not in wb.sheetnames:
        ev.fail(f"[parse_soa] ERROR: --sheet '{args.sheet}' not found; sheets: {wb.sheetnames}. Nothing written.",
                inputs=[copied])
    ws = wb[args.sheet] if args.sheet else find_controls_sheet(wb)

    rows = list(ws.iter_rows(values_only=True))
    header_idx = find_header_row(rows)
    headers = [str(c).strip().lower().replace("\n", " ") if c else "" for c in rows[header_idx]]

    picked, problems = pick_columns(headers, given)
    if picked["id"] is None and not given["id"]:
        problems.append("could not find the control ID column (give it with --id-col)")
    if picked["applicable"] is None and not given["applicable"]:
        problems.append("could not find the applicability column (give it with --applicable-col)")
    if problems:
        ev.fail(f"[parse_soa] ERROR: {'; '.join(problems)}. Sheet '{ws.title}', header row {header_idx}, headers "
                f"seen: {[h for h in headers if h]}. Nothing written.", inputs=[copied])
    ci, ca, cr, cs = (picked[r] for r in COLUMNS)

    result, prev = [], None
    for row in rows[header_idx + 1:]:
        if not any(row):
            continue

        raw_id = control_id_text(row[ci], prev) if row[ci] is not None else ""
        m = DOTTED.match(raw_id)
        prev = (int(m.group(1)), int(m.group(2))) if m else prev
        if not raw_id or raw_id.lower() in ("none", "nan"):
            continue
        # Skip domain/section header rows (no applicable value)
        if row[ca] is None:
            continue

        applicable_raw = str(row[ca]).strip()
        applicable = read_flag(row[ca], APPLICABLE_YES, APPLICABLE_NO)

        reason = str(row[cr]).strip() if cr is not None and row[cr] else ""
        # Ignore filler text such as "refer to column E" (soa_reading ignore_reason_starting)
        if reason.lower().startswith(tuple(RULES["ignore_reason_starting"])):
            reason = ""

        implemented = None
        if applicable and cs is not None:
            implemented = read_flag(row[cs], IMPLEMENTED_YES, IMPLEMENTED_NO)

        result.append({
            "control_id":      normalize_control_id(raw_id),
            "control_id_raw":  raw_id,
            "applicable":      applicable,
            "applicable_raw":  applicable_raw,
            "exclusion_reason": reason or None,
            "implemented":     implemented,
        })

    seen: dict[str, int] = {}
    for r in result:
        seen[r["control_id"]] = seen.get(r["control_id"], 0) + 1
    dupes = sorted(c for c, n in seen.items() if n > 1)
    if dupes:
        ev.fail(f"[parse_soa] ERROR: control ids appear more than once after parsing: {', '.join(dupes)}. The SoA may "
                f"store ids as numbers that lost a trailing zero (5.10 read as 5.1) out of row order; format the id "
                f"column as text in Excel and run again. Nothing written.", inputs=[copied])

    if not result:
        ev.fail(f"[parse_soa] ERROR: 0 controls parsed. Sheet '{ws.title}', header row {header_idx}, "
                f"headers seen: {[h for h in headers if h]}. Nothing written.", inputs=[copied])

    parsed_path = run_dir / "soa_parsed.json"
    parsed_path.write_text(json.dumps(result, indent=2))

    n = len(result)
    n_app = sum(1 for r in result if r["applicable"] is True)
    n_excl = sum(1 for r in result if r["applicable"] is False)
    n_unk = sum(1 for r in result if r["applicable"] is None)
    n_impl = sum(1 for r in result if r["applicable"] and r["implemented"] is not None)
    col = lambda i: f"'{headers[i]}'" if i is not None else "none"   # noqa: E731
    picks = (f"sheet '{ws.title}' (header row {header_idx + 1}); control ID column {col(ci)}, applicable column "
             f"{col(ca)}, reason column {col(cr)}, implemented column {col(cs)}")
    summary = (f"[parse_soa] {picks} | {n} controls: {n_app} applicable ({n_impl} with known implementation), "
               f"{n_excl} excluded, {n_unk} unrecognised applicability → {parsed_path}")
    print(summary)
    print("[parse_soa] Check these picks with the user. If one is wrong, run again with --sheet, --id-col, "
          "--applicable-col, --reason-col or --implemented-col (the header text).")
    ev.finish(inputs=[copied], outputs=[parsed_path], detail=summary)


if __name__ == "__main__":
    main()
