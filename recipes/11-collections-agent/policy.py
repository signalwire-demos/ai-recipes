"""The negotiation policy. Thresholds live in config.py and are read only here, server side.

Nothing in this module is ever sent to the model: the prompt, the step text, the tool
schemas and global_data carry none of these numbers. Handlers turn the reason code into
wording that says "no" without saying where the line is.
"""
import config

ACCEPT = "accept"
TOO_LOW = "monthly_too_low"
TOO_LONG = "term_too_long"
SHORT = "does_not_cover_balance"
INVALID = "invalid"


def evaluate(balance: float, monthly_amount, months) -> str:
    try:
        monthly, term = float(monthly_amount), int(months)
    except (TypeError, ValueError):
        return INVALID
    if monthly <= 0 or term <= 0:
        return INVALID
    if monthly < config.MIN_MONTHLY_PAYMENT:
        return TOO_LOW
    if term > config.MAX_TERM_MONTHS:
        return TOO_LONG
    if monthly * term + 0.005 < balance:
        return SHORT
    return ACCEPT


def refusals_exhausted(refusals: int) -> bool:
    return refusals >= config.MAX_REFUSALS
