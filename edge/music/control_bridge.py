"""Validated, private display-to-audio music control requests."""
import time
import uuid

from edge.music.auth_bridge import ROOT, _write_json, read_json


REQUEST = ROOT / "private/runtime/qqmusic-control-request.json"
STATUS = ROOT / "private/runtime/qqmusic-control-status.json"
ACTIONS = frozenset({"pause_music", "resume_music", "next_music", "previous_music"})


def request_action(action: str) -> dict:
    if action not in ACTIONS:
        raise ValueError("unsupported music control action")
    value = {"id": uuid.uuid4().hex, "action": action, "time": time.time()}
    _write_json(REQUEST, value)
    return value


def publish(request_id: str, action: str, result: dict) -> None:
    _write_json(STATUS, {"id": request_id, "action": action,
                         "ok": bool(result.get("ok")),
                         "message": str(result.get("message", ""))[:160],
                         "playing": bool(result.get("playing")),
                         "time": time.time()})
