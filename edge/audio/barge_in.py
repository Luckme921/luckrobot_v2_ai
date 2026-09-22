"""Wake-only monitoring during reply speech. Main ASR remains paused."""
import threading
import numpy as np
from edge.audio.capture.pulse import PulseCapture
from edge.audio.tts.cancellation import SpeechCancellation


class WakeInterruptMonitor:
    """Keep only Lucky KWS active while the normal capture loop is stopped."""
    def __init__(self, capture, kws):
        self.cancellation = SpeechCancellation()
        self._done = threading.Event()
        self._monitor = PulseCapture(
            source=capture.source, sample_rate=capture.sample_rate,
            channels=capture.channels, sample_format=capture.sample_format,
            input_channels=capture.input_channels,
            selected_channel=capture.selected_channel)
        self._kws = kws
        self._thread = None

    def start(self):
        self._monitor.start()
        self._thread = threading.Thread(
            target=self._listen, name="lucky-turn-interrupt", daemon=True)
        self._thread.start()
        return self

    def _listen(self):
        stream = self._kws.create_stream()
        try:
            for pcm in self._monitor.chunks(320):
                if self._done.is_set():
                    break
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                if self._kws.accept(stream, samples):
                    self.cancellation.cancel()
                    break
        except Exception as exc:
            if not self._done.is_set():
                print(f"[BARGE_IN] MONITOR_ERROR error={type(exc).__name__}", flush=True)

    def stop(self):
        self._done.set()
        self._monitor.stop()
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
