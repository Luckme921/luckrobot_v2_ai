#!/usr/bin/env bash
set -euo pipefail
BROWSER="$(command -v chromium-browser || command -v chromium || true)"
if [[ -z "$BROWSER" ]]; then
  echo "Chromium is not installed." >&2
  exit 1
fi
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars http://127.0.0.1:8765/
