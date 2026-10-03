"""Local display server and QQ Music login request bridge."""
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi import Header, HTTPException

from edge.display.state import DEFAULT_STATE
from edge.music import auth_bridge


ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).with_name("static")
STATE_PATH = Path(os.environ.get(
    "LUCKROBOT_DISPLAY_STATE",
    str(ROOT / "private/runtime/display_state.json")))

app = FastAPI(title="LuckRobot Display", docs_url=None, redoc_url=None)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("display state is not an object")
    except (OSError, ValueError, json.JSONDecodeError):
        data = dict(DEFAULT_STATE)
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/music/auth")
def music_auth():
    return JSONResponse(auth_bridge.status(), headers={"Cache-Control": "no-store"})


@app.get("/api/music/auth/qr")
def music_auth_qr():
    if auth_bridge.status().get("state") != "qr" or not auth_bridge.QR_IMAGE.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(auth_bridge.QR_IMAGE, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/music/auth/login")
def music_auth_login(x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    current = auth_bridge.status()
    if current.get("state") == "qr" and auth_bridge.QR_IMAGE.is_file():
        return JSONResponse({"state": "qr"}, headers={"Cache-Control": "no-store"})
    if current.get("state") == "starting":
        return JSONResponse({"state": "starting"}, headers={"Cache-Control": "no-store"})
    request = auth_bridge.request_login()
    return JSONResponse({"state": "requested", "id": request["id"]},
                        headers={"Cache-Control": "no-store"})
