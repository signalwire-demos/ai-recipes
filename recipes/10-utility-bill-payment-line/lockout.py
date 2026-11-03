"""Server-side failed-verification counter that survives a redial, and verified-call sessions.

In signalwire-sdk 3.7.5 the per-call tool token is an HMAC over the call_id in the request,
and global_data arrives in the request too, so a failure counter kept in global_data resets
when the caller hangs up and redials, and can be forged. This one lives in the process,
keyed by what identifies the guesser (the account being guessed, the caller ID), across
calls. In-memory and per-process: use Redis or your database once you run more than one worker.
"""
import threading
import time

MAX_KEYS = 10_000  # prune expired entries past this many, so a flood of guesses can't grow memory


class Lockout:
    def __init__(self, max_failures: int, window_secs: float):
        self.max_failures, self.window_secs = max_failures, window_secs
        self._failures: dict[str, tuple[int, float]] = {}  # key -> (count, time of last failure)
        self._lock = threading.Lock()

    def _count(self, key: str, now: float) -> int:
        count, last = self._failures.get(key, (0, 0.0))
        return count if now - last < self.window_secs else 0

    def failures(self, *keys) -> int:
        """The highest live failure count among the keys. Empty keys are ignored."""
        now = time.monotonic()
        with self._lock:
            return max((self._count(k, now) for k in keys if k), default=0)

    def locked(self, *keys) -> bool:
        return self.failures(*keys) >= self.max_failures

    def fail(self, *keys) -> int:
        """Count one failure against every key; return the highest count. Each failure
        restarts that key's window, so the lockout lasts window_secs after the last guess."""
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > MAX_KEYS:
                self._failures = {k: v for k, v in self._failures.items() if now - v[1] < self.window_secs}
            counts = [0]
            for key in filter(None, keys):
                self._failures[key] = (self._count(key, now) + 1, now)
                counts.append(self._failures[key][0])
            return max(counts)

    def clear(self, *keys) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


def caller_key(raw_data) -> str:
    """The caller ID the platform sends with every tool request ('' when there is none)."""
    caller = str((raw_data or {}).get("caller_id_num") or "").strip()
    return f"caller:{caller}" if caller else ""


def keys_for(account: str, raw_data) -> tuple[str, str, str]:
    """(account, caller ID, call) keys for one verification attempt. Empty parts are skipped."""
    call_id = str((raw_data or {}).get("call_id") or "")
    return (f"acct:{account}" if account else "", caller_key(raw_data), f"call:{call_id}" if call_id else "")


class Sessions:
    """Verified calls: call_id -> record, written only by a verify handler, read by every account
    tool, expiring ttl_secs after it was written. Tool requests carry their own global_data, so
    tools trust this, not the request. In-memory and per-process, like Lockout."""

    def __init__(self, ttl_secs: float):
        self.ttl_secs = ttl_secs
        self._records: dict[str, tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def set(self, call_id: str, record: dict) -> None:
        if not call_id:
            return
        now = time.monotonic()
        with self._lock:  # drop expired calls, then record this one
            self._records = {k: v for k, v in self._records.items() if now - v[1] < self.ttl_secs}
            self._records[call_id] = (record, now)

    def get(self, raw_data) -> dict | None:
        """The record for the request's call_id, or None if unverified or expired."""
        call_id = str((raw_data or {}).get("call_id") or "")
        with self._lock:
            record, at = self._records.get(call_id, (None, 0.0))
        return record if record is not None and time.monotonic() - at < self.ttl_secs else None
