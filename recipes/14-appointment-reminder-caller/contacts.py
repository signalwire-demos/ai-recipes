"""The appointments source (who to call, consent, time zone) and the do-not-call list."""
import csv

import config


def load_contacts() -> dict[str, dict]:
    with config.APPOINTMENTS_FILE.open(newline="") as f:
        return {row["appointment_id"]: row for row in csv.DictReader(f)}


def load_dnc() -> set[str]:
    if not config.DNC_FILE.exists():
        return set()
    return {line.strip() for line in config.DNC_FILE.read_text().splitlines() if line.strip()}


def add_dnc(phone: str) -> None:
    if phone not in load_dnc():
        with config.DNC_FILE.open("a") as f:
            f.write(phone + "\n")
