"""Local Unix IPC adapter. Remote control is ROS 2, never SSH or TCP mode gateway."""
import json
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "private/runtime/navigation"
SOCKET = RUNTIME / "control.sock"
STATUS = RUNTIME / "status.json"


def status():
    try:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        age = time.monotonic()-value["published_monotonic"]
        if not 0 <= age <= 3:
            raise ValueError("bridge stale")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return {"connected": False, "fresh": False, "navigation_ready": False,
                "state": "UNAVAILABLE", "reason": "ROS桥接进程未启动或状态已过期",
                "system": {"fresh": False}, "mapping": {"fresh": False}}


def request(command, confirmed=False):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(str(SOCKET))
            conn.sendall((json.dumps({"command": command, "confirmed": confirmed})+"\n").encode())
            with conn.makefile("rb") as stream:
                line = stream.readline(65537)
            if len(line) > 65536 or not line.endswith(b"\n"):
                raise ValueError("invalid IPC framing")
            return json.loads(line)
    except (OSError, ValueError, AttributeError):
        return {"ok": False, "status": "unavailable", "executed": False,
                "message": "导航通信未完成，若已发出请求请先查看状态，不要重复提交。"}
