import unittest

from robot_tools.fan_light import (
    FanLightController, fan_light_control, local_fan_light_request,
)
from robot_tools.chinese_colors import color_rgb, color_table


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
        self.port.replies = ([b'FAN1=100% LIGHT=OFF MODE=STATIC DATA=PA7\r\n'] +
                             [b'OK\r\n'] * 5 +
                             [b'FAN1=50% LIGHT=ON MODE=BREATH\r\n'])
        self.assertIn('MODE=BREATH', self.controller.initialize())
        self.assertEqual(self.port.writes, [
            b'STATUS\n', b'FAN1 50\n', b'PIXELS 64\n', b'BRIGHT 20\n',
            b'COLOR 255 0 0\n', b'MODE BREATH\n', b'STATUS\n',
        ])

    def test_preset_and_parameter_rejection(self):
        result = fan_light_control(self.controller, 'set_light', color_name='黄色', mode='breath')
        self.assertTrue(result['ok'])
        self.assertEqual(self.port.writes[-3:], [
            b'BRIGHT 20\n', b'COLOR 255 212 0\n', b'MODE BREATH\n'])
        self.assertFalse(fan_light_control(self.controller, 'set_speed', percent=-1)['executed'])
        self.assertTrue(fan_light_control(self.controller, 'set_speed', percent=50)['executed'])
        self.assertFalse(fan_light_control(self.controller, 'set_light', color_name='不存在', mode='static')['executed'])

    def test_firmware_error_stops_sequence(self):
        self.port.replies = [b'OK\r\n', b'ERR bad command\r\n']
        with self.assertRaises(RuntimeError):
            fan_light_control(self.controller, 'set_light', color_name='黄色', mode='breath')
        self.assertEqual(len(self.port.writes), 2)

    def test_unknown_serial_device_receives_no_write_commands(self):
        self.port.replies = [b'other device\r\n']
        with self.assertRaises(RuntimeError):
            self.controller.initialize()
        self.assertEqual(self.port.writes, [b'STATUS\n'])

    def test_exact_local_route(self):
        self.assertEqual(local_fan_light_request('红色呼吸灯。')['arguments'],
                         {'action': 'set_light', 'color_name': '红色', 'mode': 'breath'})
        self.assertIsNone(local_fan_light_request('我要红色呼吸灯吗'))
        self.assertEqual(local_fan_light_request('黄色呼吸灯')['arguments'],
                         {'action': 'set_light', 'color_name': '黄色', 'mode': 'breath'})

    def test_color_table_and_ambiguous_name(self):
        self.assertEqual(len(json_rows := [value for values in color_table().values()
                                             for value in values]), 256)
        self.assertEqual(color_rgb('黄色'), (255, 212, 0))
        self.assertEqual(color_rgb('绿色'), color_rgb('绿'))
        with self.assertRaises(ValueError):
            color_rgb('桦色')

    def test_arbitrary_rgb_breath(self):
        result = fan_light_control(self.controller, 'set_light', mode='breath',
                                   red=255, green=255, blue=0)
        self.assertTrue(result['ok'])
        self.assertEqual(self.port.writes, [b'BRIGHT 20\n',
                                            b'COLOR 255 255 0\n', b'MODE BREATH\n'])


if __name__ == '__main__':
    unittest.main()
