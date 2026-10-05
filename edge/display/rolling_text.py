"""Split spoken text into short display rows and locate the active row."""
from __future__ import annotations

import unicodedata


_BREAKS = frozenset("，,。！？!?；;：:\n")


def _cells(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1


def display_rows(text: str, max_cells: int = 58) -> list[tuple[str, int, int]]:
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
