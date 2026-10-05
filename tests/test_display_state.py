import json
from pathlib import Path
import tempfile
import unittest

from edge.display.state import DisplayPublisher
from edge.display.rolling_text import display_rows, row_index


class DisplayPublisherTests(unittest.TestCase):
    def test_rolling_rows_preserve_decimal_and_follow_spoken_offset(self):
        rows = display_rows("气温是23.5度，出门带伞。")
        self.assertEqual([row[0] for row in rows], ["气温是23.5度，", "出门带伞。"])
        self.assertEqual(row_index(rows, 0), 0)
        self.assertEqual(row_index(rows, len("气温是23.5度，")), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display.json"
            publisher = DisplayPublisher({"state_path": str(path)})
            publisher.publish(assistant_text="气温是23.5度，出门带伞。",
                              assistant_progress_chars=len("气温是23.5度，"))
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["assistant_lines"], ["气温是23.5度，", "出门带伞。"])
            self.assertEqual(state["assistant_line_index"], 1)

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
