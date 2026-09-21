import tempfile
from pathlib import Path
from edge.agent.memory_store import ConversationMemory
import threading
import unittest
from unittest.mock import Mock, patch
from edge.audio.barge_in import speak_with_wake
from edge.audio.tts.cancellation import SpeechCancellation, SpeechInterrupted


class BargeInTests(unittest.TestCase):
    def test_cancel_kills_registered_and_late_players(self):
        token = SpeechCancellation()
        first, late = Mock(), Mock()
        first.poll.return_value = late.poll.return_value = None
        token.register(first)
        token.cancel()
        token.register(late)
        first.kill.assert_called_once()
        late.kill.assert_called_once()
        with self.assertRaises(SpeechInterrupted):
            token.check()

    @patch("edge.audio.barge_in.PulseCapture")
    def test_wake_interrupts_and_releases_monitor(self, factory):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = Path(directory.name) / "memory.sqlite3"
        memory = ConversationMemory(db, recent_turns=100, compact_batch_turns=100)
        memory.add_turn("question", "archived reply")
        capture = Mock(sample_rate=16000)
        monitor = factory.return_value
        monitor.chunks.return_value = [b"\0\0" * 320]
        kws = Mock()
        kws.accept.return_value = "LUCKY"
        tts = Mock()
        def speak(*args, cancellation, **kwargs):
            self.assertTrue(cancellation.event.wait(2))
            cancellation.check()
        tts.speak.side_effect = speak
        with self.assertRaises(SpeechInterrupted):
            speak_with_wake(tts, "archived reply", "sink", capture=capture, kws=kws)
        restored = ConversationMemory(db, recent_turns=100, compact_batch_turns=100)
        self.assertEqual(restored.turn_count, 1)
        self.assertEqual(restored.prepare_context().messages[-1]["content"], "archived reply")
        monitor.stop.assert_called_once()
        self.assertFalse(any(t.name == "lucky-barge-in" for t in threading.enumerate()))

    @patch("edge.audio.barge_in.PulseCapture")
    def test_normal_speech_does_not_interrupt(self, factory):
        monitor = factory.return_value
        monitor.chunks.return_value = [b"\0\0" * 320]
        seen = threading.Event()
        kws = Mock()
        def accept(*args):
            seen.set()
            return None
        kws.accept.side_effect = accept
        tts = Mock()
        def speak(*args, cancellation, **kwargs):
            self.assertTrue(seen.wait(2))
            cancellation.check()
            return "completed"
        tts.speak.side_effect = speak
        self.assertEqual(speak_with_wake(tts, "reply", "sink", capture=Mock(), kws=kws), "completed")
        monitor.stop.assert_called_once()

    @patch("edge.audio.barge_in.PulseCapture")
    def test_capture_failure_falls_back_to_half_duplex(self, factory):
        factory.return_value.start.side_effect = OSError()
        tts = Mock()
        result = speak_with_wake(tts, "reply", "sink", capture=Mock(), kws=Mock())
        self.assertIs(result, tts.speak.return_value)
        tts.speak.assert_called_once_with("reply", "sink", before_playback=None)
        factory.return_value.stop.assert_called_once()
