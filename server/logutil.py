# -*- coding: utf-8 -*-
"""Логирование шагов GUI-автоматизации и HTTP-запросов.

Пишет в D:\\ConsPlus\\logs\\server.log (общий) с временными метками и уровнем.
Каждый шаг автоматизации помечается шаг-тегом, чтобы по логу видеть, на чём встало.
Содержимое документов в лог НЕ льём — только счётчики/заголовки/состояния.
"""
import io
import logging
import os
from logging.handlers import RotatingFileHandler

from . import config

LOG_PATH = os.path.join(config.LOGS_DIR, "server.log")
_fmt = "%(asctime)s | %(levelname)-6s | %(name)-16s | %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup():
    global _configured
    if _configured:
        return
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=5,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter(_fmt, _datefmt))
    root = logging.getLogger("cp")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(_fmt, _datefmt))
    root.addHandler(ch)
    root.propagate = False
    _configured = True


def get_logger(name="gui"):
    setup()
    return logging.getLogger("cp." + name)


# convenience
L = get_logger


class Step:
    """Контекстный логгер шага: с таймингом и перехватом исключения."""

    def __init__(self, name, logger=None, **ctx):
        self.name = name
        self.log = logger or get_logger()
        self.ctx = ctx
        self.t0 = 0.0

    def __enter__(self):
        import time
        self.t0 = time.time()
        self.log.debug("STEP> %s %s", self.name, _kv(self.ctx))
        return self

    def __exit__(self, exc_type, exc, tb):
        import time
        dt = time.time() - self.t0
        if exc_type is None:
            self.log.info("STEP< %s ok %.2fs", self.name, dt)
        else:
            self.log.exception("STEPX %s FAIL %.2fs: %s", self.name, dt, exc)
        return False  # не глотаем


def _kv(d):
    return " ".join(f"{k}={v}" for k, v in d.items())
