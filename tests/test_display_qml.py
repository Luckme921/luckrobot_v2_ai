from pathlib import Path
import unittest


class DisplayQmlTests(unittest.TestCase):
    def test_qml_contains_supported_states_and_state_endpoint(self):
        source = Path("edge/display/qml/main.qml").read_text(encoding="utf-8")
        for state in (
            "sleeping", "listening", "transcribing", "thinking",
            "speaking", "interrupted", "music",
        ):
            self.assertIn(f'robotState === "{state}"', source)
        self.assertIn("http://127.0.0.1:8765/api/state", source)

    def test_qml_has_music_motion_and_scrollable_multiline_dialogue(self):
        source = Path("edge/display/qml/main.qml").read_text(encoding="utf-8")
        self.assertIn("property var musicInfo", source)
        self.assertIn("RotationAnimation on rotation", source)
        self.assertIn("id: equalizer", source)
        self.assertIn("正在播放：《", source)
        self.assertIn('visible: root.robotState !== "music"', source)
        self.assertIn('root.robotState === "music" ?', source)
        self.assertIn("id: assistantViewport", source)
        roller = Path("edge/display/qml/RollingLines.qml").read_text(encoding="utf-8")
        self.assertIn("Flickable", roller)
        self.assertIn("wrapMode: Text.WrapAnywhere", roller)
        self.assertIn("Behavior on contentY", roller)

    def test_device_launcher_uses_validated_linuxfb_and_dynamic_touch(self):
        source = Path("scripts/run_display_qt.sh").read_text(encoding="utf-8")
        self.assertIn("LUCKROBOT_QT_PLATFORM:-linuxfb", source)
        self.assertIn("QT_QUICK_BACKEND:-software", source)
        self.assertIn("ID_INPUT_TOUCHSCREEN=1", source)
        self.assertNotIn("/dev/input/event9", source)


if __name__ == "__main__":
    unittest.main()
