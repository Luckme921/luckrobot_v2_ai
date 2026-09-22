import unittest
from unittest.mock import Mock
from robot_tools.music import TangMusicProvider, MusicTools

class TangTests(unittest.TestCase):
    def test_search_then_resolve_exact_id(self):
        provider = TangMusicProvider({})
        provider._request = Mock(side_effect=[
            [{"song_mid": "abc", "song_title": "测试", "singer_name": "歌手"}],
            {"song_mid": "abc", "song_play_url_standard": "https://audio.example/song.mp3",
             "song_play_url_accom": "https://audio.example/accompaniment.mp3"}])
        player = Mock()
        music = MusicTools({"enabled": True, "provider": "http"}, player=player)
        music.provider = provider
        self.assertEqual(music.search("测试")["status"], "needs_selection")
        player.play.assert_not_called()
        self.assertEqual(provider._request.call_count, 1)
        self.assertTrue(music.select("第一首")["playing"])
        provider._request.assert_called_with({"msg": "测试", "type": "json", "mid": "abc"})
        player.play.assert_called_once_with("https://audio.example/song.mp3")

    def test_reject_changed_id_and_non_audio(self):
        provider = TangMusicProvider({})
        for response in ({"song_mid": "other", "song_play_url": "https://example.com/x"},
                         {"song_mid": "abc", "song_play_url": "file:///tmp/x"},
                         {"song_mid": "abc", "song_play_url_accom": "https://example.com/x"}):
            provider._request = Mock(return_value=response)
            with self.assertRaises(ValueError):
                provider.resolve({"id": "abc", "query": "测试"})

    def test_invalid_search_and_duplicates(self):
        provider = TangMusicProvider({})
        provider._request = Mock(return_value={"data": [{"song_mid": "a", "song_title": "x"}]*5})
        self.assertEqual(len(provider.search("x")), 1)
        provider._request.return_value = {"error": "offline"}
        with self.assertRaises(ValueError): provider.search("x")

class FallbackTests(unittest.TestCase):
    def test_empty_or_failed_primary_uses_backup(self):
        from robot_tools.music import FallbackMusicProvider
        for failure in (False, True):
            provider = FallbackMusicProvider({})
            primary, backup = Mock(), Mock()
            primary.search.return_value = []
            if failure: primary.search.side_effect = TimeoutError()
            backup.search.return_value = [{"id": "1", "resolver": "netease"}]
            provider.providers = {"tang": primary, "netease": backup}
            songs = provider.search("稻香")
            self.assertEqual(songs[0]["resolver"], "netease")
            provider.resolve(songs[0])
            backup.resolve.assert_called_once_with(songs[0])
            primary.resolve.assert_not_called()

    def test_success_also_searches_backup(self):
        from robot_tools.music import FallbackMusicProvider
        provider = FallbackMusicProvider({})
        primary, backup = Mock(), Mock()
        primary.search.return_value = [{"id": "1", "resolver": "tang"}]
        backup.search.return_value = []
        provider.providers = {"tang": primary, "netease": backup}
        provider.search("稻香")
        backup.search.assert_called_once_with("稻香")

    def test_netease_search_mapping(self):
        from robot_tools.music import NeteaseMusicProvider
        provider = NeteaseMusicProvider({})
        provider._request = Mock(return_value={"code": 200, "data": [
            {"id": 123, "song": "测试", "singer": "歌手"},
            {"id": 123, "song": "重复"}, {"id": None, "song": "坏数据"}]})
        songs = provider.search("测试")
        self.assertEqual(len(songs), 1)
        self.assertEqual(songs[0]["id"], "123")
        self.assertEqual(songs[0]["resolver"], "netease")

    def test_netease_resolve_rejects_changed_title(self):
        from robot_tools.music import NeteaseMusicProvider
        from unittest.mock import patch
        provider = NeteaseMusicProvider({})
        with patch("robot_tools.music.TangMusicProvider._request", return_value=[{"name": "错歌", "url": "https://example.com/a"}]):
            with self.assertRaises(ValueError): provider.resolve({"id": "123", "title": "测试"})
