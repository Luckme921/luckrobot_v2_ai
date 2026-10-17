"""Local display server and QQ Music login request bridge."""
import json
import math
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi import Header, HTTPException

from edge.display.state import DEFAULT_STATE, MUSIC_COVER_IMAGE
from edge.music import auth_bridge, control_bridge


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


@app.post("/api/music/control")
def music_control(payload: dict,
                  x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    action = payload.get("action")
    if action not in control_bridge.ACTIONS:
        raise HTTPException(status_code=422)
    request = control_bridge.request_action(action)
    return JSONResponse({"state": "requested", "id": request["id"]},
                        headers={"Cache-Control": "no-store"})


@app.get("/api/music/control")
def music_control_status():
    return JSONResponse(control_bridge.read_json(control_bridge.STATUS),
                        headers={"Cache-Control": "no-store"})


@app.get("/api/music/cover")
def music_cover(v: str = ""):
    try:
        music = json.loads(STATE_PATH.read_text(encoding="utf-8")).get("music")
    except (OSError, ValueError, TypeError):
        music = None
    if (not isinstance(music, dict) or not v or
            music.get("cover_revision") != v or not MUSIC_COVER_IMAGE.is_file()):
        raise HTTPException(status_code=404)
    return FileResponse(MUSIC_COVER_IMAGE, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/music/auth/qr")
def music_auth_qr():
    if auth_bridge.status().get("state") not in {"qr", "browser"} or not auth_bridge.QR_IMAGE.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(auth_bridge.QR_IMAGE, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/music/auth/avatar")
def music_auth_avatar():
    if auth_bridge.status().get("state") != "ready" or not auth_bridge.AVATAR_IMAGE.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(auth_bridge.AVATAR_IMAGE, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/music/auth/browser")
def music_auth_browser():
    if auth_bridge.status().get("state") != "browser" or not auth_bridge.BROWSER_IMAGE.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(auth_bridge.BROWSER_IMAGE, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/music/auth/browser/click")
def music_auth_browser_click(payload: dict,
                             x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    if auth_bridge.status().get("state") != "browser":
        raise HTTPException(status_code=409)
    try:
        x, y = float(payload["x"]), float(payload["y"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422)
    if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
        raise HTTPException(status_code=422)
    auth_bridge.request_browser_click(x, y)
    return {"ok": True}


@app.post("/api/music/auth/browser/cancel")
def music_auth_browser_cancel(x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    if auth_bridge.status().get("state") != "browser":
        raise HTTPException(status_code=409)
    auth_bridge.request_browser_cancel()
    return {"ok": True}


@app.post("/api/music/auth/login")
def music_auth_login(x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    current = auth_bridge.status()
    print(f"[DISPLAY] QQ_AUTH_REQUEST previous={current.get('state', 'unknown')}", flush=True)
    if current.get("state") == "browser" and auth_bridge.BROWSER_IMAGE.is_file():
        return JSONResponse({"state": "browser"}, headers={"Cache-Control": "no-store"})
    if current.get("state") == "qr" and auth_bridge.QR_IMAGE.is_file():
        return JSONResponse({"state": "qr"}, headers={"Cache-Control": "no-store"})
    if current.get("state") == "starting":
        return JSONResponse({"state": "starting"}, headers={"Cache-Control": "no-store"})
    request = auth_bridge.request_login()
    return JSONResponse({"state": "requested", "id": request["id"]},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/music/auth/logout")
def music_auth_logout(x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    request = auth_bridge.request_action("logout")
    print("[DISPLAY] QQ_AUTH_LOGOUT_REQUEST", flush=True)
    return JSONResponse({"state": "requested", "id": request["id"]},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/music/auth/check")
def music_auth_check(x_luckrobot_display: str | None = Header(default=None)):
    if x_luckrobot_display != "1":
        raise HTTPException(status_code=403)
    request = auth_bridge.request_action("check")
    return JSONResponse({"state": "requested", "id": request["id"]},
                        headers={"Cache-Control": "no-store"})
