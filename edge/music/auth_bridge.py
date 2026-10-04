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
AVATAR_IMAGE = RUNTIME / "qqmusic-auth-avatar.png"
BROWSER_IMAGE = RUNTIME / "qqmusic-auth-browser.png"
BROWSER_CLICK = RUNTIME / "qqmusic-auth-browser-click.json"
BROWSER_CANCEL = RUNTIME / "qqmusic-auth-browser-cancel.json"


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


def request_action(action: str) -> dict:
    if action not in {"login", "logout", "check"}:
        raise ValueError("unsupported QQ Music authentication action")
    value = {"id": uuid.uuid4().hex, "time": time.time(), "action": action}
    _write_json(REQUEST, value)
    publish("starting" if action != "logout" else "logging_out")
    return value


def request_login() -> dict:
    return request_action("login")


def request_browser_click(x: float, y: float) -> dict:
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError("browser click is outside the preview")
    value = {"id": uuid.uuid4().hex, "x": x, "y": y, "time": time.time()}
    _write_json(BROWSER_CLICK, value)
    return value


def request_browser_cancel() -> dict:
    value = {"id": uuid.uuid4().hex, "time": time.time()}
    _write_json(BROWSER_CANCEL, value)
    return value


def publish(state: str, *, detail: str = "", nickname: str = "", avatar: bool = False,
            qr_available: bool = False, qr_revision: int = 0) -> None:
    _write_json(STATUS, {"state": state, "detail": detail, "nickname": nickname,
                         "avatar": bool(avatar), "qr_available": bool(qr_available),
                         "qr_revision": qr_revision, "time": time.time()})


def status() -> dict:
    value = read_json(STATUS)
    if value.get("state") in {"starting", "qr"} and time.time() - value.get("time", 0) > 180:
        return {"state": "error", "detail": "登录二维码已过期，请重新点击登录"}
    return value or {"state": "unknown", "detail": "点击登录以检查 QQ 音乐账号"}
