#!/usr/bin/env python3
"""Validate SWML files (*.swml.yaml / *.swml.json) against the SWML JSON Schema that ships
inside signalwire-sdk (signalwire/schema.json, the same schema the SDK validates with).

  python scripts/validate_swml.py recipes/06-movie-showtimes/showtimes.swml.yaml [...]
"""
import json
import sys
from importlib.resources import files
from pathlib import Path

import yaml
from jsonschema.validators import validator_for

SCHEMA = json.loads(files("signalwire").joinpath("schema.json").read_text())
VALIDATOR = validator_for(SCHEMA)(SCHEMA)


def main(argv: list[str]) -> int:
    failed = 0
    for arg in argv:
        path = Path(arg)
        doc = yaml.safe_load(path.read_text())  # YAML is a superset of JSON
        errors = sorted(VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))
        print(f"{'FAIL' if errors else 'ok  '} {path}")
        for err in errors[:20]:
            loc = "/".join(str(p) for p in err.path) or "(root)"
            print(f"  {loc}: {err.message[:300]}", file=sys.stderr)
        failed += bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
