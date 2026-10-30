#!/usr/bin/env python3
"""Check that each recipe README has exactly the 7 sections from README-TEMPLATE.md, in order,
and that "What to change first" mentions config.py (SWML-only recipes are exempt from that).

  python scripts/check_readme.py recipes/08-bank-balance-line [...]
"""
import re
import sys
from pathlib import Path

SECTIONS = ["What it does", "What it demonstrates", "Prerequisites", "Setup",
            "Run locally", "Deploy", "What to change first"]


def check(folder: Path) -> list[str]:
    readme = folder / "README.md"
    if not readme.is_file():
        return [f"{readme}: missing"]
    text = readme.read_text()
    # ignore headings inside fenced code blocks
    body = re.sub(r"^(`{3,}).*?^\1", "", text, flags=re.S | re.M)
    found = re.findall(r"^## (.+?)\s*$", body, flags=re.M)
    errors = []
    if found != SECTIONS:
        errors.append(f"{readme}: sections are {found}, expected {SECTIONS}")
    if "```mermaid" not in text:
        errors.append(f"{readme}: no mermaid diagram")
    last = body.split("## What to change first", 1)[-1]
    if (folder / "config.py").exists() and "config.py" not in last:
        errors.append(f"{readme}: 'What to change first' must point to config.py")
    return errors


def main(argv: list[str]) -> int:
    errors = [e for a in argv for e in check(Path(a))]
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
