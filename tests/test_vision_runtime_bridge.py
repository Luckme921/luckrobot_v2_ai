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
