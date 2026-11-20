"""
Shared lists every script uses: sectors (domains), certifications, intake menus, question types, the order
of the framework functions, and the AI bank names.

Called by: most scripts (imported, never run)
Input:     data/common/intake_options.json, data/csf/scope_rules.json, data/ai/scope_rules.json
Output:    -

They are read once from the data files (data/common/intake_options.json and each track's scope_rules.json). To change
one, edit the JSON; never copy a list into a script.
"""

import json
from pathlib import Path

from paths import AI_QUESTION_RULES, AI_SCOPE_RULES, INTAKE_OPTIONS, SCOPE_RULES

_common = json.loads(INTAKE_OPTIONS.read_text())

DOMAINS = [d["value"] for d in _common["domains"]]
DOMAIN_LABELS = {d["value"]: d["label"] for d in _common["domains"]}
WEIGHT_KEY = {d["value"]: d["weight_key"] for d in _common["domains"]}     # key of the domain in domain_weights.json
CERTS = [c["value"] for c in _common["certs"] if c["value"] != "none"]     # certifications with a crosswalk
CERT_LABELS = {c["value"]: c["label"] for c in _common["certs"] if c["value"] != "none"}
CERT_FILES = {c["value"]: c["file"] for c in _common["certs"] if c["value"] != "none"}
SEVERITY_ORDER = _common["severity_order"]       # question types, least to most demanding
QUESTION_TYPES = set(SEVERITY_ORDER)
_menus = {"domains": _common["domains"], "certs": _common["certs"]}
INTAKE_QUESTIONS = [{**q, "options": _menus[q["options"]] if isinstance(q["options"], str) else q["options"]}
                    for q in _common["questions"]]     # menus with their options spelled out


def load_csf_intake(run_dir) -> dict:
    """<run_dir>/csf_intake.json (written by intake.py): org, date, domain, certs. Exits with a pointer if it is missing."""
    path = Path(run_dir) / "csf_intake.json"
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found. Run scripts/intake.py first (it records org, domain and certifications).")
    return json.loads(path.read_text())


def _rank(order: list) -> dict:
    return {f: i for i, f in enumerate(order)}


CSF_FUNCTION_ORDER = _rank(json.loads(SCOPE_RULES.read_text())["function_order"])          # GV, ID, ...
_ai_rules = json.loads(AI_SCOPE_RULES.read_text())
AI_FUNCTION_ORDER = _rank(_ai_rules["function_order"])        # GOVERN, MAP, ...
AI_QUESTION_BANKS = tuple(json.loads(AI_QUESTION_RULES.read_text())["banks"])   # foundation, areas
