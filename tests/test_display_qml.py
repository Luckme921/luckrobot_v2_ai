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


if __name__ == "__main__":
    unittest.main()
