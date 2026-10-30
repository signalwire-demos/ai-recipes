"""Aggregate turn timings per configuration into a stable Markdown comparison table."""
import json
from pathlib import Path

from lab.timings import SEGMENTS, config_of, parse_turns

LABELS = {
    "mouth_to_ear_ms": "Mouth-to-ear",
    "turn_detection_ms": "Turn detection",
    "tools_other_ms": "Tools / other",
    "model_ms": "Model",
    "assembly_ms": "Utterance assembly",
    "tts_ms": "Audio (TTS)",
}


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile: deterministic, and always a value that was measured."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceil(n * pct / 100)
    return ordered[int(rank) - 1]


def load_runs(runs_dir: Path) -> dict[str, list[dict]]:
    """{config: [payload, ...]}, read from runs/<config>/<call_id>.json in sorted order."""
    runs: dict[str, list[dict]] = {}
    for path in sorted(Path(runs_dir).glob("*/*.json")):
        payload = json.loads(path.read_text())
        runs.setdefault(config_of(payload) or path.parent.name, []).append(payload)
    return runs


def summarize(runs: dict[str, list[dict]], order: list[str] | None = None) -> list[dict]:
    rows = []
    for name in (order or []) + sorted(set(runs) - set(order or [])):
        if name not in runs:
            continue
        turns, omitted = [], 0
        for payload in runs[name]:
            t, o = parse_turns(payload)
            turns += t
            omitted += o
        row = {"config": name, "calls": len(runs[name]), "turns": len(turns), "omitted": omitted}
        for seg in SEGMENTS:
            vals = [t[seg] for t in turns if t[seg] is not None]
            row[seg] = (percentile(vals, 50), percentile(vals, 95))
        rows.append(row)
    return rows


def _ms(v):
    return "n/a" if v is None else f"{v:.0f}"


def render(rows: list[dict], matrix: dict[str, dict] | None = None, attempted: dict[str, int] | None = None) -> str:
    """Markdown table. Same input -> byte-identical output (no timestamps, fixed order).

    attempted: calls placed per config this run. A config whose calls produced no payload
    still gets a row, so a failing configuration is visible instead of silently missing.
    """
    matrix, attempted = matrix or {}, attempted or {}
    seen = {r["config"] for r in rows}
    rows = rows + [{"config": n, "calls": 0, "turns": 0, "omitted": 0, **{s: (None, None) for s in SEGMENTS}}
                   for n in attempted if n not in seen]
    head = ["Config", "Model", "Voice", "Calls", "Turns"] + [f"{LABELS[s]} p50 / p95 (ms)" for s in SEGMENTS]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cfg = matrix.get(r["config"], {})
        cells = [r["config"], cfg.get("model", "?"), cfg.get("voice", "?"), str(r["calls"]) + (f" of {attempted[r['config']]}" if r["config"] in attempted else ""),
                 f"{r['turns']}" + (f" ({r['omitted']} untimed)" if r["omitted"] else "")]
        cells += [f"{_ms(r[s][0])} / {_ms(r[s][1])}" for s in SEGMENTS]
        lines.append("| " + " | ".join(cells) + " |")
    notes = [f"- {r['config']}: {matrix[r['config']]['known_issue']}" for r in rows
             if matrix.get(r["config"], {}).get("known_issue")]
    if notes:
        lines += ["", "Known issues:"] + notes
    return "\n".join(lines) + "\n"
