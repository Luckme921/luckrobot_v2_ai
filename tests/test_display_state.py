import json
from pathlib import Path
import tempfile
import unittest

from edge.display.state import DisplayPublisher


class DisplayPublisherTests(unittest.TestCase):
    def test_publishes_structured_unicode_state_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display.json"
            publisher = DisplayPublisher({"enabled": True, "state_path": str(path)})
            publisher.publish(
                state="speaking", label="正在回答",
                user_text="你好", assistant_text="你好呀")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "speaking")
            self.assertEqual(data["user_text"], "你好")
            self.assertEqual(data["assistant_text"], "你好呀")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_publishes_and_clears_now_playing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display.json"
            publisher = DisplayPublisher({"enabled": True, "state_path": str(path)})
            publisher.publish(
                state="music", label="等待 Lucky", music_marker=True,
                music={"title": "安和桥", "artists": ["宋冬野"]})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["music"]["title"], "安和桥")
            self.assertEqual(data["music"]["artists"], ["宋冬野"])
            publisher.publish(music_marker=True, music=None)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(data["music"])

    def test_disabled_publisher_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display.json"
            DisplayPublisher({"enabled": False, "state_path": str(path)}).publish(
                state="thinking")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
