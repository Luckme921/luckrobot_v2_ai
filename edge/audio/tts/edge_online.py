"""Online PCM streaming, with offline fallback only before playback submission."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from shared.timing import record
from edge.audio.tts.kokoro import TtsError, TtsResult
from edge.audio.tts.text import normalize_for_speech

class EdgeOnlineTts:
    def __init__(self, config, fallback):
        self.fallback = fallback
        self.voice = config.get("edge_voice", "zh-CN-XiaoxiaoNeural")
        self.python = str(Path(config.get("edge_python", "private/tts-eval-venv/bin/python")).absolute())
        self.first_timeout = float(config.get("edge_first_audio_timeout_seconds", 8))
        self.idle_timeout = float(config.get("edge_idle_timeout_seconds", 10))
        self.speaker_id = self.voice
        self.num_threads = fallback.num_threads

    def speak(self, text, sink, *, before_playback=None):
        state = {"submitted": False}
        try:
            return self._online(text, sink, before_playback, state)
        except Exception as exc:
            if state["submitted"]:
                print(f"[TTS] EDGE_INTERRUPTED error={type(exc).__name__} replay=false", flush=True)
                raise TtsError("Online speech interrupted after playback began") from exc
            print(f"[TTS] FALLBACK provider=kokoro error={type(exc).__name__}", flush=True)
            return self.fallback.speak(text, sink, before_playback=before_playback)

    def _online(self, text, sink, before_playback, state):
        text = normalize_for_speech(text)
        if not text or not sink.strip(): raise TtsError("Empty speech or sink")
        self.fallback._prepare_sink(sink)
        start = time.monotonic(); last = start; first = None; size = 0
        worker = player = None
        selector = selectors.DefaultSelector()
        try:
            worker = subprocess.Popen([self.python, str(Path(__file__).with_name("edge_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True)
            worker.stdin.write(json.dumps({"text": text, "voice": self.voice}).encode())
            worker.stdin.close()
            selector.register(worker.stdout, selectors.EVENT_READ)
            while True:
                now = time.monotonic()
                budget = (self.first_timeout if first is None else self.idle_timeout) - (now-last)
                if budget <= 0 or now-start > 120: raise TimeoutError("Online audio deadline")
                if not selector.select(min(budget, 1)): continue
                data = os.read(worker.stdout.fileno(), 4096)
                if not data: break
                last = time.monotonic()
                if first is None:
                    first = last-start
                    record("edge_first_decoded_pcm", first)
                    if before_playback is not None: before_playback()
                    player = subprocess.Popen(["pacat", "--playback", "--raw", f"--device={sink}",
                        "--format=s16le", "--rate=24000", "--channels=1"], stdin=subprocess.PIPE, bufsize=0)
                    record("tts_first_pcm_submit", time.monotonic()-start)
                # Conservative: any attempted write prevents repeating the utterance.
                state["submitted"] = True
                view = memoryview(data)
                while view:
                    written = player.stdin.write(view)
                    if not written: raise BrokenPipeError("PCM write failed")
                    view = view[written:]
                size += len(data)
                last = time.monotonic()
            if worker.wait(timeout=3) != 0 or not size: raise TtsError("Online audio unavailable")
            generation = time.monotonic()-start
            player.stdin.close()
            if player.wait(timeout=10) != 0: raise TtsError("Player failed")
            record("edge_audio_total", time.monotonic()-start)
            print(f"[TTS] PROVIDER edge voice={self.voice}", flush=True)
            return TtsResult(generation, size/48000, 24000, first, time.monotonic()-start, 1)
        finally:
            selector.close()
            if worker is not None:
                try: os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                worker.wait()
                if worker.stdout: worker.stdout.close()
                if worker.stdin and not worker.stdin.closed: worker.stdin.close()
            if player is not None:
                if player.poll() is None: player.kill()
                player.wait()
                if player.stdin and not player.stdin.closed: player.stdin.close()
