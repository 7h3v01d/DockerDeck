"""
DockerDeck – actions/network_volume.py
Network and Volume tab actions.
"""

from tkinter import messagebox
from docker_runner import run_docker
from utils import safe_thread
from ui_components import console_write, get_tree_widget


# ── NETWORKS ──────────────────────────────────

def network_create(root, name_entry, output_widget) -> None:
    name = name_entry.get().strip()
    if not name:
        return
    def _do():
        out, err, rc = run_docker(["network", "create", name])
        root.after(0, lambda: console_write(
            output_widget,
            f"[network create {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def network_inspect(root, networks_tree, output_widget) -> None:
    tree = get_tree_widget(networks_tree)
    sel = tree.selection() if tree else []
    if not sel:
        return
    name = tree.item(sel[0])["values"][1]
    def _do():
        out, err, _ = run_docker(["network", "inspect", name])
        root.after(0, lambda: console_write(
            output_widget, f"=== inspect {name} ===\n{out or err}\n\n"))
    safe_thread(_do)


def network_remove(root, networks_tree, output_widget) -> None:
    tree = get_tree_widget(networks_tree)
    sel = tree.selection() if tree else []
    if not sel:
        return
    name = tree.item(sel[0])["values"][1]
    if messagebox.askyesno("Remove Network",
                            f"Remove network '{name}'?", parent=root):
        def _do():
            out, err, rc = run_docker(["network", "rm", name])
            root.after(0, lambda: console_write(
                output_widget,
                f"[network rm {name}]  rc={rc}\n{out or err}\n\n"))
        safe_thread(_do)


def network_prune(root, output_widget) -> None:
    if messagebox.askyesno("Prune Networks",
                            "Remove all unused networks?", parent=root):
        def _do():
            out, err, rc = run_docker(["network", "prune", "-f"])
            root.after(0, lambda: console_write(
                output_widget, f"[network prune]\n{out or err}\n\n"))
        safe_thread(_do)


# ── VOLUMES ───────────────────────────────────

def volume_create(root, name_entry, output_widget) -> None:
    name = name_entry.get().strip()
    if not name:
        return
    def _do():
        out, err, rc = run_docker(["volume", "create", name])
        root.after(0, lambda: console_write(
            output_widget,
            f"[volume create {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def volume_inspect(root, volumes_tree, output_widget) -> None:
    tree = get_tree_widget(volumes_tree)
    sel = tree.selection() if tree else []
    if not sel:
        return
    name = tree.item(sel[0])["values"][0]
    def _do():
        out, err, _ = run_docker(["volume", "inspect", name])
        root.after(0, lambda: console_write(
            output_widget, f"=== inspect {name} ===\n{out or err}\n\n"))
    safe_thread(_do)


def volume_remove(root, volumes_tree, output_widget) -> None:
    tree = get_tree_widget(volumes_tree)
    sel = tree.selection() if tree else []
    if not sel:
        return
    name = tree.item(sel[0])["values"][0]
    if messagebox.askyesno("Remove Volume",
                            f"Remove volume '{name}'? Data will be lost!",
                            parent=root):
        def _do():
            out, err, rc = run_docker(["volume", "rm", name])
            root.after(0, lambda: console_write(
                output_widget,
                f"[volume rm {name}]  rc={rc}\n{out or err}\n\n"))
        safe_thread(_do)


def volume_prune(root, output_widget) -> None:
    if messagebox.askyesno("Prune Volumes",
                            "Remove all unused volumes? Data will be lost!",
                            parent=root):
        def _do():
            out, err, rc = run_docker(["volume", "prune", "-f"])
            root.after(0, lambda: console_write(
                output_widget, f"[volume prune]\n{out or err}\n\n"))
        safe_thread(_do)
