"""Per-utterance cancellation; never targets unrelated audio processes."""
import threading


class SpeechInterrupted(Exception):
    pass


class SpeechCancellation:
    def __init__(self):
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._players = []
        self._callbacks = []

    def check(self):
        if self.event.is_set():
            raise SpeechInterrupted()

    def register(self, player):
        with self._lock:
            self._players.append(player)
            if self.event.is_set() and player.poll() is None:
                player.kill()

    def register_callback(self, callback):
        with self._lock:
            self._callbacks.append(callback)
            cancelled = self.event.is_set()
        if cancelled:
            callback()

    def cancel(self):
        with self._lock:
            self.event.set()
            callbacks = list(self._callbacks)
            for player in self._players:
                if player.poll() is None:
                    try:
                        player.kill()
                    except ProcessLookupError:
                        pass
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
