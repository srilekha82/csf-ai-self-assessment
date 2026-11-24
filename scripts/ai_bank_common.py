"""
Helpers shared by the AI RMF bank scripts: loading the parsed sources, row ids, which roles an AI area allows, and
the foundation subcategories.

Why:       every AI step reads the same parsed sources and rules; loading them in one place keeps the steps consistent.
Called by: prepare_ai_bank, record_bank, ai_mapping, ai_questions, ai_external, pick_questions
           (imported, never run)
Input:     data/ai/ (AI RMF core, CIS safeguards, AI areas, rules)
Output:    -
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import AI_CORE, AI_SAFEGUARDS, AI_SAFEGUARD_IDS, REPO_ROOT  # noqa: E402

def load_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"[ai_bank] ERROR: cannot read {what} ({path}): {e}")


def row_id(area: str, subcategory: str) -> str:
    """The id of one mapping row (AI area x subcategory) in the area question bank."""
    return f"{area}|{subcategory}"


def area_roles(area: dict, qrules: dict, scope_rules: dict) -> list[str]:
    """Roles an area question may carry: the area's applies_to, plus `none` for areas every client gets."""
    roles = list(qrules["area_roles"]["applies_to"][area["applies_to"]])
    return (["none"] if area["id"] in scope_rules["ai_area_rules"]["always"] else []) + roles


def core_subcategories(core: dict) -> list[dict]:
    """Every subcategory of ai_rmf_core.json, flattened from its functions (GOVERN, MAP, MEASURE, MANAGE order)."""
    return [s for f in core["functions"] for s in f["subcategories"]]


def load_inputs() -> dict:
    """Reference data every validator and every prepare mode needs. Fails early with a pointer to the step that creates it."""
    if not AI_CORE.is_file():
        sys.exit(f"[ai_bank] ERROR: {AI_CORE} not found. Run parse_ai_rmf_sources.py first.")
    if not (AI_SAFEGUARDS.is_file() or AI_SAFEGUARD_IDS.is_file()):
        sys.exit(f"[ai_bank] ERROR: neither {AI_SAFEGUARDS} nor {AI_SAFEGUARD_IDS} found. Run parse_ai_rmf_sources.py.")
    core = load_json(AI_CORE, "ai_rmf_core.json")
    has_text = AI_SAFEGUARDS.is_file()   # the CIS text is local only (CC BY-NC-ND 4.0); the ids file is committed
    sg = load_json(AI_SAFEGUARDS if has_text else AI_SAFEGUARD_IDS, AI_SAFEGUARDS.name)
    text = ("title", "base_text", "ai_applicability")
    return {
        "core": core, "subs": {s["subcategory_id"]: s for s in core_subcategories(core)},
        "safeguards": {r["id"]: {**{k: "" for k in text}, **r} for r in sg["safeguards"]}, "sg_doc": sg,
        "has_text": has_text,
    }


def require_cis_text(inp: dict, what: str) -> None:
    """Agent inputs quote the CIS safeguard text, which is not in the repository: stop with the way to get it."""
    if not inp.get("has_text"):
        sys.exit(f"[ai_bank] ERROR: {what} needs the CIS safeguard text ({AI_SAFEGUARDS.name}, local only). Download "
                 "the three CIS companion guides (data/ai/source/README.md) and run parse_ai_rmf_sources.py.")


def foundation_subcategories(rules: dict, inp: dict) -> list[str]:
    """Subcategories asked once for the organisation, never mapped to an AI area: all of the foundation functions, plus
    the single subcategories listed in foundation.subcategories."""
    extra = set(rules["foundation"]["subcategories"])
    return [sid for sid, s in inp["subs"].items() if s["function"] in rules["foundation"]["functions"] or sid in extra]


def rel(path: Path) -> str:
    """Path relative to the repo root when inside it (always the case outside tests)."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)
