"""
For the maintainer: says which question banks and other build outputs are out of date with their sources, so the
build commands know what to redo. It reports only; it never rebuilds. (A client run checks only the banks' age, with
check_bank_age.py.)

Called by: /build-ai-bank (--ai-bank), /build-csf-bank (--csf)
Input:     the source files (AI RMF Playbook and CIS guides, NIST's CSF download, your CSET copy), the fingerprints each
           output recorded about them, data/metadata.json, the review spreadsheets
Output:    a report on screen; exit 1 when something needs work

Usage: .venv/bin/python ./scripts/check_freshness.py --ai-bank
       .venv/bin/python ./scripts/check_freshness.py --csf [--cset-path PATH]

  --ai-bank    for the maintainer (/build-ai-bank): one line per part of the AI RMF build (parsed sources, each bank,
               impact notes, pilot, AI areas, mapping): current, stale, missing or incomplete. Current means built from
               the source files as they are now (compared by fingerprint), complete, and approved where an approval is
               needed. Needs the source PDFs.
  --csf        for the maintainer (/build-csf-bank): the age of NIST's CSF reference data (csf2_core.json and the ISO
               27001 and PCI DSS crosswalks, from data/metadata.json), and the CSF banks against CSET (it runs git fetch
               on your CSET copy, default ~/workstuff/cset, and says so if that fails). The six banks are built
               together, so they share one record of what they were built from, and one line reports them.

Exit 0: everything checked is current. Exit 1: something needs work (listed).
"""
import json, sys, argparse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from options import AI_QUESTION_BANKS, CERT_FILES, DOMAINS  # noqa: E402
from paths import (AI_BANKS, AI_CIS_CSF_XLSX, AI_CORE,  # noqa: E402
                   AI_PARSE_CONFIG, AI_PILOT, AI_SAFEGUARD_IDS, AI_SAFEGUARDS, AI_SOURCE, AI_AREAS, AI_AREAS_XLSX, CSF_IMPACT_NOTES,
                   AI_IMPACT_NOTES_XLSX, AI_QUESTIONS_AREAS_XLSX, AI_QUESTIONS_FOUNDATION_XLSX, BANK_BUILD, DATA_AUDIT, METADATA,
                   bank_path)
import audit  # noqa: E402
from sheet_io import sheet_status  # noqa: E402
from extract_cset_candidates import DEFAULT_CSET_PATH, git, sql_changed  # noqa: E402
from ai_pilot import mapping_status, pilot_status  # noqa: E402

def load(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


AI_QUESTIONS_XLSX = {"areas": (AI_QUESTIONS_AREAS_XLSX, "area_questions"),           # review sheet, sheet_io name
                     "foundation": (AI_QUESTIONS_FOUNDATION_XLSX, "foundation_questions")}


def bank_completeness(bank: str, doc: dict) -> tuple[bool, str]:
    """Whether a question bank holds what it must now (ai_questions.bank_freshness)."""
    from ai_bank_common import load_inputs
    from ai_questions import bank_freshness
    return bank_freshness(bank, doc, load_inputs())


def ai_stages() -> list[tuple[str, bool, str]]:
    """(stage, current?, text) per stage of the AI RMF build; see the module docstring."""
    cfg = json.loads(AI_PARSE_CONFIG.read_text())
    guides = {g: audit.sha(AI_SOURCE / c["file"]) for g, c in cfg["guides"].items()}
    playbook, cis_csf = audit.sha(AI_SOURCE / cfg["playbook"]["file"]), audit.sha(AI_CIS_CSF_XLSX)
    missing = [name for name, v in [("Playbook", playbook), ("CIS -> CSF xlsx", cis_csf), *guides.items()] if v is None]
    if missing:
        return [("sources", False, f"missing: {', '.join(missing)} (see data/ai/source/README.md)")]

    def verdict(stage, doc, same, what="sources changed since it was built"):
        if doc is None:
            return stage, False, "missing"
        return (stage, True, "current") if same else (stage, False, f"stale ({what})")

    core, sg = load(AI_CORE), load(AI_SAFEGUARDS) or load(AI_SAFEGUARD_IDS)   # the ids file carries the same sources
    notes = load(CSF_IMPACT_NOTES)
    recorded = lambda sources: {g: v["sha256_16"] for g, v in sources.items()}  # noqa: E731
    stages = [
        verdict("parse", core and sg, core and sg and core["source_sha256_16"] == playbook
                and recorded(sg["sources"]) == guides),
    ]
    for bank in AI_QUESTION_BANKS:
        doc = load(AI_BANKS / f"question_bank_ai_rmf_{bank}.json")
        stage, ok, text = verdict(f"bank {bank}", doc, doc and doc["playbook_sha256_16"] == playbook
                                  and doc["guide_sha256_16"] == guides)
        if ok and stages[0][1]:
            ok, text = bank_completeness(bank, doc)
            sheet, name = AI_QUESTIONS_XLSX[bank]
            if ok and sheet.is_file() and audit.sha(sheet) != doc.get("source_sha"):
                ok, text = False, f"review sheet edited but not imported (sheet_io.py import {name})"
        stages.append((stage, ok, text))
    stage, ok, text = verdict("notes", notes, notes and notes.get("sources_sha256_16") == {
        "cis_csf": cis_csf, "MCP": guides["MCP"], "AGENT": guides["AGENT"]})
    if ok and AI_IMPACT_NOTES_XLSX.is_file() and audit.sha(AI_IMPACT_NOTES_XLSX) != notes.get("source_sha"):
        ok, text = False, "review sheet edited but not imported (sheet_io.py import impact_notes)"
    stages.append((stage, ok, text))
    stages.append(("pilot", *pilot_status(AI_PILOT)))
    stages.append(("ai areas", *sheet_status("ai_areas", AI_AREAS_XLSX, AI_AREAS)))
    stages.append(("mapping", *mapping_status()))
    return stages


def check_ai_bank() -> None:
    ev = audit.begin(DATA_AUDIT, "check_freshness_ai_bank", {})
    stages = ai_stages()
    for stage, ok, text in stages:
        print(f"{stage + ':':<16}{text}")
    todo = [stage for stage, ok, _ in stages if not ok]
    if todo:
        print(f"\nNeeds work: {', '.join(todo)}")
        ev.finish("stale", detail=f"needs work: {', '.join(todo)}", stages={s: t for s, _, t in stages})
        sys.exit(1)
    print("\nAll AI RMF stages are current: nothing to rebuild.")
    ev.finish(detail="all AI RMF stages current")
    sys.exit(0)


def cset_upstream(cset_path: Path) -> tuple[str | None, list[str], str]:
    """(CSET's newest commit or None, notes, error). Fetches once; falls back to the local commit if the fetch fails."""
    try:
        git(cset_path, "fetch")
        return git(cset_path, "rev-parse", "@{u}"), [], ""
    except (RuntimeError, OSError) as e:
        try:
            local = git(cset_path, "rev-parse", "HEAD")
        except (RuntimeError, OSError) as e2:
            return None, [], f"cannot check against CSET ({e2})"
        return local, [f"could not check upstream CSET ({e}); compared with the local CSET commit instead"], ""


def csf_bank_stage(domain: str, cset_path: Path, upstream: tuple | None = None) -> tuple[tuple[str, bool, str], list[str]]:
    """(stage line, notes) for the CSF question bank of a domain. Stale = the CSET SQL changed since the bank was built.
    `upstream` is cset_upstream()'s result, so several banks share one fetch; without it this bank fetches itself."""
    stage = f"CSF bank {domain}"
    bank = load(bank_path(domain))
    if bank is None:
        return (stage, False, "missing"), []
    from build_question_bank import bank_inputs_sha
    if bank.get("inputs_sha") != bank_inputs_sha(BANK_BUILD):
        return (stage, False, "stale (the agent judgements or csf2_core.json changed since the bank was built)"), []
    ref, notes, error = upstream or cset_upstream(cset_path)
    if ref is None:
        return (stage, False, error), notes
    built = bank.get("cset_commit")
    if built == ref:
        return (stage, True, "current"), notes
    try:
        changed = sql_changed(cset_path, built or "", ref)
    except (RuntimeError, OSError):
        changed = True  # cannot compare (unknown commit): treat as stale
    if changed:
        return (stage, False, "stale (CSET SQL changed since the bank was built)"), notes
    return (stage, True, "current (CSET moved, no SQL changed)"), notes


def reference_lines() -> list[tuple[str, bool, str]]:
    """(file, ok?, text) per NIST CSF reference file (csf2_core.json and every crosswalk), by its age in metadata.json.
    These files are downloaded by hand (NIST blocks automated downloads), so their age is a reminder to check NIST."""
    metadata = json.loads(METADATA.read_text())
    lines = []
    for name in ["csf2_core.json", *CERT_FILES.values()]:
        info = metadata.get(name, {})
        refreshed, limit = info.get("last_refreshed"), info.get("refresh_threshold_days")
        if info.get("is_placeholder") or refreshed is None:
            lines.append((name, False, "seed data, never refreshed: download it from NIST"))
            continue
        age = (date.today() - date.fromisoformat(refreshed)).days
        if limit and age > limit:
            lines.append((name, False, f"stale: refreshed {refreshed}, {age} days ago, limit {limit}"))
        else:
            lines.append((name, True, f"ok: refreshed {refreshed}, {age} days ago" + (f", limit {limit}" if limit else "")))
    return lines


def csf_banks_line(cset_path: Path, upstream: tuple) -> tuple[str, bool, str]:
    """One line for the six CSF banks: missing ones, banks built from different records, or the shared record against
    CSET (csf_bank_stage)."""
    banks = {d: load(bank_path(d)) for d in DOMAINS}
    missing = [d for d, b in banks.items() if b is None]
    if missing:
        return "CSF banks", False, f"missing: {', '.join(missing)} (run /build-csf-bank)"
    records = {(b.get("cset_commit"), json.dumps(b.get("inputs_sha"), sort_keys=True)) for b in banks.values()}
    if len(records) > 1:
        return "CSF banks", False, "built from different CSET versions or judgements (run /build-csf-bank)"
    (_, ok, text), _ = csf_bank_stage(DOMAINS[0], cset_path, upstream)
    return "CSF banks", ok, text


def check_csf(cset_path: Path) -> None:
    """NIST's CSF reference data and every sector's CSF bank against CSET, in one report."""
    ev = audit.begin(DATA_AUDIT, "check_freshness_csf", {"cset_path": str(cset_path)})
    upstream = cset_upstream(cset_path)
    stages = [*reference_lines(), csf_banks_line(cset_path, upstream)]
    for stage, ok, text in stages:
        print(f"{stage + ':':<22}{text}")
    for note in upstream[1]:
        print(f"note: {note}")
    todo = [stage for stage, ok, _ in stages if not ok]
    if todo:
        print(f"\nNeeds work: {', '.join(todo)}")
        ev.finish("stale", detail=f"needs work: {', '.join(todo)}", stages={s: t for s, _, t in stages},
                  notes=upstream[1])
        sys.exit(1)
    print("\nEverything is current.")
    ev.finish(detail="everything current", notes=upstream[1])
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="For the maintainer: what the bank builds need to redo.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ai-bank", action="store_true", help="the AI RMF build: each part against its sources")
    mode.add_argument("--csf", action="store_true", help="NIST's CSF reference data and every CSF bank against CSET")
    parser.add_argument("--cset-path", default=DEFAULT_CSET_PATH, help="with --csf: your local CSET copy")
    args = parser.parse_args()
    if args.ai_bank:
        check_ai_bank()
    check_csf(Path(args.cset_path).expanduser())


if __name__ == "__main__":
    main()
