"""Read-only local display server."""
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from edge.display.state import DEFAULT_STATE


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
