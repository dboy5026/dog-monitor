import atexit
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dogmonitor.config import Config

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(config: Config, name: str = "dogmonitor") -> logging.Logger:
    config.log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        config.log_dir / "dogmonitor.log",
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def register_shutdown_logger(logger: logging.Logger) -> None:
    def _log_shutdown() -> None:
        logger.info("Dog Monitor shutting down")

    atexit.register(_log_shutdown)
