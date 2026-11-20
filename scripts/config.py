"""
Where every file lives and the lists every script shares. Scripts import both from here, so no path or list is
typed twice.

Called by: every script (imported, never run)
Input:     data/common/intake_options.json, data/csf/scope_rules.json, data/ai/scope_rules.json,
           data/ai/question_rules.json (the shared lists)
Output:    -

Paths: the repository's folders and files (first part). Shared lists: sectors (domains), certifications, intake
menus, question types, the order of the framework functions, the AI bank names (second part), read once from the data
files; to change one, edit the JSON. Also load_csf_intake, which reads a run's csf_intake.json.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
QUESTIONNAIRE_TEMPLATE = REPO_ROOT / "templates" / "questionnaire_template.xlsx"   # the questionnaire layout
METADATA = DATA / "metadata.json"
RUNS = REPO_ROOT / "runs"                  # one folder per engagement: <Org>_<date>/ (client data)
DATA_AUDIT = DATA / "audit.jsonl"          # reference data refresh and freshness checks (see audit.py)

# Shared by both tracks
COMMON = DATA / "common"
INTAKE_OPTIONS = COMMON / "intake_options.json"   # intake menus, domains, certs, question types (shared lists below)

# CSF track
CSF = DATA / "csf"
CSF_SOURCE = CSF / "source" / "csf2.xlsx"   # NIST CPRT export; input to parse_csf_source.py (refreshed ~yearly)
CSF_CORE = CSF / "csf2_core.json"
DOMAIN_WEIGHTS = CSF / "domain_weights.json"
CSF_BANK_RULES = CSF / "bank_rules.json"   # how CSET questions are flagged and routed when a CSF bank is built
SCOPE_RULES = CSF / "scope_rules.json"   # state -> question type policy, max questions per type
EVIDENCE_PROMPTS = CSF / "evidence_prompts.json"   # evidence an assessor asks for, by CSF category
CSF_CROSSWALKS = CSF / "crosswalks"      # olir_iso27001.json, olir_pcidss.json
CSF_BANKS = CSF / "banks"                # question_bank_<domain>.json (shared, rebuilt when CSET changes)
BANK_BUILD = CSF / "bank_build"          # cset_candidates.json, cset_judgements.json, pending/verdicts

# AI track
AI = DATA / "ai"
AI_SOURCE = AI / "source"                # Playbook, CIS companion guides, CIS -> CSF xlsx (not redistributed)
AI_PILOT = AI / "bank_build" / "pilot_accepted.json"  # written by ai_pilot.py accept
AI_CORE = AI / "ai_rmf_core.json"        # 72 subcategories + Playbook suggested actions (parse_ai_rmf_sources.py)
AI_SAFEGUARDS = AI / "cis_ai_safeguards.json"   # CIS companion guide safeguards with their text (parse_ai_rmf_sources.py;
                                                # local only, not committed: CIS text is CC BY-NC-ND 4.0)
AI_SAFEGUARD_IDS = AI / "cis_ai_safeguard_ids.json"   # the same safeguards without CIS text (ids, control, IG): committed
AI_PARSE_CONFIG = AI / "parse_config.json"      # expected counts and source file names for the parser
AI_SCOPE_RULES = AI / "scope_rules.json"        # engagement-time policy for the AI RMF questionnaire
AI_EVIDENCE_PROMPTS = AI / "evidence_prompts.json"  # evidence hint per question (foundation, or by impact)
AI_BANKS = AI / "banks"                  # question_bank_ai_rmf_<foundation|areas>.json
AI_BUILD = AI / "bank_build"             # audit.jsonl, pending/verdict files, judgement_log/
AI_CIS_CSF_XLSX = AI_SOURCE / "CIS_Controls_v8.1_Mapping_to_NIST_CSF_v2.0_2024-06-24.xlsx"
CSF_IMPACT_NOTES = CSF / "ai_impact_notes.json"  # AI-world notes per CSF subcategory (Step 5)
AI_AUTHORING = AI / "authoring"          # spreadsheets a person writes or reviews (committed; not source/)
AI_AREAS_XLSX = AI_AUTHORING / "ai_areas.xlsx"   # AI areas (usage and ecosystem components): the decision, by a person
AI_AREAS = AI / "ai_areas.json"          # generated from ai_areas.xlsx by sheet_io.py import; scripts read this
AI_AREA_LABELS = AI / "area_client_labels.json"   # area id -> the plain label the client sees
AI_MAPPING_RULES = AI / "mapping_rules.json"   # candidate CIS controls per AI area, required checks, foundation functions
AI_MAPPING = AI / "mapping.json"         # AI area x AI RMF function -> subcategory, CIS safeguards, impact (record_ai_bank.py)
AI_MAPPING_XLSX = AI_AUTHORING / "mapping.xlsx"   # the mapping for review: one line per area x subcategory (sheet_io.py)
AI_MAPPING_ACCEPTED = AI / "bank_build" / "mapping_accepted.json"   # written by ai_pilot.py accept-mapping
AI_QUESTION_RULES = AI / "question_rules.json"   # question banks: roles, producer flags, impacts (step 4)
AI_SEVERITY_RULES = AI / "severity_rules.json"   # priority (High / Medium / Low) per AI RMF subcategory, Stage 2
AI_BANK_FOUNDATION = AI_BANKS / "question_bank_ai_rmf_foundation.json"   # foundation questions (record_ai_bank.py questions)
AI_BANK_AREAS = AI_BANKS / "question_bank_ai_rmf_areas.json"             # area questions (record_ai_bank.py questions)
AI_QUESTIONS_FOUNDATION_XLSX = AI_AUTHORING / "questions_foundation.xlsx"   # the foundation bank for review (sheet_io.py)
AI_IMPACT_NOTES_XLSX = AI_AUTHORING / "impact_notes.xlsx"                # the CSF AI impact notes for review
AI_QUESTIONS_AREAS_XLSX = AI_AUTHORING / "questions_areas.xlsx"             # the area bank for review (sheet_io.py)
SHEET_SPECS = COMMON / "sheet_specs.json"   # columns and allowed values of every spreadsheet sheet_io.py converts

# Which folder each crosswalk file lives in (also used to resolve metadata.json keys)
CROSSWALK_DIRS = {
    "olir_iso27001.json": CSF_CROSSWALKS,
    "olir_pcidss.json": CSF_CROSSWALKS,
}


def crosswalk_path(filename: str, base: Path = DATA) -> Path:
    """Path of a crosswalk file under `base` (the data root)."""
    return base / CROSSWALK_DIRS[filename].relative_to(DATA) / filename


def ai_bank_path(bank: str, banks_dir: Path = AI_BANKS) -> Path:
    return banks_dir / f"question_bank_ai_rmf_{bank}.json"


def bank_path(domain: str, banks_dir: Path = CSF_BANKS) -> Path:
    return banks_dir / f"question_bank_{domain}.json"


# ── Shared lists (from the data files) ──────────────────────────────────────

_common = json.loads(INTAKE_OPTIONS.read_text())

DOMAINS = [d["value"] for d in _common["domains"]]
DOMAIN_LABELS = {d["value"]: d["label"] for d in _common["domains"]}
WEIGHT_KEY = {d["value"]: d["weight_key"] for d in _common["domains"]}     # key of the domain in domain_weights.json
_certs = [c for c in _common["certs"] if "file" in c]     # the certifications: every option but "None" has a crosswalk
CERT_LABELS = {c["value"]: c["label"] for c in _certs}
CERT_FILES = {c["value"]: c["file"] for c in _certs}
CERT_NIST = {c["value"]: (c["framework"], c["nist_reference_prefix"]) for c in _certs}   # for parse_csf_source.py
SEVERITY_ORDER = _common["severity_order"]       # question types, least to most demanding
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
