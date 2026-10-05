"""Compact status log and best-effort structured display updates."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from edge.display.state import DisplayPublisher


_logger = None
_last = None
_display = DisplayPublisher({"enabled": False})


def configure_display(config):
    global _display
    _display = DisplayPublisher(config)
    _display.publish(state="sleeping", label="等待 Lucky")


def display_state(value, label):
    _display.publish(state=value, label=label)


def display_dialogue(*, user_text=None, assistant_text=None,
                     assistant_progress_chars=None):
    _display.publish(user_text=user_text, assistant_text=assistant_text,
                     assistant_progress_chars=assistant_progress_chars)


def display_music(music):
    _display.publish(music_marker=True, music=music)


def status(value):
    global _logger, _last
    if value == _last:
        return
    try:
        if _logger is None:
            Path("logs").mkdir(exist_ok=True)
            _logger = logging.getLogger("robot.status")
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
            handler = RotatingFileHandler(
                "logs/status.log", maxBytes=1000000, backupCount=2,
                encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(message)s", datefmt="%H:%M:%S"))
            _logger.addHandler(handler)
        _logger.info(value)
        _last = value
    except OSError:
        pass  # Diagnostic output must not stop the audio loop.
