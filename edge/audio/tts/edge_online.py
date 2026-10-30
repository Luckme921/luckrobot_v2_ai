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
from edge.audio.tts.prepared import prepared_audio

class EdgeOnlineTts:
    def __init__(self, config, fallback):
        self.fallback = fallback
        self.voice = config.get("edge_voice", "zh-CN-XiaoxiaoNeural")
        self.python = str(Path(config.get("edge_python", "private/tts-eval-venv/bin/python")).absolute())
        self.first_timeout = float(config.get("edge_first_audio_timeout_seconds", 8))
        self.idle_timeout = float(config.get("edge_idle_timeout_seconds", 10))
        self.speaker_id = self.voice
        self.num_threads = fallback.num_threads

    def speak(self, text, sink, *, before_playback=None, cancellation=None):
        state = {"submitted": False}
        try:
            return self._online(text, sink, before_playback, state, cancellation)
        except Exception as exc:
            if cancellation is not None: cancellation.check()
            if state["submitted"]:
                print(f"[TTS] EDGE_INTERRUPTED error={type(exc).__name__} replay=false", flush=True)
                raise TtsError("Online speech interrupted after playback began") from exc
            print(f"[TTS] FALLBACK provider=kokoro error={type(exc).__name__}", flush=True)
            return self.fallback.speak(text, sink, before_playback=before_playback, **({"cancellation": cancellation} if cancellation is not None else {}))

    def prepare(self, text, cancellation=None):
        """Download and decode a complete segment without playing it."""
        try:
            return self._prepare_online(text, cancellation)
        except Exception as exc:
            if cancellation is not None:
                cancellation.check()
            print(f"[TTS] PREPARE_FALLBACK provider=kokoro error={type(exc).__name__}", flush=True)
            return self.fallback.prepare(text, cancellation=cancellation)

    def prepare_online(self, text, cancellation=None):
        """Prepare only Edge audio; the ordered player chooses its warm fallback."""
        return self._prepare_online(text, cancellation)

    def prepare_offline(self, text, cancellation=None):
        return self.fallback.prepare(text, cancellation=cancellation)

    def speak_with_prepared_fallback(self, text, sink, fallback_future, *,
                                     before_playback=None, cancellation=None):
        state = {"submitted": False}
        try:
            return self._online(text, sink, before_playback, state, cancellation)
        except Exception as exc:
            if cancellation is not None:
                cancellation.check()
            if state["submitted"]:
                raise TtsError("Online speech interrupted after playback began") from exc
            print(f"[TTS] FALLBACK_PREPARED provider=kokoro error={type(exc).__name__}", flush=True)
            audio = fallback_future.result()
            if cancellation is not None:
                cancellation.check()
            return self.fallback.play_prepared(
                audio, sink, before_playback=before_playback,
                cancellation=cancellation)

    def _prepare_online(self, text, cancellation=None):
        text = normalize_for_speech(text)
        if not text:
            raise TtsError("Empty speech")
        start = time.monotonic()
        last = start
        first = None
        chunks = []
        worker = None
        selector = selectors.DefaultSelector()
        try:
            worker = subprocess.Popen(
                [self.python, str(Path(__file__).with_name("edge_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, start_new_session=True)
            worker.stdin.write(json.dumps({"text": text, "voice": self.voice}).encode())
            worker.stdin.close()
            selector.register(worker.stdout, selectors.EVENT_READ)
            while True:
                if cancellation is not None:
                    cancellation.check()
                now = time.monotonic()
                budget = (self.first_timeout if first is None else self.idle_timeout) - (now - last)
                if budget <= 0 or now - start > 120:
                    raise TimeoutError("Online audio deadline")
                if not selector.select(min(budget, 0.1)):
                    continue
                data = os.read(worker.stdout.fileno(), 16384)
                if not data:
                    break
                last = time.monotonic()
                if first is None:
                    first = last - start
                chunks.append(data)
            if worker.wait(timeout=3) != 0 or not chunks:
                raise TtsError("Online audio unavailable")
            generation = time.monotonic() - start
            return prepared_audio(b"".join(chunks), 24000, generation, first)
        finally:
            selector.close()
            if worker is not None:
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                worker.wait()
                if worker.stdout:
                    worker.stdout.close()
                if worker.stdin and not worker.stdin.closed:
                    worker.stdin.close()

    def play_prepared(self, audio, sink, *, before_playback=None, cancellation=None):
        self.fallback._prepare_sink(sink)
        started = time.monotonic()
        if before_playback is not None:
            before_playback()
        player = subprocess.Popen(
            ["pacat", "--playback", "--raw", f"--device={sink}",
             "--format=s16le", f"--rate={audio.sample_rate}", "--channels=1"],
            stdin=subprocess.PIPE, bufsize=0)
        if cancellation is not None:
            cancellation.register(player)
            cancellation.check()
        try:
            view = memoryview(audio.pcm)
            playback_started = False
            while view:
                if not playback_started:
                    observer = getattr(self, "playback_observer", None)
                    if observer is not None:
                        observer(True)
                    playback_started = True
                written = player.stdin.write(view)
                if not written:
                    raise TtsError("Prepared player closed its input")
                view = view[written:]
            player.stdin.close()
            if player.wait(timeout=max(10, audio.audio_seconds + 5)) != 0:
                raise TtsError("Prepared player failed")
        finally:
            if player.poll() is None:
                player.kill()
                player.wait()
            if player.stdin and not player.stdin.closed:
                player.stdin.close()
            observer = getattr(self, "playback_observer", None)
            if observer is not None:
                observer(False)
        return TtsResult(
            audio.generation_seconds, audio.audio_seconds, audio.sample_rate,
            audio.first_audio_latency_seconds, time.monotonic() - started, 1)

    def _online(self, text, sink, before_playback, state, cancellation=None):
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
                if cancellation is not None: cancellation.check()
                now = time.monotonic()
                budget = (self.first_timeout if first is None else self.idle_timeout) - (now-last)
                if budget <= 0 or now-start > 120: raise TimeoutError("Online audio deadline")
                if not selector.select(min(budget, 0.1)): continue
                data = os.read(worker.stdout.fileno(), 4096)
                if not data: break
                last = time.monotonic()
                if first is None:
                    first = last-start
                    record("edge_first_decoded_pcm", first)
                    if before_playback is not None: before_playback()
                    player = subprocess.Popen(["pacat", "--playback", "--raw", f"--device={sink}",
                        "--format=s16le", "--rate=24000", "--channels=1"], stdin=subprocess.PIPE, bufsize=0)
                    if cancellation is not None:
                        cancellation.register(player)
                        cancellation.check()
                    record("tts_first_pcm_submit", time.monotonic()-start)
                    observer = getattr(self, "playback_observer", None)
                    if observer is not None:
                        observer(True)
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
                observer = getattr(self, "playback_observer", None)
                if observer is not None:
                    observer(False)
