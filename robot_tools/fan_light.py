"""Allowlisted STM32 fan and ARGB commands over the Jetson USB UART."""

from glob import glob
from threading import Lock


class FanLightController:
    def __init__(self, port=None, serial_factory=None):
        if serial_factory is None:
            import serial
            serial_factory = serial.Serial
        if port is None:
            matches = (glob('/dev/serial/by-id/usb-Arm_DAPLink_CMSIS-DAP_*-if01') +
                       glob('/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_*-if00-port0'))
            if len(matches) != 1:
                raise RuntimeError(f'expected one STM32 UART candidate, found {len(matches)}')
            port = matches[0]
        self._serial = serial_factory(port=port, baudrate=115200, bytesize=8,
                                      parity='N', stopbits=1, timeout=1,
                                      write_timeout=1, exclusive=True)
        self._lock = Lock()

    def command(self, command):
        with self._lock:
            self._serial.write((command + '\n').encode('ascii'))
            self._serial.flush()
            reply = self._serial.readline().decode('ascii', errors='replace').strip()
        if not reply:
            raise TimeoutError('STM32 did not reply')
        if command != 'STATUS' and not reply.startswith('OK'):
            raise RuntimeError(f'STM32 rejected command: {reply}')
        return reply

    def initialize(self):
        identity = self.command('STATUS')
        if not all(marker in identity for marker in ('FAN1=', 'LIGHT=', 'MODE=', 'DATA=PA7')):
            raise RuntimeError('serial device did not return STM32 fan/light status')
        # Until PWM wiring is verified, release the control line so a powered
        # fan can use its internal pull-up and run at full speed.
        for command in ('FAN OFF', 'PIXELS 64', 'BRIGHT 20',
                        'COLOR 255 0 0', 'MODE BREATH'):
            self.command(command)
        return self.command('STATUS')

    def close(self):
        self._serial.close()


def fan_light_control(controller, action, percent=None, preset=None, red=None, green=None, blue=None, mode=None):
    if action == 'set_speed':
        return _rejected('PWM 接线尚未核实；为避免风扇停转，暂时只释放控制线使风扇全速运行。')
    elif action == 'set_light':
        commands = {
            'red_breath': ('BRIGHT 20', 'COLOR 255 0 0', 'MODE BREATH'),
            'red_static': ('BRIGHT 20', 'COLOR 255 0 0'),
            'blue_static': ('BRIGHT 20', 'COLOR 0 0 255'),
            'rainbow': ('BRIGHT 20', 'MODE RAINBOW'),
        }.get(preset)
        if commands is None and preset is None:
            if mode not in {'static', 'breath'} or any(
                type(value) is not int or not 0 <= value <= 255
                for value in (red, green, blue)
            ):
                return _rejected('请指定静态或呼吸模式，以及 0 到 255 的 RGB 颜色。')
            commands = ('BRIGHT 20', f'COLOR {red} {green} {blue}')
            if mode == 'breath':
                commands += ('MODE BREATH',)
        if commands is None:
            return _rejected('未知灯效预设。')
        for command in commands:
            controller.command(command)
        message = '控制器已接受灯效命令；实体灯光需要现场确认。'
    elif action == 'light_off':
        controller.command('LIGHT OFF')
        message = '风扇灯已关闭，风扇转速不变。'
    elif action == 'light_on':
        controller.command('LIGHT ON')
        message = '风扇灯已恢复。'
    elif action == 'status':
        return {'ok': True, 'status': 'success', 'executed': True,
                'message': controller.command('STATUS')}
    else:
        return _rejected('未知的风扇灯光操作。')
    return {'ok': True, 'status': 'success', 'executed': True, 'message': message}


def _rejected(message):
    return {'ok': False, 'status': 'rejected', 'executed': False, 'message': message}


def local_fan_light_request(text):
    """Exact, unambiguous phrases bypass cloud routing."""
    normalized = text.strip().rstrip('。！!，, ')
    presets = {
        '红色呼吸灯': {'action': 'set_light', 'preset': 'red_breath'},
        '打开红色呼吸灯': {'action': 'set_light', 'preset': 'red_breath'},
        '黄色呼吸灯': {'action': 'set_light', 'mode': 'breath', 'red': 255, 'green': 255, 'blue': 0},
        '打开黄色呼吸灯': {'action': 'set_light', 'mode': 'breath', 'red': 255, 'green': 255, 'blue': 0},
        '彩虹灯': {'action': 'set_light', 'preset': 'rainbow'},
        '打开彩虹灯': {'action': 'set_light', 'preset': 'rainbow'},
        '关闭风扇灯': {'action': 'light_off'},
        '打开风扇灯': {'action': 'light_on'},
    }
    args = presets.get(normalized)
    return {'name': 'fan_light_control', 'arguments': args} if args else None
