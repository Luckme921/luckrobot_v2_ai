import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from edge.navigation.feedback import FeedbackSpeech

class FeedbackTests(unittest.TestCase):
    def test_valid_duplicate_expired_and_busy(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'event.json'
            event = dict(schema=1, event_id='a:1', code='PLANNING_FAILED', observed_unix=time.time(), ttl_sec=10)
            p.write_text(json.dumps(event))
            with patch('edge.navigation.feedback.EVENT', p):
                reader = FeedbackSpeech()
                self.assertIsNone(reader.take(False))
                reader.poll_at = 0
                self.assertIn('规划', reader.take())
                reader.poll_at = 0
                self.assertIsNone(reader.take())
                event.update(event_id='a:2', observed_unix=time.time()-11)
                p.write_text(json.dumps(event))
                reader.poll_at = 0
                self.assertIsNone(reader.take())
    def test_unknown_code_is_not_spoken(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'event.json'
            p.write_text(json.dumps(dict(schema=1,event_id='a',code='UNKNOWN',speech_text='unsafe',observed_unix=time.time(),ttl_sec=10)))
            with patch('edge.navigation.feedback.EVENT',p):
                self.assertIsNone(FeedbackSpeech().take())
