import unittest
from unittest.mock import Mock,patch
from edge.audio.direction import DirectionMonitor
class QuietDirectionTests(unittest.TestCase):
    def test_quiet_mode_keeps_latest(self):
        monitor=DirectionMonitor({"log_samples":False})
        sample={"monotonic":1,"sensor_azimuth_deg":20}
        monitor.reader=Mock();monitor.reader.read.return_value=sample
        monitor.stop_event=Mock();monitor.stop_event.is_set.side_effect=[False,True]
        with patch("builtins.print") as output:monitor._run()
        output.assert_not_called()
        self.assertEqual(monitor._latest,sample)
    def test_repeated_errors_print_once(self):
        monitor=DirectionMonitor({})
        monitor.reader=Mock();monitor.reader.read.side_effect=RuntimeError("missing")
        monitor.stop_event=Mock();monitor.stop_event.is_set.side_effect=[False,False,True]
        with patch("builtins.print") as output:monitor._run()
        self.assertEqual(output.call_count,1)
