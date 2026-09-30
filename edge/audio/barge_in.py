"""Wake-only monitoring during reply speech. Main ASR remains paused."""
import threading
import time
import numpy as np
from edge.audio.capture.pulse import PulseCapture, PulseCaptureError
from edge.audio.tts.cancellation import SpeechCancellation


class WakeInterruptMonitor:
    """Keep only Lucky KWS active while the normal capture loop is stopped."""
    def __init__(self, capture, kws):
        self.cancellation = SpeechCancellation()
        self._done = threading.Event()
        self._ready = threading.Event()
        self._failed = threading.Event()
        self._monitor_lock = threading.Lock()
        self._monitor = None
        self._capture_kwargs = dict(
            source=capture.source,
            sample_rate=capture.sample_rate,
            channels=capture.channels,
            sample_format=capture.sample_format,
            input_channels=capture.input_channels,
            selected_channel=capture.selected_channel,
        )
        self._kws = kws
        self._thread = None
        self._last_error = None
        self._max_attempts = 3

    def start(self):
        self._thread = threading.Thread(
            target=self._listen, name="lucky-turn-interrupt", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 6.0
        while not self._ready.is_set() and not self._failed.is_set():
            if time.monotonic() >= deadline:
                self.stop()
                raise PulseCaptureError("wake monitor produced no audio")
            self._done.wait(0.02)
        if self._failed.is_set():
            self.stop()
            raise PulseCaptureError(
                f"wake monitor unavailable: {type(self._last_error).__name__}"
            )
        return self

    def _listen(self):
        for attempt in range(1, self._max_attempts + 1):
            if self._done.is_set():
                return
            monitor = PulseCapture(**self._capture_kwargs)
            with self._monitor_lock:
                self._monitor = monitor
            stream = self._kws.create_stream()
            try:
                monitor.start()
                for pcm in monitor.chunks(320):
                    if self._done.is_set():
                        return
                    if not self._ready.is_set():
                        self._ready.set()
                        print(
                            f"[BARGE_IN] MONITOR_READY attempt={attempt}",
                            flush=True,
                        )
                    samples = (
                        np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    keyword = self._kws.accept(stream, samples)
                    if keyword:
                        print(
                            f"[BARGE_IN] KWS_DETECTED keyword={keyword}",
                            flush=True,
                        )
                        self.cancellation.cancel()
                        return
                if not self._done.is_set():
                    raise PulseCaptureError("wake monitor stream ended")
            except Exception as exc:
                self._last_error = exc
                if self._done.is_set():
                    return
                if attempt < self._max_attempts:
                    print(
                        "[BARGE_IN] MONITOR_RETRY "
                        f"attempt={attempt} error={type(exc).__name__}",
                        flush=True,
                    )
                    self._done.wait(0.15)
                else:
                    print(
                        "[BARGE_IN] MONITOR_ERROR "
                        f"attempt={attempt} error={type(exc).__name__}",
                        flush=True,
                    )
                    self._failed.set()
            finally:
                monitor.stop()
                with self._monitor_lock:
                    if self._monitor is monitor:
                        self._monitor = None

    def stop(self):
        self._done.set()
        with self._monitor_lock:
            monitor = self._monitor
        if monitor is not None:
            monitor.stop()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError("Wake monitor did not stop")


def speak_with_wake(tts, text, sink, *, capture, kws, before_playback=None):
    token = SpeechCancellation()
    done = threading.Event()
    monitor = PulseCapture(source=capture.source, sample_rate=capture.sample_rate,
                           channels=capture.channels, sample_format=capture.sample_format,
                           input_channels=capture.input_channels,
                           selected_channel=capture.selected_channel)
    stream = kws.create_stream()

    def listen():
        try:
            for pcm in monitor.chunks(320):
                if done.is_set():
                    break
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                if kws.accept(stream, samples):
                    token.cancel()
                    break
        except Exception as exc:
            if not done.is_set():
                print(f"[BARGE_IN] MONITOR_ERROR error={type(exc).__name__}", flush=True)

    try:
        monitor.start()
    except Exception as exc:
        monitor.stop()
        print(f"[BARGE_IN] UNAVAILABLE error={type(exc).__name__}", flush=True)
        return tts.speak(text, sink, before_playback=before_playback)
    thread = threading.Thread(target=listen, name="lucky-barge-in", daemon=True)
    thread.start()
    try:
        result = tts.speak(text, sink, before_playback=before_playback, cancellation=token)
        token.check()
        return result
    except Exception:
        token.check()  # Convert player termination into an intentional interruption.
        raise
    finally:
        done.set()
        monitor.stop()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Wake monitor did not stop")
