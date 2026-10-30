#!/usr/bin/env python3
"""Regenerate the recipe index table in the root README.md from recipes/*/recipe.yaml.

  python scripts/build_index.py          # rewrite README.md between the markers
  python scripts/build_index.py --check  # exit 1 if README.md is out of date (CI)
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START, END = "<!-- recipes:start -->", "<!-- recipes:end -->"


def table() -> str:
    rows = ["| # | Recipe | Group | Size | Status | Channels | Primitives |",
            "|---|---|---|---|---|---|---|"]
    for manifest in sorted((ROOT / "recipes").glob("*/recipe.yaml")):
        m = yaml.safe_load(manifest.read_text())
        folder = manifest.parent.name
        num = "—" if folder == "_template" else folder[:2]
        rows.append(
            f"| {num} | [{m['title']}](recipes/{folder}/) | {m['group']} | {m['size']} | "
            f"{m['status']} | {', '.join(m['channels'])} | {', '.join(m['primitives'])} |"
        )
    return "\n".join(rows)


def render(text: str) -> str:
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    return f"{head}{START}\n{table()}\n{END}{tail}"


def main() -> int:
    current = README.read_text()
    updated = render(current)
    if "--check" in sys.argv:
        if current != updated:
            print("README.md recipe index is stale: run python scripts/build_index.py", file=sys.stderr)
            return 1
        return 0
    README.write_text(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
