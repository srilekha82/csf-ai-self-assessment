"""
Checks that the question banks a client run uses are there and recent enough. It never builds or rebuilds a bank.

Called by: /generate-questions (step 2)
Input:     the build date in each bank the run uses (the CSF bank of its sector, the two AI RMF banks); the age limits in
           data/metadata.json "question_banks"
Output:    a report on screen; exit 1 when a bank is missing or too old

Usage: .venv/bin/python ./scripts/check_bank_age.py --run runs/<Org>_<date>   (or --domain finance)

It reads only each bank's build date, so it needs no source files and works on a fresh clone. When a bank is missing or
older than its limit, it names the command the maintainer runs to rebuild it (/build-csf-bank, /build-ai-bank).
Checking a bank against its sources is the maintainer's job: check_freshness.py.

Exit 0: every bank is there and within its limit. Exit 1: a bank is missing or too old (listed).
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from options import AI_QUESTION_BANKS, DOMAINS, load_intake  # noqa: E402
from paths import AI_BANKS, DATA_AUDIT, METADATA, bank_path  # noqa: E402
import audit  # noqa: E402


def bank_problems(domain: str, today: date | None = None, limits: dict | None = None,
                  csf_file: Path | None = None, ai_dir: Path | None = None) -> list[str]:
    """One message per bank the run uses that is missing or older than its limit, naming the command to rebuild it.
    An empty list means every bank is fine."""
    today = today or date.today()
    limits = limits or json.loads(METADATA.read_text())["question_banks"]
    ai_dir = ai_dir or AI_BANKS
    banks = [(f"CSF bank {domain}", csf_file or bank_path(domain), limits["csf_max_age_days"], "/build-csf-bank")]
    banks += [(f"AI bank {b}", ai_dir / f"question_bank_ai_rmf_{b}.json", limits["ai_max_age_days"], "/build-ai-bank")
              for b in AI_QUESTION_BANKS]
    problems = []
    for name, path, limit, command in banks:
        built = json.loads(path.read_text()).get("built_on") if path.is_file() else None
        if built is None:
            problems.append(f"{name} is missing: run {command}")
        elif (today - date.fromisoformat(built)).days > limit:
            problems.append(f"{name} is too old (built {built}, limit {limit} days): run {command}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--run", help="the run folder; the sector comes from its intake.json")
    where.add_argument("--domain", choices=DOMAINS, help="the sector, when there is no run folder")
    args = parser.parse_args()
    domain = load_intake(args.run)["domain"] if args.run else args.domain
    ev = audit.begin(audit.run_log(Path(args.run)) if args.run else DATA_AUDIT, "check_bank_age", {"domain": domain})
    problems = bank_problems(domain)
    if problems:
        print("\n".join(problems))
        ev.finish("stale", detail="; ".join(problems))
        sys.exit(1)
    print("All question banks are recent enough.")
    ev.finish(detail="all banks recent enough")


if __name__ == "__main__":
    main()
