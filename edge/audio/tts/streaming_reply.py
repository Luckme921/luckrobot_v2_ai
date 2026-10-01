"""Prepare streamed model text concurrently and play punctuation chunks in order."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import queue
import threading
import time
from edge.audio.tts.cancellation import SpeechInterrupted


_BOUNDARY_CHARS = frozenset(",，、;；。.!！？?\n")
_NUMERIC_SEPARATORS = frozenset(".,")


class _PreparationCancellation:
    """Stop unused speculative audio without cancelling the turn."""
    def __init__(self, parent):
        self.parent = parent
        self.event = threading.Event()

    def check(self):
        self.parent.check()
        if self.event.is_set():
            raise SpeechInterrupted()

    def cancel(self):
        self.event.set()


def _pop_spoken_chunk(buffer):
    """Pop one punctuation chunk while preserving decimal separators.

    A streamed delta may end at ``23.`` before the next delta supplies ``5``.
    In that case the trailing period is ambiguous and must remain buffered.
    """
    for index, char in enumerate(buffer):
        if char not in _BOUNDARY_CHARS:
            continue
        if char in _NUMERIC_SEPARATORS and index > 0 and buffer[index - 1].isdigit():
            if index + 1 == len(buffer):
                return None
            if buffer[index + 1].isdigit():
                continue
        end = index + 1
        while end < len(buffer) and buffer[end] in _BOUNDARY_CHARS:
            end += 1
        return buffer[:end], buffer[end:]
    return None


class StreamingReplySpeaker:
    def __init__(self, tts, sink, cancellation, before_playback=None, max_workers=3,
                 fallback_grace_seconds=0.35):
        self.tts = tts
        self.sink = sink
        self.cancellation = cancellation
        self.before_playback = before_playback
        self.max_workers = max(1, int(max_workers))
        self.fallback_grace_seconds = max(0.0, float(fallback_grace_seconds))
        self._hedged = all(hasattr(tts, name) for name in (
            "prepare_online", "prepare_offline", "speak_with_prepared_fallback"))
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
        self._speculative_tokens = []
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="stream-tts-prepare")
        self._fallback_executor = (ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="stream-tts-kokoro")
            if self._hedged else None)
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
            parts = _pop_spoken_chunk(self._buffer)
            if parts is None:
                break
            chunk, self._buffer = parts
            self._submit(chunk.strip())

    def finish(self):
        self._submit(self._buffer.strip())
        self._buffer = ""
        self._queue.put(None)
        self._thread.join()
        for token in self._speculative_tokens:
            token.cancel()
        self._executor.shutdown(wait=not self._hedged, cancel_futures=True)
        if self._fallback_executor is not None:
            self._fallback_executor.shutdown(wait=False, cancel_futures=True)
        self._finished = True
        self.cancellation.check()
        if self._error is not None:
            raise self._error
        return self._played

    def cancel(self):
        self._buffer = ""
        self._queue.put(None)
        self._thread.join(timeout=3)
        for token in self._speculative_tokens:
            token.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._fallback_executor is not None:
            self._fallback_executor.shutdown(wait=False, cancel_futures=True)

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
        if self._hedged:
            offline_token = _PreparationCancellation(self.cancellation)
            online_token = _PreparationCancellation(self.cancellation)
            self._speculative_tokens.extend((offline_token, online_token))
            offline = self._fallback_executor.submit(
                self.tts.prepare_offline, chunk, offline_token)
            online = (None if sequence == 1 else self._executor.submit(
                self._prepare, sequence, chunk, online_token))
            self._queue.put((sequence, now, chunk, online, offline,
                             online_token, offline_token))
        else:
            future = self._executor.submit(self._prepare, sequence, chunk)
            self._queue.put((sequence, now, chunk, future, None, None, None))

    def _prepare(self, sequence, chunk, cancellation=None):
        cancellation = cancellation or self.cancellation
        cancellation.check()
        started = time.monotonic()
        audio = (self.tts.prepare_online(chunk, cancellation=cancellation)
                 if self._hedged else
                 self.tts.prepare(chunk, cancellation=cancellation))
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
                sequence, received_at, chunk, future, offline, online_token, offline_token = item
                self.cancellation.check()
                hook = self.before_playback if self._first else None
                if self._hedged and sequence == 1:
                    self.tts.speak_with_prepared_fallback(
                        chunk, self.sink, offline, before_playback=hook,
                        cancellation=self.cancellation)
                    offline_token.cancel()
                    self._last_playback_end = time.monotonic()
                    self._first = False
                    self._played = True
                    print(f"[STREAM_TTS] chunk={sequence} play_end mode=online_stream", flush=True)
                    continue
                audio = (self._choose_hedged_audio(
                    sequence, future, offline, online_token, offline_token)
                         if self._hedged else future.result())
                self.cancellation.check()
                now = time.monotonic()
                playback_gap = None if self._last_playback_end is None else now - self._last_playback_end
                print(
                    f"[STREAM_TTS] chunk={sequence} play_start "
                    f"queue_wait={now - received_at:.3f}s "
                    f"playback_gap={_seconds(playback_gap)}", flush=True)
                self.tts.play_prepared(
                    audio, self.sink, before_playback=hook,
                    cancellation=self.cancellation)
                self._last_playback_end = time.monotonic()
                self._first = False
                self._played = True
                print(f"[STREAM_TTS] chunk={sequence} play_end", flush=True)
        except BaseException as exc:
            self._error = exc

    def _choose_hedged_audio(self, sequence, online, offline,
                             online_token, offline_token):
        if not online.done():
            wait((online,), timeout=self.fallback_grace_seconds)
        self.cancellation.check()
        if online.done():
            try:
                audio = online.result()
                offline_token.cancel()
                return audio
            except Exception as exc:
                print(f"[STREAM_TTS] chunk={sequence} online_error={type(exc).__name__}", flush=True)
                return offline.result()
        if offline.done():
            print(f"[STREAM_TTS] chunk={sequence} select=kokoro reason=online_late", flush=True)
            online_token.cancel()
            return offline.result()
        while True:
            self.cancellation.check()
            done, _ = wait((online, offline), timeout=0.1, return_when=FIRST_COMPLETED)
            if online in done:
                try:
                    audio = online.result()
                    offline_token.cancel()
                    return audio
                except Exception as exc:
                    print(f"[STREAM_TTS] chunk={sequence} online_error={type(exc).__name__}", flush=True)
                    return offline.result()
            if offline in done:
                print(f"[STREAM_TTS] chunk={sequence} select=kokoro reason=online_late", flush=True)
                online_token.cancel()
                return offline.result()


def _seconds(value):
    return "n/a" if value is None else f"{value:.3f}s"
