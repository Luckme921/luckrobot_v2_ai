import threading
import time
import unittest
from concurrent.futures import Future

from edge.audio.tts.cancellation import SpeechCancellation
from edge.audio.tts.prepared import prepared_audio
from edge.audio.tts.streaming_reply import StreamingReplySpeaker, _PreparationCancellation


class _PreparedTts:
    def __init__(self):
        self.prepared = []
        self.played = []
        self.second_prepare_started = threading.Event()
        self.concurrent_prepare_observed = False

    def prepare(self, text, cancellation=None):
        self.prepared.append(text)
        if len(self.prepared) == 2:
            self.second_prepare_started.set()
        return prepared_audio(b"\x01\x00" * 240, 24000, 0.01, 0.01)

    def play_prepared(self, audio, sink, before_playback=None, cancellation=None):
        index = len(self.played)
        if before_playback:
            before_playback()
        if index == 0:
            self.concurrent_prepare_observed = self.second_prepare_started.wait(1)
        self.played.append(self.prepared[index])


class StreamingReplySpeakerTests(unittest.TestCase):
    def test_ready_online_segment_cancels_unused_offline_backup(self):
        tts = _PreparedTts()
        speaker = StreamingReplySpeaker(tts, "sink", SpeechCancellation())
        parent = SpeechCancellation()
        online_token = _PreparationCancellation(parent)
        offline_token = _PreparationCancellation(parent)
        online = Future()
        offline = Future()
        online.set_result("edge audio")
        self.assertEqual(speaker._choose_hedged_audio(
            2, online, offline, online_token, offline_token), "edge audio")
        self.assertTrue(offline_token.event.is_set())
        speaker.cancel()

    def test_edge_streams_first_segment_and_uses_warm_offline_next_segment(self):
        class HedgedTts:
            def __init__(self):
                self.streamed = []
                self.played = []
                self.online_prepared = []

            def prepare_offline(self, text, cancellation=None):
                return prepared_audio(b"\x02\x00" * 240, 24000, 0.01, 0.01)

            def prepare_online(self, text, cancellation=None):
                self.online_prepared.append(text)
                time.sleep(0.1)
                return prepared_audio(b"\x01\x00" * 240, 24000, 0.1, 0.1)

            def speak_with_prepared_fallback(self, text, sink, fallback_future,
                                             before_playback=None, cancellation=None):
                self.streamed.append(text)
                if before_playback:
                    before_playback()

            def play_prepared(self, audio, sink, before_playback=None, cancellation=None):
                self.played.append(audio.pcm[:2])

        tts = HedgedTts()
        hooks = []
        speaker = StreamingReplySpeaker(
            tts, "sink", SpeechCancellation(), before_playback=lambda: hooks.append(1),
            fallback_grace_seconds=0)
        speaker.on_event({"type": "text_delta", "text": "你好，明天见。"})
        self.assertTrue(speaker.finish())
        self.assertEqual(tts.streamed, ["你好，"])
        self.assertEqual(tts.online_prepared, ["明天见。"])
        self.assertEqual(tts.played, [b"\x02\x00"])
        self.assertEqual(hooks, [1])

    def test_prepares_concurrently_and_plays_in_text_order(self):
        tts = _PreparedTts()
        acknowledgements = []
        speaker = StreamingReplySpeaker(
            tts, "sink", SpeechCancellation(),
            before_playback=lambda: acknowledgements.append("done"),
            max_workers=3)
        speaker.on_event({"type": "text_delta", "text": "你好，今天"})
        speaker.on_event({"type": "text_delta", "text": "天气不错；出去走走。"})
        self.assertTrue(speaker.finish())
        self.assertTrue(tts.concurrent_prepare_observed)
        self.assertEqual(tts.played, ["你好，", "今天天气不错；", "出去走走。"])
        self.assertEqual(acknowledgements, ["done"])

    def test_non_text_events_are_ignored(self):
        tts = _PreparedTts()
        speaker = StreamingReplySpeaker(tts, "sink", SpeechCancellation())
        speaker.on_event({"type": "tool_start", "action": "web_search"})
        self.assertFalse(speaker.finish())
        self.assertEqual(tts.prepared, [])

    def test_decimal_point_split_across_model_deltas_is_not_a_boundary(self):
        tts = _PreparedTts()
        speaker = StreamingReplySpeaker(tts, "sink", SpeechCancellation())
        speaker.on_event({"type": "text_delta", "text": "今天气温是23."})
        speaker.on_event({"type": "text_delta", "text": "5摄氏度，注意保暖。"})
        self.assertTrue(speaker.finish())
        self.assertEqual(tts.played, ["今天气温是23.5摄氏度，", "注意保暖。"])

    def test_numeric_periods_inside_version_and_ip_are_preserved(self):
        tts = _PreparedTts()
        speaker = StreamingReplySpeaker(tts, "sink", SpeechCancellation())
        speaker.on_event({
            "type": "text_delta",
            "text": "版本是3.12.2，地址是192.168.3.23。",
        })
        self.assertTrue(speaker.finish())
        self.assertEqual(
            tts.played,
            ["版本是3.12.2，", "地址是192.168.3.23。"],
        )


if __name__ == "__main__":
    unittest.main()
