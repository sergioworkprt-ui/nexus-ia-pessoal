import logging
import logging.handlers
import os
from ibkr.config import config


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"nexus.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    os.makedirs(config.log_dir, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    fh = logging.handlers.RotatingFileHandler(
        os.path.join(config.log_dir, f"{name}.log"),
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
