"""Own only our RViz viewer. Refresh/close never calls any chassis service."""
import os
from pathlib import Path
import re
import subprocess
import threading
import yaml

ROOT = Path(__file__).resolve().parents[2]


def prepare_profile(source, target):
    profile = yaml.safe_load(source.read_text(encoding="utf-8"))
    manager = profile.setdefault("Visualization Manager", {})
    profile["Panels"] = [panel for panel in profile.get("Panels", [])
                         if panel.get("Class") == "rviz_common/Displays"]
    # Monitoring does not grant a second motion writer (RViz goals/initial pose).
    manager["Tools"] = [{"Class": "rviz_default_plugins/Interact"},
                        {"Class": "rviz_default_plugins/MoveCamera"},
                        {"Class": "rviz_default_plugins/Select"}]
    profile["Window Geometry"] = {"Width": 1100, "Height": 850, "X": 0, "Y": 70}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")


class RvizViewer:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.state = "closed"
        self.message = ""

    def status(self):
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                code = self.process.returncode
                self.process = None
                self.state = "closed" if code == 0 else "error"
                self.message = "" if code == 0 else "RViz 已退出，请查看 logs/rviz.log 或重新打开。"
            return {"state": self.state, "message": self.message}

    def request(self, action):
        if action not in {"open", "restart", "close"}:
            raise ValueError("unsupported viewer action")
        with self.lock:
            if self.state in {"starting", "closing"}:
                return {"ok": False, "message": "画面正在切换，请稍等。"}
            if action == "open" and self.process is not None and self.process.poll() is None:
                return {"ok": True, "state": "running"}
            self.state = "closing" if action == "close" else "starting"
        threading.Thread(target=self._run, args=(action,), name="rviz-viewer", daemon=True).start()
        return {"ok": True, "state": self.state}

    def _run(self, action):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=8)  # Do not kill unrelated windows/processes.
            self.process = None
            if action == "close":
                with self.lock:
                    self.state = "closed"
                return
            if not Path("/tmp/.X11-unix/X0").exists():
                raise RuntimeError("RViz 需要 X11 显示会话，请检查显示服务。")
            source = Path.home()/"luckrobot_rviz/navigation.rviz"
            if not source.is_file():
                source = ROOT/"configs/rviz/brain_monitor.rviz"
            target = ROOT/"private/runtime/rviz-monitor.rviz"
            prepare_profile(source, target)
            env = dict(os.environ, DISPLAY=":0", XAUTHORITY=str(ROOT/"private/runtime/display.Xauthority"),
                       QT_QPA_PLATFORM="xcb")
            log_path = ROOT/"logs/rviz.log"
            log_path.parent.mkdir(exist_ok=True)
            with log_path.open("ab") as log:
                self.process = subprocess.Popen(["bash", str(ROOT/"scripts/run_rviz.sh"), str(target)],
                                                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            geometry = subprocess.run(["xrandr", "--current"], env=env, capture_output=True,
                                      text=True, timeout=3).stdout
            match = re.search(r"current (\d+) x (\d+)", geometry)
            width, height = map(int, match.groups()) if match else (1280, 1024)
            window = None
            for _ in range(80):
                if self.process.poll() is not None:
                    raise RuntimeError("RViz 启动失败，请检查 logs/rviz.log。")
                windows = subprocess.run(["wmctrl", "-lp"], env=env, capture_output=True,
                                         text=True, timeout=3).stdout.splitlines()
                for line in windows:
                    fields = line.split(None, 4)
                    if (len(fields) >= 5 and fields[2] == str(self.process.pid)
                            and " - RViz" in fields[4]):
                        window = fields[0]
                        break
                if window:
                    break
                threading.Event().wait(.25)
            if not window:
                raise RuntimeError("未找到 RViz 窗口，请重新打开监视画面。")
            # RViz restores saved geometry after mapping its native window.
            threading.Event().wait(1)
            for args in (["xprop", "-id", window, "-f", "_MOTIF_WM_HINTS", "32c", "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0"],
                         ["wmctrl", "-ir", window, "-b", "remove,maximized_vert,maximized_horz"],
                         ["wmctrl", "-ir", window, "-b", "remove,fullscreen"],
                         ["wmctrl", "-ir", window, "-e", f"0,0,70,{width},{max(200,height-70)}"],
                         ["wmctrl", "-ia", window]):
                subprocess.run(args, env=env, timeout=3, check=True, capture_output=True)
            with self.lock:
                self.state, self.message = "running", ""
        except Exception as exc:
            print(f"[RVIZ] {type(exc).__name__}: {exc}", flush=True)
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
            with self.lock:
                self.state = "error"
                self.message = str(exc) if isinstance(exc, RuntimeError) else "RViz 操作失败，请检查显示环境与日志。"


viewer = RvizViewer()
