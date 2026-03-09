"""
DockerDeck – controllers/containers_controller.py

Owns all container tab behaviour: selection, action dispatch,
refresh, bulk ops, and output routing.

Boundary rules
--------------
- MAY import: services/*, utils, ui_components, actions/containers
- MAY use tkinter only for after() scheduling (no widget construction)
- MUST NOT construct tab widgets — that stays in app.py
- MUST NOT call subprocess directly
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, TYPE_CHECKING

from services.docker_service import run_sync, run_stream
from services.result import OperationResult, ErrorKind
from services.state_store import app_state
from services.notifications_service import notifications, Level
from utils import safe_thread

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk


class ContainersController:
    """
    Wires the container tab to Docker operations.

    Parameters passed from app.py (all tkinter objects):
        root         : root Tk window (for .after() scheduling)
        tree         : Treeview widget
        output_fn    : callable(text, clear=False) → writes to output console
        status_fn    : callable(str) → updates status bar
        refresh_dashboard : callable() → triggers dashboard refresh
    """

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
    #  SELECTION HELPERS
    # ─────────────────────────────────────────

    def selected_names(self) -> List[str]:
        """Return container names for all currently selected tree rows."""
        return [
            self._tree.item(s)["values"][1]
            for s in self._tree.selection()
            if self._tree.item(s)["values"]
        ]

    def one_selected(self) -> Optional[str]:
        names = self.selected_names()
        return names[0] if names else None

    # ─────────────────────────────────────────
    #  OUTPUT HELPERS
    # ─────────────────────────────────────────

    def _write(self, text: str, clear: bool = False) -> None:
        self._root.after(0, lambda: self._out(text, clear))

    def _write_result(self, result: OperationResult, label: str) -> None:
        """Write a typed result to the output console."""
        if result.ok:
            self._write(
                f"✓ {label}  (rc=0  {result.duration_s:.2f}s)\n"
                f"{result.output}\n\n"
            )
        else:
            self._write(
                f"✕ {label}  (rc={result.rc}  {result.duration_s:.2f}s)\n"
                f"{result.failure_message()}\n\n"
            )
        notifications.record_result(result)

    # ─────────────────────────────────────────
    #  SINGLE-CONTAINER ACTIONS
    # ─────────────────────────────────────────

    def _simple_action(self, docker_cmd: str, names: List[str]) -> None:
        """Generic start/stop/restart for one or more containers."""
        def _do():
            for name in names:
                self._status(f"docker {docker_cmd} {name}…")
                result = run_sync([docker_cmd, name])
                result.user_msg = f"{docker_cmd} {name}"
                self._write_result(result, f"{docker_cmd} {name}")
            self._request_refresh()
        safe_thread(_do)

    def start(self, names: List[str]) -> None:
        self._simple_action("start", names)

    def stop(self, names: List[str]) -> None:
        self._simple_action("stop", names)

    def restart(self, names: List[str]) -> None:
        self._simple_action("restart", names)

    def inspect(self, name: str) -> None:
        def _do():
            result = run_sync(["inspect", name])
            self._write(f"=== inspect {name} ===\n{result.output}\n\n")
        safe_thread(_do)

    def rename(self, old_name: str, new_name: str) -> None:
        def _do():
            result = run_sync(["rename", old_name, new_name])
            result.user_msg = f"Renamed {old_name} → {new_name}"
            self._write_result(result, f"rename {old_name} → {new_name}")
            if result.ok:
                self._request_refresh()
        safe_thread(_do)

    def copy_file(self, src: str, dst: str) -> None:
        def _do():
            result = run_sync(["cp", src, dst])
            result.user_msg = f"Copied {src} → {dst}"
            self._write_result(result, f"cp {src} → {dst}")
        safe_thread(_do)

    def get_shell_command(self, name: str) -> str:
        return f"docker exec -it {name} sh"

    # ─────────────────────────────────────────
    #  BULK ACTIONS
    # ─────────────────────────────────────────

    def stop_all(self, names: List[str]) -> None:
        """Bulk stop. Caller must confirm before calling."""
        def _do():
            ok_count = fail_count = 0
            for name in names:
                result = run_sync(["stop", name])
                label  = f"stop {name}"
                self._write_result(result, label)
                if result.ok:
                    ok_count += 1
                else:
                    fail_count += 1
            summary = f"Stopped {ok_count}/{len(names)} containers."
            if fail_count:
                summary += f" {fail_count} failed — see output."
                notifications.notify(summary, Level.WARNING)
            else:
                notifications.notify(summary, Level.SUCCESS)
            self._request_refresh()
        safe_thread(_do)

    def bulk_restart(self, names: List[str]) -> None:
        """Bulk restart. Caller must confirm."""
        def _do():
            ok_count = fail_count = 0
            for name in names:
                result = run_sync(["restart", name])
                self._write_result(result, f"restart {name}")
                if result.ok:
                    ok_count += 1
                else:
                    fail_count += 1
            summary = f"Restarted {ok_count}/{len(names)} containers."
            level = Level.SUCCESS if not fail_count else Level.WARNING
            notifications.notify(summary, level)
            self._request_refresh()
        safe_thread(_do)

    def remove(self, names: List[str]) -> None:
        """Force-remove containers. Caller must confirm."""
        def _do():
            ok_count = fail_count = 0
            for name in names:
                result = run_sync(["rm", "-f", name])
                self._write_result(result, f"rm {name}")
                if result.ok:
                    ok_count += 1
                else:
                    fail_count += 1
            summary = f"Removed {ok_count}/{len(names)} containers."
            level = Level.SUCCESS if not fail_count else Level.WARNING
            notifications.notify(summary, level)
            self._request_refresh()
        safe_thread(_do)

    # ─────────────────────────────────────────
    #  REFRESH  (debounced / coalesced)
    # ─────────────────────────────────────────

    def _request_refresh(self) -> None:
        """
        Coalesce rapid refresh requests.
        Multiple calls within 300ms produce exactly one refresh.
        """
        with self._refresh_lock:
            if self._refresh_pending:
                return
            self._refresh_pending = True
        self._root.after(300, self._do_refresh)

    def _do_refresh(self) -> None:
        with self._refresh_lock:
            self._refresh_pending = False

        def _fetch():
            args = ["ps", "-a"] if app_state.show_all_containers else ["ps"]
            args += [
                "--format",
                "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}"
            ]
            result = run_sync(args, timeout=15)
            self._root.after(0, lambda: self._populate_tree(result))
            self._refresh_dash()

        safe_thread(_fetch)

    def _populate_tree(self, result: OperationResult) -> None:
        self._tree.delete(*self._tree.get_children())
        if not result.ok:
            return
        from utils import COLORS
        for line in result.stdout.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            while len(parts) < 6:
                parts.append("")
            iid = self._tree.insert("", "end", values=parts[:6])
            status = parts[3].lower()
            tag = "running" if "up" in status else ("stopped" if "exited" in status else "")
            if tag:
                self._tree.item(iid, tags=(tag,))
        self._tree.tag_configure("running", foreground=COLORS["accent_green"])
        self._tree.tag_configure("stopped", foreground=COLORS["accent_red"])

    def refresh(self) -> None:
        """Public entry point — called by app.py refresh orchestrator."""
        self._request_refresh()
