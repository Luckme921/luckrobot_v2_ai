import unittest
from unittest.mock import Mock
from robot_tools.music import (
    FallbackMusicProvider,
    MusicTools,
    explicit_candidate,
    has_explicit_music_intent,
    is_random_request,
    is_recommendation_request,
    is_change_music_request,
)

def song(id,title="龙卷风",artist="周杰伦"):
    return dict(id=id,title=title,artists=[artist],backend="http",url="https://example.com/"+id)
class LocalMusicTests(unittest.TestCase):
    def test_qq_track_refresh_reports_auto_advance_once(self):
        controller = Mock()
        controller.current_track.return_value = "七里香 - 周杰伦"
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.playing = True
        music.current_song = {"title": "稻香", "artists": ["周杰伦"]}
        self.assertEqual(music.refresh_current_track(), {
            "title": "七里香", "artists": ["周杰伦"]})
        self.assertIsNone(music.refresh_current_track())

    def test_stop_music_phrases_take_priority_over_pending_selection(self):
        music, _ = self.setup_music([])
        music.pending = [song("one", "关闭音乐", "测试歌手")]
        music.deadline = music.clock() + 120
        for utterance in ("关闭音乐", "停止播放。", "关掉音乐", "别放了", "把歌关了"):
            with self.subTest(utterance=utterance):
                self.assertEqual(music.local_request(utterance), {
                    "name": "music_control", "arguments": {"action": "stop_music"},
                })

    def test_qq_stop_control_clears_playback_state(self):
        controller = Mock()
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.playing = True
        music.current_song = {"title": "引爆全场", "artists": ["EVER"]}
        answer = music.control(music.local_request("关闭音乐")["arguments"]["action"])
        controller.stop.assert_called_once()
        self.assertFalse(answer["playing"])
        self.assertIsNone(answer["music"])

    def test_qq_next_uses_player_track_instead_of_stale_selected_song(self):
        controller = Mock()
        controller.next.return_value = "七里香\n周杰伦"
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.playing = True
        music.current_song = {"title": "龙卷风", "artists": ["周杰伦"]}
        answer = music.control("next_music")
        self.assertEqual(answer["music"], {"title": "七里香", "artists": ["周杰伦"]})
        self.assertEqual(music.current_song, answer["music"])

    def test_qq_next_without_metadata_does_not_display_old_title(self):
        controller = Mock()
        controller.next.return_value = ""
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.current_song = {"title": "龙卷风", "artists": ["周杰伦"]}
        answer = music.control("next_music")
        self.assertIsNone(answer["music"])

    def test_recommendation_uses_curated_titles_without_provider_search_until_choice(self):
        controller = Mock()
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "preferences": {"preferred_tracks": [
                                {"artist": "周杰伦", "title": "晴天"},
                                {"artist": "邓紫棋", "title": "泡沫"},
                            ]}}, controller=controller)
        self.assertTrue(is_recommendation_request("有什么推荐的歌曲吗？"))
        request = music.local_request("有什么推荐的歌曲吗？")
        self.assertEqual(request["arguments"]["query"], "推荐")
        reply = music.search(**request["arguments"])
        self.assertEqual(reply["status"], "needs_selection")
        self.assertIn("晴天", reply["message"])
        self.assertIn("泡沫", reply["message"])
        controller.search_candidates.assert_not_called()

    def test_recommended_choice_searches_qq_then_plays_exact_artist_title(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="studio", title="泡沫", artists=["G.E.M.邓紫棋"],
                 backend="qqmusic", query="邓紫棋 泡沫"),
        ]
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "preferences": {"preferred_tracks": [
                                {"artist": "邓紫棋", "title": "泡沫"},
                            ]}}, controller=controller)
        music.search("推荐", utterance="有什么推荐的歌曲吗")
        answer = music.select("泡沫")
        self.assertTrue(answer["playing"])
        controller.search_candidates.assert_called_once_with("邓紫棋 泡沫", limit=3)
        controller.play.assert_called_once_with("邓紫棋 泡沫", preferred_mid="studio", strict_mid=True)

    def test_reference_to_pending_artist_uses_existing_choice(self):
        music, _ = self.setup_music([])
        music.pending = [song("other", "风象星座", "BigYear大年"),
                         song("wanted", "032.救命的调味品", "米小圈")]
        music.deadline = music.clock() + 120
        by_artist = music.local_request("我想听你上次搜到的米小圈的那一首")
        self.assertEqual(by_artist, {"name": "music_select",
                                     "arguments": {"selection": "wanted"}})
        by_number = music.local_request("我想听03二点那首")
        self.assertEqual(by_number, {"name": "music_select",
                                     "arguments": {"selection": "wanted"}})
        music.clear_pending()
        self.assertIsNone(music.local_request("我想听你上次搜到的米小圈那首"))
        self.assertIsNone(music.local_request("我忘了歌名，歌词里有一句下雨"))

    def test_model_suggested_song_is_saved_then_selected_without_new_keyword_search(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="qq-original", title="从头再来《知青家庭》电视剧主题曲",
                 artists=["刘欢"], backend="qqmusic", query="刘欢 从头再来")]
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        reply = "我找到了刘欢的《弯弯的月亮》、刘欢的《好汉歌》、刘欢的《从头再来》。你想听哪首？"
        self.assertTrue(music.stage_suggested_songs(reply))
        self.assertEqual([song["title"] for song in music.pending],
                         ["弯弯的月亮", "好汉歌", "从头再来"])
        request = music.local_request("那个从头再来好听吗？你播放一下给我听")
        self.assertEqual(request, {"name": "music_select", "arguments": {
            "selection": "suggested:2"}})
        answer = music.select(request["arguments"]["selection"])
        self.assertTrue(answer["playing"])
        controller.search_candidates.assert_called_once_with("刘欢 从头再来", limit=3)
        controller.play.assert_called_once_with("刘欢 从头再来", preferred_mid="qq-original", strict_mid=True)

    def test_pending_annotated_title_is_selected_from_full_sentence(self):
        music, _ = self.setup_music([])
        music.pending = [song("target", "从头再来《知青家庭》电视剧主题曲", "刘欢"),
                         song("other", "千万次的问", "刘欢")]
        music.deadline = music.clock() + 120
        request = music.local_request("就是你上次找到的那个刘欢的，从头再来，你放给我听")
        self.assertEqual(request, {"name": "music_select", "arguments": {
            "selection": "target"}})

    def test_original_requested_song_rejects_unasked_user_remix(self):
        remix = dict(id="remix", title="从头再来 (网友改编)",
                     artists=["刘欢"], backend="qqmusic")
        self.assertIsNone(explicit_candidate("刘欢 从头再来", [remix]))

    def test_pending_context_and_change_song_do_not_search_literal_suibian(self):
        music, _ = self.setup_music([])
        music.pending = [song("one", "I don't wanna see u anymore", "乃万NINEONE")]
        music.deadline = music.clock() + 120
        self.assertEqual(music.pending_context(), [{
            "index": 1, "title": "I don't wanna see u anymore", "artists": ["乃万NINEONE"]}])
        self.assertIsNone(music.local_request("我不想听随便你再找点其他歌"))

    def test_spoken_list_can_be_interrupted_and_selected_by_ordinal(self):
        music, _ = self.setup_music([])
        music.pending = [song("first", "完美先生和差不多小姐", "花粥"),
                         song("second", "原地", "祁圣翰")]
        music.deadline = music.clock() + 120
        for utterance in ("我要听第一首", "我想听你上一次找到的第一首花周畅的那首"):
            with self.subTest(utterance=utterance):
                self.assertEqual(music.local_request(utterance), {
                    "name": "music_select", "arguments": {"selection": "第一首"}})
        self.assertIsNone(music.selection_request("我不想听第一首"))

    def test_followup_change_requests_skip_literal_search(self):
        music, _ = self.setup_music([])
        music.pending = [song("old", "龙卷风", "周杰伦")]
        music.deadline = music.clock() + 120
        for phrase in (
            "再换一首歌", "我不想听，随便换一首",
            "我让你再换一首，不是说歌名是叫再换一首，而是让你再去找一首歌",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_change_music_request(phrase, has_context=True))
                request = music.local_request(phrase)
                self.assertEqual(request, {"name": "music_search", "arguments": {
                    "query": "随便", "utterance": phrase}})
        self.assertFalse(is_change_music_request("再找一点其他的", has_context=False))
        self.assertIsNone(music.local_request("你再找一点其他的音乐"))
        self.assertIsNone(music.local_request("再找一点其他的"))
        self.assertEqual(music.local_request("继续播放刚才的歌曲"), {
            "name": "music_control", "arguments": {"action": "resume_music"}})
        self.assertIsNone(music.local_request("放首歌吧，我要休息了，晚安喽"))

    def test_fresh_music_search_requires_explicit_cue(self):
        for text in [
            "放一首", "一首歌", "音乐", "歌曲", "来点小曲", "播放晴天", "我想听稻香",
            "搜一下邓紫棋的歌吧", "换歌", "再找一首歌曲", "邓紫棋的歌",
            "我想要听孙冬野南河桥", "你放那首什么跳楼机吧",
            "你搜一下那个DJ阿哲的跳楼机",
        ]:
            with self.subTest(text=text):
                self.assertTrue(has_explicit_music_intent(text))
        for text in ["马蹄", "苹果", "周杰伦", "孙冬野南河桥", "为什么播放音乐没声音", "不要播放歌曲"]:
            with self.subTest(text=text):
                self.assertFalse(has_explicit_music_intent(text))

    def test_catalog_fast_route_only_for_known_names(self):
        library = Mock()
        library.data = {"playlists": {"mine": {"songs": [
            {"title": "安和桥", "artists": ["宋冬野"]},
            {"title": "七里香", "artists": ["周杰伦"]},
        ]}}}
        music = MusicTools({"catalog_route_enabled": True, "preferences": {
            "preferred_tracks": [{"artist": "邓紫棋", "title": "泡沫"}],
            "known_artists": ["刘欢"], "known_titles": ["从头再来"],
        }}, library=library)
        for phrase in ("播放安和桥", "我想听宋冬野的歌", "播放邓紫棋的七里香",
                       "播放刘欢的七里香", "播放从头再来"):
            with self.subTest(phrase=phrase):
                self.assertEqual(music.local_request(phrase)["name"], "music_search")
        for phrase in ("播放好听的歌", "播放震撼全场的歌", "播放陌生歌曲",
                       "播放刘欢的陌生歌名", "我想听点振奋的音乐"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(music.local_request(phrase))

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
            "放吧，你随便放一首音乐",
        ]:
            music,player=self.setup_music([song("a")])
            request=music.local_request(phrase)
            self.assertIsNotNone(request,phrase)
            self.assertTrue(music.search(**request["arguments"])["playing"])
            self.assertNotEqual(music.provider.search.call_args.args[0],"歌")
            player.play.assert_called_once()

    def test_generic_random_utterance_overrides_bad_extracted_query(self):
        music, player = self.setup_music([song("a")])
        answer = music.search("你随便放一首", utterance="放吧，你随便放一首音乐")
        self.assertTrue(answer["playing"])
        self.assertNotEqual(music.provider.search.call_args.args[0], "你随便放一首")
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

    def test_qq_preferred_track_uses_artist_and_title(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="cover", title="泡沫", artists=["其他歌手"],
                 backend="qqmusic", query="邓紫棋 泡沫"),
            dict(id="original", title="泡沫", artists=["G.E.M.邓紫棋"],
                 backend="qqmusic", query="邓紫棋 泡沫"),
        ]
        music = MusicTools({
            "enabled": True, "provider": "qqmusic",
            "preferences": {
                "search_attempts": 1,
                "preferred_tracks": [{"artist": "邓紫棋", "title": "泡沫"}],
            },
        }, controller=controller)
        answer = music.search("随便", utterance="随便播放一首歌曲")
        self.assertTrue(answer["playing"])
        controller.play.assert_called_once_with(
            "邓紫棋 泡沫", preferred_mid="original", strict_mid=True)
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
        request = music.local_request("我想要听孙冬野南河桥")
        self.assertEqual(request["arguments"]["query"], "宋冬野 安和桥")
        self.assertIsNone(music.local_request("孙冬野南河桥"))
        request = music.local_request("我想听我想听宋冬野的安河桥")
        self.assertEqual(request["name"], "music_search")
        self.assertEqual(request["arguments"]["query"], "宋冬野 安和桥")
        request = music.local_request("你可以放一首歌吗？")
        self.assertEqual(request["arguments"]["query"], "随便")
        request = music.local_request("搜一下邓紫棋的歌吧")
        self.assertEqual(request["arguments"]["query"], "邓紫棋")
        request = music.local_request("这还不接听吗？邓紫棋的歌")
        self.assertEqual(request["arguments"]["query"], "邓紫棋")
        for text in ("换歌", "再找一首歌曲", "下一首"):
            with self.subTest(text=text):
                request = music.local_request(text)
                self.assertEqual(request["name"], "music_search")
                self.assertEqual(request["arguments"]["query"], "随便")
        self.assertIsNone(music.local_request("请告诉我今天的天气"))

    def test_random_prefers_a_different_track_on_next_request(self):
        controller = Mock()
        def candidates(query, limit=3):
            artist, title = query.split(" ", 1)
            return [dict(id=query, title=title, artists=[artist],
                         backend="qqmusic", query=query)]
        controller.search_candidates.side_effect = candidates
        music = MusicTools({
            "enabled": True, "provider": "qqmusic",
            "preferences": {"search_attempts": 1, "preferred_tracks": [
                {"artist": "周杰伦", "title": "晴天"},
                {"artist": "邓紫棋", "title": "泡沫"},
            ]},
        }, controller=controller)
        first = music.search("随便", utterance="随机播放一首歌")
        second = music.search("随便", utterance="随机播放一首歌")
        self.assertTrue(first["playing"])
        self.assertTrue(second["playing"])
        self.assertNotEqual(controller.play.call_args_list[0].args[0],
                            controller.play.call_args_list[1].args[0])

    def test_known_singer_title_uses_official_qq_title(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="original", title="安和桥", artists=["宋冬野"],
                 backend="qqmusic", query="宋冬野 安和桥"),
            dict(id="backing", title="安河桥 (伴奏)", artists=["其他人"],
                 backend="qqmusic", query="宋冬野 安和桥"),
        ]
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "http": {"auto_play_enabled": True}}, controller=controller)
        request = music.local_request("我要听宋冬野的安河桥")
        answer = music.search(**request["arguments"])
        self.assertTrue(answer["playing"])
        controller.search_candidates.assert_called_once_with("宋冬野 安和桥", limit=3)
        controller.play.assert_called_once_with("宋冬野 安和桥", preferred_mid="original", strict_mid=True)

    def test_asr_singer_variants_search_the_same_official_track(self):
        music, _ = self.setup_music([])
        for utterance in ("放一首松农野的安河桥", "放一首宋东野的安河桥"):
            with self.subTest(utterance=utterance):
                self.assertEqual(music.local_request(utterance)["arguments"]["query"],
                                 "宋冬野 安和桥")

    def test_qq_singer_title_does_not_offer_unrelated_audiobook(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="book", title="第428章 中原劝农安黎庶", artists=["鹤乡文化书场"],
                 backend="qqmusic", query="陌生歌手 安和桥"),
        ]
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "http": {"auto_play_enabled": True}}, controller=controller)
        reply = music.search("陌生歌手 安和桥")
        self.assertEqual(reply["status"], "not_found")
        controller.play.assert_not_called()

    def test_qq_title_search_does_not_offer_unrelated_suggestions(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="wrong", title="九张机", artists=["叶炫清"],
                 backend="qqmusic", query="跳楼机"),
        ]
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        answer = music.search("跳楼机", utterance="播放跳楼机")
        self.assertEqual(answer["status"], "not_found")
        self.assertFalse(music.has_pending)
        controller.play.assert_not_called()

    def test_qq_fuzzy_library_miss_falls_through_to_web_search(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="correct", title="跳楼机", artists=["歌手"],
                 backend="qqmusic", query="跳楼机"),
        ]
        library = Mock()
        library.search.return_value = [Mock(mid="wrong", title="九张机",
                                            artists=["叶炫清"])]
        music = MusicTools({"enabled": True, "provider": "qqmusic"},
                           controller=controller, library=library)
        answer = music.search("跳楼机", utterance="播放跳楼机")
        self.assertEqual(answer["candidates"][0]["id"], "correct")
        controller.search_candidates.assert_called_once_with("跳楼机", limit=12)

    def test_qq_title_search_keeps_matching_live_version(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="live", title="跳楼机 (Live)", artists=["歌手"],
                 backend="qqmusic", query="跳楼机"),
        ]
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        answer = music.search("跳楼机", utterance="播放跳楼机")
        self.assertEqual(answer["status"], "needs_selection")
        self.assertEqual(answer["candidates"][0]["id"], "live")

    def test_qq_playback_failure_stops_player_and_reports_it(self):
        controller = Mock()
        controller.search_candidates.return_value = [
            dict(id="studio", title="安和桥", artists=["宋冬野"],
                 backend="qqmusic", query="宋冬野 安和桥"),
        ]
        controller.play.side_effect = RuntimeError("route failed")
        music = MusicTools({"enabled": True, "provider": "qqmusic",
                            "http": {"auto_play_enabled": True}}, controller=controller)
        reply = music.search("宋冬野 安和桥")
        self.assertEqual(reply["status"], "unavailable")
        self.assertIn("QQ 音乐没有完成播放", reply["message"])
        self.assertFalse(music.playing)

    def test_replay_uses_last_selected_title_not_deictic_search_words(self):
        music, _ = self.setup_music([])
        music.last_selected_song = {"title": "完美先生和差不多小姐《电视剧片尾曲》",
                                    "artists": ["花粥"]}
        for phrase in ("你再播放一次吧", "播放刚才那首歌", "你播放刚才的花粥的那一首歌"):
            with self.subTest(phrase=phrase):
                self.assertEqual(music.local_request(phrase), {"name": "music_search",
                    "arguments": {"query": "花粥 完美先生和差不多小姐", "utterance": phrase}})
        self.assertIsNone(music.local_request("你还记得刚才那首歌吗"))

    def test_qq_wrong_track_is_stopped_and_never_reported_as_playing(self):
        controller = Mock()
        controller.play.return_value = "夜问 - 花粥"
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=controller)
        music.pending = [dict(id="wanted", title="完美先生和差不多小姐《电视剧片尾曲》",
                              artists=["花粥"], backend="qqmusic", query="花粥 完美先生和差不多小姐")]
        music.deadline = music.clock() + 120
        answer = music.select("第一首")
        self.assertEqual(answer["status"], "mismatch")
        self.assertFalse(answer["playing"])
        controller.stop.assert_called_once()

    def test_drama_annotation_does_not_make_another_song_an_explicit_match(self):
        wrong = dict(id="wrong", title="夜问《完美先生和差不多小姐》电视剧片头曲",
                     artists=["花粥"])
        self.assertIsNone(explicit_candidate("花粥 王美先生和差不多小姐", [wrong]))

    def test_singer_only_choice_with_multiple_versions_stays_local(self):
        music, _ = self.setup_music([])
        music.pending = [song("one", "安河桥 (Live)", "宋冬野"),
                         song("two", "安河桥 (Demo)", "宋冬野")]
        music.deadline = music.clock() + 120
        request = music.local_request("宋东野")
        self.assertEqual(request["name"], "music_select")
        self.assertEqual(music.select(request["arguments"]["selection"])["status"],
                         "needs_selection")

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
