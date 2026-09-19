"""One owner for the Cloud and audio process groups. Linux/Jetson only."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def port_in_use():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
            return True
    except OSError:
        return False

def stop_child(process):
    if process is None:
        return
    for sig, timeout in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        if sig != signal.SIGKILL:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return

def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check paths without starting hardware")
    args = parser.parse_args()
    missing = [str(p) for p in (ROOT/".venv/bin/python", ROOT/".env",
               ROOT/"configs/audio.yaml", ROOT/"configs/vision.yaml") if not p.exists()]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing))
    if args.check:
        print("Configuration paths OK; hardware/model loading is checked by audio startup.")
        return 0
    lock_path = ROOT/"private/runtime/robot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("This project already has a robot supervisor.")
        if port_in_use():
            raise SystemExit("Port 8000 is occupied. Stop the previous Cloud/audio pair first.")
        lock.seek(0); lock.truncate()
        lock.write(str(os.getpid())); lock.flush()
        logs = ROOT/"logs"; logs.mkdir(exist_ok=True)
        children = []
        handles = []
        stopping = False
        def shutdown(signum, frame):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        def start(name):
            log = (logs/f"{name}-latency.log").open("a", buffering=1)
            handles.append(log)
            process = subprocess.Popen(["bash", str(ROOT/f"scripts/run_{name}.sh")],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(process)
            print(f"[SUPERVISOR] {name} pid={process.pid} log={log.name}", flush=True)
            return process
        try:
            cloud = start("cloud")
            deadline = time.monotonic() + 30
            ready = False
            while not stopping and time.monotonic() < deadline:
                if cloud.poll() is not None:
                    raise RuntimeError("Cloud exited during startup; inspect its log.")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1) as r:
                        ready = r.status == 200
                except OSError:
                    pass
                if ready: break
                time.sleep(0.2)
            if stopping: return 0
            if not ready: raise RuntimeError("Cloud health check timed out.")
            audio = start("audio")
            print("[SUPERVISOR] Started. Ctrl+C stops both services.", flush=True)
            while not stopping:
                if any(p.poll() is not None for p in children):
                    raise RuntimeError("A child exited; stopping both services. Inspect logs.")
                time.sleep(0.25)
            return 0
        finally:
            for child in reversed(children):
                stop_child(child)
            for handle in handles:
                handle.close()
            print("[SUPERVISOR] Stopped.", flush=True)

if __name__ == "__main__":
    raise SystemExit(main())
