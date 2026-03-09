"""
DockerDeck – controllers/events_service.py

Docker events watcher and daemon health monitor.

Lifecycle contract
------------------
- start() launches both background services.
- stop() signals both to exit cleanly.
- Both services stop within ~1s of stop() being called.
- On daemon recovery, the events watcher is automatically restarted.
- Callers register callbacks via subscribe_*() — all callbacks are
  fired on the CALLING thread (not the main thread). Callers that need
  main-thread delivery must schedule with root.after().

Import boundary: NO tkinter.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import logging
from typing import Callable, List, Optional

from services.docker_service import daemon_available
from services.state_store import app_state, DaemonStatus
from services.notifications_service import notifications, Level
from utils import safe_thread

logger = logging.getLogger("dockerdeck.events_service")

# Docker event type → action sets
_CONTAINER_EVENTS = {
    "start", "stop", "die", "kill", "pause",
    "unpause", "destroy", "create", "rename",
}
_IMAGE_EVENTS   = {"pull", "push", "import", "delete", "tag", "untag"}
_VOLUME_EVENTS  = {"create", "destroy", "prune", "mount", "unmount"}
_NETWORK_EVENTS = {"create", "destroy", "connect", "disconnect", "prune"}

DAEMON_POLL_INTERVAL = 12   # seconds


class EventsService:
    """
    Runs two background loops:
      1. docker events JSON stream — triggers targeted UI refreshes
      2. daemon health poll — detects loss/recovery of docker daemon
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._events_active = threading.Event()

        # Callbacks — registered by controllers
        self._container_cbs:  List[Callable] = []
        self._image_cbs:      List[Callable] = []
        self._volume_cbs:     List[Callable] = []
        self._network_cbs:    List[Callable] = []
        self._daemon_lost_cbs: List[Callable] = []
        self._daemon_ok_cbs:  List[Callable] = []

    # ─────────────────────────────────────────
    #  SUBSCRIPTION
    # ─────────────────────────────────────────

    def on_container_event(self, fn: Callable) -> None:
        self._container_cbs.append(fn)

    def on_image_event(self, fn: Callable) -> None:
        self._image_cbs.append(fn)

    def on_volume_event(self, fn: Callable) -> None:
        self._volume_cbs.append(fn)

    def on_network_event(self, fn: Callable) -> None:
        self._network_cbs.append(fn)

    def on_daemon_lost(self, fn: Callable) -> None:
        self._daemon_lost_cbs.append(fn)

    def on_daemon_recovered(self, fn: Callable) -> None:
        self._daemon_ok_cbs.append(fn)

    # ─────────────────────────────────────────
    #  LIFECYCLE
    # ─────────────────────────────────────────

    def start(self) -> None:
        self._stop.clear()
        safe_thread(self._events_loop)
        safe_thread(self._daemon_monitor_loop)
        logger.info("EventsService started")

    def stop(self) -> None:
        self._stop.set()
        logger.info("EventsService stopping")

    # ─────────────────────────────────────────
    #  EVENTS WATCHER
    # ─────────────────────────────────────────

    def _events_loop(self) -> None:
        while not self._stop.is_set():
            self._events_active.set()
            try:
                proc = subprocess.Popen(
                    ["docker", "events", "--format", "{{json .}}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                logger.debug("events stream started (pid=%d)", proc.pid)

                for raw in proc.stdout:
                    if self._stop.is_set():
                        proc.terminate()
                        break
                    raw = raw.strip()
                    if not raw:
                        continue
                    self._dispatch_event(raw)

                proc.wait()
            except Exception as exc:
                logger.debug("events loop error: %s", exc)

            self._events_active.clear()
            if not self._stop.is_set():
                logger.debug("events stream ended; reconnecting in 10s")
                self._stop.wait(timeout=10)

    def _dispatch_event(self, raw: str) -> None:
        try:
            ev         = json.loads(raw)
            evt_type   = ev.get("Type", "")
            evt_action = ev.get("Action", "")
        except (json.JSONDecodeError, ValueError):
            parts      = raw.split()
            evt_type   = parts[0] if parts else ""
            evt_action = parts[1] if len(parts) > 1 else ""

        logger.debug("event: type=%s action=%s", evt_type, evt_action)

        if evt_type == "container" and evt_action in _CONTAINER_EVENTS:
            self._fire(self._container_cbs)
        elif evt_type == "image" and evt_action in _IMAGE_EVENTS:
            self._fire(self._image_cbs)
        elif evt_type == "volume" and evt_action in _VOLUME_EVENTS:
            self._fire(self._volume_cbs)
        elif evt_type == "network" and evt_action in _NETWORK_EVENTS:
            self._fire(self._network_cbs)

    def _fire(self, cbs: List[Callable]) -> None:
        for fn in cbs:
            try:
                fn()
            except Exception as exc:
                logger.debug("event callback error: %s", exc)

    # ─────────────────────────────────────────
    #  DAEMON HEALTH MONITOR
    # ─────────────────────────────────────────

    def _daemon_monitor_loop(self) -> None:
        while not self._stop.is_set():
            ok = daemon_available()
            prev = app_state.daemon_status

            if ok:
                app_state.set_daemon_status(DaemonStatus.RUNNING)
                if prev != DaemonStatus.RUNNING:
                    logger.info("Daemon recovered")
                    notifications.notify(
                        "Docker daemon reconnected — refreshing views.",
                        Level.SUCCESS,
                    )
                    self._fire(self._daemon_ok_cbs)
                    # Restart events watcher if it stopped
                    if not self._events_active.is_set():
                        safe_thread(self._events_loop)
            else:
                app_state.set_daemon_status(DaemonStatus.UNAVAILABLE)
                if prev != DaemonStatus.UNAVAILABLE:
                    logger.warning("Daemon lost")
                    notifications.notify(
                        "Docker daemon not responding. "
                        "Check Docker is running, then press Ctrl+R.",
                        Level.ERROR,
                    )
                    self._fire(self._daemon_lost_cbs)

            self._stop.wait(timeout=DAEMON_POLL_INTERVAL)
