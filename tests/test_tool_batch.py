import asyncio
import json
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from cloud.agent.client import GLMAgent, ToolBatchRequired
from cloud.api import main as api
from edge.audio.tts.cancellation import SpeechCancellation
from robot_tools.batch import execute_plan, validate_plan, needs_semantic_route
from robot_tools.registry import ToolRegistry
from robot_tools.catalog import LOCAL_SCHEMAS
from shared.errors import error_info


def action(name, **arguments):
    return {"name": name, "arguments": arguments}


class BatchTests(unittest.TestCase):
    def test_independent_actions_really_overlap_and_keep_result_order(self):
        barrier = threading.Barrier(2)
        def execute(name, arguments):
            barrier.wait(timeout=2)
            return {"ok": True, "message": name, "status": "success"}
        results = execute_plan([action("music_search", query="随便"),
                                action("fan_light_control", action="light_off")], execute)
        self.assertEqual([x["tool"] for x in results], ["music_search", "fan_light_control"])

    def test_same_resource_is_ordered_and_failure_keeps_other_result(self):
        calls = []
        def execute(name, arguments):
            calls.append(arguments["action"])
            if arguments["action"] == "light_off":
                raise OSError("serial error")
            return {"ok": True, "message": "ok"}
        results = execute_plan([action("fan_light_control", action="light_off"),
                                action("fan_light_control", action="light_on")], execute)
        self.assertEqual(calls, ["light_off", "light_on"])
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_whole_plan_is_validated_before_any_effect(self):
        execute = Mock()
        for bad in [
            action("shell", command="bad"),
            action("fan_light_control", action="set_speed", percent=True),
            action("music_control", action="stop_music", extra="bad"),
            action("fan_light_control", action="set_light", mode="breath"),
            action("volume_control", action="set"),
        ]:
            with self.assertRaises(ValueError):
                execute_plan([action("music_search", query="随便"), bad], execute)
        execute.assert_not_called()

    def test_conflicting_music_actions_and_nested_routes_rejected(self):
        with self.assertRaises(ValueError):
            validate_plan([action("music_search", query="晴天"),
                           action("music_select", selection="第一首")])
        for raw in [
            {"action": "tool_batch", "actions": [{"action": "tool_batch"}, {"action": "stop_music"}]},
            {"action": "tool_batch", "actions": [{"action": "stop_music"}]},
            {"action": "tool_batch", "actions": [{"action": "end_conversation"}, {"action": "stop_music"}]},
        ]:
            with self.assertRaises(ValueError):
                GLMAgent._parse_turn_route_arguments(json.dumps(raw))

    def test_cancel_skips_queued_actions_without_undoing_success(self):
        token = SpeechCancellation()
        def execute(name, arguments):
            token.cancel()
            return {"ok": True, "executed": True, "message": "done"}
        results = execute_plan([action("fan_light_control", action="light_off"),
                                action("fan_light_control", action="light_on")], execute, token)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[1]["status"], "cancelled")

    def test_compound_input_skips_single_tool_shortcuts(self):
        self.assertTrue(needs_semantic_route("帮我播放一首歌，并把风扇灯光调为蓝色呼吸灯"))
        self.assertTrue(needs_semantic_route("把音量调小并关掉灯光"))
        self.assertTrue(needs_semantic_route("播放晴天并把它调成蓝色"))
        self.assertFalse(needs_semantic_route("播放晴天"))

    def test_provider_error_is_classified_without_echoing_secret(self):
        class ProviderError(Exception):
            status_code = 400
            body = {"code": "DataInspectionFailed", "message": "secret"}
            request_id = "request-test"
        original = ProviderError("data_inspection_failed secret")
        wrapped = RuntimeError("wrapper")
        wrapped.__cause__ = original
        info = error_info(wrapped)
        self.assertEqual(info["reason"], "content_rejected")
        self.assertEqual(info["code"], "DataInspectionFailed")
        self.assertNotIn("secret", json.dumps(info))
        self.assertEqual(error_info(TimeoutError())["reason"], "timeout")


class BatchApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_music_and_blue_breathing_plan_crosses_api(self):
        route = GLMAgent._parse_turn_route_arguments(json.dumps({
            "action": "tool_batch", "actions": [
                {"action": "play_music", "music_query": "随便"},
                {"action": "fan_light_control", "fan_light_action": "set_light",
                 "fan_light_mode": "breath", "fan_light_red": 0,
                 "fan_light_green": 0, "fan_light_blue": 255}]}))
        agent = GLMAgent.__new__(GLMAgent)
        agent.model = "test"
        agent.system_prompt = ""
        agent._route = AsyncMock(return_value=route)
        agent._identity_authority_response = Mock(return_value=None)
        with self.assertRaises(ToolBatchRequired) as raised:
            await agent.chat("帮我播放一首歌，并把风扇灯光调为蓝色呼吸灯")
        plan = raised.exception.requests
        self.assertEqual(plan[1]["arguments"]["blue"], 255)
        self.assertEqual(plan[0]["name"], "music_search")
        fake = NS(model="test", chat=AsyncMock(side_effect=raised.exception))
        with patch.object(api, "get_agent", return_value=fake):
            response = await api.chat(api.ChatRequest(text="播放音乐并调整灯光"))
        self.assertEqual(len(response.tool_requests), 2)
        self.assertEqual(response.reply, "")

    async def test_remote_tools_have_allowlist_and_validate_before_execution(self):
        fake = NS(tool_router=NS(execute=AsyncMock(return_value={
            "tool": "get_weather", "ok": True, "location": "广州",
            "current": {"temperature_2m": 25.6}, "daily": {}})))
        with patch.object(api, "get_agent", return_value=fake):
            result = await api.execute_remote_tool(api.RemoteToolRequest(
                name="get_weather", arguments={"city": "广州"}))
            self.assertIn("25.6", result["message"])
            with self.assertRaises(api.HTTPException):
                await api.execute_remote_tool(api.RemoteToolRequest(
                    name="get_weather", arguments={"city": "广州", "days": 99}))
        self.assertEqual(fake.tool_router.execute.await_count, 1)
