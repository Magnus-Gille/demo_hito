#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

if ! python - <<'PY' >/dev/null 2>&1
import bs4
import requests
PY
then
  pip install -r requirements.txt
fi

PYTHONPATH="$PROJECT_ROOT/src" python -m leadfinder run \
  --db data/leads.db \
  --export-csv data/leads_export.csv \
  --company-limit 15 \
  --top 15 \
  --delay 2.0 \
  "$@"
