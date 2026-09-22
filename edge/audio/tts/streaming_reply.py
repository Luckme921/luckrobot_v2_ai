"""Split streamed model text at punctuation and synthesize chunks in order."""
import queue
import re
import threading


_BOUNDARY = re.compile(r"^(.+?[，、；。！？,;!?\n]+)(.*)$", re.S)


class StreamingReplySpeaker:
    def __init__(self, tts, sink, cancellation, before_playback=None):
        self.tts = tts
        self.sink = sink
        self.cancellation = cancellation
        self.before_playback = before_playback
        self._buffer = ""
        self._queue = queue.Queue()
        self._received = False
        self._played = False
        self._error = None
        self._first = True
        self._finished = False
        self._thread = threading.Thread(
            target=self._run, name="streaming-reply-tts", daemon=True)
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
            if chunk.strip():
                self._queue.put(chunk.strip())

    def finish(self):
        if self._buffer.strip():
            self._queue.put(self._buffer.strip())
        self._buffer = ""
        self._queue.put(None)
        self._thread.join()
        self._finished = True
        self.cancellation.check()
        if self._error is not None:
            raise self._error
        return self._played

    def cancel(self):
        self._buffer = ""
        self._queue.put(None)
        self._thread.join(timeout=3)

    def _run(self):
        try:
            while True:
                chunk = self._queue.get()
                if chunk is None:
                    return
                self.cancellation.check()
                hook = self.before_playback if self._first else None
                self.tts.speak(chunk, self.sink, before_playback=hook,
                               cancellation=self.cancellation)
                self._first = False
                self._played = True
        except BaseException as exc:
            self._error = exc
