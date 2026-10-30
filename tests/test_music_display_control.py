import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from edge.display.server import app
from edge.music import control_bridge
from edge.audio import status as audio_status
from edge.display.state import DisplayPublisher
from robot_tools.music import MusicTools


class MusicDisplayControlTests(unittest.TestCase):
    def test_display_control_accepts_only_known_actions_and_records_request(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(control_bridge, "REQUEST", Path(directory) / "request.json"), \
             patch.object(control_bridge, "STATUS", Path(directory) / "status.json"):
            client = TestClient(app)
            self.assertEqual(client.post("/api/music/control", json={
                "action": "pause_music"}).status_code, 403)
            self.assertEqual(client.post("/api/music/control", json={
                "action": "play_url"}, headers={"X-LuckRobot-Display": "1"}).status_code, 422)
            response = client.post("/api/music/control", json={
                "action": "pause_music"}, headers={"X-LuckRobot-Display": "1"})
            self.assertEqual(response.status_code, 200)
            request = control_bridge.read_json(control_bridge.REQUEST)
            self.assertEqual(request["action"], "pause_music")
            self.assertEqual(request["id"], response.json()["id"])
            control_bridge.publish(request["id"], "pause_music", {
                "ok": True, "playing": False, "message": "paused"})
            self.assertEqual(client.get("/api/music/control").json()["playing"], False)

    def test_paused_music_metadata_is_explicitly_marked(self):
        class Controller:
            def pause(self):
                return None

        music = MusicTools({"enabled": True, "provider": "qqmusic"}, controller=Controller())
        music.playing = True
        music.current_song = {"title": "安河桥", "artists": ["宋冬野"]}
        result = music.control("pause_music")
        self.assertTrue(result["ok"])
        self.assertFalse(result["playing"])
        self.assertEqual(result["music"]["title"], "安河桥")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(audio_status, "_display", DisplayPublisher({
                 "state_path": str(Path(directory) / "display.json")})):
            audio_status.display_music(result["music"], playing=result["playing"])
            state = control_bridge.read_json(Path(directory) / "display.json")
            self.assertFalse(state["music"]["playing"])


if __name__ == "__main__":
    unittest.main()
