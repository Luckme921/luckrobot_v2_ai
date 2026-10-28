"""System Python/rclpy process. Only small status topics and whitelisted Trigger services."""
import fcntl
import json
import os
import signal
import socketserver
import threading
import time
from edge.navigation.bridge import RUNTIME, SOCKET, STATUS
from edge.navigation.manager import TaskManager
from edge.navigation.state import RobotState, SERVICES


def main():
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = (RUNTIME/"owner.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    rclpy.init()
    node = Node("luckrobot_brain_bridge")
    state = RobotState()
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    subscriptions = [node.create_subscription(String, topic,
        lambda msg, kind=kind: state.receive(kind, msg.data), qos)
        for kind, topic in (("system", "/robot/system/status"), ("mapping", "/mapping/status"))]
    clients = {command: node.create_client(Trigger, service) for command, service in SERVICES.items()}
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, name="navigation-ros", daemon=True)
    spinner.start()

    def call_service(command):
        client = clients[command]
        if not client.wait_for_service(timeout_sec=2):
            raise ConnectionError("service unavailable")
        # Refuse duplicate servers instead of letting DDS choose a controller.
        providers = sum(SERVICES[command] in {name for name, types in node.get_service_names_and_types_by_node(n, ns)}
                        for n, ns in node.get_node_names_and_namespaces())
        if providers != 1:
            raise ConnectionError("service provider count is not one")
        future = client.call_async(Trigger.Request())
        done = threading.Event()
        future.add_done_callback(lambda _: done.set())
        if not done.wait(8):
            raise TimeoutError("outcome unknown")  # Do not retry or cancel the remote operation.
        response = future.result()
        return {"success": response.success, "message": response.message[:1000]}

    manager = TaskManager(state, call_service)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            try:
                line = self.rfile.readline(4097)
                payload = json.loads(line)
                if len(line) > 4096 or not line.endswith(b"\n") or not isinstance(payload, dict):
                    raise ValueError("invalid request")
                if set(payload) - {"command", "confirmed"} or type(payload.get("confirmed", False)) is not bool:
                    raise ValueError("invalid request")
                result = manager.submit(payload.get("command"), payload.get("confirmed", False))
            except (OSError, ValueError, TypeError):
                result = {"ok": False, "message": "导航参数无效。"}
            self.wfile.write((json.dumps(result, ensure_ascii=False)+"\n").encode())

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    if SOCKET.exists():
        SOCKET.unlink()  # Only after taking the exclusive owner lock.
    server = Server(str(SOCKET), Handler)
    os.chmod(SOCKET, 0o600)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.wait(.2):
            manager.observe()
            snapshot = manager.snapshot()
            snapshot["published_monotonic"] = time.monotonic()
            temp = STATUS.with_suffix(".tmp")
            temp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            temp.replace(STATUS)
    finally:
        manager.cancelled.set()  # Stop orchestration, never auto-stop/restart the chassis.
        server.shutdown()
        server.server_close()
        executor.shutdown(timeout_sec=2)
        spinner.join(2)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        SOCKET.unlink(missing_ok=True)
        STATUS.unlink(missing_ok=True)
        lock.close()


if __name__ == "__main__":
    main()
