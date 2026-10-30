"""The order rules: menu validation, stock and price math. No SignalWire imports, no model.

Prices are integer cents from data/menu.json. Tax is rounded half-up to the cent.
"""
import json
from decimal import ROUND_HALF_UP, Decimal

import config


def load(path) -> dict:
    return json.loads(path.read_text())


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def key_of(value) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def check_line(menu: dict, args: dict):
    """Return (line, error, missing). `missing` is the first out-of-stock token, if any."""
    key = key_of(args.get("item"))
    item = menu.get(key)
    if not item:
        return None, f"{args.get('item')} isn't on the menu.", None
    sizes = list(item["sizes"])
    size = str(args.get("size") or (sizes[0] if len(sizes) == 1 else "")).strip().lower()
    if size not in item["sizes"]:
        return None, f"{item['name']} comes in {', '.join(sizes)}. Ask which size.", None
    mods = [str(m).strip().lower() for m in args.get("modifiers") or []]
    bad = [m for m in mods if m not in item["modifiers"]]
    if bad:
        allowed = ", ".join(item["modifiers"]) or "none"
        return None, f"{', '.join(bad)} isn't an option on {item['name']}. Options: {allowed}.", None
    qty = int(args.get("quantity") or 1)
    if not 1 <= qty <= config.MAX_QUANTITY:
        return None, f"Quantity must be 1 to {config.MAX_QUANTITY}.", None
    line = {"item": key, "size": size, "modifiers": mods, "quantity": qty}
    for slot, choices in item.get("combo", {}).items():
        line[slot] = key_of(args.get(slot))
        if line[slot] not in choices:
            return None, f"The combo {slot} must be one of: {', '.join(choices)}.", None
    out = set(load(config.STOCK_FILE)["out_of_stock"])
    missing = next((t for t in [key, line.get("side"), line.get("drink"), *mods] if t in out), None)
    return line, None, missing


def substitutes(token: str) -> list:
    stock = load(config.STOCK_FILE)
    return [s for s in stock["substitutes"].get(token, []) if s not in stock["out_of_stock"]]


def unit_cents(menu: dict, line: dict) -> int:
    item = menu[line["item"]]
    return item["sizes"][line["size"]] + sum(item["modifiers"][m] for m in line["modifiers"])


def label(menu: dict, line: dict) -> str:
    parts = [f"{line['quantity']} {line['size']} {menu[line['item']]['name']}"]
    parts += [menu[line[s]]["name"] for s in ("side", "drink") if s in line]
    return ", ".join(parts + line["modifiers"])


def totals(menu: dict, order: list) -> dict:
    subtotal = sum(unit_cents(menu, ln) * ln["quantity"] for ln in order)
    tax = int((Decimal(subtotal) * Decimal(config.TAX_RATE)).quantize(0, ROUND_HALF_UP))
    return {"subtotal": money(subtotal), "tax": money(tax), "total": money(subtotal + tax)}
