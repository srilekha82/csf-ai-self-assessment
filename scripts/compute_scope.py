"""
Decides how much to ask for each CSF subcategory, for this organisation: in full, what goes beyond its certification,
or evidence only. Fixed rules, no agent.

Why:       a certification already covers part of the CSF. Asking everything from scratch wastes the client's time,
           and asking only for evidence where nothing covers it misses gaps. This applies the policy in
           data/csf/scope_rules.json to each client's certifications and SoA.
Called by: /csf-questionnaire (step 3)
Input:     <run_dir>/csf_intake.json (sector, certifications), <run_dir>/soa_parsed.json (if any), the crosswalks,
           data/csf/scope_rules.json (the policy)
Output:    <run_dir>/csf_scope.json: per subcategory the question type, why, the confidence, a note for the client
           (if any) and the related controls

Usage: .venv/bin/python ./scripts/compute_scope.py <run_dir>

Question types: full_discovery (ask from scratch), gap (ask what goes beyond what the certification covers),
confirmatory (ask for evidence that it covers it).

For each subcategory it works out a STATE (a fact) and looks up its type in scope_rules.json `states`:
  GOVERN                                     govern
  no certification / no related control      no_cert / no_mapping
  related controls, no SoA (PCI DSS always)  no_soa, or not_in_soa (only mandatory clauses, which an SoA never lists)
  ISO 27001 with an SoA, per related control implemented / applicable_not_implemented / implementation_unknown /
                                             excluded / unreadable
With several certifications or controls, the most demanding type wins. Then `sector_bumps` raise a few subcategories
one step for the client's sector. When in doubt (an excluded control, or an SoA entry that cannot be read) the
subcategory is asked in full, with a note telling the client they may answer "Not applicable" with the reason.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import (CERT_FILES, CROSSWALK_DIRS, CSF_CORE, CSF_FUNCTION_ORDER, SCOPE_RULES, SEVERITY_ORDER,  # noqa: E402
                    load_csf_intake)
import audit  # noqa: E402


def load_rules() -> dict:
    """scope_rules.json, checked: every state has a known question type, every function state exists."""
    rules = json.loads(SCOPE_RULES.read_text())
    states = rules["states"]
    bad = [n for n, s in states.items() if s["type"] not in SEVERITY_ORDER]
    bad += [s for s in rules["function_states"].values() if s not in states]
    if bad:
        sys.exit(f"[compute_scope] ERROR: {SCOPE_RULES.name} refers to unknown types/states: {bad}")
    return rules


def soa_control_state(row: dict) -> str:
    """What the SoA says about one control."""
    if row["applicable"] is None:
        return "unreadable"
    if row["applicable"] is False:
        return "excluded"
    return {True: "implemented", False: "applicable_not_implemented"}.get(row.get("implemented"),
                                                                           "implementation_unknown")


def cert_state(cert: str, sid: str, crosswalk: dict, soa: dict | None, rank) -> tuple[str, str, list]:
    """(state, the control that decided it, related controls) for one certification and one subcategory."""
    controls = crosswalk["csf_to_controls"].get(sid, [])
    if not controls:
        return "no_mapping", "", []
    if cert == "iso27001" and soa is not None:
        in_soa = [c for c in controls if c in soa]
        if not in_soa:
            return "not_in_soa", "", controls
        state, ctl = max(((soa_control_state(soa[c]), c) for c in in_soa), key=lambda r: rank(r[0]))
        return state, ctl, controls
    return "no_soa", "", controls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    run_dir = Path(parser.parse_args().run_dir)

    intake = load_csf_intake(run_dir)
    sector, certs = intake["sector"], intake["certs"]
    ev = audit.begin(audit.run_log(run_dir), "compute_scope", {"sector": sector, "certs": certs})
    inputs = [run_dir / "csf_intake.json", CSF_CORE, SCOPE_RULES]

    rules = load_rules()
    rank = lambda state: SEVERITY_ORDER.index(rules["states"][state]["type"])  # noqa: E731
    bumps = set(rules["sector_bumps"].get(sector, []))
    crosswalks = {c: json.loads((CROSSWALK_DIRS[CERT_FILES[c]] / CERT_FILES[c]).read_text()) for c in certs}

    soa, soa_path = None, run_dir / "soa_parsed.json"
    if "iso27001" in certs and soa_path.is_file():
        soa = {r["control_id"]: r for r in json.loads(soa_path.read_text())}
        inputs.append(soa_path)
        print(f"[compute_scope] Using SoA: {len(soa)} controls", file=sys.stderr)
    elif "iso27001" in certs:
        print("[compute_scope] No SoA: ISO-related subcategories are asked for evidence (low confidence)",
              file=sys.stderr)

    scope = []
    for sub in json.loads(CSF_CORE.read_text())["subcategories"]:
        sid = sub["subcategory_id"]
        if sub["subcategory_text"].startswith("[Withdrawn"):
            continue
        controls = sorted({c for cw in crosswalks.values() for c in cw["csf_to_controls"].get(sid, [])})
        if sid[:2] in rules["function_states"]:
            state, cert, ctl = rules["function_states"][sid[:2]], "", ""
        elif not certs:
            state, cert, ctl, controls = "no_cert", "", "", []
        else:
            (state, ctl, _), cert = max(((cert_state(c, sid, crosswalks[c], soa, rank), c) for c in certs),
                                        key=lambda r: rank(r[0][0]))

        policy = rules["states"][state]
        row = soa.get(ctl, {}) if soa else {}
        facts = {"cert": cert, "control": ctl, "control_no": ctl.replace("Annex A Controls: ", ""),
                 "soa_reason": f'"{row["exclusion_reason"]}"' if row.get("exclusion_reason") else "no reason given",
                 "applicable_raw": f'"{row.get("applicable_raw", "")}"'}
        qtype, reason = policy["type"], policy["reason"].format(**facts)
        if sid in bumps and qtype != SEVERITY_ORDER[-1]:
            qtype, reason = SEVERITY_ORDER[SEVERITY_ORDER.index(qtype) + 1], reason + " [sector bump applied]"
        scope.append({"subcategory_id": sid, "question_type": qtype, "state": state, "reason": reason,
                      "confidence": policy["confidence"], "note": policy.get("note", "").format(**facts),
                      "mapped_controls": controls})

    scope.sort(key=lambda e: (CSF_FUNCTION_ORDER.get(e["subcategory_id"][:2], 99), e["subcategory_id"]))
    out = run_dir / "csf_scope.json"
    out.write_text(json.dumps(scope, indent=2, ensure_ascii=False))
    counts = Counter(e["question_type"] for e in scope)
    summary = " | ".join(f"{t}: {counts.get(t, 0)}" for t in SEVERITY_ORDER)
    print(f"[compute_scope] {len(scope)} subcategories → {out}\n[compute_scope] {summary}", file=sys.stderr)
    ev.finish(inputs=inputs, outputs=[out], detail=summary, soa_used=soa is not None)


if __name__ == "__main__":
    main()
