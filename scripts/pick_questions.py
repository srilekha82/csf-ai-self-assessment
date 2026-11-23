"""
Picks this client's questions from the question banks, for one framework (the CSF or the AI RMF sheet). Fixed
rules, no agent: the questions were written and checked when the banks were built.

Why:       the banks hold every question that could be asked. A client must get only the ones their intake calls
           for, worded for what they hold, in the same order every time.
Called by: /csf-questionnaire (step 4) with --framework csf, /ai-questionnaire (step 2) with --framework ai
Input:     csf: <run_dir>/csf_intake.json and csf_scope.json, the CSF bank of the client's sector,
                data/csf/scope_rules.json (how many questions, the wording), data/csf/csf2_core.json (the outcomes and
                NIST's implementation examples)
           ai:  <run_dir>/ai_intake.json, the two AI RMF banks, data/ai/scope_rules.json and question_rules.json,
                data/ai/evidence_prompts.json, the AI area labels, data/ai/ai_rmf_core.json (the outcomes)
Output:    csf: <run_dir>/csf_questions_draft.json and csf_question_bank_used.json (a copy of the bank used)
           ai:  <run_dir>/ai_questions_draft_<bank>.json, ai_question_bank_used_<bank>.json, and ai_scope.json (why
                each subcategory was picked or left out)

Usage: .venv/bin/python ./scripts/pick_questions.py <run_dir> --framework csf|ai

CSF rules: per subcategory, the first few bank questions (how many: scope_rules.json max_questions, by the question
type compute_scope.py set), worded for the certifications held with the fixed sentences in scope_rules.json frames
("Your ISO 27001 certification should cover control(s) 5.9. Please confirm ..."). A subcategory with no bank question
gets one generic question. The Evidence Required column is NIST's implementation examples for the subcategory, word
for word (scope_rules.json frames fallback_evidence if it has none). The Confidence column gets the scope's note for
the client, else the LOW flag.

AI rules: a question is picked when all three hold:
  role       it is for a role the organisation is asked as ("none" -> none; "unsure" -> none and consumer;
             "both" -> consumer and producer; scope_rules.json client_roles)
  producer   every producer detail it needs (built on an existing model, given to others) was answered yes
  AI area    (area questions) it covers one of the organisation's AI areas
A question shared by several of the organisation's areas says "This question covers: ...". Every AI question is
full_discovery: it asks about AI, so certifications change nothing. A bank entry still marked needs_human_review is
flagged in the Confidence column. ai_intake.json is checked first (exit 1, nothing written, if it breaks a rule, e.g.
after a hand edit):
  {"ai_in_use": "none" | "some" | "unsure", "role": "consumer" | "producer" | "both" | null,
   "producer": {"built_on_existing_model": bool, "given_to_others": bool} | null, "ai_areas": [AI area ids]}

Both write one draft entry per subcategory in the shape write_questionnaire.py reads.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (AI_AREAS, AI_AREA_LABELS, AI_CORE, AI_EVIDENCE_PROMPTS, AI_FUNCTION_ORDER,  # noqa: E402
                    AI_QUESTION_BANKS, AI_QUESTION_RULES, AI_SCOPE_RULES, CERT_LABELS, CSF_CORE, CSF_FUNCTION_ORDER,
                    SCOPE_RULES, ai_bank_path, bank_path, load_csf_intake)
from ai_bank_common import core_subcategories  # noqa: E402
import audit  # noqa: E402


# ── shared ──────────────────────────────────────────────────────────────────

def draft_entry(sid: str, function: str, outcome: str, qtype: str, questions: list, evidence: str, flag: str,
                **extra) -> dict:
    """One subcategory of a draft, in the shape write_questionnaire.py reads."""
    return {"subcategory_id": sid, **extra, "function": function, "outcome": outcome, "question_type": qtype,
            "questions": questions, "evidence_prompt": evidence, "confidence_flag": flag}


def write_draft(run_dir: Path, draft_name: str, entries: list, bank_file: Path, used_name: str) -> list[Path]:
    """The draft and a copy of the bank it was picked from (so the run can be read back later)."""
    draft, used = run_dir / draft_name, run_dir / used_name
    draft.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    shutil.copy2(bank_file, used)
    return [draft, used]


# ── CSF: count by question type, worded for the certifications held ─────────

def csf_cert_phrase(certs: list) -> str:
    """'ISO 27001 certification', 'PCI DSS certification', 'ISO 27001 and PCI DSS certifications'."""
    labels = [CERT_LABELS[c] for c in certs if c in CERT_LABELS]
    if not labels:
        return "certification"
    return " and ".join(labels) + (" certifications" if len(labels) > 1 else " certification")


def csf_frame_question(base_text: str, question_type: str, mapped_controls: list, frames: dict,
                       certs: list = ()) -> str:
    """The bank question, worded for the certifications held (the wording is in scope_rules.json `frames`)."""
    frame = frames.get(question_type)
    if frame is None:
        return base_text
    controls = (", ".join(c.replace("Annex A Controls: ", "") for c in mapped_controls)
                if mapped_controls else frames["no_controls"])
    return frame.format(cert=f"Your {csf_cert_phrase(list(certs))}", controls=controls, text=base_text)


def csf_evidence_prompt(subcategory: dict, frames: dict) -> str:
    """NIST's implementation examples for the subcategory, word for word, one per line; the fixed fallback if none."""
    return "\n".join(subcategory.get("implementation_examples") or []) or frames["fallback_evidence"]


def pick_csf(run_dir: Path, ev) -> tuple[list, list, str]:
    intake = load_csf_intake(run_dir)
    bank_file = bank_path(intake["sector"])
    if not bank_file.is_file():
        ev.fail(f"[pick_questions] ERROR: {bank_file} not found. Run /build-csf-bank first.")
    rules = json.loads(SCOPE_RULES.read_text())
    bank = json.loads(bank_file.read_text())["questions"]
    core = {s["subcategory_id"]: s for s in json.loads(CSF_CORE.read_text())["subcategories"]}
    outcomes = {sid: s["subcategory_text"] for sid, s in core.items()}

    entries, fallback = [], 0
    for scope in json.loads((run_dir / "csf_scope.json").read_text()):
        sid, qtype = scope["subcategory_id"], scope["question_type"]
        selected = bank.get(sid, {}).get("candidates", [])[:rules["max_questions"][qtype]]
        if not selected:
            fallback += 1
            selected = [{"question_text": rules["frames"]["fallback_question"].format(outcome=outcomes.get(sid, sid)),
                         "cset_question_id": None}]
        questions = [{
            "question_text": csf_frame_question(c["question_text"], qtype, scope.get("mapped_controls", []),
                                            rules["frames"], intake["certs"]),
            "source_reference": (f"CSET {c['cset_set']}: {c['cset_question_id']}" if c.get("cset_set")
                                 else f"CSET: {c['cset_question_id']}" if c.get("cset_question_id")
                                 else "NIST CSF 2.0"),
            "cset_question_id": c.get("cset_question_id"),
        } for c in selected]
        flag = scope.get("note") or ("LOW — assessor verification required"
                                     if scope.get("confidence") == "low" or qtype == "confirmatory" else "")
        entries.append(draft_entry(sid, sid.split(".")[0], outcomes.get(sid, ""), qtype, questions,
                                   csf_evidence_prompt(core.get(sid, {}), rules["frames"]), flag))
    entries.sort(key=lambda e: (CSF_FUNCTION_ORDER.get(e["function"], 99), e["subcategory_id"]))

    outputs = write_draft(run_dir, "csf_questions_draft.json", entries, bank_file, "csf_question_bank_used.json")
    by_type = {t: sum(1 for e in entries if e["question_type"] == t) for t in rules["max_questions"]}
    detail = (f"csf: {len(entries)} subcategories, {sum(len(e['questions']) for e in entries)} questions; "
              f"by type {by_type}; generic question (no bank match): {fallback}")
    return [run_dir / "csf_intake.json", run_dir / "csf_scope.json", bank_file, SCOPE_RULES, CSF_CORE], \
        outputs, detail


# ── AI RMF: filter by role, producer details and AI areas ───────────────────

def ai_check_intake(p: dict, areas: list[str], qrules: dict) -> list[str]:
    if not isinstance(p, dict):
        return ["ai_intake.json must be a JSON object"]
    if p.get("ai_in_use") not in ("none", "some", "unsure"):
        return ["ai_in_use must be none, some or unsure"]
    errors = []
    role = p.get("role")
    if p["ai_in_use"] == "some" and role not in ("consumer", "producer", "both"):
        errors.append("role must be consumer, producer or both when AI is in use")
    if p["ai_in_use"] != "some" and role is not None:
        errors.append("role is asked only when AI is in use")
    flags = list(qrules["producer_flags"])
    prod = p.get("producer")
    if role in ("producer", "both"):
        if not isinstance(prod, dict) or set(prod) != set(flags) or not all(isinstance(v, bool) for v in prod.values()):
            errors.append(f"producer must be an object of booleans with exactly {flags} for a producer")
    elif prod is not None:
        errors.append("producer is only given for role producer or both")
    got = p.get("ai_areas")
    if not isinstance(got, list) or not set(got) <= set(areas):
        errors.append(f"ai_areas must be a list from {areas}")
    return errors


def ai_client_roles(p: dict, rules: dict) -> list[str]:
    return rules["client_roles"][p["role"] if p["ai_in_use"] == "some" else p["ai_in_use"]]


def ai_questions_for(bank: str, rec: dict, roles: list, flags: list, areas: list) -> list[tuple[dict, list[str]]]:
    """(question, the client's rows it covers) for every question of one bank entry the client gets."""
    out = []
    for q in rec["questions"]:
        if not set(q["roles"]) & set(roles) or not set(q["producer_flags"]) <= set(flags):
            continue
        rows = [r for r in q.get("rows", []) if rec["rows"][r]["area"] in areas] if bank == "areas" else []
        if bank == "areas" and not rows:
            continue
        out.append((q, rows))
    return out


def ai_evidence_prompt(bank: str, rec: dict, rows: list, evidence: dict, impact_order: list) -> str:
    if bank == "foundation":
        return evidence["foundation"]
    impacts = {i for r in rows for i in rec["rows"][r]["impact"]}
    return " ".join(evidence["by_impact"][i] for i in impact_order if i in impacts) or evidence["default"]


def ai_entry(bank: str, sid: str, rec: dict, picked: list, outcome: str, names: dict, rules: dict, evidence: dict,
             impact_order: list) -> dict:
    questions = []
    for q, rows in picked:
        client_areas = [names[rec["rows"][r]["area"]] for r in rows]
        questions.append({
            "question_text": q["question_text"],
            "source_reference": "AI RMF Playbook: " + "; ".join(q["playbook_refs"]),
            "cis_refs": q["cis_refs"],
            "applies_to": (rules["foundation_label"] if bank == "foundation" else
                           rules["covers_note"].format(areas="; ".join(client_areas)) if len(q["rows"]) > 1
                           else client_areas[0]),
            "rows": rows,
            "evidence_prompt": q.get("evidence_prompt") or ai_evidence_prompt(bank, rec, rows, evidence, impact_order),
        })
    flag = rules["review_flag"] if rec["status"] == "needs_human_review" else ""
    return draft_entry(sid, sid.split()[0], outcome, rules["default_type"], questions,
                       questions[0]["evidence_prompt"], flag, bank=bank)


def pick_ai(run_dir: Path, ev) -> tuple[list, list, str]:
    usage_path = run_dir / "ai_intake.json"
    inputs = [usage_path, AI_SCOPE_RULES, AI_QUESTION_RULES, AI_EVIDENCE_PROMPTS, AI_AREAS, AI_AREA_LABELS, AI_CORE]
    for p in inputs:
        if not p.is_file():
            ev.fail(f"[pick_questions] ERROR: {p} not found" + (
                " (run the intake first)" if p == usage_path else
                " (run parse_ai_rmf_sources.py)" if p == AI_CORE else ""), inputs)
    rules = json.loads(AI_SCOPE_RULES.read_text())
    qrules = json.loads(AI_QUESTION_RULES.read_text())
    evidence = json.loads(AI_EVIDENCE_PROMPTS.read_text())
    labels = json.loads(AI_AREA_LABELS.read_text())["labels"]
    names = {a["id"]: labels.get(a["id"]) for a in json.loads(AI_AREAS.read_text())["ai_areas"]}
    if not all(names.values()):
        ev.fail(f"[pick_questions] ERROR: {AI_AREA_LABELS} has no label for "
                f"{', '.join(a for a, n in names.items() if not n)}", inputs)
    outcomes = {s["subcategory_id"]: s["outcome"] for s in core_subcategories(json.loads(AI_CORE.read_text()))}
    profile = json.loads(usage_path.read_text())
    errors = ai_check_intake(profile, list(names), qrules)
    if errors:
        ev.reject(errors, "ai_intake.json", inputs)

    roles = ai_client_roles(profile, rules)
    flags = [f for f, v in (profile.get("producer") or {}).items() if v]
    scope, outputs, summary = {}, [], []
    for bank in AI_QUESTION_BANKS:
        bank_file = ai_bank_path(bank)
        if not bank_file.is_file():
            ev.fail(f"[pick_questions] ERROR: {bank_file} not found. Run /build-ai-bank first.", inputs)
        inputs.append(bank_file)
        entries, scope[bank] = [], []
        for sid, rec in json.loads(bank_file.read_text())["subcategories"].items():
            picked = ai_questions_for(bank, rec, roles, flags, profile["ai_areas"])
            covered = sorted({rec["rows"][r]["area"] for _, rows in picked for r in rows})
            reason = rules["reason"].format(roles=", ".join(roles),
                                            areas=f"; areas {', '.join(names[a] for a in covered)}" if covered else "")
            scope[bank].append({"subcategory_id": sid, "questions": len(picked), "reason": reason if picked else
                                "No question of this subcategory applies to the client's role, flags or AI areas"})
            if picked:
                entries.append(ai_entry(bank, sid, rec, picked, outcomes[sid], names, rules, evidence,
                                        list(qrules["impacts"])))
        entries.sort(key=lambda e: (AI_FUNCTION_ORDER.get(e["function"], 99),
                                    list(outcomes).index(e["subcategory_id"])))
        outputs += write_draft(run_dir, f"ai_questions_draft_{bank}.json", entries, bank_file,
                               f"ai_question_bank_used_{bank}.json")
        summary.append(f"{bank}: {len(entries)} subcategories, {sum(len(e['questions']) for e in entries)} questions")

    scope_path = run_dir / "ai_scope.json"
    scope_path.write_text(json.dumps({
        "ai_in_use": profile["ai_in_use"], "role": profile.get("role"), "roles_asked_as": roles,
        "producer_flags": flags, "ai_areas": profile["ai_areas"],
        "usage_note": rules["usage_notes"][profile["ai_in_use"]].format(
            role=profile.get("role"), areas=", ".join(names[a] for a in profile["ai_areas"])),
        "banks": scope}, indent=2, ensure_ascii=False))
    detail = f"ai: ai_in_use={profile['ai_in_use']}; roles {', '.join(roles)}; " + "; ".join(summary)
    return inputs, [scope_path, *outputs], detail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--framework", choices=["csf", "ai"], required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    ev = audit.begin(audit.run_log(run_dir), "pick_questions", {"framework": args.framework})
    inputs, outputs, detail = (pick_csf if args.framework == "csf" else pick_ai)(run_dir, ev)
    print(f"[pick_questions] {detail} → {run_dir}", file=sys.stderr)
    ev.finish(inputs=inputs, outputs=outputs, detail=detail)


if __name__ == "__main__":
    main()
