#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
xset s off -dpms || true
# This HDMI screen advertises 1024x600 as preferred despite its 16:9 panel.
OUTPUT=$(xrandr --query | awk '/ connected/{print $1; exit}')
if [[ -n "$OUTPUT" ]]; then
    xrandr --output "$OUTPUT" --mode 1920x1080 --rotate normal || true
fi
openbox --sm-disable &
unclutter -idle 1 -root &
export LUCKROBOT_QT_PLATFORM=xcb QT_QPA_PLATFORM=xcb QT_QUICK_BACKEND=software
exec bash "$ROOT/scripts/run_display_qt.sh"
