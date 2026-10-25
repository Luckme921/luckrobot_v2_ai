"""Unprivileged display bridge; peer traffic always uses the wired address."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import threading
import uuid

import yaml

from edge.network.agent import client, validate_config

ROOT = Path(__file__).resolve().parents[2]


def call(target, request):
    if target == "brain":
        return client(request)
    if target != "cerebellum":
        raise ValueError("invalid_target")
    config = yaml.safe_load((ROOT / "configs/network.yaml").read_text(encoding="utf-8"))["network"]
    host = ipaddress.IPv4Address(config["peer_host"])
    if host not in ipaddress.ip_network("10.0.0.0/24") or str(host) == "10.0.0.50":
        raise ValueError("peer_must_use_wired_address")
    user = config["peer_user"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("invalid_peer_user")
    key = ROOT / config["peer_key"]
    known = ROOT / config["peer_known_hosts"]
    if not key.is_file() or not known.is_file():
        return {"ok": False, "error": "peer_not_paired"}
    result = subprocess.run([
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known),
        "-i", str(key), user + "@" + str(host),
        "/usr/bin/python3 /usr/local/lib/luckrobot/network_agent.py --client"],
        input=json.dumps(request) + "\n", capture_output=True, text=True, timeout=60)
    if result.returncode:
        return {"ok": False, "error": "peer_unreachable"}
    return json.loads(result.stdout)


def safe_call(target, request):
    try:
        return call(target, request)
    except Exception:
        return {"ok": False, "error": "helper_unavailable"}


def statuses():
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {target: pool.submit(safe_call, target, {"action": "status"}) for target in ("brain", "cerebellum")}
        return {target: task.result() for target, task in futures.items()}


def validate_targets(configs):
    if not isinstance(configs, dict) or not configs or set(configs) - {"brain", "cerebellum"}:
        raise ValueError("invalid_targets")
    normalized = {target: validate_config(config) for target, config in configs.items()}
    if len(normalized) == 2:
        a, b = normalized.values()
        if a["ssid"] != b["ssid"] or a["security"] != b["security"] or a["password"] != b["password"]:
            raise ValueError("same_wifi_required")
        if a["method"] == b["method"] == "manual" and ipaddress.ip_interface(a["address"]).ip == ipaddress.ip_interface(b["address"]).ip:
            raise ValueError("duplicate_static_ip")
    return normalized


class NetworkJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.job = {"id": "", "state": "idle", "results": {}}

    def status(self):
        with self.lock:
            return deepcopy(self.job)

    def start(self, configs):
        configs = validate_targets(configs)  # reject the whole request before effects
        with self.lock:
            if self.job["state"] == "running":
                raise ValueError("network_busy")
            ident = uuid.uuid4().hex
            self.job = {"id": ident, "state": "running", "results": {}}
        def run():
            # Preflight both helpers before changing either Wi-Fi. Link stays wired.
            checks = {t: safe_call(t, {"action": "status"}) for t in configs}
            if any(not x.get("ok") or x.get("pending") for x in checks.values()):
                results = {t: {"ok": False, "error": "preflight_failed", "details": x} for t, x in checks.items()}
            else:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {t: pool.submit(safe_call, t, {"action": "apply", "config": c}) for t, c in configs.items()}
                    results = {t: f.result() for t, f in futures.items()}
                # A partial failure rolls back the other device, not a false global success.
                if any(not x.get("ok") for x in results.values()):
                    for t, x in list(results.items()):
                        if x.get("ok") and x.get("token"):
                            rollback = safe_call(t, {"action": "rollback", "token": x["token"]})
                            results[t] = {"ok": False, "error": "pair_failed_rolled_back" if rollback.get("ok") else "rollback_pending_timeout"}
            configs.clear()  # do not retain passwords in the job/status object
            with self.lock:
                self.job = {"id": ident, "state": "done", "results": results}
        threading.Thread(target=run, name="network-apply", daemon=True).start()
        return {"id": ident, "state": "running"}


jobs = NetworkJobs()
