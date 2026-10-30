import json
import time
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from edge.navigation.state import RobotState, gate
from edge.navigation.manager import TaskManager
from edge.display.server import app
from cloud.agent.client import GLMAgent
from robot_tools.batch import validate_plan


def feed(tracker, kind, **values):
    tracker.receive(kind, json.dumps({"schema": 1, **values}))


def ready(state, system="RUNNING", mapping="IDLE", instance="one"):
    for _ in range(2):
        feed(state, "system", state=system, instance_id=instance,
             manager_fresh=system == "RUNNING", stack_alive=system == "RUNNING")
    for _ in range(2):
        feed(state, "mapping", state=mapping, session_id="session",
             mode="localization" if mapping == "NAV_READY" else "mapping",
             map={"map_id": "map-a", "complete": True}, updated_unix=1)


class RosStateTests(unittest.TestCase):
    def test_retained_sample_is_not_online_and_gap_requires_two_again(self):
        clock = Mock(return_value=10.)
        s = RobotState(clock)
        feed(s, "system", state="STOPPED", instance_id="a")
        self.assertFalse(s.snapshot()["connected"])
        clock.return_value = 11.
        feed(s, "system", state="STOPPED", instance_id="a")
        self.assertTrue(s.snapshot()["connected"])
        clock.return_value = 15.
        self.assertFalse(s.snapshot()["connected"])
        feed(s, "system", state="STOPPED", instance_id="a")
        self.assertFalse(s.snapshot()["connected"])
        clock.return_value = 16.
        feed(s, "system", state="STOPPED", instance_id="a")
        self.assertTrue(s.snapshot()["connected"])

    def test_stale_map_ready_is_not_ready_and_instance_change_discards_mapping(self):
        clock = Mock(return_value=10.)
        s = RobotState(clock)
        ready(s, mapping="NAV_READY")
        self.assertTrue(s.snapshot()["navigation_ready"])
        clock.return_value = 14.
        self.assertFalse(s.snapshot()["navigation_ready"])
        ready(s, mapping="NAV_READY")
        feed(s, "system", state="RUNNING", instance_id="two", manager_fresh=True)
        self.assertFalse(s.snapshot()["navigation_ready"])
        self.assertEqual(s.snapshot()["mapping"], {"fresh": False, "age_seconds": None})

    def test_invalid_messages_and_unknown_states_are_conservative(self):
        s = RobotState()
        for text in ['[]', '{}', 'broken', '{"schema":true,"state":"IDLE"}']:
            self.assertFalse(s.receive("system", text))
        ready(s, mapping="NEW_STATE")
        self.assertIsNotNone(gate("auto_mapping", s.snapshot(), True))

    def test_explicit_motion_allowed_but_restart_requires_ui_confirmation(self):
        s = RobotState()
        ready(s, system="STOPPED")
        self.assertIsNone(gate("start", s.snapshot()))
        self.assertIsNotNone(gate("restart", s.snapshot()))
        self.assertIsNone(gate("auto_mapping", s.snapshot()))
        self.assertIsNone(gate("auto_mapping", s.snapshot(), True))
        self.assertIsNotNone(gate("update_map", s.snapshot(), True))


class RosTaskTests(unittest.TestCase):
    def wait_stage(self, manager, stages):
        until = time.monotonic()+2
        while time.monotonic() < until:
            task = manager.snapshot()["task"]
            if task and task["status"] in stages:
                return task
            time.sleep(.01)
        self.fail(str(manager.snapshot()))

    def test_construction_has_no_calls_and_voice_cannot_restart(self):
        state = RobotState(); ready(state)
        call = Mock()
        manager = TaskManager(state, call)
        self.assertFalse(manager.submit("restart")["ok"])
        call.assert_not_called()

    def test_explicit_mode_starts_idle_then_checks_fresh_manager(self):
        state = RobotState(); ready(state, system="STOPPED")
        def call(command):
            if command == "start":
                ready(state, instance="new")
            return {"success": True, "message": "accepted"}
        service = Mock(side_effect=call)
        manager = TaskManager(state, service)
        self.assertTrue(manager.submit("manual_mapping")["ok"])
        self.wait_stage(manager, {"accepted"})
        self.assertEqual([c.args[0] for c in service.call_args_list], ["start", "manual_mapping"])
        self.assertNotEqual(manager.snapshot()["task"]["status"], "completed")
        time.sleep(.02)
        feed(state, "mapping", state="MAPPING", session_id="session", mode="mapping", reason="manual_mapping_ready")
        manager.observe()
        self.assertEqual(manager.snapshot()["task"]["status"], "completed")

    def test_start_failure_does_not_send_mode(self):
        state = RobotState(); ready(state, system="STOPPED")
        call = Mock(return_value={"success": False, "message": "external nodes"})
        manager = TaskManager(state, call)
        manager.submit("manual_mapping")
        self.wait_stage(manager, {"rejected"})
        self.assertEqual(call.call_count, 1)

    def test_timeout_does_not_retry_or_allow_another_motion(self):
        state = RobotState(); ready(state)
        call = Mock(side_effect=TimeoutError)
        manager = TaskManager(state, call)
        manager.submit("auto_mapping", True)
        self.wait_stage(manager, {"outcome_unknown"})
        self.assertFalse(manager.submit("auto_mapping", True)["ok"])
        self.assertEqual(call.call_count, 1)

    def test_old_status_cannot_complete_pause_and_new_paused_can(self):
        state = RobotState(); ready(state, mapping="PAUSED")
        manager = TaskManager(state, Mock(return_value={"success": True, "message": "accepted"}))
        manager.submit("pause")
        self.wait_stage(manager, {"accepted"})
        manager.observe()
        self.assertEqual(manager.snapshot()["task"]["status"], "accepted")
        time.sleep(.02)
        feed(state, "mapping", state="PAUSED", session_id="session")
        manager.observe()
        self.assertEqual(manager.snapshot()["task"]["status"], "completed")

    def test_duplicate_start_and_load_latest_do_not_call_services(self):
        state = RobotState(); ready(state, mapping="NAV_READY")
        call = Mock()
        manager = TaskManager(state, call)
        self.assertFalse(manager.submit("start")["executed"])
        self.assertFalse(manager.submit("load_latest")["executed"])
        call.assert_not_called()

    def test_routing_and_plan_reject_multiple_chassis_commands(self):
        route = GLMAgent._parse_turn_route_arguments(json.dumps({
            "action": "navigation_control", "navigation_command": "load_latest"}))
        self.assertEqual(route["tool_arguments"], {"command": "load_latest"})
        with self.assertRaises(ValueError):
            GLMAgent._parse_turn_route_arguments(json.dumps({"action": "navigation_control", "navigation_command": "restart"}))
        with self.assertRaises(ValueError):
            validate_plan([{"name": "navigation_control", "arguments": {"command": c}}
                           for c in ("start", "auto_mapping")])

    def test_display_endpoint_checks_header_types_and_allowlist(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/navigation/command", json={"command": "pause"}).status_code, 403)
        headers = {"X-LuckRobot-Display": "1"}
        for payload in [{"command": "cmd_vel"}, {"command": "pause", "host": "remote"},
                        {"command": "restart", "confirmed": "true"}]:
            self.assertEqual(client.post("/api/navigation/command", json=payload, headers=headers).status_code, 422)
        with patch("edge.navigation.bridge.request", return_value={"ok": True}) as call:
            self.assertTrue(client.post("/api/navigation/command", json={"command": "restart", "confirmed": True}, headers=headers).json()["ok"])
            call.assert_called_once_with("restart", True)
