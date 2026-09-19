import unittest
from unittest.mock import Mock
from edge.audio.tts.edge_online import EdgeOnlineTts
from edge.audio.tts.kokoro import TtsError

class EdgeTtsTests(unittest.TestCase):
    def test_failure_before_audio_falls_back(self):
        fallback=Mock(); tts=EdgeOnlineTts({},fallback); gate=Mock()
        tts._online=Mock(side_effect=TimeoutError())
        self.assertIs(tts.speak("test","sink",before_playback=gate),fallback.speak.return_value)
        fallback.speak.assert_called_once_with("test","sink",before_playback=gate)

    def test_partial_audio_never_replays(self):
        fallback=Mock(); tts=EdgeOnlineTts({},fallback)
        def fail(text,sink,gate,state):
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
        self.assertTrue(tts.python.endswith("private/tts-eval-venv/bin/python"))
