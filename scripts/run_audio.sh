#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

source "$ROOT/.venv/bin/activate"

exec python -m edge.audio.runtime \
  --config "$ROOT/configs/audio.yaml"
