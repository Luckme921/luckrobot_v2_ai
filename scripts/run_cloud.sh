#!/usr/bin/env bash
set -euo pipefail

ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"

cd "$ROOT"

source "$ROOT/.venv/bin/activate"

export PYTHONPATH="$ROOT"

exec uvicorn cloud.api.main:app \
  --host 127.0.0.1 \
  --port 8000
