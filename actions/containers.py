"""
DockerDeck – actions/containers.py
Container tab actions: start, stop, restart, rename, cp, shell, remove, inspect.
"""

import tkinter as tk
from tkinter import messagebox

from docker_runner import run_docker, run_docker_stream
from validation import validate_container_name, ValidationError
from utils import COLORS, FONTS, safe_thread
from ui_components import console_write, ask_input, get_tree_widget


def get_selected_containers(containers_tree) -> list:
    """Return list of all selected container names (multi-select aware)."""
    tree = get_tree_widget(containers_tree)
    if not tree:
        return []
    return [tree.item(s)["values"][1] for s in tree.selection()]


def get_selected_container(root, containers_tree) -> str:
    """Return single selected container name, or None with a message."""
    names = get_selected_containers(containers_tree)
    if not names:
        messagebox.showinfo("Select Container", "Please select a container first.",
                            parent=root)
        return None
    return names[0]


def container_action(root, action: str, name: str, output_widget,
                     status_fn=None, success_fn=None) -> None:
    """Generic: run docker <action> <name> and write to output_widget."""
    def _do():
        if status_fn:
            status_fn(f"Running: docker {action} {name}")
        out, err, rc = run_docker([action, name])
        msg = out or err or f"{action} completed"
        root.after(0, lambda: console_write(
            output_widget, f"[{action} {name}]  rc={rc}\n{msg}\n\n"))
    safe_thread(_do)


def container_start(root, containers_tree, output_widget) -> None:
    for n in get_selected_containers(containers_tree):
        container_action(root, "start", n, output_widget)


def container_stop(root, containers_tree, output_widget) -> None:
    for n in get_selected_containers(containers_tree):
        container_action(root, "stop", n, output_widget)


def container_restart(root, containers_tree, output_widget) -> None:
    for n in get_selected_containers(containers_tree):
        container_action(root, "restart", n, output_widget)


def container_stop_all(root, containers_tree, output_widget) -> None:
    """Bulk stop all selected containers."""
    names = get_selected_containers(containers_tree)
    if not names:
        messagebox.showinfo("Select Containers",
                            "Select one or more containers first.", parent=root)
        return
    if not messagebox.askyesno("Stop All",
                                f"Stop {len(names)} container(s)?", parent=root):
        return
    def _do():
        for n in names:
            out, err, rc = run_docker(["stop", n])
            root.after(0, lambda n=n, out=out, err=err, rc=rc:
                console_write(output_widget,
                              f"[stop {n}] rc={rc} {out or err}\n"))
    safe_thread(_do)


def container_inspect(root, containers_tree, output_widget) -> None:
    n = get_selected_container(root, containers_tree)
    if not n:
        return
    def _do():
        out, err, _ = run_docker(["inspect", n])
        root.after(0, lambda: console_write(
            output_widget, f"=== inspect {n} ===\n{out or err}\n\n"))
    safe_thread(_do)


def container_rename(root, containers_tree, output_widget) -> None:
    n = get_selected_container(root, containers_tree)
    if not n:
        return
    new_name = ask_input(root, "Rename Container",
                         f"New name for '{n}':", n)
    if not new_name or new_name == n:
        return
    try:
        new_name = validate_container_name(new_name)
    except ValidationError as e:
        messagebox.showerror("Invalid Name", str(e), parent=root)
        return
    def _do():
        out, err, rc = run_docker(["rename", n, new_name])
        root.after(0, lambda: console_write(
            output_widget,
            f"[rename {n} → {new_name}] rc={rc} {out or err}\n\n"))
    safe_thread(_do)


def container_cp(root, containers_tree, output_widget) -> None:
    """Open a dialog to run docker cp."""
    n = get_selected_container(root, containers_tree)
    if not n:
        return
    dlg = tk.Toplevel(root)
    dlg.title("Copy File (docker cp)")
    dlg.geometry("500x210")
    dlg.configure(bg=COLORS["bg_dark"])
    dlg.grab_set()

    tk.Label(dlg, text="docker cp  — source and destination",
             font=FONTS["heading"],
             bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(padx=16, pady=(14, 6))
    tk.Label(dlg, text="Use  container:path  for container-side paths",
             font=FONTS["ui_sm"],
             bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack()

    entries = {}
    for lbl, default, key in [
        ("Source:", f"{n}:/path/to/file", "src"),
        ("Dest:",   "/local/path",        "dst"),
    ]:
        row = tk.Frame(dlg, bg=COLORS["bg_dark"])
        row.pack(fill="x", padx=16, pady=4)
        tk.Label(row, text=lbl, width=8, font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(side="left")
        e = tk.Entry(row, font=FONTS["mono_sm"],
                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                     insertbackground=COLORS["accent"],
                     relief="flat", bd=3,
                     highlightbackground=COLORS["border"], highlightthickness=1)
        e.insert(0, default)
        e.pack(side="left", fill="x", expand=True)
        entries[key] = e

    def do_cp():
        src = entries["src"].get().strip()
        dst = entries["dst"].get().strip()
        dlg.destroy()
        if src and dst:
            def _do():
                out, err, rc = run_docker(["cp", src, dst])
                root.after(0, lambda: console_write(
                    output_widget,
                    f"[cp {src} → {dst}] rc={rc}\n{out or err}\n\n"))
            safe_thread(_do)

    tk.Button(dlg, text="Copy", font=FONTS["ui"],
              bg=COLORS["accent"], fg="white",
              relief="flat", bd=0, padx=16, pady=6,
              command=do_cp).pack(pady=10)


def container_shell(root, containers_tree) -> None:
    """Show the exact exec command to copy and run in a terminal."""
    n = get_selected_container(root, containers_tree)
    if not n:
        return
    cmd = f"docker exec -it {n} sh"
    dlg = tk.Toplevel(root)
    dlg.title("Open Shell")
    dlg.geometry("540x200")
    dlg.configure(bg=COLORS["bg_dark"])
    dlg.grab_set()

    tk.Label(dlg, text="Run this command in your terminal:",
             font=FONTS["heading"],
             bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(padx=20, pady=(16, 8))

    cmd_var = tk.StringVar(value=cmd)
    e = tk.Entry(dlg, textvariable=cmd_var, font=FONTS["mono"],
                 bg=COLORS["bg_input"], fg=COLORS["accent"],
                 insertbackground=COLORS["accent"],
                 relief="flat", bd=4,
                 highlightbackground=COLORS["border"], highlightthickness=1,
                 readonlybackground=COLORS["bg_input"], state="readonly")
    e.pack(fill="x", padx=20)

    def copy_cmd():
        root.clipboard_clear()
        root.clipboard_append(cmd)
        copy_btn.configure(text="✓ Copied!")
        dlg.after(1500, lambda: copy_btn.configure(text="📋 Copy to Clipboard"))

    copy_btn = tk.Button(dlg, text="📋 Copy to Clipboard",
                         font=FONTS["ui"],
                         bg=COLORS["accent"], fg="white",
                         relief="flat", bd=0, padx=16, pady=8,
                         cursor="hand2", command=copy_cmd)
    copy_btn.pack(pady=12)

    tk.Label(dlg, text=f"Or try:  docker exec -it {n} bash",
             font=FONTS["mono_sm"],
             bg=COLORS["bg_dark"], fg=COLORS["text_dim"]).pack()


def container_remove(root, containers_tree, output_widget) -> None:
    names = get_selected_containers(containers_tree)
    if not names:
        messagebox.showinfo("Select Container",
                            "Please select container(s) first.", parent=root)
        return
    if messagebox.askyesno("Remove",
                            f"Remove {len(names)} container(s)?\n{', '.join(names)}",
                            parent=root):
        def _do():
            for n in names:
                out, err, rc = run_docker(["rm", "-f", n])
                root.after(0, lambda n=n, out=out, err=err, rc=rc:
                    console_write(output_widget,
                                  f"[rm {n}] rc={rc} {out or err}\n"))
        safe_thread(_do)
