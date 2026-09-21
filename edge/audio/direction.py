"""Read-only XVF3800 direction telemetry; no USB reconfiguration or motion."""
import argparse
import json
import math
import struct
import threading
import time


def decode_doa(packet, front_offset=None, clockwise=True):
    packet = bytes(packet)
    if len(packet) != 5 or packet[0] != 0:
        raise ValueError("Invalid DOA length or device status")
    angle, vad = struct.unpack("<HH", packet[1:])
    if angle >= 360 or vad not in (0, 1):
        raise ValueError("Invalid DOA fields")
    bearing = None
    if front_offset is not None:
        if not math.isfinite(float(front_offset)):
            raise ValueError("Invalid front offset")
        if vad:
            bearing = round(((angle-float(front_offset))*(1 if clockwise else -1)) % 360, 1)
    return dict(sensor_azimuth_deg=angle, speech_active=bool(vad), direction_valid=bool(vad),
                frame="microphone", robot_bearing_deg=bearing, calibrated=front_offset is not None,
                distance_m=None, position_xyz_m=None)


class XvfDirectionReader:
    def __init__(self, front_offset=None, clockwise=True):
        self.device = None
        self.front_offset, self.clockwise = front_offset, clockwise

    def read(self):
        import usb.core
        if self.device is None:
            self.device = usb.core.find(idVendor=0x2886, idProduct=0x001a)
            if self.device is None:
                raise RuntimeError("XVF3800 USB device not found")
        packet = self.device.ctrl_transfer(0xc0, 0, 0x92, 20, 5, timeout=500)
        result = decode_doa(packet, self.front_offset, self.clockwise)
        result.update(timestamp=time.time(), monotonic=time.monotonic(), status="ok")
        return result

    def close(self):
        if self.device is not None:
            import usb.util
            usb.util.dispose_resources(self.device)
            self.device = None


class DirectionMonitor:
    def __init__(self, config):
        self.interval = float(config.get("interval_seconds", 1))
        if not math.isfinite(self.interval) or not 0.2 <= self.interval <= 10:
            raise ValueError("DOA interval must be 0.2..10 seconds")
        self.reader = XvfDirectionReader(config.get("front_offset_deg"), config.get("clockwise", True))
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self._latest = None

    def latest(self, max_age_seconds=2):
        with self.lock:
            sample = dict(self._latest) if self._latest else None
        if sample is None or time.monotonic()-sample["monotonic"] > max_age_seconds:
            return None
        return sample

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name="sound-direction", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                delay = self.interval
                try:
                    sample = self.reader.read()
                    with self.lock:
                        self._latest = sample
                    print("[DOA] " + json.dumps(sample, ensure_ascii=False), flush=True)
                except Exception as exc:
                    with self.lock:
                        self._latest = None
                    print("[DOA] " + json.dumps(dict(status="unavailable", error=type(exc).__name__,
                          message=str(exc), direction_valid=False)), flush=True)
                    self._close()
                    delay = 5
                self.stop_event.wait(delay)
        finally:
            self._close()

    def _close(self):
        try:
            self.reader.close()
        except Exception:
            pass

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10000 or not 0.2 <= args.interval <= 10:
        parser.error("Invalid samples or interval")
    reader = XvfDirectionReader()
    try:
        for _ in range(args.samples):
            print("[DOA] " + json.dumps(reader.read()), flush=True)
            time.sleep(args.interval)
    finally:
        reader.close()

if __name__ == "__main__":
    main()
