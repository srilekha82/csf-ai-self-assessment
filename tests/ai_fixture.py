"""A frozen copy of the AI RMF rules, AI areas and mapping (tests/fixtures/ai/), for the unit tests.

The unit tests check the code, so they must not change when the real data does (a re-drafted area, a new AI area, a
rules edit). Importing this module points every script module at the copies; the data checks (check_*.py) still test
the real files. Reference data (the parsed Playbook and the CIS safeguard ids) stays real: it changes only with a new
source edition. Refresh the copies only on purpose, when a test needs data the copies lack.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import ai_bank_common, ai_external, ai_mapping, ai_priority, ai_questions, check_freshness, config  # noqa: E401,E402
import intake, pick_questions, prepare_ai_bank, record_bank, sheet_io, write_questionnaire  # noqa: E401,E402

FIXTURE = HERE / "fixtures" / "ai"
FILES = {
    "AI_AREAS": "ai_areas.json", "AI_AREAS_XLSX": "ai_areas.xlsx", "AI_AREA_LABELS": "area_client_labels.json",
    "AI_MAPPING": "mapping.json", "AI_MAPPING_XLSX": "mapping.xlsx", "AI_MAPPING_ACCEPTED": "mapping_accepted.json",
    "AI_MAPPING_RULES": "mapping_rules.json", "AI_QUESTION_RULES": "question_rules.json",
    "AI_SCOPE_RULES": "scope_rules.json", "AI_EVIDENCE_PROMPTS": "evidence_prompts.json",
    "AI_SEVERITY_RULES": "severity_rules.json", "AI_PILOT": "pilot_accepted.json",
    "QUESTIONNAIRE_TEMPLATE": "questionnaire_template.xlsx",
}
for module in (config, ai_bank_common, ai_external, ai_mapping, ai_priority, ai_questions, check_freshness, intake,
               pick_questions, prepare_ai_bank, record_bank, sheet_io, write_questionnaire):
    for name, file in FILES.items():
        if hasattr(module, name):
            setattr(module, name, FIXTURE / file)
