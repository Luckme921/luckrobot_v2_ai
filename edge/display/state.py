"""Publish display state without coupling the audio loop to the UI process."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading


DEFAULT_STATE = {
    "state": "sleeping",
    "label": "等待 Lucky",
    "user_text": "",
    "assistant_text": "",
    "music": None,
}


class DisplayPublisher:
    def __init__(self, config=None):
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.path = Path(config.get(
            "state_path", "private/runtime/display_state.json"))
        self._lock = threading.Lock()
        self._state = dict(DEFAULT_STATE)

    def publish(self, *, state=None, label=None, user_text=None,
                assistant_text=None, music_marker=False, music=None):
        if not self.enabled:
            return
        with self._lock:
            if state is not None:
                self._state["state"] = state
            if label is not None:
                self._state["label"] = label
            if user_text is not None:
                self._state["user_text"] = user_text
            if assistant_text is not None:
                self._state["assistant_text"] = assistant_text
            if music_marker:
                self._state["music"] = music
            self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_atomic()

    def _write_atomic(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            print(f"[DISPLAY] STATE_WRITE_ERROR {type(exc).__name__}", flush=True)
