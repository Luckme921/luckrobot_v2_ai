import threading
import unittest
from unittest.mock import Mock

import numpy as np

from edge.audio.tts.kokoro import KokoroTts, _GeneratedChunk


class PreparedTtsTests(unittest.TestCase):
    def test_kokoro_prepare_generates_pcm_on_first_call(self):
        tts = object.__new__(KokoroTts)
        tts._generation_lock = threading.Lock()
        tts._generate = Mock(return_value=_GeneratedChunk(
            samples=np.array([0.0, 0.5, -0.5], dtype=np.float32),
            sample_rate=24000,
            generation_seconds=0.02))
        audio = tts.prepare("你好")
        self.assertEqual(audio.sample_rate, 24000)
        self.assertEqual(len(audio.pcm), 6)
        tts._generate.assert_called_once_with("你好")


if __name__ == "__main__":
    unittest.main()
