#!/usr/bin/env bash
# Copy recipes/_template to recipes/<nn-slug> and stamp the manifest id.
# Usage: scripts/new_recipe.sh 08-bank-balance-line
set -euo pipefail

slug="${1:-}"
if [[ ! "$slug" =~ ^[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  echo "usage: $0 <nn-slug>   e.g. $0 08-bank-balance-line" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/recipes/_template"
dst="$root/recipes/$slug"
[[ -e "$dst" ]] && { echo "error: $dst already exists" >&2; exit 1; }

mkdir -p "$dst"
# Copy everything except local state (venvs, caches, real .env files).
(cd "$src" && tar cf - --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude .env --exclude logs .) | (cd "$dst" && tar xf -)

# Stamp the manifest: id = folder name, status = proposed, title placeholder.
python3 - "$dst/recipe.yaml" "$slug" <<'PY'
import re, sys
path, slug = sys.argv[1], sys.argv[2]
text = open(path).read()
text = re.sub(r"(?m)^id: .*$", f"id: {slug}", text)
text = re.sub(r"(?m)^status: .*$", "status: proposed", text)
title = " ".join(w.capitalize() for w in slug.split("-")[1:])
text = re.sub(r"(?m)^title: .*$", f"title: {title}", text)
open(path, "w").write(text)
PY

cat <<MSG
Created recipes/$slug from the template. Next:
  cd recipes/$slug
  python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
  pytest -q && swaig-test app.py --list-tools
Then edit app.py, config.py, recipe.yaml and README.md (keep the 7 sections).
MSG
