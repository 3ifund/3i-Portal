"""
3i Fund Portal — Logging Configuration

Splits logs into two files:
  - heartbeat log: high-volume WebSocket/quote/workflow messages (local only)
  - application log: everything else (local + remote on EC2)

Auto-detects EC2 vs on-prem:
  - On-prem (Windows): both logs write to c:\logging\portal-backend\
  - EC2 (Linux): heartbeat writes locally to /var/log/portal-backend/,
    application log writes locally AND forwards to on-prem server via TCP
"""

import logging
import logging.handlers
import os
import platform
from datetime import date


# On-prem log receiver settings (only used when running on EC2)
REMOTE_LOG_HOST = "10.90.98.123"
REMOTE_LOG_PORT = 9020

# Heartbeat logger names — high-volume loggers that stay local only
HEARTBEAT_LOGGERS = {
    "portal.quotes",
    "portal.workflows",
    "websockets",
    "uvicorn.access",
}


def _is_ec2() -> bool:
    """Detect if running on an EC2 instance by checking the metadata endpoint."""
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
    """Configure logging with split heartbeat/application files and optional remote forwarding."""

    on_ec2 = _is_ec2()

    # Determine log directory based on platform
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

    # ── Application log file (low volume: auth, admin, purchase notices, etc.) ──
    app_log_file = os.path.join(log_dir, f"{today}.log")
    app_file_handler = logging.FileHandler(app_log_file, encoding="utf-8")
    app_file_handler.setLevel(logging.DEBUG)
    app_file_handler.setFormatter(formatter)

    # ── Heartbeat log file (high volume: quotes, workflows, websockets) ──
    heartbeat_log_file = os.path.join(log_dir, f"heartbeat-{today}.log")
    heartbeat_file_handler = logging.FileHandler(heartbeat_log_file, encoding="utf-8")
    heartbeat_file_handler.setLevel(logging.DEBUG)
    heartbeat_file_handler.setFormatter(formatter)

    # ── Console handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # ── Remote handler (EC2 only — sends application logs to on-prem server) ──
    remote_handler = None
    if on_ec2:
        try:
            remote_handler = logging.handlers.SocketHandler(
                REMOTE_LOG_HOST, REMOTE_LOG_PORT
            )
            remote_handler.setLevel(logging.INFO)
            # SocketHandler sends pickled LogRecords, the receiver unpickles and formats
        except Exception:
            # If remote connection fails at startup, continue without it
            remote_handler = None

    # ── Configure root logger (catches everything not explicitly configured) ──
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(app_file_handler)
    root.addHandler(console_handler)
    if remote_handler:
        root.addHandler(remote_handler)

    # ── Configure heartbeat loggers — route to heartbeat file, NOT application file ──
    for logger_name in HEARTBEAT_LOGGERS:
        hb_logger = logging.getLogger(logger_name)
        hb_logger.propagate = False  # Don't send to root (application log)
        hb_logger.setLevel(logging.DEBUG)
        hb_logger.addHandler(heartbeat_file_handler)
        hb_logger.addHandler(console_handler)
        # Heartbeat logs do NOT get the remote handler — they stay local only

    # ── Quiet down noisy third-party loggers ──
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # ── Startup log ──
    startup_logger = logging.getLogger("portal.logging")
    startup_logger.info("Logging initialized")
    startup_logger.info("  Environment: %s", "EC2" if on_ec2 else "On-Premises")
    startup_logger.info("  Platform: %s", platform.system())
    startup_logger.info("  Log directory: %s", log_dir)
    startup_logger.info("  Application log: %s", app_log_file)
    startup_logger.info("  Heartbeat log: %s", heartbeat_log_file)
    if remote_handler:
        startup_logger.info("  Remote logging: %s:%d (application logs forwarded to on-prem)",
                           REMOTE_LOG_HOST, REMOTE_LOG_PORT)
    else:
        startup_logger.info("  Remote logging: disabled (on-prem or connection failed)")
    startup_logger.info("  Heartbeat loggers (local only): %s", ", ".join(sorted(HEARTBEAT_LOGGERS)))
