#!/usr/bin/env python3
"""Manual, one-command-at-a-time STM32 fan/ARGB serial debugger.

Stop luckrobot_run.service before using this script: the audio process owns
the serial port. This program never changes the device on startup.
"""

import argparse
from glob import glob
import sys

import serial


PATTERNS = (
    '/dev/serial/by-id/usb-Arm_DAPLink_CMSIS-DAP_*-if01',
    '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_*-if00-port0',
)


def percent(value):
    number = int(value)
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError('must be 0..100')
    return number


def channel(value):
    number = int(value)
    if not 0 <= number <= 255:
        raise argparse.ArgumentTypeError('must be 0..255')
    return number


def exchange(port, command):
    port.reset_input_buffer()
    port.write((command + '\n').encode('ascii'))
    port.flush()
    reply = port.readline().decode('ascii', errors='replace').strip()
    print(f'> {command}\n< {reply or "(timeout)"}')
    if not reply:
        raise RuntimeError('STM32 did not reply')
    if command != 'STATUS' and not reply.startswith('OK'):
        raise RuntimeError('STM32 rejected command')
    return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='explicit device path (default: unique by-id match)')
    parser.add_argument('--allow-pwm', action='store_true',
                        help='required for speed command; verify the fan keeps spinning')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('release', help='FAN OFF: release PWM line, fan internal pull-up selects full speed')
    speed = sub.add_parser('speed', help='FAN1 percentage; may stall the fan on faulty wiring')
    speed.add_argument('percent', type=percent)
    color = sub.add_parser('color')
    color.add_argument('red', type=channel)
    color.add_argument('green', type=channel)
    color.add_argument('blue', type=channel)
    bright = sub.add_parser('bright')
    bright.add_argument('percent', type=percent)
    mode = sub.add_parser('mode')
    mode.add_argument('value', choices=('static', 'breath', 'rainbow'))
    light = sub.add_parser('light')
    light.add_argument('value', choices=('on', 'off'))
    args = parser.parse_args()

    if args.action == 'speed' and not args.allow_pwm:
        parser.error('speed requires --allow-pwm; the current PWM wiring may stop the fan')
    if args.action == 'bright' and args.percent > 20:
        parser.error('brightness is limited to the verified 0..20 range')

    ports = [path for pattern in PATTERNS for path in glob(pattern)]
    if args.port is None and len(ports) != 1:
        parser.error(f'expected one serial device, found {ports}; use --port if necessary')
    path = args.port or ports[0]
    commands = {
        'status': None,
        'release': 'FAN OFF',
        'speed': f'FAN1 {getattr(args, "percent", 0)}',
        'color': f'COLOR {getattr(args, "red", 0)} {getattr(args, "green", 0)} {getattr(args, "blue", 0)}',
        'bright': f'BRIGHT {getattr(args, "percent", 0)}',
        'mode': f'MODE {getattr(args, "value", "static").upper()}',
        'light': f'LIGHT {getattr(args, "value", "off").upper()}',
    }
    try:
        with serial.Serial(path, 115200, timeout=1.5, write_timeout=1,
                           exclusive=True) as port:
            identity = exchange(port, 'STATUS')
            if not all(marker in identity for marker in ('FAN1=', 'LIGHT=', 'MODE=', 'DATA=PA7')):
                raise RuntimeError('this port did not return STM32 fan/light STATUS')
            if commands[args.action] is not None:
                exchange(port, commands[args.action])
                exchange(port, 'STATUS')
    except (serial.SerialException, OSError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
