
import logging
import os
import platform
from datetime import date


HEARTBEAT_LOGGERS = {
    "portal.quotes",
    "portal.workflows",
    "websockets",
    "uvicorn.access",
}


def _is_ec2() -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/",
            method="GET"
        )
        resp = urllib.request.urlopen(req, timeout=1)
        return resp.status == 200
    except Exception:
        return False


def setup_logging() -> None:

    on_ec2 = _is_ec2()

    if on_ec2:
        log_dir = os.environ.get("LOG_DIR", "/var/log/portal-backend")
    else:
        log_dir = os.environ.get("LOG_DIR", r"c:\logging\portal-backend")

    os.makedirs(log_dir, exist_ok=True)

    today = date.today().isoformat()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_log_file = os.path.join(log_dir, f"{today}.log")
    app_file_handler = logging.FileHandler(app_log_file, encoding="utf-8")
    app_file_handler.setLevel(logging.DEBUG)
    app_file_handler.setFormatter(formatter)

    heartbeat_log_file = os.path.join(log_dir, f"heartbeat-{today}.log")
    heartbeat_file_handler = logging.FileHandler(heartbeat_log_file, encoding="utf-8")
    heartbeat_file_handler.setLevel(logging.DEBUG)
    heartbeat_file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(app_file_handler)
    root.addHandler(console_handler)

    for logger_name in HEARTBEAT_LOGGERS:
        hb_logger = logging.getLogger(logger_name)
        hb_logger.propagate = False
        hb_logger.setLevel(logging.DEBUG)
        hb_logger.addHandler(heartbeat_file_handler)
        hb_logger.addHandler(console_handler)

    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    startup_logger = logging.getLogger("portal.logging")
    startup_logger.info("Logging initialized")
    startup_logger.info("  Environment: %s", "EC2" if on_ec2 else "On-Premises")
    startup_logger.info("  Platform: %s", platform.system())
    startup_logger.info("  Log directory: %s", log_dir)
    startup_logger.info("  Application log: %s", app_log_file)
    startup_logger.info("  Heartbeat log: %s", heartbeat_log_file)
    startup_logger.info("  Heartbeat loggers (separate file): %s", ", ".join(sorted(HEARTBEAT_LOGGERS)))
