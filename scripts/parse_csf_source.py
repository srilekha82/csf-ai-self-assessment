"""
Reads NIST's CSF 2.0 download into the CSF subcategory list and the certification crosswalks.

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
certification map to each subcategory (csf_to_controls) and the reverse (control_to_csf). NIST's file says which
controls relate to a subcategory, not how (subset, equal, ...), so a crosswalk lists coverage only. The refresh date
is what check_freshness.py --csf reads.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent))
from options import CERT_FILES, CERT_NIST  # noqa: E402
from paths import CSF_SOURCE, crosswalk_path  # noqa: E402
import audit  # noqa: E402

SOURCE = {"source_url": "https://www.nist.gov/cyberframework/csf-20-informative-references",
          "author": "NIST (CPRT export)"}


def parse_references(text: str) -> dict:
    """{cert: sorted control ids} from one Informative References cell. The standard's prefix is dropped
    ("ISO/IEC 27001:2022: Mandatory Clause:  4.1" -> "Mandatory Clause: 4.1"); a bare heading with no id is skipped."""
    found = {cert: set() for cert in CERT_NIST}
    for line in (text or "").splitlines():
        for cert, (_, prefix) in CERT_NIST.items():
            if line.strip().startswith(prefix):
                control = re.sub(r" {2,}", " ", line.strip()[len(prefix):].strip().rstrip(",").strip())
                if len(control) > 1 and not control.endswith(":"):
                    found[cert].add(control)
                break
    return {cert: sorted(ids) for cert, ids in found.items()}


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
                "implementation_examples": [p.strip() for p in re.split(r"(?=Ex\d+:)", str(examples or "").strip())
                                            if p.strip()],
                "mappings": parse_references(str(refs) if refs else ""),
            })
    return records


def crosswalk(records: list[dict], cert: str, source_file: str) -> dict:
    """The crosswalk file of one certification: subcategory -> controls, and control -> subcategories."""
    mapped = [r for r in records if r["mappings"][cert]]
    unmapped = [r["subcategory_id"] for r in records if not r["mappings"][cert] and r["subcategory_id"]]
    csf_to_controls = {
        r["subcategory_id"]: {"subcategory_text": r["subcategory_text"], "function_id": r["function_id"],
                              "category_id": r["category_id"], "implementation_examples": r["implementation_examples"],
                              "controls": r["mappings"][cert], "has_mapping": bool(r["mappings"][cert])}
        for r in records if r["subcategory_id"]}
    control_to_csf = {}
    for r in records:
        for control in r["mappings"][cert]:
            control_to_csf.setdefault(control, []).append(
                {"subcategory_id": r["subcategory_id"], "subcategory_text": r["subcategory_text"],
                 "function_id": r["function_id"], "category_id": r["category_id"]})
    return {
        "meta": {"framework": CERT_NIST[cert][0], "focal_document": "NIST CSF 2.0", **SOURCE, "source_file": source_file},
        "summary": {"total_subcategories": len(records), "subcategories_with_mapping": len(mapped),
                    "subcategories_without_mapping": len(records) - len(mapped),
                    "unique_controls_mapped": len(control_to_csf), "unmapped_subcategory_ids": sorted(unmapped)},
        "csf_to_controls": csf_to_controls,
        "control_to_csf": control_to_csf,
    }


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
        doc = crosswalk(records, cert, input_path.name)
        out = crosswalk_path(filename, base=output_dir)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2))
        written.append(out)
        counts[filename] = doc["summary"]["subcategories_with_mapping"]
        print(f"[parse_csf_source] {out}: {counts[filename]} of {len(records)} subcategories mapped, "
              f"{doc['summary']['unique_controls_mapped']} controls")

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
