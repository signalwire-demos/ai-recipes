#!/usr/bin/env python3
"""Run the latency lab: scripted calls per configuration, then a comparison table.

  # live: inside the one live-call slot (it owns :3000 and the tunnel)
  scripts/live_slot.sh 36-voice-latency-lab -- recipes/36-voice-latency-lab/.venv/bin/python \\
      recipes/36-voice-latency-lab/run_lab.py --start --calls 10

  # offline: rebuild the table from saved post-prompt payloads (or test fixtures)
  python run_lab.py --report-only [--runs tests/fixtures/runs]

Each call is placed by the monorepo's scripts/smoke_call.py: it points TEST_INBOUND at
PUBLIC_URL/?config=<name> and REST-dials TEST_CALLER -> TEST_INBOUND with a caller-side
SWML script that speaks config.CALLER_SCRIPT. After the call, the platform POSTs the
post-prompt payload to the app, which saves it under runs/<config>/; lab/ parses it.
"""
import argparse
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import config
from lab.report import load_runs, render, summarize

RECIPE = Path(__file__).resolve().parent
SMOKE = RECIPE.parents[1] / "scripts" / "smoke_call.py"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_app(env: dict, log: Path) -> subprocess.Popen:
    port = int(env["PORT"])
    if port_open(port):
        sys.exit(f"run_lab: port {port} is busy; run inside scripts/live_slot.sh")
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=RECIPE, env=env,
                            stdout=log.open("w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        if port_open(port):
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.terminate()
    sys.exit(f"run_lab: app did not start; see {log}")


def one_call(name: str, env: dict, log: Path) -> str | None:
    before = set((config.RUNS_DIR / name).glob("*.json"))
    cmd = [sys.executable, str(SMOKE), str(RECIPE), "--route", f"/?config={name}", "--log", str(log),
           "--pause", str(config.CALLER_PAUSE_SECS)]
    for line in config.CALLER_SCRIPT:
        cmd += ["--say", line]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sid = (re.search(r"call SID:\s*(\S+)", proc.stdout) or [None, None])[1]
    if not sid:
        print(f"  {name}: no call placed: {(proc.stderr or proc.stdout).strip()[-300:]}", flush=True)
        return None
    deadline = time.time() + config.PAYLOAD_WAIT_SECS
    while time.time() < deadline and not set((config.RUNS_DIR / name).glob("*.json")) - before:
        time.sleep(2)
    got = bool(set((config.RUNS_DIR / name).glob("*.json")) - before)
    print(f"  {name}: call {sid or '?'} -> post-prompt {'saved' if got else 'MISSING'}", flush=True)
    return sid


def write_report(runs_dir: Path, sids: dict[str, list] | None = None) -> str:
    table = render(summarize(load_runs(runs_dir), list(config.CONFIGS)), config.CONFIGS)
    if sids is not None:
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = config.REPORTS_DIR / f"latency-{time.strftime('%Y%m%d-%H%M%S')}.md"
        sid_lines = "".join(f"- {k}: {', '.join(s for s in v if s)}\n" for k, v in sids.items())
        path.write_text(f"# Latency lab run\n\n{table}\nCall SIDs (caller leg):\n{sid_lines}")
        print(f"report: {path}")
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calls", type=int, default=10, help="calls per configuration")
    ap.add_argument("--configs", help="comma-separated subset of config.CONFIGS")
    ap.add_argument("--start", action="store_true", help="start app.py for the run (needs :PORT free)")
    ap.add_argument("--report-only", action="store_true", help="no calls; just build the table")
    ap.add_argument("--runs", type=Path, default=config.RUNS_DIR, help="payload folder for --report-only")
    args = ap.parse_args()

    if args.report_only:
        print(write_report(args.runs), end="")
        return 0

    names = args.configs.split(",") if args.configs else list(config.CONFIGS)
    unknown = [n for n in names if n not in config.CONFIGS]
    if unknown:
        sys.exit(f"run_lab: unknown config(s): {', '.join(unknown)}")
    env = {**os.environ, "PORT": os.environ.get("PORT", "3000")}
    if not env.get("PUBLIC_URL"):
        sys.exit("run_lab: set PUBLIC_URL (the HTTPS tunnel to :PORT)")
    if not (env.get("SWML_BASIC_AUTH_USER") and env.get("SWML_BASIC_AUTH_PASSWORD")):
        env.update(SWML_BASIC_AUTH_USER="lab", SWML_BASIC_AUTH_PASSWORD=secrets.token_urlsafe(18))

    log = RECIPE / "logs" / f"lab-{time.strftime('%Y%m%d-%H%M%S')}.log"
    proc = start_app(env, log) if args.start else None
    sids: dict[str, list] = {n: [] for n in names}
    try:
        for i in range(args.calls):  # interleave configs so time-of-day drift hits all equally
            print(f"round {i + 1}/{args.calls}", flush=True)
            for name in names:
                sids[name].append(one_call(name, env, log))
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
    print(write_report(config.RUNS_DIR, sids), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
