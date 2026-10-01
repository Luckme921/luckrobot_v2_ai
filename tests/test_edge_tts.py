import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock
from edge.audio.tts.edge_online import EdgeOnlineTts
from edge.audio.tts.kokoro import TtsError

class EdgeTtsTests(unittest.TestCase):
    def test_first_segment_uses_already_prepared_fallback_before_audio(self):
        fallback = Mock()
        tts = EdgeOnlineTts({}, fallback)
        tts._online = Mock(side_effect=TimeoutError())
        future = Future()
        future.set_result("offline audio")
        tts.speak_with_prepared_fallback("test", "sink", future)
        fallback.play_prepared.assert_called_once_with(
            "offline audio", "sink", before_playback=None, cancellation=None)
        fallback.prepare.assert_not_called()

    def test_failure_before_audio_falls_back(self):
        fallback=Mock(); tts=EdgeOnlineTts({},fallback); gate=Mock()
        tts._online=Mock(side_effect=TimeoutError())
        self.assertIs(tts.speak("test","sink",before_playback=gate),fallback.speak.return_value)
        fallback.speak.assert_called_once_with("test","sink",before_playback=gate)

    def test_partial_audio_never_replays(self):
        fallback=Mock(); tts=EdgeOnlineTts({},fallback)
        def fail(text,sink,gate,state,cancellation=None):
            state["submitted"]=True
            raise BrokenPipeError()
        tts._online=fail
        with self.assertRaises(TtsError): tts.speak("test","sink")
        fallback.speak.assert_not_called()

    def test_online_success_does_not_call_offline(self):
        fallback=Mock(); tts=EdgeOnlineTts({},fallback)
        tts._online=Mock(return_value="result")
        self.assertEqual(tts.speak("test","sink"),"result")
        fallback.speak.assert_not_called()

    def test_interpreter_keeps_virtualenv_path(self):
        tts=EdgeOnlineTts({"edge_python":"private/tts-eval-venv/bin/python"},Mock())
        self.assertTrue(Path(tts.python).as_posix().endswith("private/tts-eval-venv/bin/python"))

    def test_cancel_before_audio_never_falls_back(self):
        from edge.audio.tts.cancellation import SpeechCancellation, SpeechInterrupted
        token = SpeechCancellation()
        token.cancel()
        fallback = Mock()
        tts = EdgeOnlineTts({}, fallback)
        tts._online = Mock(side_effect=TimeoutError())
        with self.assertRaises(SpeechInterrupted):
            tts.speak("test", "sink", cancellation=token)
        fallback.speak.assert_not_called()
