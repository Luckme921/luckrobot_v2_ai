from __future__ import annotations

import unittest

from edge.music.qqmusic import (
    QQMusicController,
)


class QQMusicSelectionTest(
    unittest.TestCase
):
    def test_original_beats_unrequested_live_cover(
        self,
    ) -> None:
        query = "宋冬野 安河桥"

        original = (
            QQMusicController
            ._search_result_score(
                query,
                "安和桥",
                (
                    "安和桥\\n"
                    "宋冬野\\n"
                    "安和桥北"
                ),
            )
        )

        live_cover = (
            QQMusicController
            ._search_result_score(
                query,
                "安河桥 (Live)",
                (
                    "安河桥 (Live)\\n"
                    "罗书玮 /宋冬野"
                ),
            )
        )

        self.assertGreater(
            original,
            live_cover,
        )

    def test_requested_live_not_penalized(
        self,
    ) -> None:
        score = (
            QQMusicController
            ._search_result_score(
                "周杰伦 晴天 Live",
                "晴天 (Live)",
                "晴天 (Live)\\n周杰伦",
            )
        )

        self.assertGreater(
            score,
            0,
        )


if __name__ == "__main__":
    unittest.main()


class QQMusicSafetyTest(
    unittest.TestCase
):
    def test_title_only_tied_results_are_ambiguous(
        self,
    ) -> None:
        candidates = [
            (
                10.0,
                "后来",
                "后来\n歌手A",
                None,
            ),
            (
                10.0,
                "后来",
                "后来\n歌手B",
                None,
            ),
        ]

        self.assertTrue(
            QQMusicController
            ._selection_is_ambiguous(
                "后来",
                candidates,
            )
        )

    def test_clear_winner_is_not_ambiguous(
        self,
    ) -> None:
        candidates = [
            (
                18.0,
                "晴天",
                "晴天\n周杰伦",
                None,
            ),
            (
                10.0,
                "晴天 (Live)",
                "晴天 (Live)\n其他歌手",
                None,
            ),
        ]

        self.assertFalse(
            QQMusicController
            ._selection_is_ambiguous(
                "周杰伦 晴天",
                candidates,
            )
        )


class QQMusicRepeatedTitleTest(
    unittest.TestCase
):
    def test_repeated_song_title_is_valid(
        self,
    ) -> None:
        repeated = (
            QQMusicController
            ._search_result_score(
                "宋冬野 斑马 斑马",
                "斑马，斑马",
                "斑马，斑马\n宋冬野",
            )
        )

        wrong_live = (
            QQMusicController
            ._search_result_score(
                "宋冬野 斑马 斑马",
                "斑马 (Live)",
                "斑马 (Live)\n其他歌手",
            )
        )

        self.assertGreater(
            repeated,
            wrong_live,
        )


class QQMusicQualifierSafetyTest(
    unittest.TestCase
):
    def test_artist_term_is_covered(
        self,
    ) -> None:
        missing = (
            QQMusicController
            ._unmatched_query_terms(
                "宋冬野 安河桥",
                "安和桥",
                "安和桥\n宋冬野",
            )
        )

        self.assertEqual(
            missing,
            [],
        )

    def test_wrong_artist_is_detected(
        self,
    ) -> None:
        missing = (
            QQMusicController
            ._unmatched_query_terms(
                "国风堂 醉花音",
                "醉花音",
                (
                    "醉花音\n"
                    "DeepMountains深山"
                ),
            )
        )

        self.assertIn(
            "国风堂",
            missing,
        )
