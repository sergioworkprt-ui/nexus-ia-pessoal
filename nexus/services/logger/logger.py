import logging
import logging.handlers
import os


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"nexus.{name}")
    if logger.handlers:
        return logger

    log_dir = os.getenv("LOG_DIR", "logs")
    level = os.getenv("LOG_LEVEL", "INFO")
    logger.setLevel(level)
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    fh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, f"{name}.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level, logging.INFO))
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
