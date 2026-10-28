#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
xset s off -dpms || true
openbox --sm-disable &
unclutter -idle 1 -root &
export LUCKROBOT_QT_PLATFORM=xcb QT_QPA_PLATFORM=xcb QT_QUICK_BACKEND=software
exec bash "$ROOT/scripts/run_display_qt.sh"
