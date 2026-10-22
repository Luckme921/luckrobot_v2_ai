"""Publish display state without coupling the audio loop to the UI process."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading

from edge.display.rolling_text import display_rows, row_index

MUSIC_COVER_IMAGE = Path(__file__).resolve().parents[2] / "private/runtime/music-cover.png"


DEFAULT_STATE = {
    "state": "sleeping",
    "label": "等待 Lucky",
    "user_text": "",
    "assistant_text": "",
    "assistant_lines": [],
    "assistant_line_index": 0,
    "assistant_progress_chars": 0,
    "music": None,
    "voice_playing": False,
    "light": {"on": True, "mode": "breath", "rgb": [255, 0, 0]},
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
                assistant_text=None, assistant_progress_chars=None,
                music_marker=False, music=None, light=None,
                voice_playing=None):
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
            if assistant_progress_chars is not None:
                self._state["assistant_progress_chars"] = max(0, int(assistant_progress_chars))
            if assistant_text is not None or assistant_progress_chars is not None:
                previous_index = self._state["assistant_line_index"]
                rows = display_rows(self._state["assistant_text"])
                self._state["assistant_lines"] = [row[0] for row in rows]
                self._state["assistant_line_index"] = row_index(
                    rows, self._state["assistant_progress_chars"])
                if self._state["assistant_line_index"] != previous_index:
                    print(
                        f"[DISPLAY] DIALOGUE_LINE index={self._state['assistant_line_index']} "
                        f"total={len(rows)} progress={self._state['assistant_progress_chars']}",
                        flush=True,
                    )
            if music_marker:
                self._state["music"] = music
            if light is not None:
                self._state["light"] = light
            if voice_playing is not None:
                self._state["voice_playing"] = bool(voice_playing)
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
