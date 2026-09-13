from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time


@dataclass(frozen=True)
class VisionFrame:
    path: Path
    captured_at: float
    jpeg_bytes: bytes


class FileRingBuffer:
    def __init__(
        self,
        directory: str | Path,
        pattern: str = "frame-*.jpg",
    ) -> None:
        self.directory = Path(
            directory
        )
        self.pattern = pattern

    @staticmethod
    def _is_complete_jpeg(
        data: bytes,
    ) -> bool:
        return (
            len(data) >= 4
            and data[:2] == b"\xff\xd8"
            and data[-2:] == b"\xff\xd9"
        )

    def _candidates(
        self,
    ) -> list[
        tuple[float, Path]
    ]:
        items = []

        if not self.directory.exists():
            return items

        for path in self.directory.glob(
            self.pattern
        ):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue

            if not path.is_file():
                continue

            items.append(
                (
                    stat.st_mtime,
                    path,
                )
            )

        items.sort(
            key=lambda item: (
                item[0],
                item[1].name,
            )
        )

        return items

    def _read_frame(
        self,
        path: Path,
        captured_at: float,
    ) -> VisionFrame | None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None

        if not self._is_complete_jpeg(
            data
        ):
            return None

        return VisionFrame(
            path=path,
            captured_at=captured_at,
            jpeg_bytes=data,
        )

    def latest_frame(
        self,
    ) -> VisionFrame | None:
        for captured_at, path in reversed(
            self._candidates()
        ):
            frame = self._read_frame(
                path,
                captured_at,
            )

            if frame is not None:
                return frame

        return None

    def frame_ago(
        self,
        seconds: float,
        *,
        now: float | None = None,
    ) -> VisionFrame | None:
        seconds = float(seconds)

        if seconds < 0:
            raise ValueError(
                "seconds must be >= 0"
            )

        if now is None:
            now = time.time()

        target = now - seconds

        candidates = sorted(
            self._candidates(),
            key=lambda item: abs(
                item[0] - target
            ),
        )

        for captured_at, path in candidates:
            frame = self._read_frame(
                path,
                captured_at,
            )

            if frame is not None:
                return frame

        return None

    def sample_recent(
        self,
        seconds: float,
        count: int,
        *,
        now: float | None = None,
    ) -> list[VisionFrame]:
        seconds = float(seconds)
        count = int(count)

        if seconds < 0:
            raise ValueError(
                "seconds must be >= 0"
            )

        if count <= 0:
            raise ValueError(
                "count must be > 0"
            )

        if now is None:
            now = time.time()

        cutoff = now - seconds

        candidates = [
            item
            for item in self._candidates()
            if item[0] >= cutoff
        ]

        valid = []

        for captured_at, path in candidates:
            frame = self._read_frame(
                path,
                captured_at,
            )

            if frame is not None:
                valid.append(frame)

        if len(valid) <= count:
            return valid

        if count == 1:
            return [
                valid[-1]
            ]

        last_index = len(valid) - 1

        indexes = [
            round(
                i
                * last_index
                / (count - 1)
            )
            for i in range(count)
        ]

        return [
            valid[index]
            for index in indexes
        ]
