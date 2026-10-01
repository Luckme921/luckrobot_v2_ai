import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

from cloud.agent.client import GLMAgent, VisionRequestRequired, MusicRequestRequired
from cloud.api import main as api
from edge.agent.cloud_client import CloudAgentClient, CloudAgentError
from edge.audio.acknowledgement import ToolAcknowledgement, PHRASES
from edge.audio.tts.cancellation import SpeechCancellation, SpeechInterrupted
from shared.timing import progress, trace_id, announce, measure


def response(content=None, calls=None, finish="stop"):
    return NS(choices=[NS(finish_reason=finish,
                         message=NS(content=content, tool_calls=calls))])


def legacy(action="respond_text"):
    return response(calls=[NS(function=NS(name="route_turn",
                        arguments=json.dumps({"action": action})))], finish="tool_calls")


def agent_with(*responses):
    agent = object.__new__(GLMAgent)
    agent.model = "test"
    agent.route_protocol = "json"
    agent.temperature = 0.4
    agent.max_tokens = 2048
    agent.thinking = "enabled"
    agent.reasoning_effort = "low"
    agent.system_prompt = "Robot"
    agent.client = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=responses))))
    agent.tool_router = NS(execute=AsyncMock(return_value={"message": "done"}))
    return agent


class JsonRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_answer_can_publish_text_deltas(self):
        agent = agent_with(response('{"action":"respond_text"}'))
        agent.stream_text_enabled = True
        async def chunks():
            for text in ("你好，", "世界。"):
                yield NS(choices=[NS(delta=NS(content=text))])
        agent.client.chat.completions.create.side_effect = [
            response('{"action":"respond_text"}'), chunks()]
        events = []
        token = progress.set(events.append)
        try:
            self.assertEqual(await agent.chat("hello"), "你好，世界。")
        finally:
            progress.reset(token)
        self.assertEqual([e["text"] for e in events if e["type"] == "text_delta"],
                         ["你好，", "世界。"])

    async def test_chat_uses_json_then_full_context_answer(self):
        agent = agent_with(response('{"action":"respond_text"}'), response("hello"))
        history = [{"role": "user", "content": "previous question"},
                   {"role": "assistant", "content": "private prior answer"}]
        self.assertEqual(await agent.chat("hello", history=history), "hello")
        first, second = agent.client.chat.completions.create.call_args_list
        self.assertEqual(first.kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", first.kwargs)
        self.assertNotIn("private prior answer", str(first.kwargs["messages"]))
        self.assertIn("private prior answer", str(second.kwargs["messages"]))
        agent.tool_router.execute.assert_not_awaited()

    async def test_invalid_json_retries_legacy_once(self):
        agent = agent_with(response("bad"), legacy())
        self.assertEqual((await agent._route("hello", [], "uncertain"))["action"], "respond_text")
        self.assertEqual(agent.client.chat.completions.create.await_count, 2)
        self.assertIn("tools", agent.client.chat.completions.create.call_args.kwargs)

    async def test_both_routes_invalid_fail_without_execution(self):
        agent = agent_with(response("{}"), response("not a tool call"))
        with self.assertRaises(ValueError):
            await agent.chat("hello")
        self.assertEqual(agent.client.chat.completions.create.await_count, 2)
        agent.tool_router.execute.assert_not_awaited()

    async def test_transport_failure_not_retried_as_another_protocol(self):
        agent = agent_with(TimeoutError("offline"))
        with self.assertRaises(TimeoutError):
            await agent._route("hello", [], "uncertain")
        self.assertEqual(agent.client.chat.completions.create.await_count, 1)

    async def test_tool_mode_is_explicit_rollback(self):
        agent = agent_with(legacy())
        agent.route_protocol = "tool"
        await agent._route("hello", [], "uncertain")
        self.assertNotIn("response_format", agent.client.chat.completions.create.call_args.kwargs)

    async def test_vision_and_music_remain_intermediate_actions(self):
        for data, error in [
            ('{"action":"request_vision","vision_mode":"latest"}', VisionRequestRequired),
            ('{"action":"play_music","music_query":"jazz"}', MusicRequestRequired)]:
            with self.subTest(data=data):
                agent = agent_with(response(data))
                with self.assertRaises(error):
                    await agent.chat("request")
                agent.tool_router.execute.assert_not_awaited()

    async def test_web_search_event_precedes_execution(self):
        agent = agent_with(response('{"action":"web_search","query":"weather"}'),
                           response("sunny"))
        order = []
        async def tool(*args, **kwargs):
            order.append("execute")
            self.assertEqual(order[0], "web_search")
            return {"message": "sunny"}
        agent.tool_router.execute = tool
        token = progress.set(lambda event: order.append(event["action"])
                             if event["type"] == "tool_start" else None)
        try:
            self.assertEqual(await agent.chat("weather"), "sunny")
        finally:
            progress.reset(token)
        self.assertEqual(order, ["web_search", "execute"])

    async def test_explicit_images_bypass_router(self):
        agent = agent_with(response("a cup"))
        self.assertEqual(await agent.chat("look", image_data_urls=["data:image/jpeg;base64,AA"],
                                         tool_mode="none"), "a cup")
        kwargs = agent.client.chat.completions.create.call_args.kwargs
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("tools", kwargs)


class RouteValidationTests(unittest.TestCase):
    def test_rejects_invalid_or_truncated_structures(self):
        cases = ['[]', '{}', '{"action":"unknown"}',
                 '{"action":"respond_text","surprise":1}',
                 '{"action":"web_search","query":42}',
                 '{"action":"navigate_to","location":""}',
                 '{"action":"request_vision","vision_mode":"recent","count":true}',
                 '{"action":"request_vision","vision_mode":"recent","count":100}',
                 '{"action":"request_vision","vision_mode":"recent","seconds":NaN}']
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                GLMAgent._validated_json_route(response(content).choices[0])
        with self.assertRaises(ValueError):
            GLMAgent._validated_json_route(
                response('{"action":"respond_text"}', finish="length").choices[0])

    def test_prompt_retains_identity_and_removes_tool_instruction(self):
        messages = GLMAgent._json_route_messages("look", [], "unknown")
        self.assertIn("CURRENT_LOCAL_IDENTITY=unknown", str(messages))
        self.assertNotIn("调用 route_turn", str(messages))
        self.assertIn("JSON", str(messages))

    def test_pending_music_candidates_are_visible_to_router_only(self):
        candidates = [{"index": 2, "title": "I don't wanna see u anymore",
                       "artists": ["乃万NINEONE"]}]
        messages = GLMAgent._json_route_messages("奶袜的那首", [], "uncertain", candidates)
        self.assertIn("PENDING_MUSIC_CANDIDATES", str(messages))
        self.assertIn("乃万NINEONE", str(messages))
        self.assertIn("select_music", str(messages))
        self.assertIn("2. ", str(messages))

    def test_all_route_actions_validate(self):
        cases = [
            {"action": "respond_text"},
            {"action": "request_vision", "vision_mode": "latest"},
            {"action": "request_vision", "vision_mode": "recent", "count": 3, "seconds": 4},
            {"action": "web_search", "query": "weather", "recency": "oneDay"},
            {"action": "navigate_to", "location": "kitchen"},
        ] + [{"action": a} for a in ["play_music", "recommend_music", "end_conversation",
                                      "pause_music", "resume_music", "next_music",
                                      "previous_music", "stop_music"]]
        for case in cases:
            with self.subTest(case=case):
                actual = GLMAgent._validated_json_route(response(json.dumps(case)).choices[0])
                self.assertEqual(actual["action"], case["action"])


class EventApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_delivered_before_result_and_final_schema_preserved(self):
        gate = asyncio.Event()
        async def fake_chat(*args, **kwargs):
            announce("web_search")
            await gate.wait()
            return "sunny"
        with patch.object(api, "get_agent", return_value=NS(model="test", chat=fake_chat)):
            events = api.chat_events(api.ChatRequest(text="weather", trace_id="turn1"))
            first = json.loads(await anext(events))
            self.assertEqual(first, {"type": "tool_start", "action": "web_search", "trace_id": "turn1"})
            gate.set()
            remaining = [json.loads(line) async for line in events]
            result = next(e for e in remaining if e["type"] == "result")
            self.assertEqual(result["data"]["reply"], "sunny")
            self.assertTrue(any(e.get("stage") == "cloud_total" for e in remaining))

    async def test_disconnect_cancels_work(self):
        cancelled = asyncio.Event()
        async def fake_chat(*args, **kwargs):
            announce("web_search")
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch.object(api, "get_agent", return_value=NS(model="test", chat=fake_chat)):
            events = api.chat_events(api.ChatRequest(text="weather"))
            await anext(events)
            await events.aclose()
            self.assertTrue(cancelled.is_set())

    async def test_error_has_no_final_success(self):
        fake = NS(model="test", chat=AsyncMock(side_effect=RuntimeError("secret")))
        with patch.object(api, "get_agent", return_value=fake):
            events = [json.loads(line) async for line in api.chat_events(api.ChatRequest(text="hello"))]
        self.assertIn("error", [e["type"] for e in events])
        self.assertNotIn("result", [e["type"] for e in events])
        self.assertNotIn("secret", str(events))

    async def test_concurrent_request_traces_are_isolated(self):
        async def fake_chat(*args, **kwargs):
            await asyncio.sleep(0)
            announce("web_search")
            return "done"
        async def collect(key):
            return [json.loads(x) async for x in api.chat_events(api.ChatRequest(text="hi", trace_id=key))]
        with patch.object(api, "get_agent", return_value=NS(model="test", chat=fake_chat)):
            a, b = await asyncio.gather(collect("a"), collect("b"))
        self.assertEqual([e["trace_id"] for e in a if "trace_id" in e], ["a", "a"])
        self.assertEqual([e["trace_id"] for e in b if "trace_id" in e], ["b", "b"])


class EdgeEventsTests(unittest.TestCase):
    def client(self):
        client = object.__new__(CloudAgentClient)
        client.endpoint = "http://localhost/chat"
        client.timeout_seconds = 1
        client.progress_enabled = True
        client.on_event = Mock()
        client._post_json = Mock(return_value={"reply": "legacy"})
        return client

    def test_events_and_final_response(self):
        client = self.client()
        stream = io.BytesIO(b'{"type":"tool_start","action":"web_search"}\n'
                            b'{"type":"result","data":{"reply":"ok"}}\n')
        with patch("edge.agent.cloud_client.urlopen", return_value=stream):
            self.assertEqual(client._post_chat({}), {"reply": "ok"})
        client.on_event.assert_called_once()
        client._post_json.assert_not_called()

    def test_text_delta_is_forwarded(self):
        client = self.client()
        stream = io.BytesIO(
            '{"type":"text_delta","text":"你好，"}\n'
            '{"type":"result","data":{"reply":"你好，世界。"}}\n'.encode())
        with patch("edge.agent.cloud_client.urlopen", return_value=stream):
            client._post_chat({})
        client.on_event.assert_called_once_with(
            {"type": "text_delta", "text": "你好，"})

    def test_cancellation_discards_response_and_closes_connection(self):
        client = self.client()
        token = SpeechCancellation()
        class BlockingResponse(io.BytesIO):
            def readline(self, *args):
                token.cancel()
                return b""
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()
        response_stream = BlockingResponse()
        with patch("edge.agent.cloud_client.urlopen", return_value=response_stream):
            with self.assertRaises(SpeechInterrupted):
                client._post_chat({}, token)
        self.assertTrue(response_stream.closed)

    def test_cancelled_stream_close_attribute_error_is_interruption(self):
        client = self.client()
        token = SpeechCancellation()

        class ClosingResponse(io.BytesIO):
            def readline(self, *args):
                token.cancel()
                raise AttributeError("'NoneType' object has no attribute 'peek'")

        with patch("edge.agent.cloud_client.urlopen", return_value=ClosingResponse()):
            with self.assertRaises(SpeechInterrupted):
                client._post_chat({}, token)

    def test_only_missing_endpoint_falls_back(self):
        for code in (404, 405, 500):
            client = self.client()
            with patch("edge.agent.cloud_client.urlopen",
                       side_effect=HTTPError(client.endpoint, code, "error", {}, None)):
                if code in (404, 405):
                    self.assertEqual(client._post_chat({}), {"reply": "legacy"})
                else:
                    with self.assertRaises(CloudAgentError):
                        client._post_chat({})
                    client._post_json.assert_not_called()

    def test_truncated_error_and_oversized_events_never_retry(self):
        for raw in [b"", b'{"type":"error"}\n', b'[]\n', b'x' * 131073]:
            client = self.client()
            with patch("edge.agent.cloud_client.urlopen", return_value=io.BytesIO(raw)):
                with self.assertRaises(CloudAgentError):
                    client._post_chat({})
            client._post_json.assert_not_called()


class AckTests(unittest.TestCase):
    def setUp(self):
        self.timer_patch = patch("edge.audio.acknowledgement.threading.Timer")
        self.timer = self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.proc_patch = patch("edge.audio.acknowledgement.subprocess.Popen")
        self.popen = self.proc_patch.start()
        self.addCleanup(self.proc_patch.stop)
        self.ack = ToolAcknowledgement({"web_search": Path("cached.wav")}, "sink")
        self.ack.begin_turn()

    def test_fast_result_cancels_before_playback(self):
        self.ack.on_event({"type": "tool_start", "action": "web_search"})
        self.ack.finish()
        self.ack._play(Path("cached.wav"), self.ack._generation)  # Timer firing after cancellation is harmless.
        self.popen.assert_not_called()
        self.timer.return_value.cancel.assert_called_once()

    def test_start_is_nonblocking_and_finish_serializes_final_speech(self):
        self.ack.on_event({"type": "tool_start", "action": "web_search"})
        self.ack._play(Path("cached.wav"), self.ack._generation)
        self.popen.return_value.wait.assert_not_called()
        self.ack.finish()
        self.popen.return_value.wait.assert_called_once_with(timeout=4.0)
        self.assertTrue(self.ack.played)

    def test_only_one_ack_per_turn(self):
        for _ in range(3):
            self.ack.on_event({"type": "tool_start", "action": "web_search"})
        self.assertEqual(self.timer.call_count, 1)

    def test_old_timer_cannot_speak_in_next_turn(self):
        self.ack.on_event({"type": "tool_start", "action": "web_search"})
        old_generation = self.ack._generation
        self.ack.begin_turn()
        self.ack._play(Path("cached.wav"), old_generation)
        self.popen.assert_not_called()

    def test_normal_chat_and_unknown_events_are_silent(self):
        self.ack.on_event({"type": "tool_start", "action": "respond_text"})
        self.ack.on_event({"type": "timing", "action": "web_search"})
        self.timer.assert_not_called()
        self.assertNotIn("respond_text", PHRASES)

    def test_missing_player_does_not_fail_turn(self):
        self.popen.side_effect = FileNotFoundError()
        self.ack._play(Path("cached.wav"), self.ack._generation)
        self.ack.finish()
        self.assertFalse(self.ack.played)



class HttpContractTests(unittest.TestCase):
    def test_legacy_and_event_endpoints_return_same_final_reply(self):
        from fastapi.testclient import TestClient
        async def fake_chat(*args, **kwargs):
            announce("web_search")
            return "done"
        with patch.object(api, "get_agent", return_value=NS(model="test", chat=fake_chat)):
            with TestClient(api.app) as client:
                old = client.post("/chat", json={"text": "hello", "trace_id": "test"})
                new = client.post("/chat/events", json={"text": "hello", "trace_id": "test"})
                self.assertEqual(old.status_code, 200)
                self.assertEqual(new.status_code, 200)
                self.assertIn("application/x-ndjson", new.headers["content-type"])
                events = [json.loads(line) for line in new.text.splitlines()]
                self.assertEqual(events[0]["type"], "tool_start")
                self.assertEqual(events[-1]["data"], old.json())

    def test_event_endpoint_validates_request_before_execution(self):
        from fastapi.testclient import TestClient
        with patch.object(api, "get_agent") as get_agent:
            with TestClient(api.app) as client:
                self.assertEqual(client.post("/chat/events", json={"text": ""}).status_code, 422)
            get_agent.assert_not_called()


class TtsTimingTests(unittest.TestCase):
    def test_callback_and_fallback_report_first_audio_once(self):
        import importlib
        import numpy as np
        import sys
        fake_sherpa = NS(GenerationConfig=NS)
        with patch.dict(sys.modules, {"sherpa_onnx": fake_sherpa}):
            module = importlib.import_module("edge.audio.tts.kokoro")
        module._sherpa_module = fake_sherpa
        try:
            for callback_enabled in (True, False):
                with self.subTest(callback_enabled=callback_enabled):
                    tts = object.__new__(module.KokoroTts)
                    tts.speaker_id = 50
                    tts.speed = 1.0
                    tts.silence_scale = 0.2
                    tts._prepare_sink = Mock()
                    audio = NS(samples=np.zeros(200, dtype=np.float32), sample_rate=24000)
                    import threading
                    hook_started = threading.Event()
                    generated = threading.Event()
                    hook_done = threading.Event()
                    def before_playback():
                        hook_started.set()
                        if not generated.wait(2):
                            raise RuntimeError("Synthesis did not overlap acknowledgement")
                        hook_done.set()
                    def generate(text, config, callback):
                        self.assertTrue(hook_started.wait(2))
                        if callback_enabled:
                            callback(audio.samples[:100], 0.5)
                            callback(audio.samples[100:], 1)
                        generated.set()
                        return audio
                    tts._tts = NS(generate=generate, sample_rate=24000)
                    player = Mock()
                    player.wait.return_value = 0
                    player.stdin.write.side_effect = lambda data: self.assertTrue(hook_done.is_set())
                    with patch.object(module.subprocess, "Popen", return_value=player), \
                         patch.object(module, "record") as record:
                        result = tts.speak("hello", "sink", before_playback=before_playback)
                    self.assertEqual(result.sample_rate, 24000)
                    stages = [call.args[0] for call in record.call_args_list]
                    self.assertEqual(stages.count("tts_first_callback"), 1)
                    self.assertEqual(stages.count("tts_first_pcm_submit"), 1)
                    self.assertEqual(player.stdin.write.call_count, 2 if callback_enabled else 1)
        finally:
            module._sherpa_module = None
            sys.modules.pop("edge.audio.tts.kokoro", None)

if __name__ == "__main__":
    unittest.main()
