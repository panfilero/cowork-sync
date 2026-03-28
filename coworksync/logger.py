"""Logging setup with rotating file handler."""

import os
import logging
from logging.handlers import RotatingFileHandler

APP_DIR = os.path.join(os.environ.get("APPDATA", ""), "CoworkSync")
LOG_FILE = os.path.join(APP_DIR, "coworksync.log")


def enable_verbose():
    """Switch the logger to DEBUG level (call before setup_logger if possible,
    or after — it will update the existing logger in place)."""
    logging.getLogger("coworksync").setLevel(logging.DEBUG)


def setup_logger():
    """Configure and return the application logger."""
    os.makedirs(APP_DIR, exist_ok=True)

    logger = logging.getLogger("coworksync")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=2,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logger()
