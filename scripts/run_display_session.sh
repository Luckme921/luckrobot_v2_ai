#!/usr/bin/env bash
# Minimal X11 session: full-screen robot face, optional native OpenGL RViz viewer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export DISPLAY=:0
export XAUTHORITY="$ROOT/private/runtime/display.Xauthority"
mkdir -p "$ROOT/private/runtime"
/usr/bin/python3 - <<'PY'
import os, secrets, subprocess
from pathlib import Path
p = Path(os.environ['XAUTHORITY'])
p.touch(mode=0o600, exist_ok=True)
p.chmod(0o600)
subprocess.run(['xauth', '-f', str(p)], input='add :0 . '+secrets.token_hex(16)+'\n',
               text=True, check=True, stdout=subprocess.DEVNULL)
PY
exec xinit "$ROOT/scripts/display_x11_client.sh" -- /usr/bin/Xorg :0 vt1 -keeptty -nolisten tcp -auth "$XAUTHORITY"
