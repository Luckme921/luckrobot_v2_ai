from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from edge.vision.ring_buffer import (
    FileRingBuffer,
)


JPEG = (
    b"\xff\xd8"
    b"luckrobot"
    b"\xff\xd9"
)


class FileRingBufferTests(
    unittest.TestCase
):
    def setUp(
        self,
    ) -> None:
        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.root = Path(
            self.temp.name
        )

        self.ring = FileRingBuffer(
            self.root
        )

    def tearDown(
        self,
    ) -> None:
        self.temp.cleanup()

    def _write(
        self,
        index: int,
        captured_at: float,
        *,
        valid: bool = True,
    ) -> Path:
        path = (
            self.root
            / f"frame-{index:06d}.jpg"
        )

        path.write_bytes(
            JPEG
            if valid
            else b"incomplete"
        )

        os.utime(
            path,
            (
                captured_at,
                captured_at,
            ),
        )

        return path

    def test_latest_frame(
        self,
    ) -> None:
        self._write(
            1,
            101.0,
        )

        newest = self._write(
            2,
            102.0,
        )

        frame = (
            self.ring
            .latest_frame()
        )

        self.assertIsNotNone(
            frame
        )

        self.assertEqual(
            frame.path,
            newest,
        )

        self.assertEqual(
            frame.jpeg_bytes,
            JPEG,
        )

    def test_latest_skips_incomplete(
        self,
    ) -> None:
        expected = self._write(
            1,
            101.0,
        )

        self._write(
            2,
            102.0,
            valid=False,
        )

        frame = (
            self.ring
            .latest_frame()
        )

        self.assertIsNotNone(
            frame
        )

        self.assertEqual(
            frame.path,
            expected,
        )

    def test_frame_ago(
        self,
    ) -> None:
        self._write(
            1,
            96.0,
        )

        expected = self._write(
            2,
            98.0,
        )

        self._write(
            3,
            100.0,
        )

        frame = (
            self.ring
            .frame_ago(
                2.0,
                now=100.0,
            )
        )

        self.assertIsNotNone(
            frame
        )

        self.assertEqual(
            frame.path,
            expected,
        )

    def test_sample_recent_evenly(
        self,
    ) -> None:
        for index in range(6):
            self._write(
                index,
                95.0 + index,
            )

        frames = (
            self.ring
            .sample_recent(
                5.0,
                3,
                now=100.0,
            )
        )

        self.assertEqual(
            len(frames),
            3,
        )

        self.assertEqual(
            [
                frame.path.name
                for frame in frames
            ],
            [
                "frame-000000.jpg",
                "frame-000002.jpg",
                "frame-000005.jpg",
            ],
        )

    def test_invalid_arguments(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            self.ring.frame_ago(
                -1.0
            )

        with self.assertRaises(
            ValueError
        ):
            self.ring.sample_recent(
                5.0,
                0,
            )


if __name__ == "__main__":
    unittest.main()
