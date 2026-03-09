"""
DockerDeck – controllers/network_volume_controller.py

Networks and Volumes tab behaviour.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, TYPE_CHECKING

from services.docker_service import run_sync
from services.result import OperationResult
from services.notifications_service import notifications
from utils import safe_thread

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk


class NetworkVolumeController:

    def __init__(self, root: "tk.Tk",
                 net_tree: "ttk.Treeview",
                 vol_tree: "ttk.Treeview",
                 net_output_fn: Callable,
                 vol_output_fn: Callable,
                 refresh_dashboard: Callable) -> None:
        self._root = root
        self._net_tree = net_tree
        self._vol_tree = vol_tree
        self._net_out  = net_output_fn
        self._vol_out  = vol_output_fn
        self._refresh_dash = refresh_dashboard

    def _write_net(self, text: str, clear: bool = False) -> None:
        self._root.after(0, lambda: self._net_out(text, clear))

    def _write_vol(self, text: str, clear: bool = False) -> None:
        self._root.after(0, lambda: self._vol_out(text, clear))

    def _write_result(self, write_fn, result: OperationResult, label: str) -> None:
        if result.ok:
            write_fn(f"✓ {label}  ({result.duration_s:.2f}s)\n{result.output}\n\n")
        else:
            write_fn(f"✕ {label}\n{result.failure_message()}\n\n")
        notifications.record_result(result)

    # ─────────────────────────────────────────
    #  NETWORKS
    # ─────────────────────────────────────────

    def net_selected_name(self) -> Optional[str]:
        sel = self._net_tree.selection()
        if not sel:
            return None
        vals = self._net_tree.item(sel[0])["values"]
        return vals[1] if vals else None

    def net_create(self, name: str) -> None:
        def _do():
            result = run_sync(["network", "create", name])
            result.user_msg = f"Network '{name}' created"
            self._write_result(self._write_net, result, f"network create {name}")
            if result.ok:
                self.refresh_networks()
                self._refresh_dash()
        safe_thread(_do)

    def net_inspect(self, name: str) -> None:
        def _do():
            result = run_sync(["network", "inspect", name])
            self._write_net(f"=== inspect {name} ===\n{result.output}\n\n")
        safe_thread(_do)

    def net_remove(self, name: str) -> None:
        def _do():
            result = run_sync(["network", "rm", name])
            result.user_msg = f"Network '{name}' removed"
            self._write_result(self._write_net, result, f"network rm {name}")
            if result.ok:
                self.refresh_networks()
                self._refresh_dash()
        safe_thread(_do)

    def net_prune(self) -> None:
        def _do():
            result = run_sync(["network", "prune", "-f"], timeout=60)
            result.user_msg = "Unused networks pruned"
            self._write_result(self._write_net, result, "network prune")
            if result.ok:
                self.refresh_networks()
                self._refresh_dash()
        safe_thread(_do)

    def refresh_networks(self) -> None:
        def _fetch():
            result = run_sync([
                "network", "ls", "--format",
                "{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}",
            ])
            rows: List[list] = []
            if result.ok:
                for line in result.stdout.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 4:
                        parts.append("")
                    # Fetch subnet inline (best-effort)
                    isp = run_sync([
                        "network", "inspect", parts[0],
                        "--format", "{{range .IPAM.Config}}{{.Subnet}}{{end}}"
                    ], timeout=5)
                    parts.append(isp.stdout.strip()[:30] if isp.ok else "")
                    rows.append(parts[:5])

            def _upd():
                self._net_tree.delete(*self._net_tree.get_children())
                for r in rows:
                    self._net_tree.insert("", "end", values=r)
            self._root.after(0, _upd)
        safe_thread(_fetch)

    # ─────────────────────────────────────────
    #  VOLUMES
    # ─────────────────────────────────────────

    def vol_selected_name(self) -> Optional[str]:
        sel = self._vol_tree.selection()
        if not sel:
            return None
        vals = self._vol_tree.item(sel[0])["values"]
        return vals[0] if vals else None

    def vol_create(self, name: str) -> None:
        def _do():
            result = run_sync(["volume", "create", name])
            result.user_msg = f"Volume '{name}' created"
            self._write_result(self._write_vol, result, f"volume create {name}")
            if result.ok:
                self.refresh_volumes()
                self._refresh_dash()
        safe_thread(_do)

    def vol_inspect(self, name: str) -> None:
        def _do():
            result = run_sync(["volume", "inspect", name])
            self._write_vol(f"=== inspect {name} ===\n{result.output}\n\n")
        safe_thread(_do)

    def vol_remove(self, name: str) -> None:
        def _do():
            result = run_sync(["volume", "rm", name])
            result.user_msg = f"Volume '{name}' removed"
            self._write_result(self._write_vol, result, f"volume rm {name}")
            if result.ok:
                self.refresh_volumes()
                self._refresh_dash()
        safe_thread(_do)

    def vol_prune(self) -> None:
        def _do():
            result = run_sync(["volume", "prune", "-f"], timeout=60)
            result.user_msg = "Unused volumes pruned"
            self._write_result(self._write_vol, result, "volume prune")
            if result.ok:
                self.refresh_volumes()
                self._refresh_dash()
        safe_thread(_do)

    def refresh_volumes(self) -> None:
        def _fetch():
            result = run_sync([
                "volume", "ls", "--format",
                "{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}",
            ])

            def _upd():
                self._vol_tree.delete(*self._vol_tree.get_children())
                if not result.ok:
                    return
                for line in result.stdout.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 3:
                        parts.append("")
                    self._vol_tree.insert("", "end", values=parts[:3])
            self._root.after(0, _upd)
        safe_thread(_fetch)
