#!/usr/bin/env bash
set -euo pipefail

for attempt in {1..30}; do
  if pactl info >/dev/null 2>&1; then
    echo "[STARTUP] PulseAudio ready"
    exit 0
  fi
  sleep 1
done

echo "[STARTUP] PulseAudio unavailable after 30 seconds" >&2
exit 1
