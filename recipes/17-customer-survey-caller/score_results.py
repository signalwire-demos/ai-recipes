#!/usr/bin/env python3
"""Score the survey: NPS-style report from data/results.jsonl.

  python score_results.py                       # reads config.RESULTS_FILE
  python score_results.py path/to/results.jsonl
  python score_results.py --json                # machine-readable

One respondent = one call_id. If a question was answered twice on a call, the last
answer counts. Scoring rule (config.py): ratings >= PROMOTER_MIN are promoters,
<= DETRACTOR_MAX are detractors, NPS = %promoters - %detractors.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import config


def load_respondents(path: Path) -> dict:
    respondents: dict = {}
    if not path.exists():
        return respondents
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            respondents.setdefault(row["call_id"], {})[row["question_id"]] = row["answer"]
    return respondents


def score(respondents: dict) -> dict:
    required = [q["id"] for q in config.QUESTIONS if q.get("required", True)]
    ratings = [a[config.NPS_QUESTION] for a in respondents.values() if config.NPS_QUESTION in a]
    promoters = sum(r >= config.PROMOTER_MIN for r in ratings)
    detractors = sum(r <= config.DETRACTOR_MAX for r in ratings)
    report = {
        "respondents": len(respondents),
        "complete": sum(all(k in a for k in required) for a in respondents.values()),
        "nps": {
            "rated": len(ratings),
            "promoters": promoters,
            "passives": len(ratings) - promoters - detractors,
            "detractors": detractors,
            "score": round(100 * (promoters - detractors) / len(ratings)) if ratings else None,
        },
        "questions": {},
    }
    for q in config.QUESTIONS:
        answers = [a[q["id"]] for a in respondents.values() if q["id"] in a]
        if q["type"] in ("multiple_choice", "yes_no"):
            report["questions"][q["id"]] = dict(Counter(answers).most_common())
        elif q["type"] == "rating":
            report["questions"][q["id"]] = {"average": round(sum(answers) / len(answers), 1) if answers else None}
        else:
            report["questions"][q["id"]] = [a for a in answers if a]
    return report


def render(report: dict) -> str:
    n = report["nps"]
    lines = [f"{config.SURVEY_NAME}: {report['respondents']} respondents, {report['complete']} complete",
             f"NPS {n['score'] if n['score'] is not None else 'n/a'} "
             f"({n['promoters']} promoters, {n['passives']} passives, {n['detractors']} detractors)"]
    for qid, value in report["questions"].items():
        if isinstance(value, list):
            lines.append(f"{qid}: {len(value)} comments")
            lines += [f"  - {c}" for c in value]
        else:
            lines.append(f"{qid}: {value}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", nargs="?", default=str(config.RESULTS_FILE))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = score(load_respondents(Path(args.path)))
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
