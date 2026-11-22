"""
Reads NIST's CSF 2.0 download into the CSF subcategory list and the certification crosswalks.

Why:       the CSF subcategories and the ISO 27001 / PCI DSS crosswalks come from NIST's spreadsheet. Turned into JSON
           once, every script can look them up; redoing it when NIST publishes a new version is one command.
Called by: /build-csf-bank (step 1b), when NIST publishes a new version of the file
Input:     data/csf/source/csf2.xlsx (NIST's "Download English (xlsx)"); the certifications and the prefix of their
           references in that file (data/common/intake_options.json certs)
Output:    data/csf/csf2_core.json, one crosswalk per certification in data/csf/crosswalks/ (olir_iso27001.json,
           olir_pcidss.json); the refresh date in data/metadata.json

Usage: .venv/bin/python ./scripts/parse_csf_source.py [--input data/csf/source/csf2.xlsx] [--output ./data]

The file's "CSF 2.0" sheet has one row per function, category and subcategory. A subcategory row carries NIST's
implementation examples ("Ex1: ...") and its informative references, one per line, each starting with its standard
("ISO/IEC 27001:2022: Annex A Controls: 5.1", "PCI DSS: 12.1.1").

csf2_core.json holds the subcategories with their implementation examples. Each crosswalk says which controls of one
certification map to each subcategory: {"csf_to_controls": {"GV.OC-01": ["Mandatory Clause: 4.1", ...]}}, listing only
the subcategories with a mapping. NIST's file says which controls relate to a subcategory, not how (subset, equal,
...), so a crosswalk lists coverage only. The refresh date is what check_freshness.py --csf reads.

Read by: compute_scope.py (which CSF questions a certification covers), build_question_bank.py (the ISO mapping shown
in each bank entry).
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))
from config import CERT_FILES, CERT_NIST, CSF_SOURCE, crosswalk_path  # noqa: E402
import audit  # noqa: E402

SOURCE = {"source_url": "https://www.nist.gov/cyberframework/csf-20-informative-references",
          "author": "NIST (CPRT export)"}


BARE_CONTROL = re.compile(r"^Control (\d+\.\d+)$")   # NIST lists each ISO Annex A control a second time this way
NO_CONTROL = "Mandatory Clause: None"                # NIST's placeholder for "no mandatory clause", not a control


def clean_control_id(line: str, prefix: str) -> str:
    """The control id without its standard's prefix and stray spaces or commas, in one style:
    "ISO/IEC 27001:2022: Mandatory Clause:  4.1" -> "Mandatory Clause: 4.1"; "PCI DSS: 12.1.1" -> "12.1.1";
    "ISO/IEC 27001:2022: Control 5.9" -> "Annex A Controls: 5.9" (the style of the other listing and of the SoA)."""
    control = re.sub(r" {2,}", " ", line[len(prefix):].strip().rstrip(",").strip())
    return BARE_CONTROL.sub(r"Annex A Controls: \1", control)


def parse_references(text: str) -> dict:
    """{cert: sorted control ids} from one Informative References cell (one reference per line). A line that is only
    a heading with no id ("ISO/IEC 27001:2022: Annex A Controls:"), or NIST's "Mandatory Clause: None", is skipped."""
    found = {cert: set() for cert in CERT_NIST}
    for line in (text or "").splitlines():
        for cert, (_, prefix) in CERT_NIST.items():
            if line.strip().startswith(prefix):
                control = clean_control_id(line.strip(), prefix)
                if len(control) > 1 and not control.endswith(":") and control != NO_CONTROL:
                    found[cert].add(control)
                break
    return {cert: sorted(ids) for cert, ids in found.items()}


def parse_examples(text: str) -> list[str]:
    """NIST's implementation examples cell as a list, one item per "Ex1:", "Ex2:", ..."""
    return [p.strip() for p in re.split(r"(?=Ex\d+:)", (text or "").strip()) if p.strip()]


def parse_xlsx(path: Path) -> list[dict]:
    """One record per subcategory row, with its function and category (from the rows above it), its implementation
    examples and its references per certification."""
    ws = load_workbook(path, read_only=True)["CSF 2.0"]
    records, function, category = [], (None, None), (None, None)
    for row in list(ws.iter_rows(values_only=True))[2:]:          # skip the title and header rows
        fn, cat, sub, examples, refs = row[:5]
        if fn and not cat and not sub:                              # a function row
            text = str(fn).strip()
            m = re.search(r"\((\w+)\)", text)
            function, category = (m.group(1) if m else text[:2], text), (None, None)
        elif cat and not sub:                                       # a category row
            text = str(cat).strip()
            m = re.search(r"\((\w+\.\w+)\)", text)
            category = (m.group(1) if m else None, text)
        elif sub:                                                   # a subcategory row
            text = str(sub).strip()
            m = re.match(r"^(\w+\.\w+-\d+):", text)
            records.append({
                "function_id": function[0], "function_text": function[1],
                "category_id": category[0], "category_text": category[1],
                "subcategory_id": m.group(1) if m else None,
                "subcategory_text": text[m.end():].strip() if m else text,
                "implementation_examples": parse_examples(str(examples) if examples else ""),
                "mappings": parse_references(str(refs) if refs else ""),
            })
    return records


def build_csf_to_controls(records: list[dict], cert: str) -> dict:
    """{subcategory id: control ids} for one certification, only the subcategories with a mapping.
    Given GV.OC-01: which ISO 27001 controls cover it?"""
    return {r["subcategory_id"]: r["mappings"][cert] for r in records if r["subcategory_id"] and r["mappings"][cert]}


def record_refresh(metadata_path: Path, counts: dict) -> str:
    """Mark the files just parsed as refreshed today in metadata.json. counts: {filename: record_count}."""
    if not metadata_path.is_file():
        return f"{metadata_path} not found: refresh not recorded"
    metadata = json.loads(metadata_path.read_text())
    for name, count in counts.items():
        metadata.setdefault(name, {}).update(
            {"last_refreshed": date.today().isoformat(), "is_placeholder": False, "record_count": count})
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    return f"refresh recorded in {metadata_path.name} for {', '.join(counts)}"


def main():
    parser = argparse.ArgumentParser(description="Read NIST's CSF 2.0 download into csf2_core.json and the crosswalks.")
    parser.add_argument("--input", default=str(CSF_SOURCE), help="NIST's CSF 2.0 xlsx (default: data/csf/source/csf2.xlsx)")
    parser.add_argument("--output", default="./data", help="data root (default: ./data); files go to csf/ and csf/crosswalks/")
    args = parser.parse_args()
    input_path, output_dir = Path(args.input), Path(args.output)
    ev = audit.begin(output_dir / "audit.jsonl", "parse_csf_source", {"input": str(input_path), "output": str(output_dir)})

    records = parse_xlsx(input_path)
    written, counts = [], {}
    for cert, filename in CERT_FILES.items():
        mapping = build_csf_to_controls(records, cert)
        doc = {"meta": {"framework": CERT_NIST[cert][0], "focal_document": "NIST CSF 2.0", **SOURCE,
                        "source_file": input_path.name},
               "csf_to_controls": mapping}
        out = crosswalk_path(filename, base=output_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2))
        written.append(out)
        counts[filename] = len(mapping)
        controls = {c for ids in mapping.values() for c in ids}
        print(f"[parse_csf_source] {out}: {len(mapping)} of {len(records)} subcategories mapped, "
              f"{len(controls)} controls")

    core_path = output_dir / "csf" / "csf2_core.json"
    core_path.parent.mkdir(parents=True, exist_ok=True)
    keys = ("function_id", "function_text", "category_id", "category_text", "subcategory_id", "subcategory_text",
            "implementation_examples")
    core = {"meta": {"source_file": input_path.name, **SOURCE,
                     "description": "CSF 2.0 subcategories and implementation examples."},
            "subcategories": [{k: r[k] for k in keys} for r in records]}
    core_path.write_text(json.dumps(core, indent=2))
    counts["csf2_core.json"] = sum(1 for r in records if not r["subcategory_text"].startswith("[Withdrawn"))
    print(f"[parse_csf_source] {core_path}: {len(records)} subcategories ({counts['csf2_core.json']} active)")

    metadata_path = output_dir / "metadata.json"
    print(f"[parse_csf_source] {record_refresh(metadata_path, counts)}")
    ev.finish(inputs=[input_path], outputs=written + [core_path] + ([metadata_path] if metadata_path.is_file() else []),
              detail=f"{len(records)} subcategory records parsed")


if __name__ == "__main__":
    main()
