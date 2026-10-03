import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from edge.display.server import app
from edge.music import auth_bridge


class QQMusicAuthBridgeTests(unittest.TestCase):
    def test_display_login_requires_local_ui_header_and_writes_request(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            status_path = Path(directory) / "status.json"
            with patch.object(auth_bridge, "REQUEST", request_path), patch.object(
                auth_bridge, "STATUS", status_path
            ):
                client = TestClient(app)
                self.assertEqual(client.post("/api/music/auth/login").status_code, 403)
                response = client.post("/api/music/auth/login", headers={
                    "X-LuckRobot-Display": "1"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(auth_bridge.read_json(request_path)["id"], response.json()["id"])
                self.assertEqual(client.get("/api/music/auth").json()["state"], "starting")

    def test_qr_only_served_while_authentication_is_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            qr_path = Path(directory) / "qr.png"
            qr_path.write_bytes(b"PNG")
            status_path = Path(directory) / "status.json"
            with patch.object(auth_bridge, "QR_IMAGE", qr_path), patch.object(
                auth_bridge, "STATUS", status_path
            ):
                client = TestClient(app)
                self.assertEqual(client.get("/api/music/auth/qr").status_code, 404)
                auth_bridge.publish("qr")
                self.assertEqual(client.get("/api/music/auth/qr").content, b"PNG")
                self.assertEqual(client.post("/api/music/auth/login", headers={
                    "X-LuckRobot-Display": "1"}).json()["state"], "qr")
                self.assertEqual(auth_bridge.status()["state"], "qr")
                auth_bridge.publish("ready")
                self.assertEqual(client.get("/api/music/auth/qr").status_code, 404)


if __name__ == "__main__":
    unittest.main()
