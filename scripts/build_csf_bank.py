"""
Builds the six CSF question banks, one per sector, from the CSET questions linked to CSF 2.0. No agent, no judgement:
every question and every link is CSET's, and fixed rules decide which sector gets which question.

Why:       a client should get CSET's own questions for their sector, the same every time the bank is rebuilt from the
           same CSET commit. Certifications are not applied here; a client run applies them (compute_scope.py).
Called by: /build-csf-bank (step 3)
Input:     data/csf/bank_build/cset_candidates.json (extract_cset_candidates.py), data/csf/csf2_core.json, the rules in
           data/csf/bank_rules.json
Output:    data/csf/banks/question_bank_<sector>.json for every sector

Usage: .venv/bin/python ./scripts/build_csf_bank.py [--output-dir DIR] [--cache-dir DIR]

Per CSF subcategory, in this order:
  1. CSET's own CSF 2.0 question (the NCSF_V2 set), in every sector.
  2. The other CSET questions CSET links to it, from a set for this sector (bank_rules.json sector_by_model, e.g. ACET
     for finance) or a set listed for no sector (every sector). A question with a reject flag (CSET marks it not
     answerable, or it has no text) is left out. A practice with no question text (statement_only) is shown as its
     CSET outcome text. The same wording twice in a subcategory is kept once.
The banks are always built together, from the same CSET collection, so they share one record of what they were built
from (check_freshness.py --csf checks it).
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (BANK_BUILD, CSF_BANKS, CSF_BANK_RULES, CSF_CORE, CSF_FUNCTION_ORDER, SECTORS,  # noqa: E402
                     bank_path)
import audit  # noqa: E402

BANK_RULES = json.loads(CSF_BANK_RULES.read_text())   # data/csf/bank_rules.json
REJECT_FLAGS = set(BANK_RULES["reject_flags"])
STATEMENT_FIELD = BANK_RULES["statement_only_text"]["field"]
SECTOR_BY_MODEL = {k: v for k, v in BANK_RULES["sector_by_model"].items() if k != "description"}
CSF2_SET = "NCSF_V2"  # CSET's CSF 2.0 standard (cset_candidates.json `csf2_set`), first in every subcategory


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def question_text(q: dict) -> str:
    """CSET's question text; for a practice with none, CSET's own text of the field bank_rules.json names."""
    text = q["question_text"] or (q.get("practice") or {}).get(STATEMENT_FIELD) or ""
    return " ".join(text.split())


def for_sector(q: dict, sector: str) -> bool:
    """A set listed in sector_by_model is for that sector only; any other set is for every sector."""
    return SECTOR_BY_MODEL.get(q.get("model_name"), sector) == sector and not REJECT_FLAGS & set(q["flags"])


def build_bank(sector: str, candidates: dict, active: dict[str, dict]) -> dict:
    by_sub: dict[str, list[dict]] = {sid: [] for sid in active}
    seen: dict[str, set[str]] = {sid: set() for sid in active}

    def add(sid: str, entry: dict) -> None:
        key = norm(entry["question_text"])
        if sid in active and key and key not in seen[sid]:
            seen[sid].add(key)
            by_sub[sid].append(entry)

    for sid, entry in candidates.get("csf2_set", {}).items():
        for q in entry["questions"]:
            add(sid, {"cset_question_id": q["question_id"], "cset_set": CSF2_SET, "question_text": q["question_text"],
                      "model_name": CSF2_SET})
    links = sorted(((int(m["qid"]), m["subcategory_id"]) for m in candidates["mappings"]))
    for qid, sid in links:
        q = candidates["questions"].get(str(qid))
        if q is None or not for_sector(q, sector):
            continue
        add(sid, {"cset_question_id": qid, "question_text": question_text(q), "model_name": q.get("model_name"),
                  "category": q.get("category"), "sub_category": q.get("sub_category"),
                  "text_from": STATEMENT_FIELD if not q["question_text"] else "question"})

    ordered = sorted(active, key=lambda s: (CSF_FUNCTION_ORDER.get(s[:2], 9), s))
    return {"sector": sector, "cset_commit": candidates["cset_commit"], "built_on": date.today().isoformat(),
            "inputs_sha": bank_inputs_sha(),
            "questions": {sid: {"subcategory_text": active[sid]["subcategory_text"], "candidates": by_sub[sid]}
                          for sid in ordered}}


def bank_inputs_sha() -> dict:
    """Hashes of the local inputs a bank is built from besides CSET (check_freshness compares them)."""
    return {"bank_rules": audit.sha(CSF_BANK_RULES), "csf2_core": audit.sha(CSF_CORE)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(CSF_BANKS))
    parser.add_argument("--cache-dir", default=str(BANK_BUILD))
    args = parser.parse_args()

    cache, out_dir = Path(args.cache_dir), Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = audit.begin(cache / "audit.jsonl", "build_csf_bank", {})
    candidates = load_json(cache / "cset_candidates.json")
    if candidates is None:
        ev.fail("[build_csf_bank] ERROR: cset_candidates.json not found. Run scripts/extract_cset_candidates.py first.")
    active = {s["subcategory_id"]: s for s in load_json(CSF_CORE)["subcategories"]
              if not s["subcategory_text"].startswith("[Withdrawn")}

    paths, details = [], []
    for sector in SECTORS:
        bank = build_bank(sector, candidates, active)
        path = bank_path(sector, out_dir)
        path.write_text(json.dumps(bank, indent=2, ensure_ascii=False))
        paths.append(path)
        n = sum(len(v["candidates"]) for v in bank["questions"].values())
        empty = sum(1 for v in bank["questions"].values() if not v["candidates"])
        details.append(f"{sector}: {n} questions, {empty} subcategories empty")
    print("[build_csf_bank] " + "; ".join(details) + f" (CSET {candidates['cset_commit'][:7]})")
    ev.finish(inputs=[cache / "cset_candidates.json", CSF_CORE, CSF_BANK_RULES], outputs=paths,
              detail="; ".join(details), cset_commit=candidates["cset_commit"])


if __name__ == "__main__":
    main()
