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
        *,
        now=None,
    ):
        self.recent_args = (
            seconds,
            count,
        )

        return list(
            self._recent
        )


class ExplicitLatestVisionIntentTest(
    unittest.TestCase
):
    def test_explicit_current_visual_commands(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            is_explicit_latest_vision_command,
        )

        commands = (
            "看这里",
            "看看我",
            "看一下当前画面",
            "你看到什么",
            "你能看见什么",
            "看一下镜头",
            "看这里清人间",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(
                    is_explicit_latest_vision_command(
                        command
                    )
                )

    def test_non_visual_or_recent_commands_do_not_fast_path(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            is_explicit_latest_vision_command,
        )

        commands = (
            "我是谁",
            "你认识我吗",
            "今天天气怎么样",
            "刚才发生了什么",
            "过去五秒我做了什么",
            "回顾一下刚才的画面",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(
                    is_explicit_latest_vision_command(
                        command
                    )
                )


class ExplicitVisionFastPathInferenceTest(
    unittest.TestCase
):
    def test_current_action_uses_latest(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            infer_explicit_vision_fast_path,
        )

        for command in (
            "我现在在做什么",
            "我在做什么",
            "现在我在做什么",
        ):
            with self.subTest(command=command):
                request = (
                    infer_explicit_vision_fast_path(
                        command
                    )
                )

                self.assertIsNotNone(request)
                self.assertEqual(
                    request.mode,
                    "latest",
                )
                self.assertEqual(
                    request.count,
                    1,
                )

    def test_recent_visual_command_uses_recent(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            infer_explicit_vision_fast_path,
        )

        for command in (
            "刚才发生了什么",
            "我刚才做了什么",
            "过去几秒我做了什么",
            "刚才你看到了什么",
        ):
            with self.subTest(command=command):
                request = (
                    infer_explicit_vision_fast_path(
                        command
                    )
                )

                self.assertIsNotNone(request)
                self.assertEqual(
                    request.mode,
                    "recent",
                )
                self.assertEqual(
                    request.seconds,
                    5.0,
                )
                self.assertEqual(
                    request.count,
                    5,
                )

    def test_recent_beats_latest_overlap(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            infer_explicit_vision_fast_path,
        )

        request = (
            infer_explicit_vision_fast_path(
                "刚才你看到了什么"
            )
        )

        self.assertIsNotNone(request)
        self.assertEqual(
            request.mode,
            "recent",
        )

    def test_non_visual_has_no_fast_path(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            infer_explicit_vision_fast_path,
        )

        self.assertIsNone(
            infer_explicit_vision_fast_path(
                "今天天气怎么样"
            )
        )


class VisionFastPathToolPolicyTest(
    unittest.TestCase
):
    def test_pure_visual_disables_tools(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            explicit_vision_fast_path_tool_mode,
        )

        for command in (
            "我现在在做什么",
            "看一下当前画面简单描述",
            "刚才发生了什么",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    explicit_vision_fast_path_tool_mode(
                        command
                    ),
                    "none",
                )

    def test_web_compound_preserves_tools(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            explicit_vision_fast_path_tool_mode,
        )

        for command in (
            "看这里，查一下这个东西多少钱",
            "看这里，搜一下这个东西最新价格",
            "看看我，顺便查一下今天的天气",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    explicit_vision_fast_path_tool_mode(
                        command
                    ),
                    "auto",
                )

    def test_navigation_compound_preserves_tools(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            explicit_vision_fast_path_tool_mode,
        )

        for command in (
            "看这里然后带我去实验室",
            "看看这里再导航到厨房",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    explicit_vision_fast_path_tool_mode(
                        command
                    ),
                    "auto",
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
            now=104.0,
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

    def test_capture_rejects_stale_latest(
        self,
    ) -> None:
        from edge.vision.runtime_bridge import (
            capture_turn_snapshot,
        )

        stale = self._frame(
            "stale.jpg",
            100.0,
        )

        ring = FakeRing(
            latest=stale,
            recent=[],
        )

        snapshot = capture_turn_snapshot(
            ring,
            now=103.0,
        )

        self.assertIsNone(
            snapshot.latest
        )

        self.assertEqual(
            snapshot.recent,
            (),
        )

        self.assertEqual(
            snapshot.anchor_time,
            103.0,
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
            ring,
            now=100.0,
        )

        self.assertEqual(
            snapshot.recent[-1],
            latest,
        )
