"""
DockerDeck – controllers/images_controller.py

Owns all image tab behaviour.

Boundary rules: same as containers_controller.py.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, TYPE_CHECKING

from services.docker_service import run_sync, run_stream
from services.result import OperationResult
from services.notifications_service import notifications, Level
from validation import validate_image_name, ValidationError
from utils import safe_thread

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk


class ImagesController:

    def __init__(self,
                 root: "tk.Tk",
                 tree: "ttk.Treeview",
                 output_fn: Callable,
                 status_fn: Callable,
                 refresh_dashboard: Callable) -> None:
        self._root = root
        self._tree = tree
        self._out  = output_fn
        self._status = status_fn
        self._refresh_dash = refresh_dashboard
        self._refresh_lock = threading.Lock()
        self._refresh_pending = False

    # ─────────────────────────────────────────
    #  SELECTION
    # ─────────────────────────────────────────

    def selected_values(self) -> Optional[list]:
        sel = self._tree.selection()
        if not sel:
            return None
        return list(self._tree.item(sel[0])["values"])

    # ─────────────────────────────────────────
    #  OUTPUT
    # ─────────────────────────────────────────

    def _write(self, text: str, clear: bool = False) -> None:
        self._root.after(0, lambda: self._out(text, clear))

    def _write_result(self, result: OperationResult, label: str) -> None:
        if result.ok:
            self._write(
                f"✓ {label}  ({result.duration_s:.2f}s)\n{result.output}\n\n"
            )
        else:
            self._write(
                f"✕ {label}  (rc={result.rc})\n{result.failure_message()}\n\n"
            )
        notifications.record_result(result)

    # ─────────────────────────────────────────
    #  ACTIONS
    # ─────────────────────────────────────────

    def pull(self, image: str, stream_cb: Callable[[str], None]) -> None:
        """Pull image; stream_cb receives each output line (called off main thread)."""
        def _do():
            self._status(f"Pulling {image}…")
            self._write(f"Pulling {image}…\n", clear=True)
            result = run_stream(["pull", image], stream_cb, timeout=300)
            result.user_msg = f"Pulled {image}"
            self._write_result(result, f"pull {image}")
            self._status(f"Pull complete: {image}" if result.ok else f"Pull failed: {image}")
            if result.ok:
                self._request_refresh()
        safe_thread(_do)

    def inspect(self, image_id: str) -> None:
        def _do():
            result = run_sync(["inspect", image_id])
            self._write(f"=== inspect {image_id} ===\n{result.output}\n\n")
        safe_thread(_do)

    def remove(self, image_id: str, display_name: str) -> None:
        """Remove an image. Caller must confirm."""
        def _do():
            result = run_sync(["rmi", image_id])
            result.user_msg = f"Removed {display_name}"
            self._write_result(result, f"rmi {display_name}")
            if result.ok:
                self._request_refresh()
        safe_thread(_do)

    def prune(self) -> None:
        """Prune dangling images. Caller must confirm."""
        def _do():
            result = run_sync(["image", "prune", "-f"], timeout=60)
            result.user_msg = "Dangling images pruned"
            self._write_result(result, "image prune")
            if result.ok:
                self._request_refresh()
        safe_thread(_do)

    # ─────────────────────────────────────────
    #  REFRESH
    # ─────────────────────────────────────────

    def _request_refresh(self) -> None:
        with self._refresh_lock:
            if self._refresh_pending:
                return
            self._refresh_pending = True
        self._root.after(300, self._do_refresh)

    def _do_refresh(self) -> None:
        with self._refresh_lock:
            self._refresh_pending = False

        def _fetch():
            result = run_sync([
                "images", "--format",
                "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}",
            ])
            self._root.after(0, lambda: self._populate_tree(result))
            self._refresh_dash()

        safe_thread(_fetch)

    def _populate_tree(self, result: OperationResult) -> None:
        self._tree.delete(*self._tree.get_children())
        if not result.ok:
            return
        for line in result.stdout.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            while len(parts) < 5:
                parts.append("")
            self._tree.insert("", "end", values=parts[:5])

    def refresh(self) -> None:
        self._request_refresh()
