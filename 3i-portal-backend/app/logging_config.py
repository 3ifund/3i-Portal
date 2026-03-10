"""
3i Fund Portal — Logging Configuration
Writes daily log files to c:\logging\portal-backend\YYYY-MM-DD.log
"""

import logging
import os
from datetime import date


LOG_DIR = r"c:\logging\portal-backend"


def setup_logging() -> None:
    """Configure root logger with console and daily file handlers."""
    os.makedirs(LOG_DIR, exist_ok=True)

    log_file = os.path.join(LOG_DIR, f"{date.today().isoformat()}.log")

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — daily log file
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Quiet down noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
