import unittest
import json

from cloud.agent.client import GLMAgent
from robot_tools.catalog import LOCAL_SCHEMAS
from robot_tools.fan_light import (
    FanLightController, fan_light_control,
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
        self.port.replies = ([b'FAN1=100% LIGHT=OFF MODE=STATIC DATA=PA7\r\n'] +
                             [b'OK\r\n'] * 5 +
                             [b'FAN1=50% LIGHT=ON MODE=BREATH\r\n'])
        self.assertIn('MODE=BREATH', self.controller.initialize())
        self.assertEqual(self.port.writes, [
            b'STATUS\n', b'FAN1 50\n', b'PIXELS 64\n', b'BRIGHT 20\n',
            b'COLOR 255 0 0\n', b'MODE BREATH\n', b'STATUS\n',
        ])

    def test_rgb_and_parameter_rejection(self):
        result = fan_light_control(self.controller, 'set_light', red=255,
                                   green=212, blue=0, mode='breath')
        self.assertTrue(result['ok'])
        self.assertEqual(self.port.writes[-3:], [
            b'BRIGHT 20\n', b'COLOR 255 212 0\n', b'MODE BREATH\n'])
        self.assertFalse(fan_light_control(self.controller, 'set_speed', percent=-1)['executed'])
        self.assertTrue(fan_light_control(self.controller, 'set_speed', percent=50)['executed'])
        self.assertFalse(fan_light_control(self.controller, 'set_light', red=300,
                                           green=0, blue=0, mode='static')['executed'])

    def test_firmware_error_stops_sequence(self):
        self.port.replies = [b'OK\r\n', b'ERR bad command\r\n']
        with self.assertRaises(RuntimeError):
            fan_light_control(self.controller, 'set_light', red=255,
                              green=212, blue=0, mode='breath')
        self.assertEqual(len(self.port.writes), 2)

    def test_unknown_serial_device_receives_no_write_commands(self):
        self.port.replies = [b'other device\r\n']
        with self.assertRaises(RuntimeError):
            self.controller.initialize()
        self.assertEqual(self.port.writes, [b'STATUS\n'])

    def test_arbitrary_rgb_breath(self):
        result = fan_light_control(self.controller, 'set_light', mode='breath',
                                   red=255, green=255, blue=0)
        self.assertTrue(result['ok'])
        self.assertEqual(self.port.writes, [b'BRIGHT 20\n',
                                            b'COLOR 255 255 0\n', b'MODE BREATH\n'])

    def test_display_tracks_accepted_light_commands(self):
        updates = []
        fan_light_control(self.controller, 'set_light', mode='breath',
                          red=240, green=30, blue=10, display_light=updates.append)
        fan_light_control(self.controller, 'light_off', display_light=updates.append)
        fan_light_control(self.controller, 'light_on', display_light=updates.append)
        self.assertEqual(updates, [
            {'on': True, 'mode': 'breath', 'rgb': [240, 30, 10]},
            {'on': False}, {'on': True},
        ])
        self.port.replies = [b'ERR rejected\r\n']
        with self.assertRaises(RuntimeError):
            fan_light_control(self.controller, 'light_off', display_light=updates.append)
        self.assertEqual(len(updates), 3)

    def test_model_route_passes_rgb_without_color_name(self):
        route = GLMAgent._parse_turn_route_arguments(json.dumps({
            'action': 'fan_light_control', 'fan_light_action': 'set_light',
            'fan_light_mode': 'breath', 'fan_light_red': 255,
            'fan_light_green': 212, 'fan_light_blue': 0,
        }))
        self.assertEqual(route['arguments'], {
            'action': 'set_light', 'mode': 'breath',
            'red': 255, 'green': 212, 'blue': 0,
        })
        self.assertNotIn('color_name', LOCAL_SCHEMAS['fan_light_control']['properties'])


if __name__ == '__main__':
    unittest.main()
