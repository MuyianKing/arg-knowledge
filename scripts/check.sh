#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY=".venv/Scripts/python.exe"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: $PY not found; run: uv venv --python 3.12 .venv"
  exit 1
fi

echo "==> ruff check"
"$PY" -m ruff check app tests scripts

echo "==> ruff format --check"
"$PY" -m ruff format --check app tests scripts

echo "==> pytest"
"$PY" -m pytest
