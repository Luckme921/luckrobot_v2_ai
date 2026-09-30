import unittest
from unittest.mock import Mock
from robot_tools.music import (
    FallbackMusicProvider,
    MusicTools,
    explicit_candidate,
    has_explicit_music_intent,
    is_random_request,
)

def song(id,title="龙卷风",artist="周杰伦"):
    return dict(id=id,title=title,artists=[artist],backend="http",url="https://example.com/"+id)
class LocalMusicTests(unittest.TestCase):
    def test_fresh_music_search_requires_explicit_cue(self):
        for text in ["放一首", "一首歌", "音乐", "歌曲", "来点小曲", "播放晴天", "我想听稻香"]:
            with self.subTest(text=text):
                self.assertTrue(has_explicit_music_intent(text))
        for text in ["马蹄", "苹果", "周杰伦", "为什么播放音乐没声音", "不要播放歌曲"]:
            with self.subTest(text=text):
                self.assertFalse(has_explicit_music_intent(text))

    def setup_music(self,songs):
        player=Mock()
        player.active = True
        music=MusicTools({"enabled":True,"provider":"http","http":{"auto_play_enabled":True}},player=player)
        music.provider=Mock(url="https://example.com")
        music.provider.search.return_value=songs
        return music,player

    def test_natural_player_exit_clears_music_state_once(self):
        music, player = self.setup_music([])
        music.playing = True
        music.current_song = {"title": "晴天", "artists": ["周杰伦"]}
        player.active = False
        self.assertTrue(music.playback_finished())
        self.assertFalse(music.playing)
        self.assertIsNone(music.current_song)
        self.assertFalse(music.playback_finished())

    def test_paused_player_is_not_treated_as_finished(self):
        music, player = self.setup_music([])
        music.playing = False
        music.current_song = {"title": "晴天", "artists": ["周杰伦"]}
        player.active = True
        self.assertFalse(music.playback_finished())
        self.assertIsNotNone(music.current_song)
    def test_random_does_not_search_song_literal_or_ask_selection(self):
        for phrase in [
            "播放一首歌", "随便放一首歌", "放点音乐", "随便放一首", "每日推荐",
            "放一首音乐，随便播放一首就可以", "随便播放一首歌就可以",
            "帮我随机播放一首好听的歌吧", "来点小曲",
        ]:
            music,player=self.setup_music([song("a")])
            request=music.local_request(phrase)
            self.assertIsNotNone(request,phrase)
            self.assertTrue(music.search(**request["arguments"])["playing"])
            self.assertNotEqual(music.provider.search.call_args.args[0],"歌")
            player.play.assert_called_once()

    def test_full_random_request_replaces_old_pending_list(self):
        music, player = self.setup_music([song("old", "冷门故事", "陌生歌手")])
        music.pending = [song("old", "冷门故事", "陌生歌手")]
        music.deadline = music.clock() + 120
        request = music.local_request("随便播放一首歌就可以")
        self.assertEqual(request["name"], "music_search")
        self.assertTrue(is_random_request(request["arguments"]["utterance"]))

    def test_preferred_track_is_searched_and_played_without_selection(self):
        player = Mock()
        music = MusicTools({
            "enabled": True,
            "provider": "http",
            "http": {"auto_play_enabled": True},
            "preferences": {
                "search_attempts": 1,
                "preferred_tracks": [{"artist": "周杰伦", "title": "晴天"}],
            },
        }, player=player)
        music.provider = Mock(url="https://example.com")
        music.provider.search.return_value = [
            song("cover", "晴天", "翻唱歌手"),
            song("original", "晴天 (Live)", "周杰伦"),
        ]
        music.provider.resolve.side_effect = lambda item: "https://example.com/" + item["id"]
        answer = music.search("随便", utterance="随机播放一首歌")
        self.assertTrue(answer["playing"])
        music.provider.search.assert_called_once_with("周杰伦 晴天")
        player.play.assert_called_once_with("https://example.com/original")
    def test_natural_singer_choice(self):
        music,player=self.setup_music([song("a"),song("b",artist="邓紫棋")])
        reply=music.search("龙卷风")
        self.assertIn("还是邓紫棋",reply["message"])
        self.assertEqual(music.local_request("周杰伦的")["name"],"music_select")
        self.assertTrue(music.select("周杰伦的")["playing"])
        player.play.assert_called_once_with("https://example.com/a")
    def test_explicit_title_singer_autoplays(self):
        music,player=self.setup_music([song("b",artist="邓紫棋"),song("a")])
        self.assertTrue(music.search("周杰伦的龙卷风")["playing"])
        player.play.assert_called_once_with("https://example.com/a")

    def test_repeated_natural_request_is_parsed_locally(self):
        music, _ = self.setup_music([])
        request = music.local_request("我想听我想听宋冬野的安河桥")
        self.assertEqual(request["name"], "music_search")
        self.assertEqual(request["arguments"]["query"], "宋冬野 安河桥")
        request = music.local_request("你可以放一首歌吗？")
        self.assertEqual(request["arguments"]["query"], "随便")
        self.assertIsNone(music.local_request("请告诉我今天的天气"))

    def test_natural_candidates_and_context_selection(self):
        music, player = self.setup_music([
            song("guitar", "安河桥 (吉他版)", "田洪林"),
            song("dj", "安河桥 (DJ版)", "Dj榜单"),
            song("cover", "莉莉安(翻自宋冬野)", "叫我老宋"),
        ])
        reply = music.search("安河桥")
        self.assertNotIn("1，", reply["message"])
        self.assertIn("田洪林的《安河桥 (吉他版)》", reply["message"])
        self.assertEqual(music.local_request("吉他版的")["name"], "music_select")
        self.assertTrue(music.select("田洪林的")["playing"])
        player.play.assert_called_once_with("https://example.com/guitar")

    def test_merged_results_are_ranked_before_visible_candidates(self):
        music, _ = self.setup_music([
            song("unrelated", "南山南到安河桥北", "陶玖"),
            song("original", "安河桥", "宋冬野"),
        ])
        music.auto_play_enabled = False
        reply = music.search("宋冬野的安河桥")
        self.assertEqual(reply["candidates"][0]["id"], "original")
    def test_pending_random_and_bounded_failure(self):
        music,player=self.setup_music([song("a"),song("b")])
        music.search("龙卷风")
        self.assertEqual(music.local_request("随便")["name"],"music_select")
        player.play.side_effect=RuntimeError()
        reply=music.select("随便")
        self.assertFalse(reply["ok"])
        self.assertEqual(player.play.call_count,2)
        self.assertFalse(music.has_pending)
    def test_negation_and_questions_not_local_commands(self):
        music,_=self.setup_music([])
        for text in ["不要播放龙卷风","怎么播放音乐","播放音乐为什么没声音","如果播放音乐会怎样"]:
            self.assertIsNone(music.local_request(text))

    def test_explicit_near_match_picks_highest_even_for_version(self):
        candidates = [song("live", "龙卷风 Live"), song("wrong", "龙卷雨")]
        self.assertEqual(
            explicit_candidate("杰伦的龙卷风", candidates)["id"], "live")
        self.assertIsNone(explicit_candidate("周杰伦的龙卷风",[song("a",artist="邓紫棋")]))

    def test_fallback_queries_all_sources_and_merges(self):
        provider = FallbackMusicProvider({"search_limit": 10})
        provider.providers = {"a": Mock(), "b": Mock()}
        provider.providers["a"].search.return_value = [song("a")]
        provider.providers["b"].search.return_value = [song("b", "稻香")]
        found = provider.search("周杰伦")
        self.assertEqual({item["id"] for item in found}, {"a", "b"})
        provider.providers["a"].search.assert_called_once_with("周杰伦")
        provider.providers["b"].search.assert_called_once_with("周杰伦")
    def test_single_candidate_confirmation(self):
        music,player=self.setup_music([song("a")])
        music.search("龙卷风")
        request=music.local_request("好的")
        self.assertEqual(request["arguments"]["selection"],"第一首")
        player.play.assert_not_called()
