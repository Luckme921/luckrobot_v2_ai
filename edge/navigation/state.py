"""ROS-independent state and command gates; no service invocation in this module."""
import json
import threading
import time

SERVICES = {
    "start": "/robot/system/start", "stop": "/robot/system/stop",
    "restart": "/robot/system/restart", "manual_mapping": "/mapping/manual_mapping",
    "auto_mapping": "/mapping/auto_mapping", "finish_mapping": "/mapping/finish_mapping",
    "load_latest": "/mapping/load_latest", "pause": "/mapping/pause",
    "resume": "/mapping/resume", "cancel": "/mapping/cancel",
}
TOOL_COMMANDS = tuple(c for c in SERVICES if c != "restart") + ("status",)
MOTION = {"auto_mapping", "resume"}
MODE_ENTRY = {"manual_mapping", "auto_mapping", "load_latest"}
INTERRUPTS = {"pause", "cancel", "stop"}
MODE_STATES = {"STARTING", "IDLE", "MAPPING", "EXPLORING", "BLOCKED", "EXPLORATION_COMPLETE",
               "STOPPING", "SAVING", "CHECKPOINT_SAVED", "MAP_READY", "LOCALIZING", "NAV_READY",
               "WAITING_INITIAL_POSE", "PAUSED", "INCOMPLETE", "CANCELLED", "ERROR"}


class RobotState:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.samples = {}
        self.generation = 0
        self.error = "waiting_for_ros"

    def receive(self, kind, raw):
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
                return False
            if not isinstance(data.get("state"), str):
                return False
        except (ValueError, TypeError):
            return False
        with self.lock:
            now = self.clock()
            old = self.samples.get(kind)
            key = "instance_id" if kind == "system" else "session_id"
            same = old and old["data"].get(key) == data.get(key) and now-old["received"] <= 3
            if old and not same:
                self.generation += 1
                if kind == "system" and old["data"].get(key) != data.get(key):
                    self.samples.pop("mapping", None)
            self.samples[kind] = {"data": data, "received": now,
                                  "updates": old["updates"]+1 if same else 1}
            self.error = ""
        return True

    def snapshot(self):
        with self.lock:
            out = {"generation": self.generation, "error": self.error}
            for kind in ("system", "mapping"):
                item = self.samples.get(kind)
                age = self.clock()-item["received"] if item else None
                out[kind] = dict(item["data"]) if item else {}
                out[kind]["fresh"] = bool(item and item["updates"] >= 2 and age <= 3)
                out[kind]["age_seconds"] = round(age, 2) if age is not None else None
            system, mapping = out["system"], out["mapping"]
            out["connected"] = system["fresh"]
            out["fresh"] = bool(system["fresh"] and system.get("state") == "RUNNING"
                                 and system.get("manager_fresh") is True and mapping["fresh"])
            out["state"] = mapping.get("state", "UNAVAILABLE")
            out["reason"] = mapping.get("reason", system.get("reason", self.error))
            out["map"] = mapping.get("map")
            out["navigation_ready"] = bool(out["fresh"] and out["state"] == "NAV_READY"
                                            and isinstance(out["map"], dict)
                                            and out["map"].get("complete") is True)
            return out


def gate(command, snapshot, confirmed=False):
    """Return a user-visible rejection; None permits this explicit request."""
    if command not in SERVICES:
        return "不支持此导航指令。"
    if command == "restart" and not confirmed:
        return "重启需在屏幕维护区确认，不通过语音自动执行。"
    system = snapshot["system"]
    if not system["fresh"]:
        return "小脑监督状态未就绪或已过期，请检查有线 ROS 通信。"
    if system.get("state") not in {"STOPPED", "STARTING", "RUNNING", "STOPPING", "FAULT"}:
        return "未知监督状态，暂停提交新任务。"
    if command in {"start", "stop", "restart"}:
        if system["state"] in {"STARTING", "STOPPING"}:
            return "软件栈正在切换，请先等待结果。"
        return None
    if system.get("state") == "STOPPED" and command in MODE_ENTRY:
        return None  # Explicit mode task may start fixed idle stack first.
    if not snapshot["fresh"] or snapshot["state"] not in MODE_STATES:
        return "底盘模式状态未就绪或已过期，不能执行新任务。"
    state = snapshot["state"]
    if command in MODE_ENTRY and state not in {"IDLE", "MAPPING", "PAUSED", "NAV_READY",
            "INCOMPLETE", "CANCELLED", "WAITING_INITIAL_POSE"}:
        return "当前不能切换模式，请先暂停并等待 PAUSED。"
    if command == "finish_mapping" and (snapshot["mapping"].get("mode") != "mapping" or
                                         state not in {"MAPPING", "PAUSED", "INCOMPLETE"}):
        return "当前不允许确认建图完成；不能把受阻或探索中的状态冒充完成。"
    return None
