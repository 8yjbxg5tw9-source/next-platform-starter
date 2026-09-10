"""Application-wide paths, logging and crash guarding.

Every unexpected exception is routed into ``app_debug.log`` instead of
silently killing the process; all file handling goes through ``pathlib``
with UTF-8 so Azerbaijani/Turkish/Russian characters in video names are safe.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_NAME = "Akai"
APP_VERSION = "1.0.0"

WHATSAPP_TEXT = (
    "Əgər abunə olmaq istəyirsinizsə, +994 10 310 09 29 "
    "nömrəsinə WhatsApp-dan yazın."
)


def app_dir() -> Path:
    """Folder the executable (or this package) lives in."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


BASE_DIR = app_dir()
ASSETS_DIR = BASE_DIR / "assets"
MODELS_DIR = BASE_DIR / "models"
ICON_PATH = ASSETS_DIR / "icon.ico"
LOG_FILE = BASE_DIR / "app_debug.log"


def server_url() -> str:
    """License server base URL: server.txt next to the exe, else env, else local."""
    override = BASE_DIR / "server.txt"
    if override.exists():
        try:
            text = override.read_text(encoding="utf-8").strip()
            if text:
                return text.rstrip("/")
        except OSError:
            pass
    return os.environ.get("AKAI_SERVER", "http://127.0.0.1:8000").rstrip("/")


_logger: logging.Logger | None = None


def setup_logging() -> logging.Logger:
    """File + stderr logging, plus a global excepthook (no silent crashes)."""
    global _logger
    logger = logging.getLogger("akai")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except OSError:
        pass  # read-only folder: keep stderr only
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    def _excepthook(exc_type, exc, tb):  # pragma: no cover - last resort
        logger.error("İdarə olunmayan xəta", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook
    _logger = logger
    return logger


def log() -> logging.Logger:
    return _logger or setup_logging()
