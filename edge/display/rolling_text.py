"""Split spoken text into short display rows and locate the active row."""
from __future__ import annotations

import unicodedata
import threading


_BREAKS = frozenset("，,。！？!?；;：:\n")


def _cells(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def display_rows(text: str, max_cells: int = 38) -> list[tuple[str, int, int]]:
    """Return (visible text, start offset, end offset), preserving input order."""
    rows = []
    start = 0
    width = 0
    for pos, char in enumerate(text):
        width += _cells(char)
        decimal = (char in ".," and pos > 0 and pos + 1 < len(text)
                   and text[pos - 1].isdigit() and text[pos + 1].isdigit())
        if (char in _BREAKS and not decimal) or width >= max_cells:
            segment = text[start:pos + 1].strip()
            if segment:
                rows.append((segment, start, pos + 1))
            start = pos + 1
            width = 0
    if start < len(text):
        segment = text[start:].strip()
        if segment:
            rows.append((segment, start, len(text)))
    return rows


def row_index(rows: list[tuple[str, int, int]], progress: int) -> int:
    if not rows:
        return 0
    for index, (_, _, end) in enumerate(rows):
        if progress < end:
            return index
    return len(rows) - 1


class SpokenTextScroller:
    """Approximate line progress while a non-streamed TTS reply is playing."""

    def __init__(self, text: str, publish, *, seconds_per_cell: float = 0.11):
        self.rows = display_rows(text)
        self.publish = publish
        self.seconds_per_cell = seconds_per_cell
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None or len(self.rows) < 2:
            return
        self._thread = threading.Thread(target=self._run, name="display-speech-scroll",
                                        daemon=True)
        self._thread.start()

    def _run(self):
        for row, _, end in self.rows[:-1]:
            cells = sum(_cells(char) for char in row)
            if self._stop.wait(max(0.5, cells * self.seconds_per_cell)):
                return
            self.publish(end)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
