#!/usr/bin/env bash
# Run a command while holding the single live-call slot (port 3000 + the one ngrok tunnel).
#
#   scripts/live_slot.sh <recipe> [--no-wait] [--wait-max SECONDS] -- <command> [args...]
#
# Example:
#   scripts/live_slot.sh _template -- .venv/bin/python scripts/smoke_call.py recipes/_template \
#       --start --say "Are you open on Thursday?" --say "No, that's all. Bye."
#
# Lock: mkdir $LIVE_LOCK_DIR (default ~/workdir/demos/.live-lock), atomic on every filesystem.
# The holder file records recipe, user, host, pid and timestamps. A heartbeat refreshes it every
# 60 s while the command runs. A lock is stale (and is taken over) when its heartbeat is older
# than 20 minutes, or its holder pid is gone on this host.
#
# Port guard: after taking the lock, if anything is already listening on $LIVE_PORT (default
# 3000), the slot refuses to run and prints what that listener is. Nothing is ever killed.
set -euo pipefail

LOCK_DIR="${LIVE_LOCK_DIR:-$HOME/workdir/demos/.live-lock}"
PORT="${LIVE_PORT:-3000}"
STALE_SECS=$((20 * 60))
POLL_SECS=10

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

recipe="${1:-}"; [[ -z "$recipe" || "$recipe" == --* ]] && usage; shift
wait=1; wait_max=0
while [[ $# -gt 0 && "$1" != "--" ]]; do
  case "$1" in
    --no-wait) wait=0 ;;
    --wait-max) wait_max="$2"; shift ;;
    *) usage ;;
  esac
  shift
done
[[ "${1:-}" == "--" ]] || usage; shift
[[ $# -gt 0 ]] || usage

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
holder_field() { sed -n "s/^$1=//p" "$LOCK_DIR/holder" 2>/dev/null | head -1; }

lock_is_stale() {
  [[ -f "$LOCK_DIR/holder" ]] || { # dir without holder file: only stale if old
    (( $(date +%s) - $(mtime "$LOCK_DIR") > 30 )); return; }
  local age=$(( $(date +%s) - $(mtime "$LOCK_DIR/holder") ))
  (( age > STALE_SECS )) && return 0
  local h p; h="$(holder_field host)"; p="$(holder_field pid)"
  [[ "$h" == "$(hostname)" && -n "$p" ]] && ! kill -0 "$p" 2>/dev/null && return 0
  return 1
}

show_holder() { sed 's/^/    /' "$LOCK_DIR/holder" 2>/dev/null || echo "    (no holder file)"; }

start=$(date +%s)
until mkdir "$LOCK_DIR" 2>/dev/null; do
  if lock_is_stale; then
    echo "live_slot: taking over a stale lock:" >&2; show_holder >&2
    rm -rf "$LOCK_DIR"; continue
  fi
  if (( ! wait )); then echo "live_slot: slot busy:" >&2; show_holder >&2; exit 75; fi
  if (( wait_max > 0 && $(date +%s) - start > wait_max )); then
    echo "live_slot: gave up after ${wait_max}s; slot held by:" >&2; show_holder >&2; exit 75
  fi
  echo "live_slot: waiting for slot (held by $(holder_field recipe), since $(holder_field started))" >&2
  sleep "$POLL_SECS"
done

cleanup() {
  [[ -n "${hb_pid:-}" ]] && kill "$hb_pid" 2>/dev/null || true
  # Only remove the lock if it is still ours.
  [[ "$(holder_field pid)" == "$$" ]] && rm -rf "$LOCK_DIR"
}
trap cleanup EXIT INT TERM

cat > "$LOCK_DIR/holder" <<EOF
recipe=$recipe
user=$(id -un)
host=$(hostname)
pid=$$
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
command=$*
EOF

listener="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true)"
if [[ -n "$listener" ]]; then
  echo "live_slot: refusing to run: something that does not hold the slot is listening on :$PORT" >&2
  echo "$listener" | sed 's/^/    /' >&2
  for pid in $(echo "$listener" | awk '{print $2}' | sort -u); do
    echo "    pid $pid: $(ps -o command= -p "$pid" 2>/dev/null) (cwd: $(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'))" >&2
  done
  echo "live_slot: not killing it. Stop it yourself (if it is yours) and retry." >&2
  exit 69
fi

( while sleep 60; do touch "$LOCK_DIR/holder" 2>/dev/null || exit 0; done ) &
hb_pid=$!

echo "live_slot: slot acquired for $recipe; running: $*" >&2
set +e
"$@"
rc=$?
set -e
echo "live_slot: command exited $rc; releasing slot" >&2
exit $rc
