"""Single-task orchestration, independent of rclpy for deterministic safety tests."""
import json
import threading
import time
import uuid
from edge.navigation.state import gate, MODE_ENTRY, INTERRUPTS


class TaskManager:
    def __init__(self, state, call_service, startup_timeout=90):
        self.state, self.call_service = state, call_service
        self.startup_timeout = startup_timeout
        self.lock = threading.RLock()
        self.task = None
        self.cancelled = threading.Event()

    def snapshot(self):
        with self.lock:
            result = self.state.snapshot()
            result["task"] = dict(self.task) if self.task else None
            return result

    def _update(self, task_id, **values):
        with self.lock:
            if self.task and self.task["id"] == task_id:
                self.task.update(values)
                snapshot = self.state.snapshot()
                self.task["session_id"] = snapshot["mapping"].get("session_id")
                self.task["map_id"] = (snapshot.get("map") or {}).get("map_id") if isinstance(snapshot.get("map"), dict) else None
                print("[NAVIGATION] " + json.dumps(self.task, ensure_ascii=False), flush=True)

    def submit(self, command, confirmed=False):
        if command == "status":
            return {"ok": True, "navigation": self.snapshot()}
        with self.lock:
            snapshot = self.state.snapshot()
            if command == "acknowledge_unknown":
                if not confirmed or not snapshot["system"]["fresh"]:
                    return {"ok": False, "message": "需现场核对最新状态并确认。"}
                if self.task and self.task["status"] in {"outcome_unknown", "state_changed", "observation_timeout"}:
                    self.task["status"] = "acknowledged"
                return {"ok": True, "message": "已确认当前状态；没有重发或恢复旧任务。"}
            rejected = gate(command, snapshot, confirmed)
            if rejected:
                return {"ok": False, "status": "rejected", "executed": False, "message": rejected}
            if command == "start" and snapshot["system"].get("state") == "RUNNING":
                return {"ok": True, "executed": False, "message": "小脑软件已运行，没有重复启动。"}
            if self.task and self.task["status"] in {"starting", "calling", "accepted", "running",
                                                    "outcome_unknown", "observation_timeout", "state_changed"}:
                if command not in INTERRUPTS:
                    return {"ok": False, "status": "busy", "message": "已有底盘任务未结束或结果不确定，请先查询、暂停或取消。"}
            if command == "load_latest" and snapshot["navigation_ready"]:
                return {"ok": True, "executed": False, "message": "当前地图已就绪，没有重复加载。"}
            self.cancelled.set()
            self.cancelled = threading.Event()
            task_id = uuid.uuid4().hex
            self.task = {"id": task_id, "command": command, "status": "starting",
                         "instance_id": snapshot["system"].get("instance_id"),
                         "created_monotonic": time.monotonic(), "message": "准备提交请求，尚未执行完成。"}
            threading.Thread(target=self._run, args=(task_id, command, confirmed, self.cancelled),
                             name="navigation-task", daemon=True).start()
            return {"ok": True, "status": "queued", "executed": False, "completed": False,
                    "task_id": task_id, "message": "已登记底盘任务，正在检查并提交；请查看屏幕实时状态，尚未确认执行完成。"}

    def _run(self, task_id, command, confirmed, cancelled):
        try:
            snapshot = self.state.snapshot()
            initial_instance = snapshot["system"].get("instance_id")
            if command in MODE_ENTRY and snapshot["system"].get("state") == "STOPPED":
                self._update(task_id, status="starting", message="请求启动小脑软件到 idle，不启动探索。")
                response = self.call_service("start")
                if not response["success"]:
                    self._update(task_id, status="rejected", message=response["message"])
                    return
                deadline = time.monotonic()+self.startup_timeout
                while not cancelled.wait(.2):
                    snapshot = self.state.snapshot()
                    if snapshot["fresh"]:
                        initial_instance = snapshot["system"].get("instance_id")
                        break
                    if snapshot["system"].get("state") == "FAULT":
                        self._update(task_id, status="failed", message="小脑启动报告 FAULT。")
                        return
                    if time.monotonic() >= deadline:
                        self._update(task_id, status="observation_timeout", message="等待启动状态超时，不继续模式请求。")
                        return
            if cancelled.is_set():
                return
            snapshot = self.state.snapshot()
            rejected = gate(command, snapshot, confirmed)
            if rejected or snapshot["system"].get("instance_id") != initial_instance:
                self._update(task_id, status="state_changed", message=rejected or "实例已变化，旧任务授权失效。")
                return
            self._update(task_id, status="calling", instance_id=initial_instance,
                         message="请求中；超时不代表未执行。")
            if cancelled.is_set():
                return
            response = self.call_service(command)
            self._update(task_id, status="accepted" if response["success"] else "rejected",
                         accepted_monotonic=time.monotonic(), message=response["message"])
        except TimeoutError:
            self._update(task_id, status="outcome_unknown", message="ROS服务响应超时，结果未知；没有自动重试，请先核对状态。")
        except Exception as exc:
            self._update(task_id, status="failed", message="ROS服务不可用："+type(exc).__name__)

    def observe(self):
        with self.lock:
            if not self.task or self.task["status"] not in {"accepted", "running"}:
                return
            snapshot = self.state.snapshot()
            task, system = self.task, snapshot["system"]
            command, state = task["command"], snapshot["state"]
            if not system["fresh"]:
                return  # UI immediately shows stale; never infer a stopped robot.
            if command not in {"start", "restart"} and system.get("instance_id") != task["instance_id"]:
                self._update(task["id"], status="state_changed", message="软件实例已变化，旧任务不自动恢复。")
                return
            received_kind = "system" if command in {"start", "stop", "restart"} else "mapping"
            item = self.state.samples.get(received_kind)
            if not item or item["received"] <= task["accepted_monotonic"]:
                return  # Old retained/state response cannot confirm the operation.
            if system.get("state") == "FAULT" or (snapshot["fresh"] and state in {"ERROR", "INCOMPLETE"}):
                self._update(task["id"], status="failed", message=str(snapshot["reason"]))
                return
            done = False
            if command in {"start", "restart"}:
                done = snapshot["fresh"] and system.get("state") == "RUNNING" and state == "IDLE"
                if command == "restart":
                    done = done and (task["instance_id"] != system.get("instance_id"))
            elif command == "stop":
                done = system.get("state") == "STOPPED" and system.get("stack_alive") is False
            elif snapshot["fresh"]:
                done = ((command in {"load_latest", "finish_mapping", "auto_mapping"} and snapshot["navigation_ready"]) or
                        (command == "manual_mapping" and state == "MAPPING" and "manual_mapping_ready" in str(snapshot["reason"])) or
                        (command == "pause" and state == "PAUSED") or
                        (command == "cancel" and state == "CANCELLED") or
                        (command == "resume" and (state == "EXPLORING" or snapshot["navigation_ready"])))
            if done:
                self._update(task["id"], status="completed", message="已根据新鲜底盘状态确认本次模式操作完成（不代表到达某地点）。")
            elif snapshot["fresh"] and state == "EXPLORING" and task["status"] != "running":
                self._update(task["id"], status="running", message="正在探索，尚未完成地图保存和定位。")
            elif snapshot["fresh"] and state == "WAITING_INITIAL_POSE":
                self._update(task["id"], status="waiting_initial_pose", message="需现场提供可信当前位姿；不会自动发送零坐标或复用旧位置。")
