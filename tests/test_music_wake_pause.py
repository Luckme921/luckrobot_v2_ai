import threading
import time
import unittest
from unittest.mock import Mock, patch
from robot_tools.music import MusicTools
from edge.music.qqmusic import QQMusicController, QQMusicError


class MusicWakePauseTests(unittest.TestCase):
    def test_wake_pauses_browser_even_when_cached_playing_flag_is_false(self):
        controller = Mock(running=True)
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.current_song = {"title": "安河桥"}
        self.assertFalse(music.playing)
        result = music.pause_for_conversation()
        controller.pause.assert_called_once()
        self.assertFalse(result["playing"])
        self.assertEqual(result["music"]["title"], "安河桥")

    def test_backend_failure_does_not_falsely_mark_music_paused(self):
        controller = Mock(running=True)
        controller.pause.side_effect = QQMusicError("timeout")
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.playing = True
        with self.assertRaises(QQMusicError):
            music.pause_for_conversation()
        self.assertTrue(music.playing)

    def test_pause_waits_for_inflight_resume_then_wins(self):
        entered, release = threading.Event(), threading.Event()
        controller = Mock(running=True)
        def resume():
            entered.set()
            release.wait(1)
            return "安河桥 - 宋冬野"
        controller.resume.side_effect = resume
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        a = threading.Thread(target=lambda: music.control("resume_music"))
        b = threading.Thread(target=music.pause_for_conversation)
        a.start()
        self.assertTrue(entered.wait(1))
        b.start()
        release.set()
        a.join(2); b.join(2)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertFalse(music.playing)
        music.playlist_name = "我喜欢"
        with patch.object(music, "_play_next_playlist") as next_song:
            self.assertIsNone(music.advance_playlist_if_needed("另一首"))
            next_song.assert_not_called()

    def test_http_player_paused_and_unstarted_browser_not_launched(self):
        player = Mock(active=True)
        music = MusicTools({"enabled": True, "provider": "http"}, player=player)
        music.pause_for_conversation()
        player.pause.assert_called_once()
        controller = Mock(running=False)
        MusicTools({"enabled": True}, controller=controller).pause_for_conversation()
        controller.pause.assert_not_called()

    def test_qq_pause_checks_all_tabs_and_restores_original(self):
        controller = QQMusicController(profile_path=".")
        driver = Mock()
        controller._driver = driver
        driver.current_window_handle = "one"
        driver.window_handles = ["one", "two"]
        driver.current_url = "https://y.qq.com/portal/player.html"
        driver.find_element.return_value.get_attribute.return_value = "btn_big_play--pause"
        with patch.object(controller, "_wait") as wait:
            controller.pause()
            self.assertEqual(wait.return_value.until.call_count, 2)
        clicks = [call for call in driver.execute_script.call_args_list if "arguments[0].click()" in call.args[0]]
        self.assertEqual(len(clicks), 2)
        self.assertEqual(driver.switch_to.window.call_args.args, ("one",))
