import struct
import time
import unittest
from unittest.mock import Mock, patch
from edge.audio.direction import decode_doa, DirectionMonitor

class DirectionTests(unittest.TestCase):
    def packet(self, angle, vad):
        return bytes([0])+struct.pack("<HH",angle,vad)
    def test_uint16_and_unknown_position(self):
        r=decode_doa(self.packet(353,1))
        self.assertEqual(r["sensor_azimuth_deg"],353)
        self.assertTrue(r["direction_valid"])
        self.assertIsNone(r["robot_bearing_deg"])
        self.assertIsNone(r["position_xyz_m"])
    def test_silence(self):
        r=decode_doa(self.packet(353,0),0)
        self.assertFalse(r["direction_valid"])
        self.assertIsNone(r["robot_bearing_deg"])
    def test_calibration(self):
        self.assertEqual(decode_doa(self.packet(10,1),350)["robot_bearing_deg"],20)
        self.assertEqual(decode_doa(self.packet(10,1),350,False)["robot_bearing_deg"],340)
    def test_invalid_packet(self):
        for packet in [b"",bytes([1])+struct.pack("<HH",0,1),self.packet(360,1),self.packet(0,2)]:
            with self.assertRaises(ValueError):decode_doa(packet)
    def test_expiry_and_copy(self):
        m=DirectionMonitor({});self.assertIsNone(m.latest())
        m._latest={"monotonic":time.monotonic(),"angle":10}
        m.latest()["angle"]=20
        self.assertEqual(m.latest()["angle"],10)
        m._latest["monotonic"]-=10
        self.assertIsNone(m.latest())
    def test_error_clears_sample(self):
        m=DirectionMonitor({});m._latest={"monotonic":time.monotonic()}
        m.reader=Mock();m.reader.read.side_effect=RuntimeError("unplugged")
        m.stop_event=Mock();m.stop_event.is_set.side_effect=[False,True]
        with patch("builtins.print"):m._run()
        self.assertIsNone(m.latest())
        m.stop_event.wait.assert_called_once_with(5)
    def test_invalid_poll_interval(self):
        for value in [float("nan"),0,100]:
            with self.assertRaises(ValueError):DirectionMonitor({"interval_seconds":value})
