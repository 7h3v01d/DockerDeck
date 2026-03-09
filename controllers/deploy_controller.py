"""
DockerDeck – controllers/deploy_controller.py

Owns deploy tab behaviour: field validation, command building,
preset management, and deploy execution.

Boundary rules: same as containers_controller.py.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional, TYPE_CHECKING

from services.docker_service import run_stream
from services.result import OperationResult
from services.notifications_service import notifications, Level
from services.settings_service import settings
from actions.deploy import (
    validate_field, validate_all_fields,
    build_run_command,
)
from validation import ValidationError
from utils import safe_thread

if TYPE_CHECKING:
    import tkinter as tk


class DeployController:
    """
    Handles all deploy tab interactions.

    field_values_fn : callable() → dict {key: str}  — reads current field values
    output_fn       : callable(text, clear=False)    — writes to deploy console
    status_fn       : callable(str)                  — updates status bar
    preview_fn      : callable(str)                  — updates command preview
    """

    def __init__(self,
                 root: "tk.Tk",
                 field_values_fn: Callable,
                 output_fn: Callable,
                 status_fn: Callable,
                 preview_fn: Callable) -> None:
        self._root       = root
        self._fv         = field_values_fn
        self._out        = output_fn
        self._status     = status_fn
        self._preview    = preview_fn
        self._stop_event = threading.Event()

    # ─────────────────────────────────────────
    #  VALIDATION
    # ─────────────────────────────────────────

    def validate_field(self, key: str) -> tuple:
        """Returns (ok: bool, error_msg: str)."""
        val = self._fv().get(key, "")
        return validate_field(key, val)

    def validate_all(self) -> tuple:
        return validate_all_fields(self._fv())

    def update_preview(self, detach: bool) -> None:
        """Rebuild and display the command preview. Silent on validation error."""
        try:
            cmd = build_run_command(self._fv(), detach)
            self._root.after(0, lambda: self._preview(" ".join(cmd)))
        except Exception:
            pass

    # ─────────────────────────────────────────
    #  DEPLOY
    # ─────────────────────────────────────────

    def deploy(self, detach: bool,
               confirm_fn: Callable[[str], bool]) -> None:
        """
        Validate → preview → confirm → execute in background.

        confirm_fn(command_str) → bool  — called on main thread before execution.
        Returns immediately; all work happens in a background thread.
        """
        fv = self._fv()
        ok, err = validate_all_fields(fv)
        if not ok:
            self._root.after(0, lambda: self._out(f"✕ Validation failed:\n{err}\n\n", True))
            return

        try:
            cmd = build_run_command(fv, detach)
        except ValidationError as exc:
            self._root.after(0, lambda: self._out(f"✕ {exc}\n\n", True))
            return

        cmd_str = " ".join(cmd)

        # confirm_fn must run on main thread
        confirmed = {"v": False}
        done = threading.Event()

        def _ask():
            confirmed["v"] = confirm_fn(cmd_str)
            done.set()

        self._root.after(0, _ask)
        done.wait(timeout=30)

        if not confirmed["v"]:
            return

        docker_args = cmd[1:]   # strip 'docker'
        self._stop_event.clear()

        def _do():
            self._root.after(0, lambda: self._out(
                f"$ {cmd_str}\n\n", True))
            self._status("Deploying…")

            def cb(line):
                self._root.after(0, lambda l=line: self._out(l))

            result = run_stream(docker_args, cb,
                                stop_event=self._stop_event, timeout=300)
            result.user_msg = "Deploy complete" if result.ok else "Deploy failed"

            self._root.after(0, lambda: self._out(
                f"\n--- Done (rc={result.rc}  {result.duration_s:.2f}s) ---\n"))
            self._status(result.user_msg)
            notifications.record_result(result)

        safe_thread(_do)

    def cancel(self) -> None:
        self._stop_event.set()

    # ─────────────────────────────────────────
    #  PRESETS
    # ─────────────────────────────────────────

    def save_preset(self, name: str, field_values: dict, detach: bool) -> None:
        data = dict(field_values)
        data["__detach"] = detach
        settings.save_preset(name, data)
        notifications.notify(f"Preset '{name}' saved.", Level.SUCCESS)

    def delete_preset(self, name: str) -> None:
        settings.delete_preset(name)

    def load_preset(self, name: str) -> Optional[dict]:
        return settings.presets.get(name)

    @property
    def preset_names(self) -> list:
        return list(settings.presets.keys())
