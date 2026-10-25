"""Root-owned, Wi-Fi-only NetworkManager helper. Install standalone on both brains.

JSON via a group-restricted Unix socket; --client is also a forced SSH command.
Secrets travel through stdin/D-Bus only, never through argv or logs.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import uuid

SOCKET = "/run/luckrobot-network/control.sock"
PENDING = Path("/run/luckrobot-network/pending.json")
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
PROTECTED = ipaddress.ip_network("10.0.0.0/24")
LIMIT = 8192


def validate_config(value):
    if not isinstance(value, dict) or set(value) - {"ssid", "password", "security", "method", "address", "gateway", "dns"}:
        raise ValueError("invalid_config")
    c = dict(value)
    ssid = c.get("ssid", "")
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32 or any(ord(x) < 32 for x in ssid):
        raise ValueError("invalid_ssid")
    password = c.get("password", "")
    security = c.get("security", "wpa-psk")
    if security not in {"open", "wpa-psk", "sae"} or not isinstance(password, str):
        raise ValueError("unsupported_security")
    if security != "open" and not (8 <= len(password.encode("utf-8")) <= 63 or
                                   (security == "wpa-psk" and re.fullmatch(r"[0-9a-fA-F]{64}", password))):
        raise ValueError("invalid_password")
    if any(ord(x) < 32 for x in password):
        raise ValueError("invalid_password")
    method = c.get("method", "auto")
    if method not in {"auto", "manual"}:
        raise ValueError("invalid_method")
    c.update(security=security, password=password, method=method)
    if method == "manual":
        if "/" not in str(c.get("address", "")):
            raise ValueError("prefix_required")
        interface = ipaddress.IPv4Interface(c["address"])
        gateway = ipaddress.IPv4Address(c.get("gateway", ""))
        if (interface.network.overlaps(PROTECTED) or interface.ip.is_loopback or
                interface.ip.is_multicast or interface.ip.is_unspecified or
                interface.ip in {interface.network.network_address, interface.network.broadcast_address} or
                gateway not in interface.network or gateway == interface.ip or
                gateway in {interface.network.network_address, interface.network.broadcast_address}):
            raise ValueError("invalid_address_or_gateway")
        dns = c.get("dns", [])
        if not isinstance(dns, list) or not 1 <= len(dns) <= 3:
            raise ValueError("dns_required")
        c.update(address=str(interface), gateway=str(gateway), dns=[str(ipaddress.IPv4Address(x)) for x in dns])
    return c


def nmcli(*args, timeout=12):
    result = subprocess.run(["/usr/bin/nmcli", *args], capture_output=True, text=True,
                            timeout=timeout, env={**os.environ, "LC_ALL": "C"})
    if result.returncode:
        # Never forward stderr: NetworkManager may echo connection data.
        raise RuntimeError("nmcli_failed_" + str(result.returncode))
    return result.stdout.strip()


def split_row(line):
    fields, current, escape = [], "", False
    for char in line:
        if escape:
            current += char
            escape = False
        elif char == "\\":
            escape = True
        elif char == ":":
            fields.append(current)
            current = ""
        else:
            current += char
    fields.append(current)
    return fields


class NetworkManager:
    def __init__(self, interface):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus()
        self.manager = dbus.Interface(self.bus.get_object(NM, NM_PATH), NM)
        self.interface = interface
        self.lock = threading.Lock()
        self.pending = None
        try:
            self.pending = json.loads(PENDING.read_text())
        except (OSError, ValueError):
            pass

    def device(self):
        path = self.manager.GetDeviceByIpIface(self.interface)
        props = self.dbus.Interface(self.bus.get_object(NM, path), "org.freedesktop.DBus.Properties")
        if int(props.Get(NM + ".Device", "DeviceType")) != 2:
            raise ValueError("wifi_interface_required")
        return path

    def active_pending(self):
        if self.pending:
            props = self.dbus.Interface(self.bus.get_object(NM, NM_PATH), "org.freedesktop.DBus.Properties")
            if self.pending["checkpoint"] not in [str(x) for x in props.Get(NM, "Checkpoints")]:
                self.discard_connection(self.pending["connection"])
                self.pending = None
                PENDING.unlink(missing_ok=True)
        return self.pending

    def discard_connection(self, path):
        try:
            self.dbus.Interface(self.bus.get_object(NM, path), NM + ".Settings.Connection").Delete()
        except self.dbus.DBusException:
            pass  # It may already have been removed by NetworkManager.

    def status(self):
        self.device()  # refuse configuration mistakes (especially Ethernet)
        raw = subprocess.run(["/usr/sbin/ip", "-j", "address"], capture_output=True, text=True, timeout=5, check=True)
        interfaces = [{"name": x["ifname"], "up": x.get("operstate") == "UP",
                       "addresses": [a["local"] + "/" + str(a["prefixlen"]) for a in x.get("addr_info", []) if a["family"] == "inet"]}
                      for x in json.loads(raw.stdout) if x["ifname"] == self.interface or x["ifname"].startswith(("en", "eth"))]
        pending = self.active_pending()
        return {"hostname": socket.gethostname(), "wifi_interface": self.interface, "interfaces": interfaces,
                "connection": nmcli("-g", "GENERAL.CONNECTION", "device", "show", self.interface),
                "pending": {"token": pending["token"], "expires": pending["expires"]} if pending else None}

    def scan(self):
        self.device()
        rows = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                     "ifname", self.interface, "--rescan", "yes", timeout=20)
        networks = {}
        for row in rows.splitlines():
            fields = split_row(row)
            if len(fields) != 4 or not fields[1]:
                continue
            active, ssid, signal, security = fields
            item = {"ssid": ssid, "signal": int(signal), "security": security, "active": active == "*"}
            if ssid not in networks or item["signal"] > networks[ssid]["signal"]:
                networks[ssid] = item
        return {"networks": sorted(networks.values(), key=lambda x: -x["signal"])}

    def apply(self, config):
        c = validate_config(config)
        if self.active_pending():
            raise ValueError("confirmation_pending")
        dbus = self.dbus
        device = self.device()
        checkpoint = self.manager.CheckpointCreate([device], dbus.UInt32(180), dbus.UInt32(0))
        token, ident = uuid.uuid4().hex, str(uuid.uuid4())
        connection = None
        try:
            settings = {
                "connection": {"id": "LuckRobot Wi-Fi " + c["ssid"], "uuid": ident,
                               "type": "802-11-wireless", "interface-name": self.interface,
                               "autoconnect": False, "autoconnect-priority": dbus.Int32(100)},
                "802-11-wireless": {"ssid": dbus.ByteArray(c["ssid"].encode()), "mode": "infrastructure"},
                "ipv4": {"method": c["method"], "route-metric": dbus.Int64(600)},
                "ipv6": {"method": "auto"},
            }
            if c["security"] != "open":
                settings["802-11-wireless-security"] = {"key-mgmt": c["security"], "psk": c["password"]}
            if c["method"] == "manual":
                address = ipaddress.IPv4Interface(c["address"])
                settings["ipv4"].update({
                    "address-data": dbus.Array([dbus.Dictionary({"address": str(address.ip), "prefix": dbus.UInt32(address.network.prefixlen)}, signature="sv")], signature="a{sv}"),
                    "gateway": c["gateway"],
                    "dns": dbus.Array([dbus.UInt32(struct.unpack("=I", socket.inet_aton(x))[0]) for x in c["dns"]], signature="u")})
            settings = dbus.Dictionary({k: dbus.Dictionary(v, signature="sv") for k, v in settings.items()}, signature="sa{sv}")
            store = dbus.Interface(self.bus.get_object(NM, NM_PATH + "/Settings"), NM + ".Settings")
            connection = store.AddConnectionUnsaved(settings)
            self.pending = {"token": token, "checkpoint": str(checkpoint), "connection": str(connection),
                            "uuid": ident, "expires": time.time() + 180}
            PENDING.write_text(json.dumps(self.pending))
            os.chmod(PENDING, 0o600)
            nmcli("--wait", "35", "connection", "up", "uuid", ident, "ifname", self.interface, timeout=40)
            return {"state": "awaiting_confirmation", "token": token, "expires": self.pending["expires"]}
        except Exception:
            self.manager.CheckpointRollback(checkpoint)
            if connection:
                self.discard_connection(connection)
            self.pending = None
            PENDING.unlink(missing_ok=True)
            raise

    def finish(self, token, confirm):
        pending = self.active_pending()
        if not pending or token != pending["token"]:
            raise ValueError("confirmation_expired")
        if confirm:
            if nmcli("-g", "GENERAL.CON-UUID", "device", "show", self.interface) != pending["uuid"]:
                raise ValueError("connection_not_active")
            connection = self.dbus.Interface(self.bus.get_object(NM, pending["connection"]), NM + ".Settings.Connection")
            settings = connection.GetSettings()
            if "802-11-wireless-security" in settings:
                secrets = connection.GetSecrets("802-11-wireless-security")
                settings["802-11-wireless-security"].update(secrets.get("802-11-wireless-security", {}))
            settings["connection"]["autoconnect"] = self.dbus.Boolean(True)
            connection.UpdateUnsaved(settings)
            connection.Save()
            self.manager.CheckpointDestroy(pending["checkpoint"])
        else:
            self.manager.CheckpointRollback(pending["checkpoint"])
            self.discard_connection(pending["connection"])
        self.pending = None
        PENDING.unlink(missing_ok=True)
        return {"state": "confirmed" if confirm else "rolled_back"}

    def dispatch(self, request):
        with self.lock:
            if not isinstance(request, dict):
                raise ValueError("invalid_request")
            action = request.get("action")
            if action == "status" and set(request) == {"action"}:
                return self.status()
            if action == "scan" and set(request) == {"action"}:
                return self.scan()
            if action == "apply" and set(request) == {"action", "config"}:
                return self.apply(request["config"])
            if action in {"confirm", "rollback"} and set(request) == {"action", "token"}:
                return self.finish(request["token"], action == "confirm")
            raise ValueError("invalid_action")


def client(request):
    encoded = json.dumps(request).encode() + b"\n"
    if len(encoded) > LIMIT:
        raise ValueError("request_too_large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(55)
        sock.connect(SOCKET)
        sock.sendall(encoded)
        return json.loads(sock.makefile("rb").readline(65536))


def serve(interface):
    manager = NetworkManager(interface)
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            try:
                line = self.rfile.readline(LIMIT + 1)
                if len(line) > LIMIT:
                    raise ValueError("request_too_large")
                result = {"ok": True, **manager.dispatch(json.loads(line))}
            except Exception as exc:
                # Only our constant error identifiers may leave the helper.
                reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)) else type(exc).__name__
                result = {"ok": False, "error": reason}
            self.wfile.write(json.dumps(result).encode() + b"\n")
    Path(SOCKET).parent.mkdir(parents=True, exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", action="store_true")
    parser.add_argument("--interface", default="wlP1p1s0")
    args = parser.parse_args()
    if args.client:
        try:
            line = sys.stdin.buffer.readline(LIMIT + 1)
            if len(line) > LIMIT:
                raise ValueError("request_too_large")
            print(json.dumps(client(json.loads(line))))
        except Exception:
            print(json.dumps({"ok": False, "error": "helper_unavailable"}))
    else:
        serve(args.interface)
