"""Rotating ASR, wake and assistant-text log for on-device debugging."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class ConversationLog:
    def __init__(self, config):
        self.enabled = bool(config.get("enabled", False))
        self.log_sleeping_asr = bool(config.get("log_sleeping_asr", False))
        self.path = Path(config.get("path", "logs/conversation.log"))
        self.max_chars = max(200, int(config.get("max_text_chars", 12000)))
        self._logger = None

    def write(self, kind, text, **fields):
        if not self.enabled:
            return
        value = str(text).replace("\r", " ").replace("\n", " ").strip()
        if not value:
            return
        value = value[:self.max_chars]
        metadata = " ".join(
            f"{key}={str(item).replace(' ', '_')}"
            for key, item in fields.items() if item is not None)
        try:
            logger = self._get_logger()
            logger.info("[%s]%s %s", kind, " " + metadata if metadata else "", value)
        except OSError:
            pass

    def _get_logger(self):
        if self._logger is not None:
            return self._logger
        self.path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("robot.conversation." + str(self.path.absolute()))
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = RotatingFileHandler(
                self.path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            logger.addHandler(handler)
        self._logger = logger
        return logger

    def close(self):
        if self._logger is None:
            return
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)
        self._logger = None
