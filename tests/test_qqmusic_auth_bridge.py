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

    def test_account_info_reports_page_identity_and_saves_avatar(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = QQMusicController(profile_path=directory)
            driver = Mock()
            avatar = Mock()
            avatar.is_displayed.return_value = True
            avatar.screenshot.side_effect = lambda path: Path(path).write_bytes(b"PNG")
            driver.find_elements.return_value = [avatar]
            driver.find_element.return_value = avatar
            driver.execute_script.return_value = "测试昵称"
            driver.window_handles = ["search"]
            controller._driver = driver
            controller._search_handle = "search"
            with patch("edge.music.qqmusic.WebDriverWait") as wait:
                wait.return_value.until.side_effect = lambda condition: condition(driver)
                info = controller.account_info(Path(directory) / "avatar.png")
            self.assertEqual(info, {"state": "ready", "nickname": "测试昵称", "avatar": True})

    def test_logout_removes_only_dedicated_profile_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            for name in ("cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm"):
                (profile / name).write_bytes(b"cookie")
            (profile / "prefs.js").write_text("keep", encoding="utf-8")
            controller = QQMusicController(profile_path=profile)
            controller.logout_account()
            self.assertFalse(any(profile.glob("cookies.sqlite*")))
            self.assertEqual((profile / "prefs.js").read_text(encoding="utf-8"), "keep")

    def test_account_name_falls_back_to_qq_profile_page(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = QQMusicController(profile_path=directory)
            driver = Mock()
            avatar = Mock()
            avatar.is_displayed.return_value = True
            name = Mock(text="网页昵称")
            driver.find_elements.side_effect = lambda by, selector: (
                [name] if selector == ".profile__name" else
                [avatar] if selector == "img.top_login__cover" else [])
            driver.find_element.return_value = avatar
            driver.execute_script.return_value = ""
            driver.window_handles = ["search"]
            controller._driver = driver
            controller._search_handle = "search"
            with patch("edge.music.qqmusic.WebDriverWait") as wait:
                wait.return_value.until.side_effect = lambda condition: condition(driver)
                info = controller.account_info()
            self.assertEqual(info["nickname"], "网页昵称")
            driver.get.assert_any_call("https://y.qq.com/n/ryqq/profile")

    def test_browser_login_reuses_existing_modal_and_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = QQMusicController(profile_path=directory)
            driver = Mock()
            login_link = Mock(text="登录")
            login_link.is_displayed.return_value = True
            modal = Mock()
            modal.is_displayed.return_value = True
            driver.find_elements.side_effect = lambda by, selector: (
                [login_link] if selector == "a.top_login__link" else
                [modal] if selector == "iframe.login-box-bd__ifr_qq" else [])
            driver.window_handles = ["search"]
            driver.current_url = "https://y.qq.com/n/ryqq/search"
            driver.get_screenshot_as_png.return_value = b"PNG"
            controller._driver = driver
            controller._search_handle = "search"
            get_cancel = Mock(side_effect=[{"id": "old"}, {"id": "old"}, {"id": "new"}])
            publish = Mock()
            with patch("edge.music.qqmusic.WebDriverWait") as wait, patch(
                "edge.music.qqmusic.time.sleep"
            ):
                wait.return_value.until.side_effect = lambda condition: "login"
                result = controller.authenticate_with_browser(
                    Path(directory) / "browser.png", publish,
                    lambda: {"id": "old"}, get_cancel)
            self.assertFalse(result)
            publish.assert_any_call("browser", qr_available=False, qr_revision=0)
            publish.assert_any_call("required")
            driver.find_element.assert_not_called()
            self.assertFalse((Path(directory) / "browser.png").exists())

    def test_browser_click_maps_normalized_viewport_coordinates(self):
        driver = Mock()
        target = Mock(tag_name="button")
        driver.execute_script.side_effect = [[1280, 634], [target, 0, 0]]
        QQMusicController._click_browser_at(driver, 0.5, 0.25)
        self.assertEqual(driver.execute_script.call_args_list[1].args[-2:], (640, 158))
        target.click.assert_called_once()

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

    def test_logout_and_avatar_are_local_display_only(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            status_path = Path(directory) / "status.json"
            avatar_path = Path(directory) / "avatar.png"
            avatar_path.write_bytes(b"PNG")
            with patch.object(auth_bridge, "REQUEST", request_path), patch.object(
                auth_bridge, "STATUS", status_path
            ), patch.object(auth_bridge, "AVATAR_IMAGE", avatar_path):
                client = TestClient(app)
                self.assertEqual(client.post("/api/music/auth/logout").status_code, 403)
                auth_bridge.publish("ready", nickname="测试昵称", avatar=True)
                self.assertEqual(client.get("/api/music/auth/avatar").content, b"PNG")
                response = client.post("/api/music/auth/logout", headers={
                    "X-LuckRobot-Display": "1"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(auth_bridge.read_json(request_path)["action"], "logout")
                self.assertEqual(client.get("/api/music/auth/avatar").status_code, 404)

    def test_browser_preview_click_and_cancel_are_session_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            browser_path = Path(directory) / "browser.png"
            click_path = Path(directory) / "click.json"
            cancel_path = Path(directory) / "cancel.json"
            status_path = Path(directory) / "status.json"
            browser_path.write_bytes(b"PNG")
            with patch.object(auth_bridge, "BROWSER_IMAGE", browser_path), patch.object(
                auth_bridge, "BROWSER_CLICK", click_path
            ), patch.object(auth_bridge, "BROWSER_CANCEL", cancel_path), patch.object(
                auth_bridge, "STATUS", status_path
            ):
                client = TestClient(app)
                self.assertEqual(client.get("/api/music/auth/browser").status_code, 404)
                auth_bridge.publish("browser")
                self.assertEqual(client.get("/api/music/auth/browser").content, b"PNG")
                url = "/api/music/auth/browser/click"
                self.assertEqual(client.post(url, json={"x": 0.5, "y": 0.5}).status_code, 403)
                headers = {"X-LuckRobot-Display": "1"}
                self.assertEqual(client.post(url, json={"x": -0.1, "y": 0.5},
                                             headers=headers).status_code, 422)
                self.assertEqual(client.post(url, json={"x": 0.5, "y": 0.25},
                                             headers=headers).status_code, 200)
                self.assertEqual(auth_bridge.read_json(click_path)["y"], 0.25)
                self.assertEqual(client.post("/api/music/auth/browser/cancel",
                                             headers=headers).status_code, 200)
                self.assertIn("id", auth_bridge.read_json(cancel_path))
                auth_bridge.publish("required")
                self.assertEqual(client.get("/api/music/auth/browser").status_code, 404)
                self.assertEqual(client.post(url, json={"x": 0.5, "y": 0.5},
                                             headers=headers).status_code, 409)


if __name__ == "__main__":
    unittest.main()
