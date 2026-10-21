#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PY=".venv/Scripts/python.exe"
"$PY" -m ruff format app tests scripts
"$PY" -m ruff check --fix app tests scripts
