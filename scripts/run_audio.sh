#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

source "$ROOT/.venv/bin/activate"

# Keep the robot microphone available continuously.
# PulseAudio idle suspend caused unreliable USB microphone
# resume behavior during repeated runtime starts.
SUSPEND_ID="$(
  pactl list short modules 2>/dev/null |
  awk '$2 == "module-suspend-on-idle" {print $1; exit}'
)"

if [[ -n "${SUSPEND_ID}" ]]; then
  pactl unload-module "${SUSPEND_ID}" >/dev/null || true
fi

exec python -m edge.audio.runtime \
  --config "$ROOT/configs/audio.yaml"
