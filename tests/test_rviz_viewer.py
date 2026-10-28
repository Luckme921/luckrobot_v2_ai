import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml
from fastapi.testclient import TestClient
from edge.display.server import app
from edge.display.rviz import prepare_profile


class RvizViewerTests(unittest.TestCase):
    def test_monitor_copy_preserves_source_and_removes_motion_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/"source.rviz", Path(directory)/"monitor.rviz"
            original = {"Panels": [{"Class": "nav2_rviz_plugins/Navigation 2"}, {"Class": "rviz_common/Displays"}],
                        "Visualization Manager": {"Tools": [{"Class": "nav2_rviz_plugins/GoalTool"}],
                                                   "Displays": [{"Name": "Map", "Topic": {"Value": "/map"}}]}}
            source.write_text(yaml.safe_dump(original), encoding="utf-8")
            prepare_profile(source, target)
            self.assertEqual(yaml.safe_load(source.read_text()), original)
            monitor = yaml.safe_load(target.read_text())
            self.assertEqual(monitor["Visualization Manager"]["Displays"], original["Visualization Manager"]["Displays"])
            self.assertNotIn("nav2_rviz_plugins/Navigation 2", str(monitor))
            self.assertNotIn("GoalTool", str(monitor))
            self.assertEqual(monitor["Window Geometry"]["Y"], 70)

    def test_viewer_api_has_no_arbitrary_command_or_path(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/rviz/action", json={"action": "open"}).status_code, 403)
        headers = {"X-LuckRobot-Display": "1"}
        for payload in [{"action": "shell"}, {"action": []}, {"action": "open", "path": "/tmp/x"}]:
            self.assertEqual(client.post("/api/rviz/action", json=payload, headers=headers).status_code, 422)
        with patch("edge.display.rviz.viewer.request", return_value={"ok": True}) as request:
            self.assertTrue(client.post("/api/rviz/action", json={"action": "restart"}, headers=headers).json()["ok"])
            request.assert_called_once_with("restart")
