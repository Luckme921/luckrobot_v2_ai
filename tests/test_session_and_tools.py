import asyncio
import json
import signal
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, AsyncMock, patch
from edge.audio.wake.session import InteractionGate
from robot_tools.music import MusicTools, HttpMusicProvider, DirectAudioPlayer
from robot_tools.edge import build_edge_tools
from robot_tools.weather import get_weather
from robot_tools.cloud import ToolRouter, ToolCallBudget
from cloud.agent.client import GLMAgent, LocalToolRequestRequired
from cloud.api.main import ChatRequest
from cloud.api import main as api


def gate():
    return InteractionGate(wake_command_timeout_seconds=8, normal_timeout_seconds=12,
        chat_timeout_seconds=20, transcript_aliases=["lucky"], transcript_exact_aliases=[],
        chat_mode_triggers=["陪我聊"], sleep_phrases=["不聊了", "再见"],
        emergency_stop_phrases=["停", "停止", "别动"])


class EndConversationTest(unittest.TestCase):
    def test_explicit_end_returns_to_kws_and_stays_asleep(self):
        for phrase in ["结束对话", "结束聊天", "停止对话", "请结束对话吧", "lucky，结束对话", "退出聊天"]:
            with self.subTest(phrase=phrase):
                g = gate(); g.on_wake(now=0); g.process("陪我聊", now=1)
                self.assertEqual(g.process(phrase, now=2).action, "sleep")
                self.assertEqual(g.state, g.SLEEPING)
                self.assertEqual(g.deadline, 0)
                g.on_robot_reply_finished(now=3)
                self.assertEqual(g.process("今天的天气", now=4).action, "ignore")
                g.on_wake(now=5)
                self.assertEqual(g.process("你好", now=6).action, "awake")
                self.assertEqual(g.process("今天的天气", now=7).action, "command")

    def test_negative_quoted_and_substring_are_not_exit(self):
        for phrase in ["不要结束对话", "结束对话是什么意思", "给我讲一个再见的故事", "不用结束聊天"]:
            g = gate(); g.on_wake(now=0)
            self.assertEqual(g.process(phrase, now=1).action, "command")

    def test_emergency_stop_keeps_its_priority(self):
        g = gate(); g.on_wake(now=0)
        self.assertEqual(g.process("停止运动", now=1).action, "emergency_stop")

    def test_sleeping_speech_cannot_wake_without_kws(self):
        g = gate()
        self.assertEqual(g.process("lucky你好", now=1).action, "ignore")


class MusicFlowTest(unittest.TestCase):
    def setUp(self):
        self.clock = Mock(return_value=1)
        self.player = Mock()
        self.music = MusicTools({"enabled": True, "provider": "http"}, player=self.player, clock=self.clock)
        self.music.provider = Mock(url="https://example.test/search")
        self.songs = [
            {"id": "a", "title": "晴天", "artists": ["甲"], "url": "https://media.test/a", "backend": "http"},
            {"id": "b", "title": "夜曲", "artists": ["乙"], "url": "https://media.test/b", "backend": "http"}]
        self.music.provider.search.return_value = self.songs

    def test_search_never_plays_and_hides_signed_urls(self):
        r = self.music.search("周杰伦")
        self.assertEqual(r["status"], "needs_selection")
        self.assertEqual(len(r["candidates"]), 2)
        self.assertNotIn("https://", json.dumps(r))
        self.player.play.assert_not_called()

    def test_user_choice_plays_exact_cached_url_without_another_search(self):
        self.music.search("周杰伦")
        self.assertEqual(self.music.selection_request("请播放第二首"), "第二首")
        r = self.music.select("第二首")
        self.assertTrue(r["playing"])
        self.player.play.assert_called_once_with("https://media.test/b")
        self.music.provider.search.assert_called_once()
        self.assertFalse(self.music.has_pending)

    def test_song_name_selects_exact_entry(self):
        self.music.search("周杰伦")
        self.assertTrue(self.music.select("播放晴天")["ok"])
        self.player.play.assert_called_once_with("https://media.test/a")

    def test_invalid_choice_never_becomes_arbitrary_url(self):
        self.music.search("周杰伦")
        for value in ["第九首", "https://evil.test/audio", "不存在的歌"]:
            self.assertFalse(self.music.select(value)["ok"])
        self.player.play.assert_not_called()

    def test_duplicate_title_requires_index(self):
        self.music.provider.search.return_value = [self.songs[0], dict(self.songs[1], title="晴天")]
        self.music.search("晴天")
        self.assertEqual(self.music.select("晴天")["status"], "needs_selection")
        self.player.play.assert_not_called()

    def test_end_or_timeout_invalidates_selection(self):
        self.music.search("周杰伦")
        self.music.clear_pending()
        self.assertEqual(self.music.select("第一首")["status"], "expired")
        self.music.search("周杰伦")
        self.clock.return_value = 200
        self.assertEqual(self.music.select("第一首")["status"], "expired")
        self.player.play.assert_not_called()

    def test_expired_url_requires_new_search(self):
        self.music.provider.search.return_value = [dict(self.songs[0], expires_at=1)]
        self.music.search("晴天")
        self.assertEqual(self.music.select("第一首")["status"], "expired")
        self.player.play.assert_not_called()

    def test_disabled_music_is_spoken_unavailable_not_silent_error(self):
        self.music.config["enabled"] = False
        r = self.music.search("晴天")
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], "unavailable")
        self.music.provider.search.assert_not_called()

    def test_qq_selection_is_strict_and_not_replaced_by_nearest_song(self):
        controller = Mock()
        library = Mock()
        library.search.return_value = [NS(mid="qq1", title="晴天", artists=["甲"])]
        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller, library)
        music.search("晴天")
        music.select("第一首")
        controller.play.assert_called_once_with("晴天", preferred_mid="qq1", strict_mid=True)

    def test_player_rejects_local_paths(self):
        player = DirectAudioPlayer(lambda: "speaker")
        with patch("robot_tools.music.subprocess.Popen") as start:
            with self.assertRaises(ValueError):
                player.play("file:///etc/passwd")
            start.assert_not_called()


class ToolContractTest(unittest.TestCase):
    def test_volume_and_music_are_callable_by_name_with_arguments(self):
        volume = Mock()
        volume.execute.return_value = 30
        music = Mock()
        registry = build_edge_tools(volume, music)
        r = registry.execute("volume_control", {"action": "set", "percent": 30})
        self.assertEqual(r["percent"], 30)
        self.assertEqual(volume.execute.call_args.args[0].percent, 30)
        volume.reset_mock()
        self.assertFalse(registry.execute("volume_control", {"action": "set", "percent": 999})["ok"])
        volume.execute.assert_not_called()
        self.assertFalse(registry.execute("shell", {"command": "anything"})["ok"])

    def test_new_llm_routes_have_typed_arguments(self):
        for raw, expected in [
            ('{"action":"get_weather","city":"深圳","days":2}', "get_weather"),
            ('{"action":"volume_control","volume_action":"set","percent":35}', "volume_control"),
            ('{"action":"select_music","music_query":"第二首"}', "select_music")]:
            self.assertEqual(GLMAgent._parse_turn_route_arguments(raw)["action"], expected)

    def test_weather_needs_a_city_instead_of_guessing(self):
        with patch("robot_tools.weather._get") as fetch:
            r = get_weather("")
            self.assertEqual(r["status"], "needs_input")
            fetch.assert_not_called()

    def test_weather_keeps_provider_data_and_handles_errors(self):
        locations = {"results": [{"name": "深圳", "latitude": 22.5, "longitude": 114.0}]}
        forecast = {"current": {"temperature_2m": 25}, "daily": {"time": ["2026-09-19"]}}
        with patch("robot_tools.weather._get", side_effect=[locations, forecast]):
            r = get_weather("深圳")
            self.assertEqual(r["current"]["temperature_2m"], 25)
            self.assertEqual(r["source"], "Open-Meteo")
        with patch("robot_tools.weather._get", side_effect=OSError()):
            self.assertFalse(get_weather("深圳")["ok"])

    def test_ambiguous_weather_city_requests_clarification(self):
        data = {"results": [{"name": "X", "latitude": 1}, {"name": "X", "latitude": 2}]}
        with patch("robot_tools.weather._get", return_value=data) as fetch:
            self.assertEqual(get_weather("X")["status"], "needs_input")
            self.assertEqual(fetch.call_count, 1)


class AsyncToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_budget_prevents_duplicate_calls(self):
        router = ToolRouter(); budget = ToolCallBudget()
        with patch("robot_tools.cloud.get_weather", return_value={"ok": True}) as weather:
            await router.execute("get_weather", {"city": "深圳"}, budget=budget)
            r = await router.execute("get_weather", {"city": "深圳"}, budget=budget)
            self.assertFalse(r["ok"]); self.assertEqual(weather.call_count, 1)

    async def test_local_tool_api_is_an_intermediate_request(self):
        error = LocalToolRequestRequired("volume_control", {"action": "set", "percent": 30})
        fake = NS(model="test", chat=AsyncMock(side_effect=error))
        with patch.object(api, "get_agent", return_value=fake):
            r = await api.chat(ChatRequest(text="音量设为30"))
        self.assertEqual(r.reply, "")
        self.assertEqual(r.tool_request.arguments["percent"], 30)


class LauncherTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Jetson process groups")
    def test_shutdown_targets_only_owned_process_group(self):
        from scripts.run_robot import stop_child
        process = Mock(pid=123)
        with patch("scripts.run_robot.os.killpg") as kill:
            stop_child(process)
        self.assertEqual(kill.call_args_list[0].args, (123, signal.SIGINT))
        process.wait.assert_called()
