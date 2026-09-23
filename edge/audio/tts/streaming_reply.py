"""Prepare streamed model text concurrently and play punctuation chunks in order."""
from concurrent.futures import ThreadPoolExecutor
import queue
import re
import threading
import time


_BOUNDARY = re.compile(r"^(.+?[,，、;；。.!！？?\n]+)(.*)$", re.S)


class StreamingReplySpeaker:
    def __init__(self, tts, sink, cancellation, before_playback=None, max_workers=3):
        self.tts = tts
        self.sink = sink
        self.cancellation = cancellation
        self.before_playback = before_playback
        self.max_workers = max(1, int(max_workers))
        self._buffer = ""
        self._queue = queue.Queue()
        self._received = False
        self._played = False
        self._error = None
        self._first = True
        self._finished = False
        self._sequence = 0
        self._last_model_chunk_at = None
        self._last_playback_end = None
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="stream-tts-prepare")
        self._thread = threading.Thread(
            target=self._run, name="streaming-reply-playback", daemon=True)
        self._thread.start()

    @property
    def received_text(self):
        return self._received

    @property
    def played(self):
        return self._played

    @property
    def finished(self):
        return self._finished

    def on_event(self, event):
        if event.get("type") != "text_delta":
            return
        text = event.get("text")
        if not isinstance(text, str) or not text:
            return
        self._received = True
        self._buffer += text
        while True:
            match = _BOUNDARY.match(self._buffer)
            if match is None:
                break
            chunk, self._buffer = match.groups()
            self._submit(chunk.strip())

    def finish(self):
        self._submit(self._buffer.strip())
        self._buffer = ""
        self._queue.put(None)
        self._thread.join()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._finished = True
        self.cancellation.check()
        if self._error is not None:
            raise self._error
        return self._played

    def cancel(self):
        self._buffer = ""
        self._queue.put(None)
        self._thread.join(timeout=3)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, chunk):
        if not chunk:
            return
        now = time.monotonic()
        self._sequence += 1
        sequence = self._sequence
        model_gap = None if self._last_model_chunk_at is None else now - self._last_model_chunk_at
        self._last_model_chunk_at = now
        print(
            f"[STREAM_TTS] chunk={sequence} received chars={len(chunk)} "
            f"model_gap={_seconds(model_gap)}", flush=True)
        future = self._executor.submit(self._prepare, sequence, chunk)
        self._queue.put((sequence, now, future))

    def _prepare(self, sequence, chunk):
        self.cancellation.check()
        started = time.monotonic()
        audio = self.tts.prepare(chunk, cancellation=self.cancellation)
        elapsed = time.monotonic() - started
        print(
            f"[STREAM_TTS] chunk={sequence} prepared synth={elapsed:.3f}s "
            f"audio={audio.audio_seconds:.3f}s "
            f"leading_silence={audio.leading_silence_seconds * 1000:.0f}ms "
            f"trailing_silence={audio.trailing_silence_seconds * 1000:.0f}ms",
            flush=True)
        return audio

    def _run(self):
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                sequence, received_at, future = item
                self.cancellation.check()
                audio = future.result()
                self.cancellation.check()
                now = time.monotonic()
                playback_gap = None if self._last_playback_end is None else now - self._last_playback_end
                print(
                    f"[STREAM_TTS] chunk={sequence} play_start "
                    f"queue_wait={now - received_at:.3f}s "
                    f"playback_gap={_seconds(playback_gap)}", flush=True)
                hook = self.before_playback if self._first else None
                self.tts.play_prepared(
                    audio, self.sink, before_playback=hook,
                    cancellation=self.cancellation)
                self._last_playback_end = time.monotonic()
                self._first = False
                self._played = True
                print(f"[STREAM_TTS] chunk={sequence} play_end", flush=True)
        except BaseException as exc:
            self._error = exc


def _seconds(value):
    return "n/a" if value is None else f"{value:.3f}s"
