import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from edge.display.server import app
from edge.network.agent import NetworkManager, split_row, validate_config
from edge.network.bridge import NetworkJobs, validate_targets


def config(**kwargs):
    return {"ssid": "test:Wi-Fi", "password": "example123", **kwargs}


class NetworkTests(unittest.TestCase):
    def test_saved_profile_reference_contains_no_password(self):
        saved = {"ssid":"test", "saved_uuid":"8c05ad99-dcbc-4f9b-a301-c71c16aa0ac1"}
        self.assertEqual(validate_config(saved), saved)
        self.assertEqual(len(validate_targets({"brain":saved, "cerebellum":saved})), 2)
        for bad in [{**saved, "password":"do-not-accept"}, {**saved, "saved_uuid":"--shell"}]:
            with self.assertRaises(ValueError): validate_config(bad)

    def test_dhcp_and_static_validation(self):
        self.assertEqual(validate_config(config())["method"], "auto")
        valid = config(method="manual", address="192.168.3.40/24", gateway="192.168.3.1", dns=["223.5.5.5"])
        self.assertEqual(validate_config(valid)["address"], "192.168.3.40/24")
        for change in [{"address": "10.0.0.50/24"}, {"address": "10.0.1.1/8"},
                       {"address": "192.168.3.40"}, {"gateway": "192.168.2.1"},
                       {"gateway": "192.168.3.40"}, {"dns": []}, {"interface": "eth0"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config({**valid, **change})

    def test_pair_requires_distinct_addresses_and_same_wifi(self):
        static = config(method="manual", address="192.168.3.40/24", gateway="192.168.3.1", dns=["1.1.1.1"])
        with self.assertRaises(ValueError):
            validate_targets({"brain": static, "cerebellum": static})
        with self.assertRaises(ValueError):
            validate_targets({"brain": config(), "cerebellum": config(ssid="different")})
        self.assertEqual(len(validate_targets({"brain":config(), "cerebellum":config()})), 2)

    def test_invalid_secret_and_fields_are_rejected(self):
        for c in [config(password="bad"), config(ssid="x\n[connection]"), config(security="wpa-eap"),
                  config(command="reboot"), config(ssid="你" * 11)]:
            with self.assertRaises(ValueError):
                validate_config(c)
        self.assertEqual(split_row(r"*:test\:ap:80:WPA2"), ["*", "test:ap", "80", "WPA2"])

    def wait_job(self, jobs):
        for _ in range(200):
            if jobs.status()["state"] == "done":
                return jobs.status()
            time.sleep(.01)
        self.fail("network job did not finish")

    def test_preflight_failure_prevents_any_network_change(self):
        calls = []
        def execute(target, request):
            calls.append(request["action"])
            return {"ok":target == "brain"}
        with patch("edge.network.bridge.safe_call", side_effect=execute):
            jobs = NetworkJobs()
            jobs.start({"brain":config(), "cerebellum":config()})
            self.wait_job(jobs)
        self.assertEqual(calls, ["status", "status"])

    def test_pair_concurrent_and_partial_failure_rolls_back(self):
        barrier = threading.Barrier(2)
        calls = []
        def execute(target, request):
            calls.append((target, request["action"]))
            if request["action"] == "status": return {"ok":True}
            if request["action"] == "rollback": return {"ok":True}
            barrier.wait(timeout=2)
            return {"ok":target == "brain", "token":"a" * 32}
        with patch("edge.network.bridge.safe_call", side_effect=execute):
            jobs = NetworkJobs()
            jobs.start({"brain":config(), "cerebellum":config()})
            result = self.wait_job(jobs)
        self.assertIn(("brain", "rollback"), calls)
        self.assertNotIn("example123", json.dumps(result))

    def test_helper_rejects_arbitrary_operation(self):
        helper = NetworkManager.__new__(NetworkManager)
        helper.lock = threading.Lock()
        for request in [{"action":"shell", "command":"reboot"}, {"action":"scan", "interface":"eth0"}]:
            with self.assertRaises(ValueError): helper.dispatch(request)

    def test_confirmation_requires_live_matching_token(self):
        helper = NetworkManager.__new__(NetworkManager)
        helper.active_pending = Mock(return_value={"token":"good"})
        helper.manager = Mock()
        with self.assertRaises(ValueError): helper.finish("bad", True)
        helper.manager.CheckpointDestroy.assert_not_called()

    def test_confirmation_rejects_disconnected_candidate(self):
        helper = NetworkManager.__new__(NetworkManager)
        helper.active_pending = Mock(return_value={"token":"good", "uuid":"new-profile"})
        helper.interface = "wifi0"
        helper.manager = Mock()
        with patch("edge.network.agent.nmcli", return_value="old-profile"), self.assertRaises(ValueError):
            helper.finish("good", True)
        helper.manager.CheckpointDestroy.assert_not_called()

    def test_display_rejects_unauthorized_and_invalid_payload(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/network/action", json={"action":"scan","target":"brain"}).status_code, 403)
        with patch("edge.network.bridge.jobs.start") as start:
            self.assertEqual(client.post("/api/network/action", headers={"X-LuckRobot-Display":"1"},
                                        json={"action":"shell"}).status_code, 422)
            start.assert_not_called()


if __name__ == "__main__": unittest.main()
