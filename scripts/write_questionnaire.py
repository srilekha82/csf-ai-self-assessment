"""
Writes the picked questions into the questionnaire workbook, one row per question.

Called by: /csf-questionnaire and /ai-questionnaire, after check_questionnaire.py passes
Input:     <run_dir>/csf_questions_draft.json, or the two ai_questions_draft_<bank>.json files; <run_dir>/ai_intake.json
           (which AI areas to show); templates/questionnaire_template.xlsx (the layout)
Output:    <run_dir>/questionnaire.xlsx (its CSF sheet, or its AI RMF and AI systems sheets)

Usage: .venv/bin/python ./scripts/write_questionnaire.py <questions_json>... <output_xlsx> [--framework csf|ai]

  csf (default)  csf_questions_draft.json -> sheet "CSF Questionnaire"
  ai             ai_questions_draft_foundation.json and ai_questions_draft_areas.json -> sheet "AI RMF Questionnaire",
                 with an Area column (whole organisation, one AI area, or "This question covers: ...")

The layout (sheets, headers, colours, widths, drop-downs) lives in the template, not here: change it in Excel. The first
run copies the template into the run folder; each mode then clears and refills only its own sheet, writing each value
under its header by name, so the two can be written in any order and a column can be moved in the template.

The AI systems sheet (the client lists its AI systems for the GOVERN 1.6 inventory question) is shown only when that
question is asked: AI in use "none" does not get it, so it is hidden. Its AI area columns show only the client's own AI
areas (ai_intake.json); for AI in use "unsure" all of them, since the sheet is how such a client finds out what AI it has.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
from options import AI_FUNCTION_ORDER, AI_QUESTION_BANKS, CSF_FUNCTION_ORDER  # noqa: E402
from paths import AI_AREA_LABELS, AI_QUESTION_RULES, QUESTIONNAIRE_TEMPLATE  # noqa: E402
import audit  # noqa: E402

FRAMEWORKS = {"csf": {"sheet": "CSF Questionnaire", "order": CSF_FUNCTION_ORDER},
              "ai": {"sheet": "AI RMF Questionnaire", "order": AI_FUNCTION_ORDER}}


def row_values(framework: str, entry: dict, q_num: int, q: dict) -> dict:
    """{header: value} for one question row. Answer and Evidence stay blank for the client."""
    row = {"Function": entry.get("function", ""), "Subcategory ID": entry.get("subcategory_id", ""), "Q#": q_num,
           "Outcome": entry.get("outcome", ""), "Question Type": entry.get("question_type", ""),
           "Question": q.get("question_text", ""), "Source": q.get("source_reference", ""),
           "Confidence": entry.get("confidence_flag", ""), "Evidence Required": entry.get("evidence_prompt", "")}
    if framework == "ai":
        row.update({"Area": q.get("applies_to", ""), "CIS Reference": ", ".join(q.get("cis_refs", [])),
                    "Evidence Required": q.get("evidence_prompt") or entry.get("evidence_prompt", "")})
    return row


def fill_questions(ws, framework: str, entries: list[dict]) -> int:
    """Clear the sheet below its header and write one row per question; returns the number of rows."""
    columns = {c.value: c.column for c in ws[1] if c.value}
    missing = sorted(set(row_values(framework, {}, 0, {})) - set(columns))
    if missing:
        sys.exit(f"[write_questionnaire] ERROR: the template's '{ws.title}' sheet has no column {missing}; "
                 f"fix {QUESTIONNAIRE_TEMPLATE.name}. Nothing written.")
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    bank_order = {b: i for i, b in enumerate(AI_QUESTION_BANKS)}
    order = FRAMEWORKS[framework]["order"]
    entries = sorted(entries, key=lambda e: (order.get(e.get("function", ""), 99), e.get("subcategory_id", ""),
                                             bank_order.get(e.get("bank"), 9)))
    row = 2
    for entry in entries:
        for q_num, q in enumerate(entry.get("questions", []), 1):
            for header, value in row_values(framework, entry, q_num, q).items():
                ws.cell(row=row, column=columns[header], value=value).alignment = Alignment(wrap_text=True,
                                                                                            vertical="top")
            row += 1
    ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{max(row - 1, 1)}"
    return row - 2


def show_inventory(wb, entries: list[dict], usage_path: Path) -> str:
    """Show the AI systems sheet only when the inventory question is asked, with the client's AI area columns."""
    inv = json.loads(AI_QUESTION_RULES.read_text())["ai_system_inventory"]
    ws = wb[inv["sheet"]]
    if not any(e.get("subcategory_id") == inv["subcategory"] for e in entries):
        ws.sheet_state = "veryHidden"
        return f"{inv['sheet']} sheet hidden (the inventory question is not asked)"
    ws.sheet_state = "visible"
    labels = json.loads(AI_AREA_LABELS.read_text())["labels"]
    usage = json.loads(usage_path.read_text()) if usage_path.is_file() else {}
    show_all = usage.get("ai_in_use", "unsure") == "unsure"
    shown = set(labels.values()) if show_all else {labels[a] for a in usage.get("ai_areas", [])}
    for cell in ws[2]:
        if cell.value in labels.values():
            ws.column_dimensions[cell.column_letter].hidden = cell.value not in shown
    return f"{inv['sheet']} sheet: {'all' if show_all else len(shown)} AI area columns shown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="question file(s), then the output xlsx")
    parser.add_argument("--framework", choices=list(FRAMEWORKS), default="csf")
    args = parser.parse_args()
    if len(args.paths) < 2 or (args.framework == "csf" and len(args.paths) != 2):
        parser.error("give one question file (csf) or one or two (ai), then the output xlsx")
    *question_files, output = args.paths
    entries = [e for f in question_files for e in json.loads(Path(f).read_text())]
    outpath = Path(output)
    ev = audit.begin(audit.run_log(outpath.parent), "write_questionnaire",
                     {"questions": question_files, "output": output, "framework": args.framework})
    if not outpath.is_file():
        shutil.copyfile(QUESTIONNAIRE_TEMPLATE, outpath)
    wb = openpyxl.load_workbook(outpath)
    sheet = FRAMEWORKS[args.framework]["sheet"]
    rows = fill_questions(wb[sheet], args.framework, entries)
    line = f"{sheet}: {rows} question rows, {len(entries)} subcategories"
    if args.framework == "ai":
        line += "; " + show_inventory(wb, entries, outpath.parent / "ai_intake.json")
    wb.save(outpath)
    print(f"Written: {outpath} [{line}]")
    ev.finish(inputs=[*question_files, QUESTIONNAIRE_TEMPLATE], outputs=[outpath], detail=line)


if __name__ == "__main__":
    main()
