import unittest

from robot_tools.fan_light import (
    FanLightController, fan_light_control, local_fan_light_request,
)


class FakeSerial:
    def __init__(self, **kwargs):
        self.writes = []
        self.replies = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def readline(self):
        return self.replies.pop(0) if self.replies else b'OK\r\n'

    def close(self):
        self.closed = True


class FanLightTest(unittest.TestCase):
    def setUp(self):
        self.port = FakeSerial()
        self.controller = FanLightController('/dev/test', lambda **kw: self.port)

    def test_startup_order(self):
        self.port.replies = [b'OK\r\n'] * 5 + [b'FAN1=50% LIGHT=ON MODE=BREATH\r\n']
        self.assertIn('MODE=BREATH', self.controller.initialize())
        self.assertEqual(self.port.writes, [
            b'FAN1 50\n', b'PIXELS 64\n', b'BRIGHT 20\n',
            b'COLOR 255 0 0\n', b'MODE BREATH\n', b'STATUS\n',
        ])

    def test_preset_and_parameter_rejection(self):
        result = fan_light_control(self.controller, 'set_light', preset='red_breath')
        self.assertTrue(result['ok'])
        self.assertEqual(self.port.writes[-3:], [
            b'BRIGHT 20\n', b'COLOR 255 0 0\n', b'MODE BREATH\n'])
        self.assertFalse(fan_light_control(self.controller, 'set_speed', percent=-1)['executed'])
        self.assertFalse(fan_light_control(self.controller, 'set_light', preset='flash')['executed'])

    def test_firmware_error_stops_sequence(self):
        self.port.replies = [b'OK\r\n', b'ERR bad command\r\n']
        with self.assertRaises(RuntimeError):
            fan_light_control(self.controller, 'set_light', preset='red_breath')
        self.assertEqual(len(self.port.writes), 2)

    def test_exact_local_route(self):
        self.assertEqual(local_fan_light_request('红色呼吸灯。')['arguments'],
                         {'action': 'set_light', 'preset': 'red_breath'})
        self.assertIsNone(local_fan_light_request('我要红色呼吸灯吗'))


if __name__ == '__main__':
    unittest.main()
