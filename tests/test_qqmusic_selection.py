from __future__ import annotations

import unittest
import threading
import subprocess
from unittest.mock import Mock, patch
from selenium.common.exceptions import InvalidSessionIdException
from urllib3.exceptions import MaxRetryError

from edge.music.qqmusic import (
    QQMusicController,
    QQMusicError,
    _driver_locked,
)


class QQMusicSessionRecoveryTest(unittest.TestCase):
    def test_audio_route_retries_disappeared_firefox_input(self):
        controller = QQMusicController(profile_path=".", speaker_match_any=["XVF3800"])
        controller._firefox_sink_inputs = Mock(side_effect=[["old"], ["new"]])
        def run(args, **kwargs):
            if args[:2] == ["pactl", "move-sink-input"] and args[2] == "old":
                raise subprocess.CalledProcessError(1, args, stderr="No such entity")
            return Mock(returncode=0)
        with patch("edge.music.qqmusic.resolve_speaker", return_value="usb-speaker"), \
             patch("edge.music.qqmusic.subprocess.run", side_effect=run), \
             patch("edge.music.qqmusic.time.sleep"):
            self.assertEqual(controller.route_audio(wait_seconds=1), "usb-speaker")
        self.assertEqual(controller._firefox_sink_inputs.call_count, 2)

    def test_stop_pauses_every_active_player_window(self):
        controller = QQMusicController(profile_path=".")
        driver = Mock()
        driver.window_handles = ["player-one", "player-two"]
        driver.current_url = "https://y.qq.com/portal/player.html"
        driver.find_element.return_value.get_attribute.return_value = "btn_big_play btn_big_play--pause"
        with patch.object(controller, "_require_driver", return_value=driver):
            controller.stop()
        self.assertEqual(driver.execute_script.call_count, 2)

    def test_search_candidate_reads_artist_from_song_row(self):
        controller = QQMusicController(profile_path=".")
        driver = Mock()
        link = Mock()
        link.text = "泡沫"
        link.get_attribute.return_value = "https://y.qq.com/n/ryqq/songDetail/song-123"
        link.is_displayed.return_value = True
        artist_cell = Mock(text="G.E.M.邓紫棋 / 合唱歌手")
        link.find_element.return_value.find_elements.return_value = [artist_cell]
        driver.find_elements.return_value = [link]
        with patch.object(controller, "_require_driver", return_value=driver), \
             patch.object(controller, "_ensure_search_window"), \
             patch.object(controller, "_wait") as wait:
            wait.return_value.until.side_effect = lambda collect: collect(driver)
            songs = controller.search_candidates("邓紫棋 泡沫")
        self.assertEqual(songs[0]["artists"], ["G.E.M.邓紫棋", "合唱歌手"])

    def test_search_restarts_dead_browser_once(self):
        class FakeController:
            def __init__(self):
                self._driver_lock = threading.RLock()
                self.calls = 0
                self.closed = 0

            def close(self):
                self.closed += 1

            @_driver_locked
            def search_candidates(self, query):
                self.calls += 1
                if self.calls == 1:
                    raise InvalidSessionIdException("browser exited")
                return [query]

        controller = FakeController()
        self.assertEqual(controller.search_candidates("泡沫"), ["泡沫"])
        self.assertEqual((controller.calls, controller.closed), (2, 1))

    def test_search_restarts_when_driver_connection_is_gone(self):
        class FakeController:
            def __init__(self):
                self._driver_lock = threading.RLock()
                self.calls = 0
                self.closed = 0

            def close(self):
                self.closed += 1

            @_driver_locked
            def search_candidates(self, query):
                self.calls += 1
                if self.calls == 1:
                    raise MaxRetryError(None, "/session/dead", reason="refused")
                return [query]

        controller = FakeController()
        self.assertEqual(controller.search_candidates("安和桥"), ["安和桥"])
        self.assertEqual((controller.calls, controller.closed), (2, 1))

    def test_controls_do_not_repeat_after_browser_exits(self):
        class FakeController:
            def __init__(self):
                self._driver_lock = threading.RLock()
                self.calls = 0
                self.closed = 0

            def close(self):
                self.closed += 1

            @_driver_locked
            def next(self):
                self.calls += 1
                raise InvalidSessionIdException("browser exited")

        controller = FakeController()
        with self.assertRaises(QQMusicError):
            controller.next()
        self.assertEqual((controller.calls, controller.closed), (1, 1))


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
