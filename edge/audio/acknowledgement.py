"""Cached tool acknowledgements, independent of model/tool execution."""
import subprocess
import threading
import time
from shared.timing import record

PHRASES = {
    "web_search": "我帮你查一下。",
    "get_weather": "我帮你查一下天气。",
    "request_vision": "我看一下。",
    "play_music": "我帮你找一下音乐。",
    "navigate_to": "我检查一下导航请求。",
}

class ToolAcknowledgement:
    def __init__(self, clips, sink, delay_seconds=0.35):
        self.clips = clips
        self.sink = sink
        self.delay = max(0.0, float(delay_seconds))
        self._lock = threading.Lock()
        self._timer = None
        self._process = None
        self._seen = False
        self._closed = True
        self._generation = 0
        self.played = False

    def begin_turn(self):
        self.finish()
        with self._lock:
            self._generation += 1
            self._closed = False
            self._seen = False
            self.played = False

    def on_event(self, event):
        if event.get("type") != "tool_start":
            return
        path = self.clips.get(event.get("action"))
        if path is None or self.sink == "<unavailable>":
            return
        with self._lock:
            if self._closed or self._seen:
                return
            self._seen = True
            self._timer = threading.Timer(self.delay, self._play, args=(path, self._generation))
            self._timer.daemon = True
            self._timer.start()

    def _play(self, path, generation):
        with self._lock:
            if self._closed or generation != self._generation:
                return
            try:
                self._process = subprocess.Popen(
                    ["paplay", f"--device={self.sink}", str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.played = True
            except OSError as exc:
                print(f"[ACK] playback unavailable: {type(exc).__name__}", flush=True)

    def finish(self):
        """Cancel unstarted speech; drain a started short clip before final TTS."""
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            process, self._process = self._process, None
        if process is not None:
            started = time.monotonic()
            try:
                process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            record("ack_drain", time.monotonic() - started)
