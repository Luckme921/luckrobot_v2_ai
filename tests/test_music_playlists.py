import unittest
from unittest.mock import Mock, patch

from robot_tools.music import MusicTools


def library():
    songs = [
        {"mid": "a", "title": "晴天", "artists": ["周杰伦"]},
        {"mid": "b", "title": "稻香", "artists": ["周杰伦"]},
        {"mid": "c", "title": "七里香", "artists": ["周杰伦"]},
        {"mid": "d", "title": "夜曲", "artists": ["周杰伦"]},
    ]
    cached = Mock()
    cached.data = {"playlists": {"mine": {"id": "mine", "name": "我喜欢", "songs": songs}}}
    cached.playlist_names.return_value = ["我喜欢"]
    return cached


class PlaylistMusicTests(unittest.TestCase):
    def make_music(self):
        controller = Mock()
        controller.play.side_effect = lambda query, **kwargs: (
            query.split(" ", 1)[1] + " - " + query.split(" ", 1)[0])
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "preferences": {"preferred_tracks": [
                                {"artist": "王菲", "title": "红豆"},
                                {"artist": "陈奕迅", "title": "十年"},
                            ]}}, controller=controller, library=library())
        return music, controller

    def test_playlist_request_plays_cached_songs_in_order(self):
        music, controller = self.make_music()
        request = music.local_request("播放我喜欢歌单")
        self.assertEqual(request["name"], "music_search")
        with patch("robot_tools.music.time.monotonic", return_value=100):
            answer = music.search(**request["arguments"])
        self.assertTrue(answer["playing"])
        self.assertEqual(controller.play.call_args.kwargs["preferred_mid"], "a")
        self.assertEqual(len(music.playlist_queue), 3)
        self.assertIsNone(music.advance_playlist_if_needed("晴天 - 周杰伦"))
        with patch("robot_tools.music.time.monotonic", return_value=110):
            advanced = music.advance_playlist_if_needed("别的歌 - 别人")
        self.assertTrue(advanced["playing"])
        self.assertEqual(controller.play.call_args.kwargs["preferred_mid"], "b")
        music.control("stop_music")
        self.assertEqual(music.playlist_queue, [])

    def test_personal_and_curated_recommendations_avoid_recent_items(self):
        music, _ = self.make_music()
        with patch("robot_tools.music.random.shuffle", side_effect=lambda items: None):
            first = music.search("推荐", utterance="推荐几首歌")
            second = music.search("推荐", utterance="推荐几首歌")
        self.assertEqual(first["status"], "needs_selection")
        self.assertEqual(len(first["candidates"]), 3)
        self.assertTrue(any(item["artists"] == ["王菲"] for item in first["candidates"]))
        self.assertTrue(any(item["artists"] == ["周杰伦"] for item in first["candidates"]))
        self.assertNotEqual([item["title"] for item in first["candidates"]],
                            [item["title"] for item in second["candidates"]])

    def test_recommend_from_my_playlist_only_uses_personal_cache(self):
        music, _ = self.make_music()
        request = music.local_request("从我的歌单推荐三首")
        self.assertEqual(request["arguments"]["query"], "推荐")
        reply = music.search(**request["arguments"])
        self.assertEqual(len(reply["candidates"]), 3)
        self.assertTrue(all(song["artists"] == ["周杰伦"] for song in reply["candidates"]))

    def test_random_song_can_use_personal_cache(self):
        music, controller = self.make_music()
        with patch("robot_tools.music.random.shuffle", side_effect=lambda items: None), \
             patch("robot_tools.music.random.random", return_value=0.0):
            reply = music.search("随便", utterance="随便放一首歌")
        self.assertTrue(reply["playing"])
        self.assertEqual(controller.play.call_args.kwargs["preferred_mid"], "a")

    def test_playlist_stops_after_last_track(self):
        music, controller = self.make_music()
        with patch("robot_tools.music.time.monotonic", return_value=100):
            music.search("歌单", utterance="播放我喜欢歌单")
        with patch("robot_tools.music.time.monotonic", return_value=110):
            for _ in range(3):
                music.advance_playlist_if_needed("其他歌 - 别人")
            finished = music.advance_playlist_if_needed("其他歌 - 别人")
        self.assertFalse(finished["playing"])
        self.assertIsNone(music.playlist_name)
        controller.stop.assert_called()
