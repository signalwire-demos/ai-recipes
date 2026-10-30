"""AI Restaurant Reservation Line: two steps, one scoped tool.

Governance point: `take_booking` exposes exactly one tool, book_table, and has no
navigation (valid_steps=[]). The model can't announce a booking it hasn't made:
only the book_table handler, after it has checked the hours and the party size
in code and written the row, moves the call to `confirmed`. `confirmed` has zero
tools and reads the booking back from global_data.
"""
import json
import re
import secrets
import threading
from datetime import date, datetime, timedelta

from signalwire import AgentBase, FunctionResult

import config

_write_lock = threading.Lock()


def save_booking(booking: dict) -> None:
    """Append one booking to the JSON-list sink in config.RESERVATIONS_FILE."""
    path = config.RESERVATIONS_FILE
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append(booking)
        path.write_text(json.dumps(rows, indent=2) + "\n")


def _minutes(hhmm: str) -> int:
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def check_request(party_size, day: str, time: str, today: date) -> str | None:
    """Return a reason the request can't be booked, or None if it can."""
    try:
        party = int(party_size)
    except (TypeError, ValueError):
        return "The party size must be a number."
    if party < 1:
        return "The party size must be at least one."
    if party > config.MAX_PARTY:
        return (f"We can seat at most {config.MAX_PARTY} guests per booking. "
                "Offer a smaller party or suggest calling our events team.")
    try:
        when = datetime.strptime(f"{day} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "I need the date as YYYY-MM-DD and the time as 24-hour HH:MM."
    if when.date() < today:
        return "That date is in the past. Ask for a future date."
    if when.date() > today + timedelta(days=config.BOOKING_WINDOW_DAYS):
        return f"We only take bookings up to {config.BOOKING_WINDOW_DAYS} days ahead."
    weekday = when.strftime("%A").lower()
    hours = config.OPENING_HOURS.get(weekday)
    if not hours:
        return f"We are closed on {weekday.capitalize()}s. Ask for another day."
    last = _minutes(hours["close"]) - config.LAST_SEATING_MINUTES
    if not _minutes(hours["open"]) <= _minutes(time) <= last:
        latest = f"{last // 60:02d}:{last % 60:02d}"
        return (f"On {weekday.capitalize()}s we seat from {hours['open']} "
                f"until {latest}. Ask for a time in that window.")
    return None


def add_today(query_params, body_params, headers, agent) -> None:
    """Per request: tell the model today's date so it can turn "Friday" into a date."""
    today = date.today()
    agent.update_global_data({"today": today.isoformat(), "weekday": today.strftime("%A")})


class ReservationAgent(AgentBase):
    def __init__(self, **kwargs):
        super().__init__(name="restaurant-reservations", route=config.ROUTE,
                         port=config.PORT, **kwargs)
        self.add_language("English", config.LANGUAGE_CODE, config.VOICE)
        self.prompt_add_section(
            "Role",
            f"You take table reservations by phone for {config.RESTAURANT_NAME}. "
            "Be brief and warm. Today is ${global_data.weekday}, ${global_data.today}.",
        )
        self.set_dynamic_config_callback(add_today)

        ctx = self.define_contexts().add_context("default")
        ctx.add_step("take_booking") \
            .set_text(
                "Collect the guest's name, party size, date, time and a callback phone "
                "number. Convert the date to YYYY-MM-DD and the time to 24-hour HH:MM, "
                "then call book_table. If book_table says no, tell the caller why and "
                "ask for something that works. Never say a table is booked until "
                "book_table has confirmed it."
            ) \
            .set_functions(["book_table"]) \
            .set_valid_steps([])  # no next_step tool: only the handler can leave this step
        ctx.add_step("confirmed") \
            .set_text(
                "Read the booking back: ${global_data.booking.name}, a party of "
                "${global_data.booking.party_size} on ${global_data.booking.date} at "
                "${global_data.booking.time}, confirmation code "
                "${global_data.booking.ref}. Thank them and say goodbye."
            ) \
            .set_functions([])  # explicit: zero tools (steps inherit tools otherwise)

    @AgentBase.tool(
        name="book_table",
        description="Book a table once you have every detail. Returns whether it worked.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the booking"},
                "party_size": {"type": "integer", "description": "Number of guests"},
                "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                "time": {"type": "string", "description": "Time as 24-hour HH:MM"},
                "phone": {"type": "string", "description": "Callback phone number"},
            },
            "required": ["name", "party_size", "date", "time", "phone"],
        },
    )
    def book_table(self, args, raw_data):
        name = str(args.get("name", "")).strip()
        phone = re.sub(r"\D", "", str(args.get("phone", "")))
        if not name:
            return FunctionResult("I need a name for the booking.")
        if not 10 <= len(phone) <= 15:
            return FunctionResult("That phone number doesn't look complete. Ask for it again.")
        problem = check_request(args.get("party_size"), str(args.get("date", "")).strip(),
                                str(args.get("time", "")).strip(), date.today())
        if problem:
            return FunctionResult(problem)  # no actions: the call stays in take_booking

        booking = {
            "ref": f"R-{secrets.randbelow(10000):04d}",
            "name": name,
            "party_size": int(args["party_size"]),
            "date": args["date"].strip(),
            "time": args["time"].strip(),
            "phone": phone,
        }
        save_booking(booking)
        return (
            FunctionResult(f"Booked. Confirmation code {booking['ref']}.")
            .update_global_data({"booking": booking})
            .swml_change_step("confirmed")
        )


agent = ReservationAgent()

if __name__ == "__main__":
    agent.run()
