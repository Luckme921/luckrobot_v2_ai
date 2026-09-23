#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/.venv/bin/activate"
exec uvicorn edge.display.server:app --host 127.0.0.1 --port 8765 --log-level warning
