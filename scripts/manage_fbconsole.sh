#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
if [[ "$ACTION" != "detach" && "$ACTION" != "attach" ]]; then
  echo "Usage: $0 detach|attach" >&2
  exit 2
fi
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Framebuffer console management requires root." >&2
  exit 1
fi

VALUE=0
[[ "$ACTION" == "attach" ]] && VALUE=1
FOUND=0
for console in /sys/class/vtconsole/vtcon*; do
  [[ -r "$console/name" && -w "$console/bind" ]] || continue
  if grep -qi "frame buffer" "$console/name"; then
    printf '%s\n' "$VALUE" > "$console/bind"
    echo "[DISPLAY] fbconsole $ACTION $(basename "$console")"
    FOUND=1
  fi
done

if [[ "$FOUND" -ne 1 ]]; then
  echo "No writable framebuffer console binding found." >&2
  exit 1
fi
