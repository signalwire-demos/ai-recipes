"""Aggregate stored win/loss extractions into a markdown report.

  python analyze.py --since 7d                       # SUMMARY_SOURCE from .env (default fixtures)
  python analyze.py --source local --since 24h --out report.md

Every record is re-validated against extraction.SCHEMA here too, so a malformed summary is
listed under "Flagged" and never counted, whatever wrote it.
"""
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
import extraction


def load(source: str) -> list[dict]:
    if source == "signalwire":
        raise SystemExit(
            "SUMMARY_SOURCE=signalwire: TODO(blocked: signalwire-sdk 3.7.5 has no REST endpoint "
            "that returns post-prompt summaries). Use local (what on_summary stored) or fixtures.")
    path = config.FIXTURES_FILE if source == "fixtures" else config.CALLS_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def window(records: list[dict], since: str, now: datetime | None) -> list[dict]:
    """Keep records newer than `since` (e.g. 7d, 24h, all). `now` anchors the window."""
    if since == "all" or not records:
        return records
    m = re.fullmatch(r"(\d+)([dh])", since)
    if not m:
        raise SystemExit(f"--since must look like 7d, 24h or all, not {since!r}")
    span = timedelta(days=int(m[1])) if m[2] == "d" else timedelta(hours=int(m[1]))
    cutoff = (now or datetime.now(timezone.utc)) - span
    return [r for r in records if datetime.fromisoformat(r["received_at"]) >= cutoff]


def split(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """(valid summaries, flagged rows). The stored `valid` flag is not trusted on its own."""
    good, flagged = [], []
    for r in records:
        summary, errors = extraction.parse(r.get("summary") if r.get("valid") else None)
        if errors:
            flagged.append({**r, "errors": r.get("errors") or errors})
        else:
            good.append({**summary, "call_id": r.get("call_id")})
    return good, flagged


def table(header: list[str], rows: list[list]) -> list[str]:
    if not rows:
        return ["None."]
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return out + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]


def ranked(counter: Counter) -> list[list]:
    return [[k, n] for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:config.TOP_N]]


def report(good: list[dict], flagged: list[dict], title: str) -> str:
    outcomes = Counter(s["outcome"] for s in good)
    decided = outcomes["won"] + outcomes["lost"]
    rate = f"{100 * outcomes['won'] / decided:.0f}%" if decided else "n/a"
    lines = [f"# {title}", "",
             f"{len(good)} interviews analyzed, {len(flagged)} flagged. "
             f"Won {outcomes['won']}, lost {outcomes['lost']}, no decision {outcomes['no_decision']}. "
             f"Win rate (won / decided): {rate}.", ""]
    for outcome in ("won", "lost"):
        reasons = Counter(r for s in good if s["outcome"] == outcome for r in s["reasons"])
        lines += [f"## Top reasons we {outcome}", ""] + table(["Reason", "Calls"], ranked(reasons)) + [""]

    vs = {}
    for s in good:
        name = extraction.competitor_name(s["competitor"])
        if name:
            vs.setdefault(name, Counter())[s["outcome"]] += 1
    rows = [[n, c["won"], c["lost"], c["no_decision"]]
            for n, c in sorted(vs.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))]
    lines += ["## Head to head", ""] + table(["Competitor", "Won", "Lost", "No decision"], rows) + [""]

    objections = Counter(o.strip().lower() for s in good for o in s["objections"])
    lines += ["## Most common objections", ""] + table(["Objection", "Calls"], ranked(objections)) + [""]

    lines += ["## Flagged (not counted)", ""]
    lines += [f"- `{f.get('call_id')}`: {f['errors'][0]}" for f in flagged] or ["None."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> str:
    p = argparse.ArgumentParser(description="Win/loss report from stored call extractions.")
    p.add_argument("--source", default=config.SUMMARY_SOURCE, choices=["fixtures", "local", "signalwire"])
    p.add_argument("--since", default="7d", help="7d, 24h, ... or all")
    p.add_argument("--out", help="write the report here instead of stdout")
    args = p.parse_args(argv)

    records = load(args.source)
    # Fixtures are a frozen week of synthetic calls: anchor the window at the newest one.
    now = (max(datetime.fromisoformat(r["received_at"]) for r in records)
           if args.source == "fixtures" and records else None)
    good, flagged = split(window(records, args.since, now))
    text = report(good, flagged, f"Win/loss report ({args.source}, last {args.since})")
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    else:
        print(text, end="")
    return text


if __name__ == "__main__":
    main()
