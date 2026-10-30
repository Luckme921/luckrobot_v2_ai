#!/usr/bin/env bash
set -euo pipefail
if BROWSER="$(command -v chromium-browser || command -v chromium || true)" \
  && [[ -n "$BROWSER" ]]; then
  exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars \
    http://127.0.0.1:8765/
fi

if BROWSER="$(command -v firefox || true)" && [[ -n "$BROWSER" ]]; then
  exec "$BROWSER" --kiosk http://127.0.0.1:8765/
fi

echo "Chromium or Firefox is required." >&2
exit 1
