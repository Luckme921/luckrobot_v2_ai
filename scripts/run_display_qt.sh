#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM="${LUCKROBOT_QT_PLATFORM:-linuxfb}"

export QT_QPA_PLATFORM="$PLATFORM"
export QT_SELECT="${QT_SELECT:-qt5}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
export QT_QPA_EGLFS_ALWAYS_SET_MODE="${QT_QPA_EGLFS_ALWAYS_SET_MODE:-1}"

if [[ -z "${QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS:-}" ]]; then
  for candidate in /dev/input/event*; do
    if udevadm info --query=property --name "$candidate" 2>/dev/null \
      | grep -q '^ID_INPUT_TOUCHSCREEN=1$'; then
      export QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS="$candidate"
      break
    fi
  done
fi

exec qmlscene -platform "$PLATFORM" "$ROOT/edge/display/qml/main.qml"
