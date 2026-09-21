"""Per-utterance cancellation; never targets unrelated audio processes."""
import threading


class SpeechInterrupted(Exception):
    pass


class SpeechCancellation:
    def __init__(self):
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._players = []

    def check(self):
        if self.event.is_set():
            raise SpeechInterrupted()

    def register(self, player):
        with self._lock:
            self._players.append(player)
            if self.event.is_set() and player.poll() is None:
                player.kill()

    def cancel(self):
        with self._lock:
            self.event.set()
            for player in self._players:
                if player.poll() is None:
                    try:
                        player.kill()
                    except ProcessLookupError:
                        pass
