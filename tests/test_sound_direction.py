import struct
import time
import unittest
from unittest.mock import Mock,patch
from edge.audio.direction import decode_doa, DirectionMonitor, XvfDirectionReader
class DirectionTests(unittest.TestCase):
    def packet(self,a,v):return bytes([0])+struct.pack("<HH",a,v)
    def test_full_uint16_angle(self):
        r=decode_doa(self.packet(353,1))
        self.assertEqual(r["sensor_azimuth_deg"],353)
        self.assertTrue(r["direction_valid"])
        self.assertIsNone(r["distance_m"])
        self.assertIsNone(r["robot_bearing_deg"])
    def test_silence_is_not_valid_direction(self):
        r=decode_doa(self.packet(270,0),90)
        self.assertFalse(r["direction_valid"])
        self.assertIsNone(r["robot_bearing_deg"])
    def test_calibrated_clockwise_bearing(self):
        self.assertEqual(decode_doa(self.packet(10,1),350)["robot_bearing_deg"],20)
        self.assertEqual(decode_doa(self.packet(10,1),350,False)["robot_bearing_deg"],340)
    def test_reject_invalid_packets(self):
        for data in [b"",bytes([1])+struct.pack("<HH",10,1),self.packet(360,1),self.packet(20,2)]:
            with self.assertRaises(ValueError):decode_doa(data)
    def test_latest_copy_and_expiry(self):
        m=DirectionMonitor({});self.assertIsNone(m.latest())
        m._latest={"monotonic":time.monotonic(),"angle":10}
        r=m.latest();r["angle"]=20
        self.assertEqual(m.latest()["angle"],10)
        m._latest["monotonic"]-=10
        self.assertIsNone(m.latest())
    def test_error_clears_previous_direction(self):
        m=DirectionMonitor({});m._latest={"monotonic":time.monotonic()}
        m.reader=Mock();m.reader.read.side_effect=RuntimeError("unplugged")
        m.stop_event=Mock();m.stop_event.is_set.side_effect=[False,True]
        with patch("builtins.print"):m._run()
        self.assertIsNone(m.latest())
        m.stop_event.wait.assert_called_once_with(5)
