#!/usr/bin/env python3
"""Place one scripted live call into a recipe and report what happened.

Run it inside the live-call slot, from the repo root with the root .venv:

  scripts/live_slot.sh _template -- .venv/bin/python scripts/smoke_call.py recipes/_template \
      --start --say "Are you open on Thursday?" --say "No, that's everything. Goodbye."

What it does:
  1. Loads credentials from the repo-root .env and the recipe's .env (recipe wins for
     SWML_BASIC_AUTH_*, PUBLIC_URL and PORT). Secrets are never printed.
  2. --start: launches the recipe (`<recipe>/.venv/bin/python app.py`, else this python) on
     PORT with output to <recipe>/logs/smoke-<ts>.log, and stops it afterwards.
  3. Points the TEST_INBOUND number's call handler at https://USER:PASS@<PUBLIC_URL host><route>.
  4. REST-dials TEST_CALLER -> TEST_INBOUND. The caller leg runs an inline SWML script that
     waits, speaks each --say line with a pause after it, then hangs up.
  5. Waits for the call to end and prints call SID, status, duration and whether the
     recipe's SWML was fetched (POST <route> lines in the app log during the call).

Modes for recipes without an app.py (SWML-only recipes such as #6):
  --serve-swml FILE  serves FILE (YAML or JSON, sent as JSON) on PORT at --route behind basic
                     auth, logs each request to <recipe>/logs/smoke-<ts>.log and points
                     TEST_INBOUND at it. Same report as --start.
  --url URL          points TEST_INBOUND at URL as given (no basic auth added), e.g. a SWML
                     script you host elsewhere. Add --log to check the fetch.
  app.py is only required with --start.

--dry-run prints the plan and the caller SWML without changing the number or dialing.
Exit code: 0 if the call completed and the SWML was fetched, 1 otherwise.
"""
import argparse
import base64
import http.server
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "ended", "failed", "busy", "no-answer", "canceled"}


def read_env(path: Path) -> dict:
    out = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            value = m[2].strip().strip("'\"") if m else ""
            if value and not line.lstrip().startswith("#"):  # KEY= must not mask the root .env
                out[m[1]] = value
    return out


def caller_swml(lines, first_wait, pause, tail):
    main = [{"play": {"url": f"silence:{first_wait}"}}]
    for text in lines:
        main += [{"play": {"url": f"say:{text}"}}, {"play": {"url": f"silence:{pause}"}}]
    main += [{"play": {"url": f"silence:{tail}"}}, {"hangup": {}}]
    return {"version": "1.0.0", "sections": {"main": main}}


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_app(recipe: Path, env: dict, port: int, log_path: Path) -> subprocess.Popen:
    if port_open(port):
        sys.exit(f"smoke_call: port {port} is already in use; run inside scripts/live_slot.sh")
    py = recipe / ".venv" / "bin" / "python"
    py = str(py) if py.exists() else sys.executable
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([py, "app.py"], cwd=recipe, env=env,
                            stdout=log_path.open("w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        if proc.poll() is not None:
            sys.exit(f"smoke_call: app exited early (code {proc.returncode}); see {log_path}")
        if port_open(port):
            return proc
        time.sleep(0.5)
    proc.terminate()
    sys.exit(f"smoke_call: app did not open port {port} within 30s; see {log_path}")


def serve_swml(swml_file: Path, route: str, user: str, password: str, port: int,
               log_path: Path) -> http.server.ThreadingHTTPServer:
    """Serve one static SWML document the way an app would, with an access log smoke_call can scan."""
    if port_open(port):
        sys.exit(f"smoke_call: port {port} is already in use; run inside scripts/live_slot.sh")
    text = swml_file.read_text()
    if swml_file.suffix in {".yaml", ".yml"}:
        import yaml
        doc = yaml.safe_load(text)
    else:
        doc = json.loads(text)
    body = json.dumps(doc).encode()
    want = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("w", buffering=1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if self.headers.get("Authorization") != want:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="smoke"')
                self.end_headers()
            elif self.path.split("?")[0] != route.split("?")[0]:
                self.send_error(404)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        do_GET = do_POST = _reply

        def log_message(self, fmt, *a):
            log_fh.write(f"{self.address_string()} - [{self.log_date_time_string()}] {fmt % a}\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def number_id(client, e164: str) -> str:
    for n in client.phone_numbers.list(filter_number=e164).get("data", []):
        if n.get("number") == e164:
            return n["id"]
    sys.exit(f"smoke_call: {e164} is not on this project")


def call_status(client, call_id, frm, to, since):
    try:
        log = client.logs.voice.get(call_id)
        if log and log.get("status"):
            return log
    except Exception:
        pass
    try:  # fall back: newest log for this from/to pair created after we dialed
        for log in client.logs.voice.list().get("data", []):
            if log.get("id") == call_id:
                return log
            if log.get("from") == frm and log.get("to") == to and log.get("created_at", "") >= since:
                return log
    except Exception:
        pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe", type=Path)
    ap.add_argument("--say", action="append", default=[], help="a line the caller speaks (repeatable)")
    ap.add_argument("--first-wait", type=int, default=6, help="seconds before the first line (agent greets)")
    ap.add_argument("--pause", type=int, default=8, help="seconds of silence after each line")
    ap.add_argument("--tail", type=int, default=4, help="seconds of silence before hanging up")
    ap.add_argument("--route", default="/", help="agent route on the app (default /)")
    ap.add_argument("--start", action="store_true", help="start the recipe app for the call")
    ap.add_argument("--log", type=Path, help="app log to scan when not using --start")
    ap.add_argument("--serve-swml", type=Path, metavar="FILE",
                    help="SWML-only recipe: serve FILE on PORT at --route instead of running app.py")
    ap.add_argument("--url", help="point TEST_INBOUND at this URL as given (no app, no basic auth added)")
    ap.add_argument("--max-wait", type=int, default=300, help="seconds to wait for the call to end")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    recipe = args.recipe.resolve()
    if sum(map(bool, (args.start, args.serve_swml, args.url))) > 1:
        sys.exit("smoke_call: use only one of --start, --serve-swml, --url")
    if args.start and not (recipe / "app.py").is_file():
        sys.exit(f"smoke_call: {recipe}/app.py not found (SWML-only recipe? use --serve-swml or --url)")
    if args.serve_swml:
        args.serve_swml = (args.serve_swml if args.serve_swml.is_absolute() else Path.cwd() / args.serve_swml)
        if not args.serve_swml.is_file():
            sys.exit(f"smoke_call: {args.serve_swml} not found")

    # Worktrees have no .env of their own: fall back to the main checkout's (or RECIPES_ENV_FILE).
    root_env = Path(os.environ.get("RECIPES_ENV_FILE", ROOT / ".env"))
    if not root_env.is_file():
        root_env = Path.home() / "workdir/demos/.env"
    env = {**os.environ, **read_env(root_env), **read_env(recipe / ".env")}
    env.setdefault("PUBLIC_URL", "https://briankwest.ngrok.io")
    env.setdefault("PORT", "3000")
    for key in ("SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_API_TOKEN", "SIGNALWIRE_SPACE", "TEST_INBOUND", "TEST_CALLER"):
        if not env.get(key):
            sys.exit(f"smoke_call: {key} is not set (repo-root .env or recipe .env)")
    if not args.url and not (env.get("SWML_BASIC_AUTH_USER") and env.get("SWML_BASIC_AUTH_PASSWORD")):
        if not (args.start or args.serve_swml):
            sys.exit("smoke_call: set SWML_BASIC_AUTH_USER/PASSWORD in the recipe .env (or use --start)")
        env["SWML_BASIC_AUTH_USER"] = "smoke"
        env["SWML_BASIC_AUTH_PASSWORD"] = secrets.token_urlsafe(18)
    env["SWML_PROXY_URL_BASE"] = env["PUBLIC_URL"].rstrip("/")

    if args.url:
        handler_url = args.url
        u = urlparse(args.url)
        shown_url = u._replace(netloc=f"{u.username}:***@{u.hostname}" if u.password else u.netloc).geturl()
    else:
        host = urlparse(env["PUBLIC_URL"]).netloc
        auth = f"{quote(env['SWML_BASIC_AUTH_USER'], safe='')}:{quote(env['SWML_BASIC_AUTH_PASSWORD'], safe='')}"
        handler_url = f"https://{auth}@{host}{args.route}"
        shown_url = f"https://{env['SWML_BASIC_AUTH_USER']}:***@{host}{args.route}"
    swml = caller_swml(args.say or ["Hello, this is a test call."], args.first_wait, args.pause, args.tail)

    print(f"recipe:   {recipe.relative_to(ROOT) if recipe.is_relative_to(ROOT) else recipe}")
    print(f"handler:  TEST_INBOUND {env['TEST_INBOUND']} -> {shown_url}")
    if args.serve_swml:
        print(f"serving:  {args.serve_swml} on :{env['PORT']}{args.route}")
    print(f"caller:   TEST_CALLER {env['TEST_CALLER']} speaks {len(args.say) or 1} line(s)")
    if args.dry_run:
        print(json.dumps(swml, indent=2))
        return 0

    from signalwire.rest import RestClient
    client = RestClient(project=env["SIGNALWIRE_PROJECT_ID"], token=env["SIGNALWIRE_API_TOKEN"],
                        host=env["SIGNALWIRE_SPACE"])

    proc, server, log_path = None, None, args.log
    if args.start:
        log_path = recipe / "logs" / f"smoke-{time.strftime('%Y%m%d-%H%M%S')}.log"
        proc = start_app(recipe, env, int(env["PORT"]), log_path)
    elif args.serve_swml:
        log_path = recipe / "logs" / f"smoke-{time.strftime('%Y%m%d-%H%M%S')}.log"
        server = serve_swml(args.serve_swml, args.route, env["SWML_BASIC_AUTH_USER"],
                            env["SWML_BASIC_AUTH_PASSWORD"], int(env["PORT"]), log_path)
    log_offset = log_path.stat().st_size if log_path and log_path.exists() else 0

    try:
        client.phone_numbers.set_swml_webhook(number_id(client, env["TEST_INBOUND"]), handler_url)
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        call = client.calling.dial(from_=env["TEST_CALLER"], to=env["TEST_INBOUND"], swml=swml)
        call_id = call.get("id")
        print(f"call SID: {call_id}")

        status, deadline = {}, time.time() + args.max_wait
        while time.time() < deadline:
            time.sleep(5)
            status = call_status(client, call_id, env["TEST_CALLER"], env["TEST_INBOUND"], since)
            if status.get("status") in TERMINAL:
                break
        time.sleep(2)  # let the app flush its access log
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    fetched = None
    if log_path and log_path.exists():
        with log_path.open() as fh:
            fh.seek(log_offset)
            new = fh.read()
        route = re.escape(args.route)
        fetched = len(re.findall(rf'"POST {route}(\?[^ ]*)? HTTP/1\.[01]" 200', new))
        swaig = len(re.findall(r'"POST [^ ]*swaig[^ ]* HTTP/1\.[01]" 200', new))

    print(f"status:   {status.get('status', 'unknown')}")
    print(f"duration: {status.get('duration', 'unknown')}s")
    if fetched is None:
        print("SWML fetched: unknown (pass --start, --serve-swml or --log <app log>)")
    else:
        print(f"SWML fetched: {'yes' if fetched else 'NO'} ({fetched} POST {args.route}, {swaig} SWAIG calls)")
        print(f"app log:  {log_path}")
    return 0 if status.get("status") in {"completed", "ended"} and fetched else 1


if __name__ == "__main__":
    sys.exit(main())
