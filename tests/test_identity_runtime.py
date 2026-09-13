import unittest

from edge.vision.face_identity import (
    FaceIdentityObservation,
)
from edge.vision.identity_runtime import (
    classify_turn_identity,
)
from edge.vision.ring_buffer import (
    VisionFrame,
)
from edge.vision.runtime_bridge import (
    TurnVisionSnapshot,
)


def observation(
    *,
    best,
    center,
    area=0.10,
):
    return FaceIdentityObservation(
        box=(
            0.0,
            0.0,
            100.0,
            100.0,
        ),
        detection_score=0.9,
        area_ratio=area,
        best_exemplar_cosine=best,
        centroid_cosine=center,
    )


class FakeScorer:
    def analyze_jpeg(
        self,
        jpeg_bytes,
    ):
        kind = jpeg_bytes.decode(
            "ascii"
        )

        if kind == "owner":
            return (
                observation(
                    best=0.60,
                    center=0.55,
                ),
            )

        if kind == "unknown":
            return (
                observation(
                    best=0.20,
                    center=0.15,
                ),
            )

        return ()


def snapshot(
    kinds,
):
    frames = tuple(
        VisionFrame(
            path=None,
            captured_at=float(
                index
            ),
            jpeg_bytes=(
                kind.encode(
                    "ascii"
                )
            ),
        )
        for index, kind
        in enumerate(kinds)
    )

    return TurnVisionSnapshot(
        anchor_time=(
            frames[-1].captured_at
            if frames
            else 0.0
        ),
        latest=(
            frames[-1]
            if frames
            else None
        ),
        recent=frames,
    )


class TurnIdentityTest(
    unittest.TestCase
):
    def test_owner_three_of_five(
        self,
    ):
        result = (
            classify_turn_identity(
                snapshot(
                    [
                        "unknown",
                        "owner",
                        "owner",
                        "none",
                        "owner",
                    ]
                ),
                FakeScorer(),
            )
        )

        self.assertEqual(
            result.state,
            "owner",
        )
        self.assertEqual(
            result.owner_votes,
            3,
        )

    def test_unknown_three_of_five(
        self,
    ):
        result = (
            classify_turn_identity(
                snapshot(
                    [
                        "unknown",
                        "owner",
                        "unknown",
                        "none",
                        "unknown",
                    ]
                ),
                FakeScorer(),
            )
        )

        self.assertEqual(
            result.state,
            "unknown",
        )
        self.assertEqual(
            result.unknown_votes,
            3,
        )

    def test_insufficient_evidence(
        self,
    ):
        result = (
            classify_turn_identity(
                snapshot(
                    [
                        "owner",
                        "none",
                        "none",
                        "none",
                        "unknown",
                    ]
                ),
                FakeScorer(),
            )
        )

        self.assertEqual(
            result.state,
            "uncertain",
        )
        self.assertEqual(
            result.usable_votes,
            2,
        )


if __name__ == "__main__":
    unittest.main()
