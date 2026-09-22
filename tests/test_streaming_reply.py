import unittest
from unittest.mock import Mock

from edge.audio.tts.cancellation import SpeechCancellation
from edge.audio.tts.streaming_reply import StreamingReplySpeaker


class StreamingReplySpeakerTests(unittest.TestCase):
    def test_splits_at_requested_punctuation_and_preserves_order(self):
        tts = Mock()
        token = SpeechCancellation()
        speaker = StreamingReplySpeaker(tts, "sink", token)
        speaker.on_event({"type": "text_delta", "text": "你好，今天"})
        speaker.on_event({"type": "text_delta", "text": "天气不错；出去走走。"})
        self.assertTrue(speaker.finish())
        chunks = [call.args[0] for call in tts.speak.call_args_list]
        self.assertEqual(chunks, ["你好，", "今天天气不错；", "出去走走。"])

    def test_non_text_events_are_ignored(self):
        tts = Mock()
        speaker = StreamingReplySpeaker(tts, "sink", SpeechCancellation())
        speaker.on_event({"type": "tool_start", "action": "web_search"})
        self.assertFalse(speaker.finish())
        tts.speak.assert_not_called()
