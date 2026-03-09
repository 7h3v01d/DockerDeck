"""
DockerDeck – utils.py
Threading helpers, debounce, shared constants, and logging setup.

Notification log: now handled by services.notifications_service.
This module keeps a thin legacy shim (log_notification / get_notification_log)
so existing tests continue to pass without modification.
"""

import sys
import logging
import threading
import traceback
from collections import deque
from datetime import datetime
from typing import Callable, Optional

# ─────────────────────────────────────────────
#  VERSIONING
# ─────────────────────────────────────────────
__version__ = "4.0.0"
__app_name__ = "DockerDeck"


# ─────────────────────────────────────────────
#  STRUCTURED LOGGING SETUP
# ─────────────────────────────────────────────

def configure_logging(level: int = logging.WARNING,
                      log_file: Optional[str] = None) -> None:
    """
    Configure the root 'dockerdeck' logger.
    Call once at startup (main.py does this).
    """
    root_logger = logging.getLogger("dockerdeck")
    root_logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root_logger.addHandler(sh)

    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            root_logger.addHandler(fh)
        except Exception as exc:
            root_logger.warning("Could not open log file %s: %s", log_file, exc)


# ─────────────────────────────────────────────
#  THEME & STYLE CONFIG
# ─────────────────────────────────────────────
COLORS = {
    "bg_dark":        "#0d1117",
    "bg_card":        "#161b22",
    "bg_hover":       "#1c2128",
    "bg_input":       "#0d1117",
    "border":         "#30363d",
    "accent":         "#58a6ff",
    "accent_green":   "#3fb950",
    "accent_red":     "#f85149",
    "accent_orange":  "#d29922",
    "accent_purple":  "#bc8cff",
    "accent_cyan":    "#39d353",
    "text_primary":   "#e6edf3",
    "text_secondary": "#8b949e",
    "text_dim":       "#484f58",
    "tab_active":     "#58a6ff",
    "tab_inactive":   "#8b949e",
    "running":        "#3fb950",
    "stopped":        "#f85149",
    "paused":         "#d29922",
    # WCAG AA contrast overrides (ratio vs #0d1117 bg_dark)
    # text_dim  #484f58  2.28:1 — decorative only (dots/separators, never real text)
    # text_disabled was #6e7681 (4.12:1 FAIL AA) — bumped to 4.94:1 PASS AA
    "text_disabled":  "#7a8390",
    # Focus ring: 7.49:1 vs bg_dark — WCAG AAA
    "focus_ring":     "#58a6ff",
}

FONTS = {
    "mono":    ("Courier New", 10),
    "mono_sm": ("Courier New", 9),
    "mono_lg": ("Courier New", 12),
    "ui":      ("Segoe UI", 10),
    "ui_sm":   ("Segoe UI", 9),
    "ui_lg":   ("Segoe UI", 13, "bold"),
    "title":   ("Segoe UI", 16, "bold"),
    "heading": ("Segoe UI", 11, "bold"),
}


# ─────────────────────────────────────────────
#  LEGACY NOTIFICATION LOG (shim for old tests)
#  Real notification log is in services/notifications_service.py
# ─────────────────────────────────────────────
MAX_LOG_ENTRIES = 200
_notification_log: deque = deque(maxlen=MAX_LOG_ENTRIES)
_log_lock = threading.Lock()


def log_notification(message: str, level: str = "info") -> None:
    """Append a timestamped entry. Shim — prefer notifications_service."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _log_lock:
        _notification_log.appendleft({"ts": ts, "level": level, "msg": message})


def get_notification_log() -> list:
    """Return a snapshot of the notification log (newest first). Shim."""
    with _log_lock:
        return list(_notification_log)


# ─────────────────────────────────────────────
#  THREAD SAFETY
# ─────────────────────────────────────────────
_err_callback: Optional[Callable[[str], None]] = None


def set_error_callback(fn: Callable[[str], None]) -> None:
    global _err_callback
    _err_callback = fn


def _thread_excepthook(args) -> None:
    msg = "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_tb))
    print(f"[DockerDeck unhandled thread exception]\n{msg}", file=sys.stderr)
    if _err_callback:
        try:
            _err_callback(
                f"Unexpected error: {args.exc_value}\n\n"
                "See console for full traceback."
            )
        except Exception:
            pass


threading.excepthook = _thread_excepthook


def safe_thread(target: Callable, *args, **kwargs) -> threading.Thread:
    """Launch target in a daemon thread, surfacing exceptions via error callback."""
    def _wrapper(*a, **kw):
        try:
            target(*a, **kw)
        except Exception as e:
            msg = traceback.format_exc()
            print(f"[Thread error]\n{msg}", file=sys.stderr)
            if _err_callback:
                try:
                    _err_callback(f"Background error: {e}")
                except Exception:
                    pass

    t = threading.Thread(target=_wrapper, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


# ─────────────────────────────────────────────
#  DEBOUNCE HELPER
# ─────────────────────────────────────────────
class Debouncer:
    """
    Delays fn() until delay_ms ms have passed since the last call.
    Requires a tkinter widget for .after().
    """
    def __init__(self, widget, fn: Callable, delay_ms: int = 300):
        self._widget  = widget
        self._fn      = fn
        self._delay   = delay_ms
        self._job     = None

    def __call__(self, *args, **kwargs):
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
        self._job = self._widget.after(
            self._delay, lambda: self._fn(*args, **kwargs)
        )


# ─────────────────────────────────────────────
#  TEMPLATE STRINGS
# ─────────────────────────────────────────────
COMPOSE_TEMPLATE = """\
version: '3.8'

services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
    volumes:
      - ./html:/usr/share/nginx/html
    restart: unless-stopped
    networks:
      - app-network

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: mydb
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - app-network

networks:
  app-network:
    driver: bridge

volumes:
  pgdata:
"""

DOCKERFILE_TEMPLATE = """\
# ── Base Image ──────────────────────────────
FROM python:3.11-slim

# ── Metadata ────────────────────────────────
LABEL maintainer="you@example.com"
LABEL version="1.0"

# ── Environment ─────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    APP_HOME=/app

# ── Working Directory ───────────────────────
WORKDIR $APP_HOME

# ── System Dependencies ─────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# ── Python Dependencies ─────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application Code ────────────────────────
COPY . .

# ── Expose Port ─────────────────────────────
EXPOSE 8000

# ── Healthcheck ─────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD curl -f http://localhost:8000/health || exit 1

# ── Entry Point ─────────────────────────────
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""
