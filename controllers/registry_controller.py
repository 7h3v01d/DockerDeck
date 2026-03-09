"""
DockerDeck – controllers/registry_controller.py

Registry login/logout/push/pull behaviour.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from services.docker_service import run_sync, run_stream, run_login
from services.result import OperationResult
from services.notifications_service import notifications
from validation import validate_image_name, ValidationError
from utils import safe_thread

if TYPE_CHECKING:
    import tkinter as tk


class RegistryController:

    def __init__(self, root: "tk.Tk", output_fn: Callable,
                 status_fn: Callable) -> None:
        self._root   = root
        self._out    = output_fn
        self._status = status_fn

    def _write(self, text: str, clear: bool = False) -> None:
        self._root.after(0, lambda: self._out(text, clear))

    def _write_result(self, result: OperationResult, label: str) -> None:
        if result.ok:
            self._write(f"✓ {label}\n{result.output}\n\n")
        else:
            self._write(f"✕ {label}\n{result.failure_message()}\n\n")
        notifications.record_result(result)

    def login(self, url: str, user: str, password: str) -> None:
        """
        SECURITY: password piped via stdin only.
        Caller MUST wipe the entry widget before calling.
        """
        args = (
            ["login", url, "-u", user, "--password-stdin"]
            if url and url != "docker.io"
            else ["login", "-u", user, "--password-stdin"]
        )

        def _do():
            self._status("Logging in to registry…")
            def cb(text):
                self._write(text)
            result = run_login(args, password, cb)
            result.user_msg = "Registry login successful" if result.ok else "Registry login failed"
            notifications.record_result(result)
            self._status(result.user_msg)
        safe_thread(_do)

    def logout(self, url: str) -> None:
        def _do():
            result = run_sync(["logout", url])
            self._write_result(result, f"logout {url}")
        safe_thread(_do)

    def push(self, src: str, dst: str) -> None:
        def _do():
            if src != dst:
                tag_result = run_sync(["tag", src, dst])
                self._write(f"[tag] {tag_result.output}\n")
            self._write(f"Pushing {dst}…\n")
            def cb(line):
                self._write(line)
            result = run_stream(["push", dst], cb, timeout=600)
            result.user_msg = f"Pushed {dst}" if result.ok else f"Push failed: {dst}"
            notifications.record_result(result)
        safe_thread(_do)

    def pull(self, img: str) -> None:
        def _do():
            def cb(line):
                self._write(line)
            result = run_stream(["pull", img], cb, timeout=300)
            result.user_msg = f"Pulled {img}" if result.ok else f"Pull failed: {img}"
            notifications.record_result(result)
        safe_thread(_do)
