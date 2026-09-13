from __future__ import annotations

from dataclasses import dataclass
import unittest

from edge.vision.runtime_bridge import (
    VisionSelectionError,
    select_vision_frames,
)


@dataclass
class Request:
    mode: str
    seconds: float
    count: int


class FakeRing:
    def __init__(
        self,
        *,
        latest=None,
        recent=None,
    ) -> None:
        self._latest = latest
        self._recent = list(
            recent
            or []
        )

        self.recent_args = None

    def latest_frame(
        self,
    ):
        return self._latest

    def sample_recent(
        self,
        seconds,
        count,
    ):
        self.recent_args = (
            seconds,
            count,
        )

        return list(
            self._recent
        )


class VisionRuntimeBridgeTest(
    unittest.TestCase
):
    def test_latest(
        self,
    ) -> None:
        frame = object()

        ring = FakeRing(
            latest=frame
        )

        frames = select_vision_frames(
            ring,
            Request(
                mode="latest",
                seconds=0.0,
                count=1,
            ),
        )

        self.assertEqual(
            frames,
            [frame],
        )

    def test_recent(
        self,
    ) -> None:
        frames_expected = [
            object(),
            object(),
            object(),
        ]

        ring = FakeRing(
            recent=frames_expected
        )

        frames = select_vision_frames(
            ring,
            Request(
                mode="recent",
                seconds=4.0,
                count=3,
            ),
        )

        self.assertEqual(
            frames,
            frames_expected,
        )

        self.assertEqual(
            ring.recent_args,
            (
                4.0,
                3,
            ),
        )

    def test_recent_requires_two_frames(
        self,
    ) -> None:
        ring = FakeRing(
            recent=[
                object()
            ]
        )

        with self.assertRaises(
            VisionSelectionError
        ):
            select_vision_frames(
                ring,
                Request(
                    mode="recent",
                    seconds=5.0,
                    count=5,
                ),
            )

    def test_invalid_mode(
        self,
    ) -> None:
        ring = FakeRing()

        with self.assertRaises(
            VisionSelectionError
        ):
            select_vision_frames(
                ring,
                Request(
                    mode="other",
                    seconds=0.0,
                    count=1,
                ),
            )


if __name__ == "__main__":
    unittest.main()


class TurnAlignedVisionTest(
    unittest.TestCase
):
    @staticmethod
    def _frame(
        name: str,
        captured_at: float,
    ):
        from pathlib import Path

        from edge.vision.ring_buffer import (
            VisionFrame,
        )

        return VisionFrame(
            path=Path(name),
            captured_at=captured_at,
            jpeg_bytes=(
                b"\xff\xd8"
                + name.encode("utf-8")
                + b"\xff\xd9"
            ),
        )

    def test_capture_turn_snapshot(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            capture_turn_snapshot,
        )

        frames = [
            self._frame(
                f"f{i}.jpg",
                100.0 + i,
            )
            for i in range(5)
        ]

        ring = FakeRing(
            latest=frames[-1],
            recent=frames,
        )

        snapshot = capture_turn_snapshot(
            ring,
            recent_seconds=5.0,
            recent_count=10,
        )

        self.assertEqual(
            snapshot.latest,
            frames[-1],
        )

        self.assertEqual(
            snapshot.anchor_time,
            104.0,
        )

        self.assertEqual(
            len(snapshot.recent),
            5,
        )

    def test_latest_uses_frozen_frame(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            TurnVisionSnapshot,
            select_turn_snapshot_frames,
        )

        frozen = self._frame(
            "frozen.jpg",
            100.0,
        )

        snapshot = TurnVisionSnapshot(
            anchor_time=100.0,
            latest=frozen,
            recent=(
                frozen,
            ),
        )

        frames = (
            select_turn_snapshot_frames(
                snapshot,
                Request(
                    mode="latest",
                    seconds=0.0,
                    count=1,
                ),
            )
        )

        self.assertEqual(
            frames,
            [frozen],
        )

    def test_recent_is_relative_to_anchor(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            TurnVisionSnapshot,
            select_turn_snapshot_frames,
        )

        frames = [
            self._frame(
                f"f{i}.jpg",
                95.0 + i,
            )
            for i in range(6)
        ]

        snapshot = TurnVisionSnapshot(
            anchor_time=100.0,
            latest=frames[-1],
            recent=tuple(
                frames
            ),
        )

        selected = (
            select_turn_snapshot_frames(
                snapshot,
                Request(
                    mode="recent",
                    seconds=2.0,
                    count=3,
                ),
            )
        )

        self.assertEqual(
            [
                frame.captured_at
                for frame in selected
            ],
            [
                98.0,
                99.0,
                100.0,
            ],
        )

    def test_capture_adds_latest(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            capture_turn_snapshot,
        )

        old = self._frame(
            "old.jpg",
            99.0,
        )

        latest = self._frame(
            "latest.jpg",
            100.0,
        )

        ring = FakeRing(
            latest=latest,
            recent=[
                old
            ],
        )

        snapshot = capture_turn_snapshot(
            ring
        )

        self.assertEqual(
            snapshot.recent[-1],
            latest,
        )
