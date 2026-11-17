"""
The two AI RMF question banks (foundation and areas). Checks generated questions and evidence lines before they are
stored, combines the generator's and checker's files (assemble), says whether a bank is complete, and converts the
banks to and from their review spreadsheets.

Called by: record_ai_bank.py (questions, evidence, assemble), sheet_io.py (the question sheets),
           check_freshness.py (bank completeness), record_judgements.py
Input:     data/ai/mapping.json, data/ai/question_rules.json, data/ai/scope_rules.json, the parsed AI RMF and CIS data
Output:    data/ai/banks/question_bank_ai_rmf_<foundation|areas>.json

Terms (mapping row, foundation, producer details, needs human review): see docs/guide.md, Glossary.
"""

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import AI_AREAS, AI_BANKS, AI_MAPPING, AI_MAPPING_RULES, AI_QUESTION_RULES, AI_SCOPE_RULES  # noqa: E402
from ai_bank_common import area_roles, foundation_subcategories, load_json, row_id  # noqa: E402


BANK_DESCRIPTION = {
    "areas": ("AI RMF area questions: every question that could be asked per mapping row (AI area x subcategory, "
              "data/ai/mapping.json), keyed by subcategory. A question lists the rows it covers (one question may stand "
              "for several areas' rows), the roles it is asked of and any producer flags; build_ai_questions.py picks a "
              "client's questions by filtering on their AI areas, role and producer flags. rows_sha is the hash of the "
              "subcategory's mapping rows the questions were written for; rows gives each row's area and impact (for the "
              "covers note and the evidence prompt). Recorded by record_ai_bank.py questions."),
    "foundation": ("AI RMF foundation questions: every question that could be asked once for the organisation (GOVERN "
                   "and the foundation subcategories of mapping_rules.json), keyed by subcategory, each with the roles "
                   "it is asked of (none, consumer, producer) and any producer flags. Recorded by record_ai_bank.py "
                   "questions."),
}
MIN_QUESTION_CHARS = 30
PLAYBOOK_REF = re.compile(r"^((?:GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+) [—–-] suggested action (\d+)$")
REASON_PART = re.compile(r"(?:^|; )Q(\d+): ")    # assemble joins failures as "Q<n>: reason; Q<m>: reason"
WHOLE = "Whole subcategory: "                      # how a question_number 0 failure shows on every line of the sheet
STALE = "the mapping rows changed since these questions were written: check them against the rows, then set pass"


def question_context(inp: dict) -> dict:
    """What validate_questions checks against: the accepted mapping's rows per subcategory, the roles each area allows,
    the foundation subcategories and the question rules."""
    for p, how in ((AI_MAPPING, "record and accept the mapping first"), (AI_AREAS, "sheet_io.py import ai_areas")):
        if not p.is_file():
            sys.exit(f"[record_ai_bank] ERROR: {p} not found ({how})")
    qrules = load_json(AI_QUESTION_RULES, "question_rules.json")
    scope_rules = load_json(AI_SCOPE_RULES, "scope_rules.json")
    areas = {a["id"]: a for a in load_json(AI_AREAS, "ai_areas.json")["ai_areas"]}
    rows: dict[str, dict] = {}
    for area_id, entry in load_json(AI_MAPPING, "mapping.json")["areas"].items():
        roles = area_roles(areas[area_id], qrules, scope_rules)
        for r in entry["rows"]:
            rows.setdefault(r["subcategory"], {})[row_id(area_id, r["subcategory"])] = {
                "roles": roles, "cis_refs": r["cis_refs"], "folded": r.get("folded", []),
                "area": area_id, "impact": r["impact"], "sig": [r["why"], r["cis_refs"], r.get("folded", [])]}
    return {"rows": rows, "foundation": foundation_subcategories(load_json(AI_MAPPING_RULES, "mapping_rules.json"), inp),
            "roles": list(qrules["roles"]), "flags": list(qrules["producer_flags"]),
            "foundation_count": qrules["foundation_questions"], "row_max": qrules["row_questions"]["max"]}


def rows_sha(rows: dict) -> str:
    """Hash of a subcategory's mapping rows as the questions were written for them (a changed row makes them stale)."""
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def rows_record(ctx: dict, sid: str) -> dict:
    """What an area bank entry stores about the rows its questions were written for."""
    return {"rows_sha": rows_sha({r: v["sig"] for r, v in ctx["rows"][sid].items()}),
            "rows": {r: {"area": v["area"], "impact": v["impact"]} for r, v in ctx["rows"][sid].items()}}


def bank_freshness(bank: str, doc: dict, inp: dict) -> tuple[bool, str]:
    """(complete?, text) for a question bank against what it must hold now: area bank, every subcategory with mapping rows,
    each written for the rows as they are now (rows_sha); foundation bank, every foundation subcategory."""
    ctx = question_context(inp)
    want = list(ctx["rows"]) if bank == "areas" else ctx["foundation"]
    have = doc["subcategories"]
    missing = [s for s in want if s not in have]
    extra = [s for s in have if s not in want]
    changed = [s for s in want if s in have and bank == "areas"
               and have[s].get("rows_sha") != rows_sha({r: v["sig"] for r, v in ctx["rows"][s].items()})]
    review = sum(1 for e in have.values() if e["status"] == "needs_human_review")
    if missing or extra or changed:
        parts = ([f"{len(missing)} of {len(want)} subcategories missing"] if missing else []) + \
                ([f"no longer in the bank's scope: {', '.join(extra)}"] if extra else []) + \
                ([f"mapping rows changed since written: {', '.join(changed)}"] if changed else [])
        return False, "incomplete (" + "; ".join(parts) + ")"
    return True, f"current ({len(have)} subcategories, {review} need human review)"


def check_question(tag: str, sid: str, q, bank: str, inp: dict, ctx: dict) -> list[str]:
    """Problems of one question (fields, refs, roles, flags; area bank: the rows it covers)."""
    need = {"question_text", "playbook_refs", "cis_refs", "roles", "producer_flags"} | ({"rows"} if bank == "areas" else set())
    if not isinstance(q, dict) or not need <= set(q) <= need | {"evidence_prompt"}:
        return [f"{tag}: fields must be exactly {sorted(need)} (and an optional evidence_prompt)"
                + (f"; diff {sorted(set(q) ^ need)}" if isinstance(q, dict) else "")]
    if "evidence_prompt" in q and (not isinstance(q["evidence_prompt"], str)
                                   or len(q["evidence_prompt"].strip()) < MIN_QUESTION_CHARS):
        return [f"{tag}: evidence_prompt must be text of at least {MIN_QUESTION_CHARS} characters"]
    if not all(isinstance(q[k], list) for k in need - {"question_text"}):
        return [f"{tag}: {sorted(need - {'question_text'})} must be lists"]
    errors = []
    if len(str(q["question_text"]).strip()) < MIN_QUESTION_CHARS:
        errors.append(f"{tag}: question_text shorter than {MIN_QUESTION_CHARS} characters")
    rows = ctx["rows"].get(sid, {})
    covered = [rows[r] for r in q.get("rows", []) if r in rows]
    if bank == "areas":
        bad = [r for r in q["rows"] if r not in rows]
        if not q["rows"] or bad or len(set(q["rows"])) != len(q["rows"]):
            errors.append(f"{tag}: rows must be distinct mapping rows of {sid} (unknown: {bad})")
    allowed_subs = {sid} | {f for r in covered for f in r["folded"]}
    if not q["playbook_refs"]:
        errors.append(f"{tag}: playbook_refs must name at least one suggested action")
    for ref in q["playbook_refs"]:
        m = PLAYBOOK_REF.match(str(ref))
        if not m or m.group(1) not in allowed_subs:
            errors.append(f"{tag}: playbook_ref {ref!r} must be '<subcategory> — suggested action N' for "
                          f"{sorted(allowed_subs)}")
        elif not 1 <= int(m.group(2)) <= len(inp["subs"][m.group(1)]["suggested_actions"]):
            errors.append(f"{tag}: {m.group(1)} has no suggested action {m.group(2)}")
    allowed_cis = {c for r in covered for c in r["cis_refs"]}
    if set(q["cis_refs"]) - allowed_cis:
        errors.append(f"{tag}: cis_refs {sorted(set(q['cis_refs']) - allowed_cis)} are not safeguards of the rows it "
                      f"covers" + (" (foundation questions cite none)" if bank == "foundation" else ""))
    roles = q["roles"]
    allowed_roles = (set.intersection(*(set(r["roles"]) for r in covered)) if covered else set()) \
        if bank == "areas" else set(ctx["roles"])
    if not roles or len(set(roles)) != len(roles) or set(roles) - allowed_roles:
        errors.append(f"{tag}: roles {roles} must be distinct and from {sorted(allowed_roles)}"
                      + (" (the roles every covered row's area allows)" if bank == "areas" else ""))
    flags = q["producer_flags"]
    if set(flags) - set(ctx["flags"]) or len(set(flags)) != len(flags):
        errors.append(f"{tag}: producer_flags must be distinct and from {ctx['flags']}")
    elif flags and roles != ["producer"]:
        errors.append(f"{tag}: a question with producer flags is asked of producers only (roles ['producer'])")
    return errors


def validate_questions(data, bank: str, inp: dict, ctx: dict) -> list[str]:
    """The whole file, per subcategory: status, the questions, and coverage (area bank: every row asked once, or up to
    row_questions max times, per role its area allows, folded outcomes cited; foundation: the count, a consumer and a producer question).

    A question: question_text, playbook_refs ["<subcategory> — suggested action N", ...], cis_refs, roles (none /
    consumer / producer), producer_flags (the producer details, data/ai/question_rules.json); in the area bank also
    rows (mapping row ids "<area>|<subcategory>" it covers).

    Area bank: the subcategory has rows in data/ai/mapping.json; each row is asked once (twice at most, row_questions
    max) for each role its area allows; a question's roles are allowed by every row it covers; its cis_refs are
    safeguards of those rows; a row with folded subcategories has its question cite a suggested action of each.
    Foundation bank: the subcategory is a foundation one; it has question_rules.json foundation_questions min to max
    questions (plus producer_only_extra for producers), at least one consumer and one producer question without
    producer details, and no cis_refs. Both: real suggested action numbers, distinct question texts, and a question
    needing producer details has roles ["producer"] only. Whether a question reveals practice is the evaluator's job.
    A subcategory a person decided in the review sheet is not overwritten unless --replace-human."""
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object keyed by subcategory id"]
    errors = []
    for sid, entry in data.items():
        if bank == "areas" and sid not in ctx["rows"]:
            errors.append(f"{sid}: not a subcategory with mapping rows (foundation subcategories go in the foundation bank)")
            continue
        if bank == "foundation" and sid not in ctx["foundation"]:
            errors.append(f"{sid}: not a foundation subcategory")
            continue
        if not isinstance(entry, dict) or entry.get("status") not in ("pass", "needs_human_review"):
            errors.append(f"{sid}: status must be 'pass' or 'needs_human_review'")
            continue
        if entry.get("turns") not in (1, 2):
            errors.append(f"{sid}: turns must be 1 or 2")
        if entry["status"] == "needs_human_review" and not str(entry.get("reason", "")).strip():
            errors.append(f"{sid}: needs_human_review requires the evaluator's reason")
        qs = entry.get("questions")
        if not isinstance(qs, list) or not qs:
            errors.append(f"{sid}: questions must be a non-empty list")
            continue
        problems = [e for n, q in enumerate(qs, 1) for e in check_question(f"{sid}#{n}", sid, q, bank, inp, ctx)]
        texts = [str(q.get("question_text", "")).strip().lower() for q in qs if isinstance(q, dict)]
        if len(set(texts)) != len(texts):
            problems.append(f"{sid}: the same question_text twice")
        errors += problems
        if problems:
            continue
        if bank == "areas":
            for rid, row in ctx["rows"][sid].items():
                for role in row["roles"]:
                    n = sum(1 for q in qs if rid in q["rows"] and role in q["roles"])
                    if not 1 <= n <= ctx["row_max"]:
                        errors.append(f"{sid}: row {rid} is asked {n} times for role {role} (1 to {ctx['row_max']})")
                for f in row["folded"]:
                    if not any(rid in q["rows"] and any(str(r).startswith(f + " ") for r in q["playbook_refs"])
                               for q in qs):
                        errors.append(f"{sid}: row {rid} folds {f}; one of its questions must cite a suggested action "
                                      f"of {f}")
        else:
            fc = ctx["foundation_count"]
            lo, hi, extra = fc["min"], fc["max"], fc["producer_only_extra"]
            shared = sum(1 for q in qs if q["roles"] != ["producer"])
            if not lo <= len(qs) <= hi + extra or shared > hi:
                errors.append(f"{sid}: {len(qs)} questions ({shared} not producer-only); a foundation subcategory has "
                              f"{lo} to {hi}, plus up to {extra} asked of producers only")
            for role in ("consumer", "producer"):
                if not any(role in q["roles"] and not q["producer_flags"] for q in qs):
                    errors.append(f"{sid}: no {role} question without producer flags (every {role} is scored on it)")
    return errors


EVIDENCE_MAX_CHARS = 400


def evidence_targets(bank: str) -> dict[tuple[str, int], dict]:
    """{(subcategory, question number 1-based): question} for the bank's questions with no evidence_prompt yet."""
    doc = load_json(AI_BANKS / f"question_bank_ai_rmf_{bank}.json", f"{bank} bank")
    return {(sid, n): q for sid, e in doc["subcategories"].items() for n, q in enumerate(e["questions"], 1)
            if not q.get("evidence_prompt")}


def validate_evidence(data, review, bank: str) -> list[str]:
    """The evidence writer's file {subcategory: {"<question number>": "evidence prompt"}}, only for questions with no
    evidence_prompt yet, and the evidence evaluator's verdicts [{subcategory_id, question_number, verdict, reason}], one
    per written prompt."""
    if not isinstance(data, dict) or not data:
        return ["the file must be a non-empty JSON object {subcategory: {question number: evidence prompt}}"]
    targets, errors, written = evidence_targets(bank), [], set()
    for sid, per in data.items():
        if not isinstance(per, dict) or not per:
            errors.append(f"{sid}: must map question numbers to evidence prompts")
            continue
        for n, text in per.items():
            key = (sid, int(n)) if str(n).isdigit() else None
            if key not in targets:
                errors.append(f"{sid} question {n}: not a {bank} bank question without an evidence prompt")
            elif not isinstance(text, str) or not MIN_QUESTION_CHARS <= len(text.strip()) <= EVIDENCE_MAX_CHARS:
                errors.append(f"{sid} question {n}: evidence prompt must be {MIN_QUESTION_CHARS} to "
                              f"{EVIDENCE_MAX_CHARS} characters")
            else:
                written.add(key)
    if not isinstance(review, list):
        return errors + ["--review must be the evaluator's JSON list of verdicts"]
    got = []
    for v in review:
        key = (v.get("subcategory_id"), v.get("question_number")) if isinstance(v, dict) else None
        got.append(key)
        if key not in written:
            errors.append(f"verdict {v!r}: not an evidence prompt in this file")
        elif v.get("verdict") not in ("pass", "fail") or (v["verdict"] == "fail" and not str(v.get("reason", "")).strip()):
            errors.append(f"verdict {key}: must be pass or fail, and a fail needs a reason")
    if sorted(written) != sorted(k for k in got if k in written) or len(got) != len(set(got)):
        errors.append(f"the review needs exactly one verdict per written evidence prompt "
                      f"(missing {sorted(written - set(got))})")
    return errors


def human_decided(data, args) -> list[str]:
    """A subcategory a person decided in the review sheet is not overwritten by agent output unless --replace-human."""
    path = AI_BANKS / f"question_bank_ai_rmf_{args.bank}.json"
    if not isinstance(data, dict) or not path.is_file() or getattr(args, "replace_human", False):
        return []
    bank = load_json(path, path.name)["subcategories"]
    return [f"{sid}: decided by a person in the review sheet; leave it out of the batch, or pass --replace-human if the "
            "person agreed to regenerate it" for sid in data if bank.get(sid, {}).get("decided_by") == "human"]


def split_reason(reason: str) -> dict[int, str]:
    """{question number: reason} from a stored review_reason (0 = the whole subcategory); {} if it has no Q<n> parts."""
    cuts = list(REASON_PART.finditer(reason or ""))
    parts: dict[int, str] = {}
    for m, nxt in zip(cuts, cuts[1:] + [None]):
        text = reason[m.end():nxt.start() if nxt else None].strip()
        parts[int(m.group(1))] = "; ".join(filter(None, [parts.get(int(m.group(1))), text]))
    return parts


def join_reason(parts: dict[int, str]) -> str:
    return "; ".join(f"Q{n}: {t}" for n, t in sorted(parts.items()))[:500]


def review_view(bank: str, entry: dict, sid: str, ctx: dict) -> dict:
    """The entry as the review sheet shows it: an area entry whose mapping rows changed since its questions were written
    is flagged for the whole subcategory (STALE) until a person sets it pass."""
    if bank != "areas" or sid not in ctx["rows"] or entry.get("rows_sha") == rows_record(ctx, sid)["rows_sha"]:
        return entry
    parts = split_reason(entry.get("review_reason", "")) if entry["status"] != "pass" else {}
    return dict(entry, status="needs_human_review", review_reason=join_reason({**parts, 0: STALE}))


def line_review(entry: dict, n: int) -> tuple[str, str]:
    """(status, reason) of question n's sheet line: only its own failure and any whole-subcategory one. A reason
    without Q<n> parts (written by hand) flags every line."""
    if entry["status"] == "pass":
        return "pass", ""
    reason = entry.get("review_reason", "")
    parts = split_reason(reason)
    if not parts:
        return "needs_human_review", reason
    own = "\n".join(filter(None, [parts.get(n), WHOLE + parts[0] if 0 in parts else ""]))
    return ("needs_human_review" if own else "pass"), own


def reason_from_lines(lines: list[dict]) -> dict[int, str]:
    """The inverse of line_review over a subcategory's lines as they are now (renumbered by position)."""
    parts: dict[int, str] = {}
    for n, ln in enumerate(lines, 1):
        if ln["status"] != "needs_human_review":
            continue
        own, _, whole = str(ln.get("review_reason") or "").partition(WHOLE)
        if whole.strip():
            parts[0] = whole.strip()
        if own.strip() or not whole.strip():
            parts[n] = own.strip() or "flagged in the review sheet"
    return parts


def question_sheet_rows(bank: str, doc: dict, inp: dict) -> list[dict]:
    """One review-sheet line per question of the bank (sheet_io.py export area_questions / foundation_questions)."""
    names = {a["id"]: a["name"] for a in load_json(AI_AREAS, "ai_areas.json")["ai_areas"]}
    ctx = question_context(inp)
    lines = []
    for sid, entry in doc["subcategories"].items():
        entry = review_view(bank, entry, sid, ctx)
        for n, q in enumerate(entry["questions"], 1):
            areas = [r.split("|")[0] for r in q.get("rows", [])]
            status, reason = line_review(entry, n)
            lines.append({
                "subcategory": sid, "outcome": inp["subs"][sid]["outcome"], "q": str(n), "areas": areas,
                "area_names": "; ".join(names.get(a, a) for a in areas), "roles": q["roles"],
                "producer_flags": q["producer_flags"], "question_text": q["question_text"],
                "playbook_refs": q["playbook_refs"], "cis_refs": q["cis_refs"],
                "evidence_prompt": q.get("evidence_prompt", ""), "status": status,
                "review_reason": reason, "decided_by": entry.get("decided_by", "agent")})
    return lines


def questions_from_sheet(bank: str, lines: list[dict], doc: dict, inp: dict) -> tuple[dict, list[str], int]:
    """(new bank, problems, subcategories changed) from the review sheet. The whole bank is checked with
    validate_questions; a subcategory whose questions, status or flagged questions differ from the bank is stored as
    decided_by human. Each line carries its own status; the subcategory is needs_human_review while any line is. An area
    subcategory whose mapping rows changed (review_view) is stored against the rows as they are now once every line is
    set pass.
    Subcategories come from generation: the sheet may not add one or drop one."""
    by_sub: dict[str, list[dict]] = {}
    problems = []
    for n, ln in enumerate(lines, 2):
        if ln["subcategory"] not in doc["subcategories"]:
            problems.append(f"row {n}: {ln['subcategory']} is not in the {bank} bank (new subcategories come from "
                            "/build-ai-bank)")
            continue
        by_sub.setdefault(ln["subcategory"], []).append(ln)
    dropped = [sid for sid in doc["subcategories"] if sid not in by_sub]
    if dropped:
        problems.append(f"every subcategory keeps at least one question; no lines left for {', '.join(dropped)}")
    if problems:
        return doc, problems, 0
    ctx = question_context(inp)
    data, changed = {}, []
    for sid, sub_lines in by_sub.items():
        old = review_view(bank, doc["subcategories"][sid], sid, ctx)
        old_evidence = {q["question_text"]: q["evidence_prompt"] for q in old["questions"] if q.get("evidence_prompt")}
        qs = []
        for ln in sub_lines:
            q = {"question_text": ln["question_text"], "playbook_refs": ln["playbook_refs"], "cis_refs": ln["cis_refs"],
                 "roles": ln["roles"], "producer_flags": ln["producer_flags"]}
            if bank == "areas":
                q["rows"] = [row_id(a, sid) for a in ln["areas"]]
            evidence = str(ln.get("evidence_prompt") or "").strip() or old_evidence.get(ln["question_text"])
            if evidence:   # a blank cell keeps what the bank has for the same question
                q["evidence_prompt"] = evidence
            qs.append(q)
        parts = reason_from_lines(sub_lines)
        status = "needs_human_review" if parts else "pass"
        data[sid] = {"status": status, "turns": old["turns"], "questions": qs,
                     **({"reason": join_reason(parts)} if parts else {})}
        old_parts = split_reason(old.get("review_reason", "")) if old["status"] != "pass" else {}
        if qs != old["questions"] or status != old["status"] or (old_parts and parts != old_parts):
            changed.append(sid)
    problems = validate_questions(data, bank, inp, ctx)
    if problems:
        return doc, problems, 0
    new = json.loads(json.dumps(doc))
    for sid in changed:
        e = new["subcategories"][sid]
        e.update({"status": data[sid]["status"], "questions": data[sid]["questions"], "decided_by": "human"})
        if data[sid]["status"] == "pass":
            e.pop("review_reason", None)
            if bank == "areas":
                e.update(rows_record(ctx, sid))
        else:
            e["review_reason"] = data[sid]["reason"]
    passed = sum(1 for e in new["subcategories"].values() if e["status"] == "pass")
    new["summary"] = {"subcategories": len(new["subcategories"]), "passed": passed,
                      "needs_human_review": len(new["subcategories"]) - passed,
                      "questions": sum(len(e["questions"]) for e in new["subcategories"].values())}
    return new, [], len(changed)


def words_match(quote, text: str) -> bool:
    """True if quote is the start of text (at least three words, ignoring case and punctuation)."""
    norm = lambda s: re.findall(r"[a-z0-9]+", str(s).lower())   # noqa: E731
    q = norm(quote or "")
    return len(q) >= 3 and norm(text)[:len(q)] == q


QUESTION_CHECKS = [str(n) for n in range(1, 10)]   # prompts/ai_rmf_question_evaluator.md, checks 1-9
TURN_TWO_RECHECKS = {"6", "7"}   # an unchanged question that passed turn 1 may newly fail only these (a rewrite clashes)


def verdict_failures(gen: dict, verdicts, name: str) -> dict[tuple[str, int], list[tuple[str, str]]]:
    """{(subcategory, question number): [(check, reason), ...]} of the failures in an evaluator verdict file, which must
    hold a verdict on every check for every question of `gen`, quoting the start of that question and of no other
    (`starts_with`), and a
    `complete` verdict per subcategory (number 0)."""
    if not isinstance(verdicts, list):
        sys.exit(f"[record_ai_bank] ERROR: {name} must be a JSON list of verdicts")
    want = {(sid, n) for sid, v in gen.items() for n in range(len(v["questions"]) + 1)}
    got, problems = {}, []
    for v in verdicts:
        key = (v.get("subcategory_id"), v.get("question_number")) if isinstance(v, dict) else None
        if key not in want or key in got:
            problems.append(f"unexpected or repeated verdict {key}")
            continue
        keys = ["complete"] if key[1] == 0 else QUESTION_CHECKS
        checks, reasons = v.get("checks"), v.get("reasons") or {}
        starts = [n for n, q in enumerate(gen[key[0]]["questions"], 1)
                  if words_match(v.get("starts_with"), q["question_text"])]
        if key[1] and starts != [key[1]]:
            problems.append(f"{key}: starts_with {v.get('starts_with')!r} must be the start of question {key[1]} and of no "
                            f"other (matches {starts})")
            continue
        if not isinstance(checks, dict) or sorted(checks) != sorted(keys) or \
                not set(checks.values()) <= {"pass", "fail", "n/a"}:
            problems.append(f"{key}: checks must be exactly {keys}, each pass, fail or n/a")
            continue
        fails = [c for c in keys if checks[c] == "fail"]
        if not all(str(reasons.get(c, "")).strip() for c in fails):
            problems.append(f"{key}: every failed check needs a reason")
            continue
        got[key] = [(c, str(reasons[c]).strip()) for c in fails]
    problems += [f"no verdict for {k}" for k in sorted(want - set(got), key=str)]
    if problems:
        sys.exit(f"[record_ai_bank] ERROR: {name}:\n  - " + "\n  - ".join(problems))
    return {k: f for k, f in got.items() if f}


def assemble(gen1: Path, eval1: Path, gen2: Path | None, eval2: Path | None, out: Path) -> str:
    """The file `questions` records, from generator output and evaluator verdicts. No judgement: a subcategory
    passes iff the last evaluation fails nothing in it.

    An evaluator file must hold a verdict on checks 1-9 for every question and a `complete` verdict per subcategory.
    A second-round file may fail a question that is unchanged and passed round 1 only on checks 6 and 7. A revision
    (gen2) replaces the subcategories it covers."""
    g1 = load_json(gen1, "generator output")
    if not isinstance(g1, dict):
        sys.exit("[record_ai_bank] ERROR: generator output has the wrong JSON type")
    if bool(gen2) != bool(eval2):
        sys.exit("[record_ai_bank] ERROR: --gen2 and --eval2 go together")
    f1 = verdict_failures(g1, load_json(eval1, "evaluator verdicts"), "turn 1 verdicts")
    final, last_fail, turns = {sid: v["questions"] for sid, v in g1.items()}, f1, {sid: 1 for sid in g1}
    if gen2:
        g2 = load_json(gen2, "revision output")
        if not isinstance(g2, dict) or set(g2) - set(final):
            sys.exit("[record_ai_bank] ERROR: revision output must be an object of turn 1 subcategories")
        f2 = verdict_failures(g2, load_json(eval2, "second evaluation"), "turn 2 verdicts")
        flipped = [f"{sid} Q{n} check {c}" for (sid, n), fails in f2.items() if n
                   and g2[sid]["questions"][n - 1] in g1[sid]["questions"]
                   and (sid, g1[sid]["questions"].index(g2[sid]["questions"][n - 1]) + 1) not in f1
                   for c, _ in fails if c not in TURN_TWO_RECHECKS]
        if flipped:
            sys.exit("[record_ai_bank] ERROR: turn 2 verdicts fail questions that are unchanged and passed turn 1 (only "
                     f"checks {sorted(TURN_TWO_RECHECKS)} may change): {', '.join(flipped)}")
        for sid, v in g2.items():
            final[sid], turns[sid] = v["questions"], 2
        last_fail = {k: f for k, f in f1.items() if k[0] not in g2} | f2
    failing: dict[str, list[str]] = {}
    for (sid, n), fails in sorted(last_fail.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        failing.setdefault(sid, []).append(
            f"Q{n}: " + "; ".join(r if c == "complete" else f"check {c}: {r}" for c, r in fails))
    result = {}
    for sid in final:
        entry = {"status": "needs_human_review" if sid in failing else "pass", "turns": turns[sid], "questions": final[sid]}
        if sid in failing:
            entry["reason"] = "; ".join(failing[sid])[:500]
        result[sid] = entry
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return f"{len(result)} subcategories: {len(result) - len(failing)} pass, {len(failing)} need human review → {out.name}"


def store_questions(data: dict, args, inp: dict) -> tuple[Path, str]:
    """Store checked questions in their bank (entries replaced per subcategory); returns (path, summary)."""
    today = date.today().isoformat()
    path = AI_BANKS / f"question_bank_ai_rmf_{args.bank}.json"
    AI_BANKS.mkdir(parents=True, exist_ok=True)
    bank = load_json(path, path.name) if path.is_file() else {"bank": args.bank, "subcategories": {}}
    ctx = question_context(inp)
    for sid, entry in data.items():
        bank["subcategories"][sid] = {
            "status": entry["status"], "turns": entry["turns"],
            **({"review_reason": entry["reason"]} if entry.get("reason") else {}),
            **(rows_record(ctx, sid) if args.bank == "areas" else {}),
            "questions": entry["questions"]}
    bank["subcategories"] = {sid: bank["subcategories"][sid] for sid in inp["subs"] if sid in bank["subcategories"]}
    bank.update({"description": BANK_DESCRIPTION[args.bank], "built_on": today,
                 "playbook_sha256_16": inp["core"]["source_sha256_16"],
                 "guide_sha256_16": {g: s["sha256_16"] for g, s in inp["sg_doc"]["sources"].items()}})
    passed = sum(1 for e in bank["subcategories"].values() if e["status"] == "pass")
    review = len(bank["subcategories"]) - passed
    bank["summary"] = {"subcategories": len(bank["subcategories"]), "passed": passed, "needs_human_review": review,
                       "questions": sum(len(e["questions"]) for e in bank["subcategories"].values())}
    path.write_text(json.dumps(bank, indent=2, ensure_ascii=False))
    return path, (f"{args.bank} bank: recorded {len(data)} subcategories; bank has {passed} passed, {review} needing "
                  f"human review, {bank['summary']['questions']} questions")


def store_evidence(data: dict, args, inp: dict) -> tuple[Path, str]:
    """Store the evidence lines the evaluator passed in their bank; returns (path, summary)."""
    review = load_json(Path(args.review), "review file")
    failed = {(v["subcategory_id"], v["question_number"]) for v in review if v["verdict"] == "fail"}
    path = AI_BANKS / f"question_bank_ai_rmf_{args.bank}.json"
    bank = load_json(path, path.name)
    stored = 0
    for sid, per in data.items():
        for n, text in per.items():
            if (sid, int(n)) not in failed:   # a failed prompt is not stored: the generic line stays for it
                bank["subcategories"][sid]["questions"][int(n) - 1]["evidence_prompt"] = text.strip()
                stored += 1
    path.write_text(json.dumps(bank, indent=2, ensure_ascii=False))
    left = len(evidence_targets(args.bank))
    return path, (f"{args.bank} bank: {stored} evidence prompts stored, {len(failed)} failed the check (not "
                  f"stored); {left} questions still without one. Refresh the review sheet (sheet_io.py export).")
