"""Compact status stream, separate from diagnostic logs."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
_logger = None
_last = None

def status(value):
    global _logger, _last
    if value == _last: return
    try:
        if _logger is None:
            Path("logs").mkdir(exist_ok=True)
            _logger = logging.getLogger("robot.status")
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
            handler = RotatingFileHandler("logs/status.log", maxBytes=1000000, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
            _logger.addHandler(handler)
        _logger.info(value)
        _last = value
    except OSError:
        pass  # Diagnostic output must not stop the audio loop.
