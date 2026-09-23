import tempfile
import unittest
from pathlib import Path

from edge.audio.conversation_log import ConversationLog


class ConversationLogTests(unittest.TestCase):
    def test_writes_single_line_utf8_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversation.log"
            log = ConversationLog({"enabled": True, "path": str(path)})
            log.write("ASR_SLEEP", "拉克\n你好", duration="1.20s")
            log.write("ASSISTANT", "你好呀", model="test")
            content = path.read_text(encoding="utf-8")
            self.assertIn("[ASR_SLEEP] duration=1.20s 拉克 你好", content)
            self.assertIn("[ASSISTANT] model=test 你好呀", content)
            log.close()

    def test_disabled_log_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversation.log"
            ConversationLog({"enabled": False, "path": str(path)}).write("ASR", "你好")
            self.assertFalse(path.exists())
