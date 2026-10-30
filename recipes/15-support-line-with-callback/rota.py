"""Is a human free right now? The mock rota in data/rota.json. Swap for your ACD."""
import json
from datetime import datetime

import pytz

import config

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def human_available(now: datetime | None = None) -> bool:
    if config.AVAILABILITY in ("free", "busy"):
        return config.AVAILABILITY == "free"
    rota = json.loads(config.ROTA_FILE.read_text())
    now = now or datetime.now(pytz.utc)
    local = now.astimezone(pytz.timezone(rota["timezone"]))
    day, hhmm = DAYS[local.weekday()], local.strftime("%H:%M")
    return any(
        day in s["days"] and s["start"] <= hhmm < s["end"] and s["agent"] not in rota["busy"]
        for s in rota["shifts"]
    )
