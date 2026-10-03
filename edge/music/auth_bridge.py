"""Private file bridge between the Qt display server and the audio process."""

import json
import os
from pathlib import Path
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "private/runtime"
REQUEST = RUNTIME / "qqmusic-auth-request.json"
STATUS = RUNTIME / "qqmusic-auth-status.json"
QR_IMAGE = RUNTIME / "qqmusic-auth-qr.png"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def request_login() -> dict:
    value = {"id": uuid.uuid4().hex, "time": time.time()}
    _write_json(REQUEST, value)
    publish("starting")
    return value


def publish(state: str, *, detail: str = "") -> None:
    _write_json(STATUS, {"state": state, "detail": detail, "time": time.time()})


def status() -> dict:
    value = read_json(STATUS)
    if value.get("state") in {"starting", "qr"} and time.time() - value.get("time", 0) > 180:
        return {"state": "error", "detail": "登录二维码已过期，请重新点击登录"}
    return value or {"state": "unknown", "detail": "点击登录以检查 QQ 音乐账号"}
