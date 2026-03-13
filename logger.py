"""
logger.py — Professional Structured Logging
Free — uses Python's built-in logging module
Logs to both console (Koyeb) and rotating file
"""

import logging
import logging.handlers
import os
import json
from datetime import datetime

LOG_DIR  = "logs"
LOG_FILE = f"{LOG_DIR}/competeiq.log"


def setup_logging():
    """Call once at startup."""
    os.makedirs(LOG_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler (visible in Koyeb logs)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Rotating file handler — max 5MB × 3 files
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass  # File logging optional — console always works

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class AnalysisLogger:
    """Structured logger for analysis events."""

    def __init__(self, user_id: int, business_name: str):
        self.log          = get_logger("analysis")
        self.user_id      = user_id
        self.business     = business_name
        self.start_time   = datetime.now()
        self.tool_calls   = 0
        self.search_count = 0

    def event(self, event: str, **kwargs):
        data = {"user": self.user_id, "business": self.business,
                "event": event, **kwargs}
        self.log.info(json.dumps(data, ensure_ascii=False))

    def tool_called(self, name: str, query: str = ""):
        self.tool_calls += 1
        if name in ("brave_search", "web_search"):
            self.search_count += 1
        self.log.debug(
            f"[u:{self.user_id}] tool={name} query={query[:60]!r} "
            f"total_calls={self.tool_calls}"
        )

    def quality_result(self, score: float, passed: bool, reflections: int):
        elapsed = (datetime.now() - self.start_time).seconds
        self.event("quality_gate",
                   score=score, passed=passed,
                   reflections=reflections,
                   elapsed_s=elapsed,
                   searches=self.search_count,
                   tool_calls=self.tool_calls)

    def error(self, msg: str, exc: Exception = None):
        self.log.error(
            f"[u:{self.user_id}] {msg}" +
            (f" | {type(exc).__name__}: {exc}" if exc else "")
        )

    def done(self, score: float):
        elapsed = (datetime.now() - self.start_time).seconds
        self.event("analysis_done",
                   score=score, elapsed_s=elapsed,
                   searches=self.search_count)
        self.log.info(
            f"✅ Analysis done — user={self.user_id} "
            f"score={score} time={elapsed}s searches={self.search_count}"
        )
