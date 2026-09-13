import unittest

import numpy as np

from edge.vision.face_identity import (
    score_owner_embedding,
)


class FaceIdentityTest(
    unittest.TestCase
):
    def test_exact_exemplar_match(
        self,
    ) -> None:
        exemplars = np.asarray(
            [
                [1.0, 0.0],
                [0.0, 1.0],
            ],
            dtype=np.float32,
        )

        centroid = np.asarray(
            [
                1.0,
                1.0,
            ],
            dtype=np.float32,
        )

        best, center = (
            score_owner_embedding(
                np.asarray(
                    [
                        2.0,
                        0.0,
                    ],
                    dtype=np.float32,
                ),
                exemplars,
                centroid,
            )
        )

        self.assertAlmostEqual(
            best,
            1.0,
            places=5,
        )

        self.assertAlmostEqual(
            center,
            2 ** -0.5,
            places=5,
        )

    def test_dimension_mismatch(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            score_owner_embedding(
                np.ones(
                    3,
                    dtype=np.float32,
                ),
                np.ones(
                    (
                        2,
                        4,
                    ),
                    dtype=np.float32,
                ),
                np.ones(
                    3,
                    dtype=np.float32,
                ),
            )


class OwnerPresenceTest(
    unittest.TestCase
):
    def _obs(
        self,
        *,
        best,
        center,
        area=0.10,
    ):
        from edge.vision.face_identity import (
            FaceIdentityObservation,
        )

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

    def test_owner_match(
        self,
    ):
        from edge.vision.face_identity import (
            resolve_owner_presence,
        )

        result = (
            resolve_owner_presence(
                (
                    self._obs(
                        best=0.60,
                        center=0.55,
                    ),
                )
            )
        )

        self.assertTrue(
            result.owner_present
        )

        self.assertEqual(
            result.usable_face_count,
            1,
        )

        self.assertEqual(
            result.unknown_face_count,
            0,
        )

    def test_unknown_rejected(
        self,
    ):
        from edge.vision.face_identity import (
            resolve_owner_presence,
        )

        result = (
            resolve_owner_presence(
                (
                    self._obs(
                        best=0.27,
                        center=0.26,
                    ),
                )
            )
        )

        self.assertFalse(
            result.owner_present
        )

        self.assertEqual(
            result.unknown_face_count,
            1,
        )

    def test_tiny_false_face_ignored(
        self,
    ):
        from edge.vision.face_identity import (
            resolve_owner_presence,
        )

        result = (
            resolve_owner_presence(
                (
                    self._obs(
                        best=0.80,
                        center=0.80,
                        area=0.005,
                    ),
                )
            )
        )

        self.assertFalse(
            result.owner_present
        )

        self.assertEqual(
            result.usable_face_count,
            0,
        )


class OwnerTemporalConsensusTest(
    unittest.TestCase
):
    def _result(
        self,
        owner: bool,
    ):
        from edge.vision.face_identity import (
            OwnerPresenceResult,
        )

        return OwnerPresenceResult(
            owner_present=owner,
            usable_face_count=1,
            unknown_face_count=(
                0 if owner else 1
            ),
            owner=None,
        )

    def test_owner_three_of_five(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerTemporalConsensus,
        )

        tracker = (
            OwnerTemporalConsensus()
        )

        tracker.update(
            self._result(True)
        )
        tracker.update(
            self._result(False)
        )

        result = tracker.update(
            self._result(True)
        )

        self.assertEqual(
            result.state,
            "uncertain",
        )

        result = tracker.update(
            self._result(True)
        )

        self.assertEqual(
            result.state,
            "owner",
        )

    def test_unknown_three_votes(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerTemporalConsensus,
        )

        tracker = (
            OwnerTemporalConsensus()
        )

        tracker.update(
            self._result(False)
        )
        tracker.update(
            self._result(False)
        )

        result = tracker.update(
            self._result(False)
        )

        self.assertEqual(
            result.state,
            "unknown",
        )


class OwnerTemporalFreshnessTest(
    unittest.TestCase
):
    def _owner_result(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerPresenceResult,
        )

        return OwnerPresenceResult(
            owner_present=True,
            usable_face_count=1,
            unknown_face_count=0,
            owner=None,
        )

    def _no_face_result(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerPresenceResult,
        )

        return OwnerPresenceResult(
            owner_present=False,
            usable_face_count=0,
            unknown_face_count=0,
            owner=None,
        )

    def test_short_no_face_gap_keeps_owner(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerTemporalConsensus,
        )

        tracker = OwnerTemporalConsensus(
            stale_after_seconds=2.0,
        )

        tracker.update(
            self._owner_result(),
            now=10.0,
        )
        tracker.update(
            self._owner_result(),
            now=10.1,
        )
        result = tracker.update(
            self._owner_result(),
            now=10.2,
        )

        self.assertEqual(
            result.state,
            "owner",
        )

        result = tracker.update(
            self._no_face_result(),
            now=11.0,
        )

        self.assertEqual(
            result.state,
            "owner",
        )

    def test_stale_owner_expires(
        self,
    ):
        from edge.vision.face_identity import (
            OwnerTemporalConsensus,
        )

        tracker = OwnerTemporalConsensus(
            stale_after_seconds=2.0,
        )

        tracker.update(
            self._owner_result(),
            now=20.0,
        )
        tracker.update(
            self._owner_result(),
            now=20.1,
        )
        tracker.update(
            self._owner_result(),
            now=20.2,
        )

        result = tracker.update(
            self._no_face_result(),
            now=22.3,
        )

        self.assertEqual(
            result.state,
            "uncertain",
        )

        self.assertEqual(
            result.samples,
            0,
        )

        self.assertEqual(
            result.owner_votes,
            0,
        )
