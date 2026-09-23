#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM="${LUCKROBOT_QT_PLATFORM:-eglfs}"

export QT_QPA_PLATFORM="$PLATFORM"
export QT_SELECT="${QT_SELECT:-qt5}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-opengl}"
export QT_QPA_EGLFS_ALWAYS_SET_MODE="${QT_QPA_EGLFS_ALWAYS_SET_MODE:-1}"

if [[ -e /dev/input/event9 ]] && [[ -z "${QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS:-}" ]]; then
  export QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS="/dev/input/event9"
fi

exec qmlscene -platform "$PLATFORM" "$ROOT/edge/display/qml/main.qml"
