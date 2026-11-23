"""
Collects every CSET question linked to a CSF 2.0 subcategory, from CISA's CSET SQL files. No judgement;
the same for every sector.

Why:       CSET has no plain list of its questions: they exist only as SQL changes spread over hundreds of files.
           Replaying them gives the current questions and their CSF links, the raw material of the CSF banks.
Called by: /build-csf-bank (step 2)
Input:     the SQL migration files in your local CSET copy; the "truncated" rule in data/csf/bank_rules.json
Output:    data/csf/bank_build/cset_candidates.json

Usage: .venv/bin/python ./scripts/extract_cset_candidates.py [--cset-path PATH] [--output-dir DIR] [--force] [--no-pull]

cset_candidates.json holds, per CSF subcategory, CSET's own CSF 2.0 question (question set NCSF_V2) and the
maturity-model questions (ACET, CPG, SSG ...) CSET links to it, with text, category, model and practice fields. CSET
has no plain question list: its SQL migration files add, change and delete rows over time. replay() reads them in file
order and keeps each table's rows as they are after the last file (every INSERT, UPDATE and DELETE counts).

It skips the work when CSET has not changed since the last run (same commit, or no SQL file changed). Each question
gets flags for later steps: empty_text, truncated, not_answerable, statement_only (a practice with no question text;
the bank shows its CSET outcome text instead).

SQL tables read: MATURITY_REFERENCES (Gen_File_Id 692 = CSF 2.0), MATURITY_QUESTIONS, MATURITY_MODELS, and for NCSF_V2
REQUIREMENT_QUESTIONS_SETS, NEW_REQUIREMENT, NEW_QUESTION.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import BANK_BUILD, CSF_BANK_RULES  # noqa: E402
import audit  # noqa: E402

DEFAULT_CSET_PATH = "~/workstuff/cset"
SQL_SUBPATH = "CSETWebApi/CSETWeb_Api/CSETWebCore.UpgradeLibrary/VersionUpgrader/SQL"
CSF_GEN_FILE_ID = 692
CSF2_SET_NAME = "NCSF_V2"   # CSET's own CSF 2.0 standard: one question per subcategory

# Column order of MATURITY_QUESTIONS inserts that carry no column list (old migrations).
DEFAULT_QUESTION_COLUMNS = ["Mat_Question_Id", "Question_Title", "Question_Text", "Supplemental_Info",
                            "Category", "Sub_Category", "Maturity_Level_Id", "Sequence", "Maturity_Model_Id"]

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
SUBCATEGORY_ID = re.compile(r"[A-Z]{2}\.[A-Z]{2}-\d{2}$")


def git(cset_path: Path, *args) -> str:
    result = subprocess.run(["git", "-C", str(cset_path), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def sql_changed(cset_path: Path, old: str, new: str) -> bool:
    """True if a migration .sql file this script reads (under SQL_SUBPATH) differs between two CSET commits.
    Raises RuntimeError if git cannot compare them (for example an unknown commit)."""
    return bool(git(cset_path, "diff", "--name-only", old, new, "--", f"{SQL_SUBPATH}/*.sql"))


def read_sql_file(f: Path) -> str:
    raw = f.read_bytes()
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16-le")
    if raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16-be")
    return raw.decode("utf-8", errors="replace")


# ── SQL value tokeniser ───────────────────────────────────────────────────────

def parse_value(s: str, i: int):
    """Parse one SQL literal at s[i]. Returns (python_value, next_index)."""
    while i < len(s) and s[i] in " \t":
        i += 1
    if s.startswith("N'", i) or s.startswith("'", i):
        i += 2 if s[i] == "N" else 1
        buf = []
        while i < len(s):
            if s[i] == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                return "".join(buf), i + 1
            buf.append(s[i])
            i += 1
        return "".join(buf), i
    if s.startswith("NULL", i):
        return None, i + 4
    m = NUMBER.match(s, i)
    if m:
        txt = m.group()
        return (float(txt) if "." in txt else int(txt)), m.end()
    # anything else (function call, hex, ...): read to the next top-level comma/paren
    depth, j = 0, i
    while j < len(s):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            if depth == 0:
                break
            depth -= 1
        elif s[j] == "," and depth == 0:
            break
        j += 1
    return s[i:j].strip(), j


def parse_values(s: str, i: int) -> list:
    """Parse a comma-separated literal list starting at s[i] up to the closing ')'."""
    vals = []
    while i < len(s):
        v, i = parse_value(s, i)
        vals.append(v)
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
            continue
        break
    return vals


def parse_insert(line: str, default_cols: list[str] | None = None) -> dict | None:
    """{column: value} of one INSERT. An INSERT without a column list uses default_cols."""
    m = re.search(r"INSERT INTO \[dbo\]\.\[\w+\]\s*(?:\((.*?)\))?\s*VALUES\s*\(", line)
    if not m:
        return None
    cols = re.findall(r"\[(\w+)\]", m.group(1)) if m.group(1) else (default_cols or [])
    vals = parse_values(line, m.end())
    return dict(zip(cols, vals))


ASSIGN = re.compile(r"\s*\[(\w+)\]\s*=\s*")


def parse_assignments(text: str, i: int, separator: str) -> tuple[dict, int]:
    """[A]=v <separator> [B]=v ... from text[i]: ({A: v, B: v}, index after the last one)."""
    out = {}
    while True:
        cm = ASSIGN.match(text, i)
        if not cm:
            return out, i
        out[cm.group(1)], i = parse_value(text, cm.end())
        rest = re.match(r"\s*" + separator + r"\s*", text[i:], re.I)
        if not rest:
            return out, i
        i += rest.end()


def parse_update(line: str) -> tuple[dict, dict]:
    """'UPDATE ... SET [A]=v, [B]=v WHERE [K]=k AND ...' -> ({A: v, B: v}, {K: k, ...})."""
    m = re.search(r"\bSET\s+", line)
    if not m:
        return {}, {}
    sets, i = parse_assignments(line, m.end(), ",")
    w = re.compile(r"\s*WHERE\s+", re.I).match(line, i)
    return sets, (parse_assignments(line, w.end(), "AND")[0] if w else {})


def parse_delete(line: str) -> dict:
    """'DELETE FROM ... WHERE [K]=k AND ...' -> {K: k, ...}."""
    m = re.search(r"\bWHERE\s+", line, re.I)
    return parse_assignments(line, m.end(), "AND")[0] if m else {}


# ── extraction ────────────────────────────────────────────────────────────────

STATEMENT_START = ("INSERT INTO", "UPDATE ", "DELETE FROM")


def join_multiline_statements(lines: list[str]) -> list[str]:
    """
    Question text often contains line breaks, so one INSERT/UPDATE spans several lines. A statement
    is complete once its quotes balance ('' escapes keep the parity), so keep appending lines until
    they do. Without this, text is cut at the first line break.
    """
    out: list[str] = []
    buf: str | None = None
    for line in lines:
        if buf is None:
            if line.lstrip().startswith(STATEMENT_START) and line.count("'") % 2 == 1:
                buf = line
            else:
                out.append(line)
        else:
            buf += "\n" + line
            if buf.count("'") % 2 == 0:
                out.append(buf)
                buf = None
    if buf is not None:
        out.append(buf)
    return out


def read_sql_lines(cset_sql: Path) -> list[str]:
    """One entry per SQL statement (multi-line statements joined), files in name order."""
    lines: list[str] = []
    for sql_file in sorted(cset_sql.glob("*.sql")):
        lines.extend(join_multiline_statements(read_sql_file(sql_file).splitlines()))
    return lines


def replay(lines: list[str], table: str, key: tuple[str, ...], default_cols: list[str] | None = None) -> dict:
    """The rows of one table after every migration: INSERT adds a row, UPDATE changes it, DELETE removes it, in file
    order. Rows are keyed by the `key` columns (the table's primary key), as a tuple."""
    stmt = re.compile(r"^(INSERT INTO|UPDATE|DELETE FROM) \[dbo\]\.\[%s\][\s(]" % table)
    rows: dict[tuple, dict] = {}
    for line in lines:
        line = line.lstrip("\ufeff \t")                     # some statements are indented or start with a BOM
        m = stmt.match(line)
        if not m:
            continue
        if m.group(1) == "INSERT INTO":
            row = parse_insert(line, default_cols)
            if row and all(k in row for k in key):
                rows[tuple(row[k] for k in key)] = row
        elif m.group(1) == "UPDATE":
            sets, where = parse_update(line)
            old = tuple(where.get(k) for k in key)
            if old in rows:
                row = rows.pop(old)
                row.update(sets)
                rows[tuple(row[k] for k in key)] = row      # an update may change a key column
        else:
            rows.pop(tuple(parse_delete(line).get(k) for k in key), None)
    return rows


def csf_mappings(lines: list[str]) -> set[tuple[int, str]]:
    """(maturity question id, CSF 2.0 subcategory) for every link in MATURITY_REFERENCES to the CSF 2.0 file."""
    refs = replay(lines, "MATURITY_REFERENCES", ("Mat_Question_Id", "Gen_File_Id", "Section_Ref"))
    return {(q, ref) for q, f, ref in refs if f == CSF_GEN_FILE_ID and SUBCATEGORY_ID.match(str(ref or ""))}


def clean_text(raw: str | None) -> str:
    return re.sub(r"<[^>]+>", "", raw or "").strip()


# ── CSET's own CSF 2.0 set (NCSF_V2): one question per subcategory ────────────

TRAILING_REF = re.compile(r"\s*\([A-Z]{2}\.[A-Z]{2}-\d{2}\)(?=[.?]?$)")


def extract_csf2_set(lines: list[str]) -> dict[str, dict]:
    """CSET's CSF 2.0 standard (NCSF_V2): subcategory -> its question(s). Every subcategory has one in CSET."""
    reqs = replay(lines, "NEW_REQUIREMENT", ("Requirement_Id",))
    texts = replay(lines, "NEW_QUESTION", ("Question_Id",))
    links = sorted((q, r["Requirement_Id"]) for (q, name), r in
                   replay(lines, "REQUIREMENT_QUESTIONS_SETS", ("Question_Id", "Set_Name")).items() if name == CSF2_SET_NAME)
    out: dict[str, dict] = {}
    for qid, rid in links:
        sid = str((reqs.get((rid,)) or {}).get("Requirement_Title") or "")
        text = clean_text((texts.get((qid,)) or {}).get("Simple_Question"))
        if not SUBCATEGORY_ID.match(sid) or not text:
            continue
        out.setdefault(sid, {"questions": []})["questions"].append(
            {"question_id": qid, "question_text": TRAILING_REF.sub("", text)})
    return dict(sorted(out.items()))


PRACTICE_FIELDS = {"Security_Practice": "security_practice", "Outcome": "outcome", "Scope": "scope",
                   "Risk_Addressed": "risk_addressed", "Recommend_Action": "recommend_action"}


def practice_fields(row: dict) -> dict:
    out = {name: clean_text(row.get(col)) for col, name in PRACTICE_FIELDS.items()}
    return {k: v for k, v in out.items() if v}


TRUNCATED = json.loads(CSF_BANK_RULES.read_text())["truncated"]   # data/csf/bank_rules.json


def question_flags(raw_text: str | None, is_answerable, practice: dict) -> list[str]:
    text = clean_text(raw_text)
    flags = []
    if not text:
        flags.append("statement_only" if practice else "empty_text")
    elif text.endswith(tuple(TRUNCATED["ends_with"])) or len(text) < TRUNCATED["min_chars"]:
        flags.append("truncated")
    if is_answerable in (0, False, "0"):
        flags.append("not_answerable")
    return flags


def build_candidates(lines: list[str], cset_commit: str) -> dict:
    """cset_candidates.json: per question its text, model, category and practice fields with flags; the question ->
    subcategory mappings; and CSET's own CSF 2.0 set."""
    pairs = csf_mappings(lines)
    qids = {q for q, _ in pairs}
    models = {m: r.get("Model_Name") for (m,), r in replay(lines, "MATURITY_MODELS", ("Maturity_Model_Id",)).items()}
    rows = {q: r for (q,), r in replay(lines, "MATURITY_QUESTIONS", ("Mat_Question_Id",), DEFAULT_QUESTION_COLUMNS).items()
            if q in qids}
    questions = {}
    for qid in sorted(rows):
        r = rows[qid]
        practice = practice_fields(r)
        questions[str(qid)] = {
            "question_text": clean_text(r.get("Question_Text")),
            "category": r.get("Category"),
            "sub_category": r.get("Sub_Category"),
            "model_name": models.get(r.get("Maturity_Model_Id")),
            "practice": practice,
            "flags": question_flags(r.get("Question_Text"), r.get("Is_Answerable"), practice),
        }
    return {
        "cset_commit": cset_commit,
        "questions": questions,
        "mappings": [{"qid": q, "subcategory_id": s} for q, s in sorted(pairs) if str(q) in questions],
        "csf2_set": extract_csf2_set(lines),
    }


def freshness(out_path: Path, cset_path: Path, cset_commit: str) -> str:
    """'extract' | 'current' | 'patched'."""
    if not out_path.exists():
        return "extract"
    data = json.loads(out_path.read_text())
    stored = data.get("cset_commit")
    if stored == cset_commit:
        return "current"
    try:
        changed = not stored or sql_changed(cset_path, stored, cset_commit)
    except RuntimeError:   # the stored commit is unknown to this clone (rewritten history, shallow clone)
        changed = True
    if changed:
        return "extract"
    data["cset_commit"] = cset_commit
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return "patched"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cset-path", default=DEFAULT_CSET_PATH)
    parser.add_argument("--output-dir", default=str(BANK_BUILD))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-pull", action="store_true")
    args = parser.parse_args()

    cset_path = Path(args.cset_path).expanduser()
    cset_sql = cset_path / SQL_SUBPATH
    out_path = Path(args.output_dir) / "cset_candidates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ev = audit.begin(out_path.parent / "audit.jsonl", "extract_cset_candidates",
                     {"cset_path": str(cset_path), "force": args.force, "no_pull": args.no_pull})
    if not cset_sql.is_dir():
        ev.fail(f"[extract_cset_candidates] ERROR: CSET SQL folder not found: {cset_sql}")

    try:
        if not args.no_pull:
            git(cset_path, "pull", "--ff-only")
        cset_commit = git(cset_path, "rev-parse", "HEAD")
    except RuntimeError as e:
        ev.fail(f"[extract_cset_candidates] ERROR: could not update CSET repo at {cset_path}: {e}. "
                "Resolve manually before rebuilding.")

    status = "extract" if args.force else freshness(out_path, cset_path, cset_commit)
    if status == "current":
        print(f"Candidates up to date (commit {cset_commit[:8]}). Nothing to extract.")
        ev.finish(outputs=[out_path], detail="up to date, nothing extracted", cset_commit=cset_commit)
        return
    if status == "patched":
        print(f"SHA advanced but no SQL changed. Stored commit updated to {cset_commit[:8]}.")
        ev.finish(outputs=[out_path], detail="commit advanced, no SQL changed; stored commit updated", cset_commit=cset_commit)
        return

    data = build_candidates(read_sql_lines(cset_sql), cset_commit)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    flag_counts: dict[str, int] = {}
    for q in data["questions"].values():
        for f in q["flags"]:
            flag_counts[f] = flag_counts.get(f, 0) + 1
    no_model = sum(1 for q in data["questions"].values() if q["model_name"] is None)
    detail = (f"{len(data['questions'])} questions, {len(data['mappings'])} mappings, CSF 2.0 set ({CSF2_SET_NAME}) "
              f"{len(data['csf2_set'])} subcategories; flags {flag_counts}; no model: {no_model}")
    print(f"Extracted: {out_path}\nCSET commit: {cset_commit}\n{detail}")
    ev.finish(outputs=[out_path], detail=detail, cset_commit=cset_commit)

if __name__ == "__main__":
    main()
