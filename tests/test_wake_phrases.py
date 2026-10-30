import tempfile
import unittest
import wave
from pathlib import Path
from test_session_and_tools import gate
from edge.audio.tts.phrase_cache import cache_path,valid_clip
class WakePhraseTests(unittest.TestCase):
    def test_greeting_only_local_but_commands_preserved(self):
        for text in ["lucky", "lucky你好", "lucky，你好呀！", "你好", "你在吗"]:
            g=gate();g.on_wake(now=0)
            self.assertEqual(g.process(text,now=1).action,"awake")
            self.assertEqual(g.state,g.AWAKE_WAIT_COMMAND)
        for text in ["lucky你好，帮我查天气", "lucky播放稻香", "你好是什么意思", "你好，去厨房"]:
            g=gate();g.on_wake(now=0)
            self.assertEqual(g.process(text,now=1).action,"command")
    def test_active_greeting_is_normal_conversation(self):
        g=gate();g.on_wake(now=0);g.process("聊聊天",now=1)
        self.assertEqual(g.process("你好",now=2).action,"command")
    def test_cache_validates_and_keys_voice_text(self):
        self.assertNotEqual(cache_path("a","你好"),cache_path("b","你好"))
        self.assertNotEqual(cache_path("a","你好"),cache_path("a","我在"))
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"a.wav"
            self.assertFalse(valid_clip(p))
            with wave.open(str(p),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b"\0"*100)
            self.assertTrue(valid_clip(p))
            p.write_bytes(b"broken")
            self.assertFalse(valid_clip(p))
