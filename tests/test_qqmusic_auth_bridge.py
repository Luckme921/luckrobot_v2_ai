import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from edge.display.server import app
from edge.music import auth_bridge
from edge.music.qqmusic import QQMusicController


class QQMusicAuthBridgeTests(unittest.TestCase):
    def test_firefox_uses_persistent_profile_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = QQMusicController(profile_path=directory)
            with patch("edge.music.qqmusic.webdriver.Firefox") as firefox, patch(
                "edge.music.qqmusic.Service"
            ):
                firefox.return_value.current_window_handle = "search"
                controller.start()
                options = firefox.call_args.kwargs["options"]
                self.assertEqual(options.arguments[-2:], ["-profile", str(Path(directory).resolve())])
                self.assertIsNone(options.profile)
                controller.close()

    def test_existing_login_does_not_request_new_qr(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = QQMusicController(profile_path=directory)
            driver = Mock()
            driver.find_elements.return_value = [Mock(is_displayed=lambda: True, text="account")]
            controller._driver = driver
            controller._search_handle = "search"
            driver.window_handles = ["search"]
            publish = Mock()
            with patch("edge.music.qqmusic.WebDriverWait") as wait:
                wait.return_value.until.side_effect = lambda condition: condition(driver)
                self.assertTrue(controller.authenticate_with_qr(Path(directory) / "qr.png", publish))
            publish.assert_called_once_with("ready")
            driver.find_element.assert_not_called()

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
