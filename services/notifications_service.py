"""
DockerDeck – services/notifications_service.py

Structured notification and operation logging service.

Responsibilities
----------------
- Record every operation start/end with command, rc, duration, trace
- Maintain the user-visible notification log (newest-first)
- Emit log records to Python's logging system for debug capture
- Separate user-visible summaries from debug detail

Import boundary: NO tkinter, NO docker_service.
"""

from __future__ import annotations

import logging
import traceback
import threading
from collections import deque
from datetime import datetime
from typing import Callable, List, Optional

from services.result import OperationResult, ErrorKind

logger = logging.getLogger("dockerdeck.notifications")


# ─────────────────────────────────────────────
#  NOTIFICATION ENTRY
# ─────────────────────────────────────────────

class Level:
    INFO    = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR   = "error"


class NotificationEntry:
    __slots__ = ("ts", "level", "msg", "detail", "op_id")

    def __init__(self, msg: str, level: str = Level.INFO,
                 detail: str = "", op_id: Optional[int] = None):
        self.ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.level  = level
        self.msg    = msg
        self.detail = detail   # debug-only; not shown in toast
        self.op_id  = op_id

    @property
    def icon(self) -> str:
        return {
            Level.SUCCESS: "✓",
            Level.WARNING: "⚠",
            Level.ERROR:   "✕",
        }.get(self.level, "ℹ")


# ─────────────────────────────────────────────
#  SERVICE
# ─────────────────────────────────────────────

MAX_ENTRIES = 300


class NotificationService:
    """
    Thread-safe notification log + operation event emitter.

    Usage
    -----
    notif = NotificationService()
    notif.subscribe(lambda e: show_toast(e.msg))
    notif.record_result(result)
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._log: deque[NotificationEntry] = deque(maxlen=MAX_ENTRIES)
        self._listeners: List[Callable[[NotificationEntry], None]] = []

    # ── Subscription ─────────────────────────

    def subscribe(self, fn: Callable[[NotificationEntry], None]) -> None:
        """Register fn to be called on every new notification (any thread)."""
        with self._lock:
            self._listeners.append(fn)

    def _emit(self, entry: NotificationEntry) -> None:
        listeners = []
        with self._lock:
            self._log.appendleft(entry)
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                pass

    # ── Public API ───────────────────────────

    def notify(self, msg: str, level: str = Level.INFO,
               detail: str = "", op_id: Optional[int] = None) -> None:
        """Post a user-visible notification."""
        entry = NotificationEntry(msg, level, detail, op_id)
        log_fn = {
            Level.SUCCESS: logger.info,
            Level.WARNING: logger.warning,
            Level.ERROR:   logger.error,
        }.get(level, logger.info)
        log_fn("notify [%s]: %s", level, msg)
        if detail:
            logger.debug("notify detail: %s", detail)
        self._emit(entry)

    def record_result(self, result: OperationResult) -> None:
        """
        Derive and post a notification from an OperationResult.
        Called by controllers after every operation.
        """
        cmd_short = " ".join(result.command[:4])

        if result.ok:
            msg   = result.user_msg or f"{cmd_short} completed"
            level = Level.SUCCESS
            detail = (
                f"cmd={result.short_cmd()}\n"
                f"rc=0  duration={result.duration_s:.2f}s"
            )
            logger.info(
                "OP OK: cmd=%s duration=%.2fs op_id=%d",
                cmd_short, result.duration_s, result.op_id,
            )
        elif result.cancelled:
            msg   = f"Cancelled: {cmd_short}"
            level = Level.WARNING
            detail = f"op_id={result.op_id}"
            logger.info("OP CANCELLED: cmd=%s op_id=%d", cmd_short, result.op_id)
        else:
            msg   = result.user_msg or result.failure_message().split("\n")[0]
            level = Level.ERROR
            detail = (
                f"cmd={result.short_cmd()}\n"
                f"rc={result.rc}  duration={result.duration_s:.2f}s\n"
                f"kind={result.error_kind.name}\n"
                f"stderr={result.stderr[:500]}"
            )
            logger.error(
                "OP FAIL: cmd=%s rc=%d duration=%.2fs kind=%s",
                cmd_short, result.rc, result.duration_s, result.error_kind.name,
            )

        self._emit(NotificationEntry(msg, level, detail, result.op_id))

    def record_exception(self, exc: Exception, context: str = "") -> None:
        """Record an unexpected Python exception."""
        tb = traceback.format_exc()
        logger.exception("Unhandled exception in %s: %s", context, exc)
        self._emit(NotificationEntry(
            msg=f"Unexpected error: {exc}",
            level=Level.ERROR,
            detail=f"context={context}\n{tb}",
        ))

    def get_log(self) -> List[NotificationEntry]:
        """Return snapshot of log (newest first)."""
        with self._lock:
            return list(self._log)


# ── Singleton ─────────────────────────────────
notifications = NotificationService()
