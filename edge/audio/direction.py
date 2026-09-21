
"""Read-only XVF3800 DOA telemetry. No USB configuration changes or motion output."""

import argparse
import json
import math
import struct
import threading
import time


def decode_doa(packet, front_offset=None, clockwise=True):
    packet=bytes(packet)
    if len(packet)!=5: raise ValueError("Unexpected DOA packet length")
    if packet[0]!=0: raise ValueError(f"DOA device status {packet[0]}")
    angle,vad=struct.unpack("<HH",packet[1:])
    if not 0<=angle<360 or vad not in (0,1): raise ValueError("Invalid DOA fields")
    calibrated=front_offset is not None
    bearing=None
    if calibrated and vad:
        if not math.isfinite(float(front_offset)): raise ValueError("Invalid front offset")
        bearing=round(((angle-float(front_offset))*(1 if clockwise else -1))%360,1)
    return dict(sensor_azimuth_deg=angle,speech_active=bool(vad),
                direction_valid=bool(vad),frame="microphone",robot_bearing_deg=bearing,
                calibrated=calibrated,distance_m=None,position_xyz_m=None)


class XvfDirectionReader:
    def __init__(self, front_offset=None, clockwise=True):
        self.device=None;self.front_offset=front_offset;self.clockwise=clockwise

    def read(self):
        import usb.core
        if self.device is None:
            self.device=usb.core.find(idVendor=0x2886,idProduct=0x001a)
            if self.device is None: raise RuntimeError("XVF3800 USB device not found")
        # Vendor IN read: resource 20, DOA_VALUE command 18 with read bit 0x80.
        data=self.device.ctrl_transfer(0xc0,0,0x92,20,5,timeout=500)
        sample=decode_doa(data,self.front_offset,self.clockwise)
        sample.update(timestamp=time.time(),monotonic=time.monotonic(),status="ok")
        return sample

    def close(self):
        if self.device is not None:
            import usb.util
            usb.util.dispose_resources(self.device)
            self.device=None


class DirectionMonitor:
    def __init__(self, config):
        self.config=config;self.stop_event=threading.Event();self.thread=None
        self.interval=max(0.2,min(10.,float(config.get("interval_seconds",1))))
        self.reader=XvfDirectionReader(config.get("front_offset_deg"),config.get("clockwise",True))
        self._latest=None;self.lock=threading.Lock()
        self._last_error = None

    def latest(self, max_age_seconds=2):
        with self.lock:
            sample=dict(self._latest) if self._latest else None
        if sample is None or time.monotonic()-sample["monotonic"]>max_age_seconds:
            return None
        return sample

    def start(self):
        if self.thread is not None: return
        self.thread=threading.Thread(target=self._run,name="sound-direction",daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                delay=self.interval
                try:
                    sample=self.reader.read()
                    with self.lock: self._latest=sample
                    self._last_error = None
                    if self.config.get("log_samples", False):
                        print("[DOA] "+json.dumps(sample,ensure_ascii=False),flush=True)
                except Exception as exc:
                    with self.lock: self._latest=None
                    error = (type(exc).__name__, str(exc))
                    if error != self._last_error:
                        print("[DOA] "+json.dumps(dict(status="unavailable",error=error[0],
                            message=error[1],direction_valid=False)),flush=True)
                    self._last_error = error
                    try:self.reader.close()
                    except Exception:pass
                    delay=5
                self.stop_event.wait(delay)
        finally:
            self.reader.close()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:self.thread.join(timeout=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=10)
    parser.add_argument("--interval",type=float,default=1)
    args=parser.parse_args()
    if not 1<=args.samples<=10000 or not 0.2<=args.interval<=10:parser.error("Invalid samples or interval")
    reader=XvfDirectionReader()
    try:
        for _ in range(args.samples):
            print("[DOA] "+json.dumps(reader.read()),flush=True)
            time.sleep(args.interval)
    finally:reader.close()
if __name__=="__main__":main()
