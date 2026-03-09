"""
DockerDeck – services/state_store.py

Central application state store.

Replaces the scattered instance variables in app.py with a single, inspectable
store.  All mutations go through explicit setters so controllers can subscribe
to specific state changes without polling.

Threading: all public methods are thread-safe (protected by _lock).
The UI layer may call getters from any thread; setters trigger registered
listeners on the CALLING thread — callers that need main-thread delivery
must wrap with root.after().

Import boundary: NO tkinter, NO docker_service here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ─────────────────────────────────────────────
#  SUB-STATE TYPES
# ─────────────────────────────────────────────

class DaemonStatus:
    UNKNOWN     = "unknown"
    RUNNING     = "running"
    UNAVAILABLE = "unavailable"


@dataclass
class ActiveOperation:
    op_id:    int
    label:    str                          # "Pulling nginx:latest…"
    cancel:   Optional[threading.Event]   # set to cancel; None if not cancellable


# ─────────────────────────────────────────────
#  STORE
# ─────────────────────────────────────────────

class AppStateStore:
    """
    Holds all runtime state for DockerDeck.

    Usage
    -----
    state = AppStateStore()
    state.subscribe("daemon_status", lambda v: update_ui(v))
    state.set_daemon_status(DaemonStatus.RUNNING)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}

        # ── Core state fields ──
        self._daemon_status: str              = DaemonStatus.UNKNOWN
        self._selected_container: str         = ""
        self._selected_image: str             = ""
        self._log_follow_active: bool         = False
        self._log_follow_container: str       = ""
        self._active_operations: Dict[int, ActiveOperation] = {}
        self._show_all_containers: bool       = False

    # ─────────────────────────────────────────
    #  SUBSCRIPTION
    # ─────────────────────────────────────────

    def subscribe(self, key: str, fn: Callable[[Any], None]) -> None:
        """Register fn to be called whenever key changes."""
        with self._lock:
            self._listeners.setdefault(key, []).append(fn)

    def _notify(self, key: str, value: Any) -> None:
        """Fire listeners for key. Called while NOT holding _lock."""
        listeners = []
        with self._lock:
            listeners = list(self._listeners.get(key, []))
        for fn in listeners:
            try:
                fn(value)
            except Exception:
                pass

    # ─────────────────────────────────────────
    #  DAEMON STATUS
    # ─────────────────────────────────────────

    @property
    def daemon_status(self) -> str:
        with self._lock:
            return self._daemon_status

    def set_daemon_status(self, status: str) -> None:
        changed = False
        with self._lock:
            if self._daemon_status != status:
                self._daemon_status = status
                changed = True
        if changed:
            self._notify("daemon_status", status)

    @property
    def daemon_ok(self) -> bool:
        return self.daemon_status == DaemonStatus.RUNNING

    # ─────────────────────────────────────────
    #  SELECTIONS
    # ─────────────────────────────────────────

    @property
    def selected_container(self) -> str:
        with self._lock:
            return self._selected_container

    def set_selected_container(self, name: str) -> None:
        with self._lock:
            self._selected_container = name
        self._notify("selected_container", name)

    @property
    def selected_image(self) -> str:
        with self._lock:
            return self._selected_image

    def set_selected_image(self, name: str) -> None:
        with self._lock:
            self._selected_image = name
        self._notify("selected_image", name)

    # ─────────────────────────────────────────
    #  LOG FOLLOW
    # ─────────────────────────────────────────

    @property
    def log_follow_active(self) -> bool:
        with self._lock:
            return self._log_follow_active

    @property
    def log_follow_container(self) -> str:
        with self._lock:
            return self._log_follow_container

    def set_log_follow(self, active: bool, container: str = "") -> None:
        with self._lock:
            self._log_follow_active = active
            self._log_follow_container = container if active else ""
        self._notify("log_follow", (active, container))

    # ─────────────────────────────────────────
    #  ACTIVE OPERATIONS (job tracker)
    # ─────────────────────────────────────────

    def register_operation(self, op: ActiveOperation) -> None:
        with self._lock:
            self._active_operations[op.op_id] = op
        self._notify("operations", self.active_operation_count)

    def complete_operation(self, op_id: int) -> None:
        with self._lock:
            self._active_operations.pop(op_id, None)
        self._notify("operations", self.active_operation_count)

    def cancel_operation(self, op_id: int) -> None:
        with self._lock:
            op = self._active_operations.get(op_id)
        if op and op.cancel:
            op.cancel.set()

    def cancel_all(self) -> None:
        with self._lock:
            ops = list(self._active_operations.values())
        for op in ops:
            if op.cancel:
                op.cancel.set()

    @property
    def active_operation_count(self) -> int:
        with self._lock:
            return len(self._active_operations)

    @property
    def active_operations(self) -> List[ActiveOperation]:
        with self._lock:
            return list(self._active_operations.values())

    # ─────────────────────────────────────────
    #  CONTAINER FILTER
    # ─────────────────────────────────────────

    @property
    def show_all_containers(self) -> bool:
        with self._lock:
            return self._show_all_containers

    def set_show_all_containers(self, value: bool) -> None:
        with self._lock:
            self._show_all_containers = value
        self._notify("show_all_containers", value)


# ── Singleton ─────────────────────────────────
# One store per process — controllers share this reference.
app_state = AppStateStore()
