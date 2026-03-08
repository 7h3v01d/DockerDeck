"""
DockerDeck – app.py
Main application window. All tkinter lives here.
Action modules contain zero tkinter — they are pure logic called from here.
"""

import os
import sys
import json
import time
import threading
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from utils import (
    __version__, COLORS, FONTS,
    safe_thread, set_error_callback,
    log_notification, get_notification_log,
    COMPOSE_TEMPLATE, DOCKERFILE_TEMPLATE, Debouncer,
)
from docker_runner import run_docker, run_docker_stream, docker_available
from validation import validate_image_name, validate_container_name, ValidationError
from ui_components import (
    make_card, make_console, make_tree, get_tree_widget,
    make_stat_card, console_write, ask_input,
)
from actions.containers import (
    get_selected_names,
    container_start, container_stop, container_restart,
    container_stop_all, container_inspect,
    container_rename_exec, container_cp_exec,
    container_remove, get_shell_command,
)
from actions.images import (
    image_pull_exec, image_inspect_exec,
    image_remove_exec, image_prune_exec,
)
from actions.deploy import (
    FIELD_VALIDATORS, validate_field, validate_all_fields,
    build_run_command, deploy_exec,
    load_presets, save_presets, get_field_values, PRESETS_PATH,
)
from actions.network_volume import (
    network_create, network_inspect, network_remove, network_prune,
    volume_create, volume_inspect, volume_remove, volume_prune,
)
from actions.registry import (
    registry_login_exec, registry_logout_exec,
    registry_push_exec, registry_pull_exec,
)


class DockerDeck(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(f"DockerDeck v{__version__}  —  Docker Package & Deploy Suite")
        self.geometry("1280x840")
        self.minsize(960, 640)
        self.configure(bg=COLORS["bg_dark"])

        set_error_callback(self._show_error_notification)

        self.selected_container = tk.StringVar()
        self.selected_image     = tk.StringVar()
        self.log_stop_event     = threading.Event()
        self._stats_stop_event  = threading.Event()
        self._events_stop       = threading.Event()

        self.presets = load_presets()

        self._build_ui()
        self._check_docker()
        self._check_for_updates()
        self._start_events_watcher()
        self._setup_shortcuts()
        self._refresh_all()

    # ─────────────────────────────── BUILD UI ──

    def _build_ui(self):
        self._build_header()
        self._build_notification_bar()
        self._build_status_bar()
        self._build_notebook()

    def _build_header(self):
        hdr = tk.Frame(self, bg=COLORS["bg_card"], height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="🐳  DockerDeck",
                 font=("Segoe UI", 17, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["accent"]).pack(
                     side="left", padx=20, pady=12)

        self.docker_status_label = tk.Label(
            hdr, text="● Checking…", font=FONTS["ui_sm"],
            bg=COLORS["bg_card"], fg=COLORS["accent_orange"])
        self.docker_status_label.pack(side="left", padx=6)

        for txt, cmd, color in [
            ("⟳  Refresh",  self._refresh_all,     COLORS["text_primary"]),
            ("ℹ  About",    self._show_about,       COLORS["text_secondary"]),
            ("📋 Log",      self._show_log_history, COLORS["text_secondary"]),
        ]:
            tk.Button(hdr, text=txt,
                      font=FONTS["ui_sm"], bg=COLORS["bg_hover"],
                      fg=color, relief="flat", bd=0, padx=10,
                      cursor="hand2", activebackground=COLORS["border"],
                      command=cmd).pack(side="right", padx=6, pady=12)

        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x")

    # ─────────────────────────── NOTIFICATION BAR ──

    def _build_notification_bar(self):
        self._notif_frame = tk.Frame(self, bg="#1a1000")
        self._notif_frame.pack(fill="x")
        self._notif_frame.pack_forget()

        inner = tk.Frame(self._notif_frame, bg="#1a1000")
        inner.pack(fill="x", padx=12, pady=4)

        self._notif_icon = tk.Label(inner, text="⚠", font=FONTS["ui"],
                                    bg="#1a1000", fg=COLORS["accent_orange"])
        self._notif_icon.pack(side="left", padx=(0, 6))

        self._notif_label = tk.Label(inner, text="", font=FONTS["ui_sm"],
                                     bg="#1a1000", fg=COLORS["text_primary"],
                                     anchor="w", justify="left", wraplength=900)
        self._notif_label.pack(side="left", fill="x", expand=True)

        tk.Button(inner, text="✕", font=FONTS["ui_sm"],
                  bg="#1a1000", fg=COLORS["text_secondary"],
                  relief="flat", bd=0, cursor="hand2",
                  command=self._hide_notification).pack(side="right")

    def _show_error_notification(self, message: str,
                                  icon: str = "⚠", color: str = None):
        color = color or COLORS["accent_orange"]
        level = "success" if icon == "✓" else "error"
        log_notification(message, level)
        def _show():
            self._notif_icon.configure(text=icon, fg=color)
            self._notif_label.configure(text=message)
            self._notif_frame.pack(fill="x")
        self.after(0, _show)

    def _show_success_notification(self, message: str):
        self._show_error_notification(message, icon="✓",
                                       color=COLORS["accent_green"])

    def _hide_notification(self):
        self._notif_frame.pack_forget()

    def _show_log_history(self):
        dlg = tk.Toplevel(self)
        dlg.title("Notification Log History")
        dlg.geometry("700x450")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="📋  Notification History  (newest first)",
                 font=FONTS["heading"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))

        txt = scrolledtext.ScrolledText(
            dlg, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            relief="flat", bd=4,
            highlightbackground=COLORS["border"], highlightthickness=1)
        txt.pack(fill="both", expand=True, padx=12, pady=8)

        entries = get_notification_log()
        txt.insert("end", "(no log entries yet)\n" if not entries else
                   "".join(f"[{e['ts']}]  {'✓' if e['level']=='success' else '⚠'}  {e['msg']}\n"
                           for e in entries))
        txt.configure(state="disabled")

        tk.Button(dlg, text="Close", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=8)

    def _build_status_bar(self):
        self.status_bar = tk.Label(
            self, text="Ready", font=FONTS["mono_sm"],
            bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
            anchor="w", padx=12)
        self.status_bar.pack(fill="x", side="bottom")
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x", side="bottom")

    def _build_notebook(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Custom.TNotebook",
                        background=COLORS["bg_dark"],
                        borderwidth=0, tabmargins=[0, 0, 0, 0])
        style.configure("Custom.TNotebook.Tab",
                        background=COLORS["bg_card"],
                        foreground=COLORS["tab_inactive"],
                        font=FONTS["ui"], padding=[18, 8], borderwidth=0)
        style.map("Custom.TNotebook.Tab",
                  background=[("selected", COLORS["bg_dark"])],
                  foreground=[("selected", COLORS["tab_active"])],
                  expand=[("selected", [0, 0, 0, 0])])
        # Style ttk widgets for consistent dark theme
        style.configure("DockerCombo.TCombobox",
                        fieldbackground=COLORS["bg_input"],
                        background=COLORS["bg_hover"],
                        foreground=COLORS["text_primary"],
                        arrowcolor=COLORS["text_secondary"],
                        selectbackground=COLORS["accent"],
                        selectforeground="white")
        style.configure("DockerSpin.TSpinbox",
                        fieldbackground=COLORS["bg_input"],
                        background=COLORS["bg_hover"],
                        foreground=COLORS["text_primary"],
                        arrowcolor=COLORS["text_secondary"])

        self.nb = ttk.Notebook(self, style="Custom.TNotebook")
        self.nb.pack(fill="both", expand=True)

        self._build_tab_dashboard()
        self._build_tab_containers()
        self._build_tab_images()
        self._build_tab_deploy()
        self._build_tab_compose()
        self._build_tab_logs()
        self._build_tab_network()
        self._build_tab_volumes()
        self._build_tab_advanced()

    # ─────────────────────────── SHORTCUTS ──

    def _setup_shortcuts(self):
        self.bind_all("<Control-r>", lambda _: self._refresh_all())
        self.bind_all("<F5>",        lambda _: self._refresh_all())

    # ─────────────────────────── DASHBOARD TAB ──

    def _build_tab_dashboard(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🏠  Dashboard  ")

        tk.Label(frame, text="System Overview", font=FONTS["title"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(
                     anchor="w", padx=24, pady=(18, 6))
        tk.Label(frame, text="Real-time status of your Docker environment",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(anchor="w", padx=24, pady=(0, 16))

        stats_row = tk.Frame(frame, bg=COLORS["bg_dark"])
        stats_row.pack(fill="x", padx=24, pady=(0, 16))

        self.stat_cards = {}
        for key, label, val, color in [
            ("containers_running", "▶  Running",  "0", COLORS["accent_green"]),
            ("containers_stopped", "■  Stopped",  "0", COLORS["accent_red"]),
            ("images_total",       "🗂  Images",   "0", COLORS["accent"]),
            ("volumes_total",      "💾  Volumes",  "0", COLORS["accent_purple"]),
            ("networks_total",     "🌐  Networks", "0", COLORS["accent_cyan"]),
        ]:
            card = make_stat_card(stats_row, label, val, color)
            card.pack(side="left", padx=(0, 12), fill="x", expand=True)
            self.stat_cards[key] = card

        cols = tk.Frame(frame, bg=COLORS["bg_dark"])
        cols.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        cols.rowconfigure(0, weight=1)

        left = make_card(cols, "⚡  Active Containers")
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        self.dash_containers_text = make_console(left, height=12)
        self.dash_containers_text.pack(fill="both", expand=True, padx=8, pady=8)

        right = make_card(cols, "🚀  Quick Actions")
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        for txt, cmd, color in [
            ("▶  Start Container",    self._quick_start,   COLORS["accent_green"]),
            ("■  Stop Container",     self._quick_stop,    COLORS["accent_red"]),
            ("🔄  Restart Container", self._quick_restart, COLORS["accent_orange"]),
            ("🗑  Remove Stopped",    self._prune_stopped, COLORS["accent_red"]),
            ("📦  Pull Image",        self._quick_pull,    COLORS["accent"]),
            ("🧹  System Prune",      self._system_prune,  COLORS["accent_orange"]),
        ]:
            tk.Button(right, text=txt, font=FONTS["ui"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=16, pady=9,
                      anchor="w", cursor="hand2",
                      activebackground=COLORS["border"],
                      activeforeground=color,
                      command=cmd).pack(fill="x", padx=12, pady=3)

    # ─────────────────────────── CONTAINERS TAB ──

    def _build_tab_containers(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  📦  Containers  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)

        tk.Label(tb, text="Containers", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.show_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(tb, text="Show all (incl. stopped)",
                       variable=self.show_all_var,
                       font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                       fg=COLORS["text_secondary"],
                       selectcolor=COLORS["bg_card"],
                       activebackground=COLORS["bg_dark"],
                       command=self._refresh_containers).pack(side="left", padx=16)

        for txt, cmd, color in [
            ("▶ Start",      self._c_start,      COLORS["accent_green"]),
            ("■ Stop",       self._c_stop,       COLORS["accent_red"]),
            ("🔄 Restart",   self._c_restart,    COLORS["accent_orange"]),
            ("✏ Rename",     self._c_rename,     COLORS["accent_purple"]),
            ("📂 Copy File", self._c_cp,         COLORS["accent"]),
            ("📋 Inspect",   self._c_inspect,    COLORS["accent"]),
            ("🖥 Shell Cmd", self._c_shell,      COLORS["accent_purple"]),
            ("⛔ Stop All",  self._c_stop_all,   COLORS["accent_red"]),
            ("🗑 Remove",    self._c_remove,     COLORS["accent_red"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=2)

        cols_cfg = [
            ("ID", 80), ("Name", 160), ("Image", 200),
            ("Status", 100), ("Ports", 180), ("Created", 120),
        ]
        self.containers_tree = make_tree(frame, cols_cfg, multiselect=True)
        self.containers_tree.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        get_tree_widget(self.containers_tree).bind(
            "<<TreeviewSelect>>", self._on_container_select)

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.containers_output = make_console(out_card, height=5)
        self.containers_output.pack(fill="x", padx=8, pady=8)

        self._refresh_containers()

    # ── container action helpers (UI layer — handles confirm dialogs) ──

    def _c_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.containers_output, text, clear))

    def _c_names(self) -> list:
        tree = get_tree_widget(self.containers_tree)
        return get_selected_names(tree) if tree else []

    def _c_one(self) -> str:
        names = self._c_names()
        if not names:
            messagebox.showinfo("Select Container",
                                "Please select a container first.")
            return None
        return names[0]

    def _c_start(self):
        names = self._c_names()
        if names:
            container_start(self, names, self._c_output)

    def _c_stop(self):
        names = self._c_names()
        if names:
            container_stop(self, names, self._c_output)

    def _c_restart(self):
        names = self._c_names()
        if names:
            container_restart(self, names, self._c_output)

    def _c_stop_all(self):
        names = self._c_names()
        if not names:
            messagebox.showinfo("Select Containers",
                                "Select one or more containers first.")
            return
        if messagebox.askyesno("Stop All",
                                f"Stop {len(names)} container(s)?"):
            container_stop_all(self, names, self._c_output)

    def _c_inspect(self):
        n = self._c_one()
        if n:
            container_inspect(self, n, self._c_output)

    def _c_rename(self):
        n = self._c_one()
        if not n:
            return
        new_name = ask_input(self, "Rename Container",
                             f"New name for '{n}':", n)
        if not new_name or new_name == n:
            return
        ok, err = True, ""
        try:
            validate_container_name(new_name)
        except ValidationError as e:
            ok, err = False, str(e)
        if not ok:
            messagebox.showerror("Invalid Name", err)
            return
        container_rename_exec(self, n, new_name, self._c_output)

    def _c_cp(self):
        n = self._c_one()
        if not n:
            return
        dlg = tk.Toplevel(self)
        dlg.title("Copy File (docker cp)")
        dlg.geometry("500x210")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="docker cp  — source and destination",
                 font=FONTS["heading"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(padx=16, pady=(14, 6))
        tk.Label(dlg, text="Use  container:path  for container-side paths",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack()

        entries = {}
        for lbl, default, key in [
            ("Source:", f"{n}:/path/to/file", "src"),
            ("Dest:",   "/local/path",        "dst"),
        ]:
            row = tk.Frame(dlg, bg=COLORS["bg_dark"])
            row.pack(fill="x", padx=16, pady=4)
            tk.Label(row, text=lbl, width=8, font=FONTS["ui_sm"],
                     bg=COLORS["bg_dark"],
                     fg=COLORS["text_secondary"]).pack(side="left")
            e = tk.Entry(row, font=FONTS["mono_sm"],
                         bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                         insertbackground=COLORS["accent"], relief="flat", bd=3,
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            e.insert(0, default)
            e.pack(side="left", fill="x", expand=True)
            entries[key] = e

        def do_cp():
            src = entries["src"].get().strip()
            dst = entries["dst"].get().strip()
            dlg.destroy()
            if src and dst:
                container_cp_exec(self, src, dst, self._c_output)

        tk.Button(dlg, text="Copy", font=FONTS["ui"],
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=6,
                  command=do_cp).pack(pady=10)

    def _c_shell(self):
        n = self._c_one()
        if not n:
            return
        cmd = get_shell_command(n)
        dlg = tk.Toplevel(self)
        dlg.title("Open Shell")
        dlg.geometry("540x200")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="Run this command in your terminal:",
                 font=FONTS["heading"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(padx=20, pady=(16, 8))

        e = tk.Entry(dlg, font=FONTS["mono"],
                     bg=COLORS["bg_input"], fg=COLORS["accent"],
                     insertbackground=COLORS["accent"], relief="flat", bd=4,
                     highlightbackground=COLORS["border"], highlightthickness=1,
                     readonlybackground=COLORS["bg_input"], state="readonly")
        e.configure(state="normal")
        e.insert(0, cmd)
        e.configure(state="readonly")
        e.pack(fill="x", padx=20)

        def copy_cmd():
            self.clipboard_clear()
            self.clipboard_append(cmd)
            copy_btn.configure(text="✓ Copied!")
            dlg.after(1500, lambda: copy_btn.configure(
                text="📋 Copy to Clipboard"))

        copy_btn = tk.Button(dlg, text="📋 Copy to Clipboard",
                             font=FONTS["ui"], bg=COLORS["accent"], fg="white",
                             relief="flat", bd=0, padx=16, pady=8,
                             cursor="hand2", command=copy_cmd)
        copy_btn.pack(pady=12)
        tk.Label(dlg, text=f"Or try:  docker exec -it {n} bash",
                 font=FONTS["mono_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_dim"]).pack()

    def _c_remove(self):
        names = self._c_names()
        if not names:
            messagebox.showinfo("Select Container",
                                "Please select container(s) first.")
            return
        if messagebox.askyesno(
            "Remove",
            f"Remove {len(names)} container(s)?\n{', '.join(names)}"
        ):
            container_remove(self, names, self._c_output)

    # ─────────────────────────── IMAGES TAB ──

    def _build_tab_images(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🗂  Images  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Images", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self.pull_entry = tk.Entry(
            tb, font=FONTS["mono"], width=28,
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat", bd=4,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.pull_entry.insert(0, "image:tag")
        self.pull_entry.pack(side="right", padx=(4, 0))
        tk.Label(tb, text="Pull:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="right")

        for txt, cmd, color in [
            ("⬇ Pull",    self._i_pull,    COLORS["accent"]),
            ("📋 Inspect", self._i_inspect, COLORS["accent"]),
            ("▶ Run",     self._i_run,     COLORS["accent_green"]),
            ("🗑 Remove",  self._i_remove,  COLORS["accent_red"]),
            ("🧹 Prune",   self._i_prune,   COLORS["accent_orange"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        cols_cfg = [
            ("Repository", 240), ("Tag", 120), ("Image ID", 120),
            ("Size", 90), ("Created", 150),
        ]
        self.images_tree = make_tree(frame, cols_cfg)
        self.images_tree.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        get_tree_widget(self.images_tree).bind(
            "<<TreeviewSelect>>", self._on_image_select)

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.images_output = make_console(out_card, height=5)
        self.images_output.pack(fill="x", padx=8, pady=8)

        self._refresh_images()

    def _i_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.images_output, text, clear))

    def _i_pull(self):
        raw = self.pull_entry.get().strip()
        try:
            image = validate_image_name(raw)
        except ValidationError as e:
            messagebox.showerror("Invalid Image Name", str(e))
            return
        image_pull_exec(self, image, self._i_output, self._set_status)

    def _i_inspect(self):
        tree = get_tree_widget(self.images_tree)
        sel  = tree.selection() if tree else []
        if not sel:
            messagebox.showinfo("Select Image", "Please select an image.")
            return
        image_inspect_exec(self, tree.item(sel[0])["values"][2],
                            self._i_output)

    def _i_run(self):
        """Pre-fill Deploy tab with selected image and switch to it."""
        tree = get_tree_widget(self.images_tree)
        sel  = tree.selection() if tree else []
        if not sel:
            messagebox.showinfo("Select Image", "Please select an image.")
            return
        vals = tree.item(sel[0])["values"]
        img  = f"{vals[0]}:{vals[1]}"
        self.deploy_fields["deploy_image"].delete(0, "end")
        self.deploy_fields["deploy_image"].insert(0, img)
        self._validate_deploy_field("deploy_image")
        self.nb.select(3)

    def _i_remove(self):
        tree = get_tree_widget(self.images_tree)
        sel  = tree.selection() if tree else []
        if not sel:
            messagebox.showinfo("Select Image", "Please select an image.")
            return
        vals = tree.item(sel[0])["values"]
        if messagebox.askyesno("Remove Image",
                                f"Remove image '{vals[0]}:{vals[1]}'?"):
            image_remove_exec(self, vals[2], f"{vals[0]}:{vals[1]}",
                               self._i_output)

    def _i_prune(self):
        if messagebox.askyesno("Prune Images",
                                "Remove all dangling images?"):
            image_prune_exec(self, self._i_output)

    # ─────────────────────────── DEPLOY TAB ──

    def _build_tab_deploy(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🚀  Deploy  ")

        pane = tk.Frame(frame, bg=COLORS["bg_dark"])
        pane.pack(fill="both", expand=True, padx=16, pady=12)
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=2)
        pane.rowconfigure(0, weight=1)

        form_card = make_card(pane, "🛠  Deploy Configuration")
        form_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        fields_cfg = [
            ("Image Name:",     "deploy_image",   "nginx:latest"),
            ("Container Name:", "deploy_name",    "my-container"),
            ("Port Mapping:",   "deploy_ports",   "8080:80"),
            ("Env Variables:",  "deploy_env",     "KEY=value"),
            ("Volume Mount:",   "deploy_volumes", "./data:/data"),
            ("Network:",        "deploy_network", "bridge"),
            ("Restart Policy:", "deploy_restart", "unless-stopped"),
            ("Extra Args:",     "deploy_extra",   "--memory 512m"),
        ]
        self.deploy_fields     = {}
        self._deploy_indicators = {}
        self._deploy_err_labels = {}
        self._field_debouncers  = {}

        for label, key, placeholder in fields_cfg:
            row = tk.Frame(form_card, bg=COLORS["bg_card"])
            row.pack(fill="x", padx=12, pady=2)

            lbl_row = tk.Frame(row, bg=COLORS["bg_card"])
            lbl_row.pack(fill="x")
            tk.Label(lbl_row, text=label, font=FONTS["ui_sm"], width=16,
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
            dot = tk.Label(lbl_row, text="●", font=FONTS["ui_sm"],
                           bg=COLORS["bg_card"], fg=COLORS["text_dim"])
            dot.pack(side="right", padx=(4, 0))
            e = tk.Entry(lbl_row, font=FONTS["mono_sm"], width=20,
                         bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                         insertbackground=COLORS["accent"],
                         relief="flat", bd=3,
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            e.insert(0, placeholder)
            e.pack(side="right", fill="x", expand=True)

            # Error label below field
            err_lbl = tk.Label(row, text="", font=("Segoe UI", 8),
                               bg=COLORS["bg_card"],
                               fg=COLORS["accent_red"],
                               anchor="e")
            err_lbl.pack(fill="x")

            self.deploy_fields[key]      = e
            self._deploy_indicators[key] = dot
            self._deploy_err_labels[key] = err_lbl

            db = Debouncer(self,
                           lambda k=key: self._validate_deploy_field(k), 250)
            self._field_debouncers[key] = db
            e.bind("<KeyRelease>", lambda ev, k=key: self._field_debouncers[k]())
            e.bind("<FocusOut>",   lambda ev, k=key: self._validate_deploy_field(k))

        self.deploy_detach = tk.BooleanVar(value=True)
        tk.Checkbutton(form_card, text="Run detached (-d)",
                       variable=self.deploy_detach,
                       font=FONTS["ui_sm"],
                       bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                       selectcolor=COLORS["bg_input"],
                       activebackground=COLORS["bg_card"]).pack(
                           anchor="w", padx=12, pady=4)

        # Presets
        preset_row = tk.Frame(form_card, bg=COLORS["bg_card"])
        preset_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(preset_row, text="Preset:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_card"],
                 fg=COLORS["text_secondary"]).pack(side="left")
        self.preset_var   = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            preset_row, textvariable=self.preset_var,
            font=FONTS["mono_sm"], width=16,
            style="DockerCombo.TCombobox")
        self.preset_combo.pack(side="left", padx=4)
        self._refresh_presets_combo()

        for txt, cmd, color in [
            ("💾 Save", self._preset_save,   COLORS["accent"]),
            ("📂 Load", self._preset_load,   COLORS["accent"]),
            ("🗑 Del",  self._preset_delete, COLORS["accent_red"]),
        ]:
            tk.Button(preset_row, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=8, pady=4,
                      cursor="hand2", command=cmd).pack(side="left", padx=2)

        tk.Button(form_card, text="🚀  Deploy Container",
                  font=("Segoe UI", 11, "bold"),
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=10,
                  cursor="hand2",
                  command=self._deploy_container).pack(
                      fill="x", padx=12, pady=8)

        # Preview + copy
        preview_card = make_card(form_card, "Preview Command")
        preview_card.pack(fill="x", padx=12, pady=(0, 6))
        copy_row = tk.Frame(preview_card, bg=COLORS["bg_card"])
        copy_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Button(copy_row, text="📋 Copy", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=3,
                  cursor="hand2",
                  command=self._copy_deploy_command).pack(side="right")
        self.deploy_preview = make_console(preview_card, height=3)
        self.deploy_preview.pack(fill="x", padx=8, pady=8)

        for key in self.deploy_fields:
            self._validate_deploy_field(key)

        right_card = make_card(pane, "📡  Deploy Output")
        right_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        self.deploy_output = make_console(right_card, height=999)
        self.deploy_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _deploy_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.deploy_output, text, clear))

    def _validate_deploy_field(self, key: str) -> bool:
        e   = self.deploy_fields[key]
        dot = self._deploy_indicators[key]
        err = self._deploy_err_labels[key]
        val = e.get().strip()
        ok, msg = validate_field(key, val)
        if ok:
            dot.configure(fg=COLORS["accent_green"] if val else COLORS["text_dim"])
            e.configure(highlightbackground=COLORS["border"])
            err.configure(text="")
        else:
            dot.configure(fg=COLORS["accent_red"])
            e.configure(highlightbackground=COLORS["accent_red"])
            # Show truncated error inline
            short = msg.split("\n")[0][:60]
            err.configure(text=short)
        self._update_deploy_preview()
        return ok

    def _update_deploy_preview(self):
        try:
            fv  = {k: e.get() for k, e in self.deploy_fields.items()}
            cmd = build_run_command(fv, self.deploy_detach.get())
            console_write(self.deploy_preview, " ".join(cmd), clear=True)
        except Exception:
            pass

    def _copy_deploy_command(self):
        try:
            fv  = {k: e.get() for k, e in self.deploy_fields.items()}
            cmd = build_run_command(fv, self.deploy_detach.get())
            self.clipboard_clear()
            self.clipboard_append(" ".join(cmd))
            self._show_success_notification("Command copied to clipboard.")
        except Exception:
            pass

    def _deploy_container(self):
        fv = {k: e.get() for k, e in self.deploy_fields.items()}
        ok, err_msg = validate_all_fields(fv)
        if not ok:
            messagebox.showerror("Validation Error", err_msg)
            return
        try:
            cmd = build_run_command(fv, self.deploy_detach.get())
        except ValidationError as e:
            messagebox.showerror("Validation Error", str(e))
            return

        if not messagebox.askyesno(
            "Confirm Deploy",
            f"Execute this command?\n\n{' '.join(cmd)}\n\n"
            "Ensure you trust all input values."
        ):
            return
        deploy_exec(self, cmd[1:], self._deploy_output, self._set_status)

    def _refresh_presets_combo(self):
        if hasattr(self, "preset_combo"):
            self.preset_combo["values"] = list(self.presets.keys())

    def _preset_save(self):
        name = ask_input(self, "Save Preset", "Preset name:", "")
        if not name:
            return
        fv = {k: e.get() for k, e in self.deploy_fields.items()}
        fv["__detach"] = self.deploy_detach.get()
        self.presets[name] = fv
        try:
            save_presets(self.presets)
            self._refresh_presets_combo()
            self.preset_var.set(name)
            self._show_success_notification(f"Preset '{name}' saved.")
        except Exception as e:
            messagebox.showerror("Preset Error", f"Could not save: {e}")

    def _preset_load(self):
        name = self.preset_var.get()
        if name not in self.presets:
            messagebox.showinfo("Presets",
                                "Select a preset from the dropdown first.")
            return
        data = self.presets[name]
        for k, e in self.deploy_fields.items():
            e.delete(0, "end")
            e.insert(0, data.get(k, ""))
            self._validate_deploy_field(k)
        self.deploy_detach.set(data.get("__detach", True))

    def _preset_delete(self):
        name = self.preset_var.get()
        if name in self.presets:
            del self.presets[name]
            try:
                save_presets(self.presets)
            except Exception:
                pass
            self._refresh_presets_combo()
            self.preset_var.set("")

    # ─────────────────────────── COMPOSE TAB ──

    def _build_tab_compose(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🎼  Compose  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Docker Compose", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self.compose_path = tk.StringVar(value="docker-compose.yml")
        tk.Entry(tb, textvariable=self.compose_path,
                 font=FONTS["mono_sm"], width=30,
                 bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                 insertbackground=COLORS["accent"],
                 relief="flat", bd=3,
                 highlightbackground=COLORS["border"],
                 highlightthickness=1).pack(side="right", padx=(4, 0))
        tk.Label(tb, text="File:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="right")
        tk.Button(tb, text="📂 Browse", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=5,
                  cursor="hand2",
                  command=self._browse_compose).pack(side="right", padx=3)

        pane = tk.Frame(frame, bg=COLORS["bg_dark"])
        pane.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)

        left = make_card(pane, "📝  Compose File Editor")
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        self.compose_editor = scrolledtext.ScrolledText(
            left, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"],
            relief="flat", bd=4, wrap="none",
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.compose_editor.insert("1.0", COMPOSE_TEMPLATE)
        self.compose_editor.pack(fill="both", expand=True, padx=8, pady=8)

        editor_btns = tk.Frame(left, bg=COLORS["bg_card"])
        editor_btns.pack(fill="x", padx=8, pady=(0, 8))
        for txt, cmd, color in [
            ("💾 Save",  self._compose_save,    COLORS["accent"]),
            ("📂 Load",  self._browse_compose,  COLORS["accent"]),
            ("🗑 Clear", self._compose_clear,   COLORS["accent_red"]),
        ]:
            tk.Button(editor_btns, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        right = make_card(pane, "⚙️  Compose Actions")
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        for label, args, color in [
            ("⬆  Up (start all)",    ["compose", "up", "-d"],             COLORS["accent_green"]),
            ("⬆  Up (with build)",   ["compose", "up", "-d", "--build"],  COLORS["accent_green"]),
            ("⬇  Down (stop all)",   ["compose", "down"],                 COLORS["accent_red"]),
            ("⬇  Down (rm volumes)", ["compose", "down", "-v"],           COLORS["accent_red"]),
            ("🔄  Restart",          ["compose", "restart"],              COLORS["accent_orange"]),
            ("📋  PS (status)",      ["compose", "ps"],                   COLORS["accent"]),
            ("📜  Logs",             ["compose", "logs", "--tail=50"],    COLORS["accent"]),
            ("🏗  Build",            ["compose", "build"],                COLORS["accent_purple"]),
            ("📦  Pull",             ["compose", "pull"],                 COLORS["accent"]),
        ]:
            tk.Button(right, text=label, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=14, pady=7,
                      anchor="w", cursor="hand2",
                      command=lambda a=args: self._compose_run(a)).pack(
                          fill="x", padx=8, pady=2)

        tk.Frame(right, bg=COLORS["border"], height=1).pack(
            fill="x", padx=8, pady=6)
        tk.Label(right, text="Output:", font=FONTS["heading"],
                 bg=COLORS["bg_card"],
                 fg=COLORS["text_secondary"]).pack(anchor="w", padx=8)
        self.compose_output = make_console(right, height=999)
        self.compose_output.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # ─────────────────────────── LOGS TAB ──

    def _build_tab_logs(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  📜  Logs  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Container Logs", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self.logs_container_var = tk.StringVar()
        self.logs_container_combo = ttk.Combobox(
            tb, textvariable=self.logs_container_var,
            font=FONTS["mono_sm"], width=28,
            style="DockerCombo.TCombobox")
        self.logs_container_combo.pack(side="right", padx=(4, 0))
        tk.Label(tb, text="Container:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="right")

        self.logs_tail = tk.IntVar(value=100)
        tk.Spinbox(tb, from_=10, to=10000, increment=10,
                   textvariable=self.logs_tail, width=6,
                   font=FONTS["mono_sm"],
                   bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                   buttonbackground=COLORS["bg_hover"]).pack(
                       side="right", padx=4)
        tk.Label(tb, text="Tail:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="right")

        for txt, cmd, color in [
            ("📜 Fetch Logs",  self._fetch_logs,  COLORS["accent"]),
            ("▶ Follow Logs",  self._follow_logs, COLORS["accent_green"]),
            ("■ Stop Follow",  self._stop_follow, COLORS["accent_red"]),
            ("🗑 Clear",       self._clear_logs,  COLORS["text_dim"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        log_card = make_card(frame, "Logs")
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.logs_text = make_console(log_card, height=999)
        self.logs_text.pack(fill="both", expand=True, padx=8, pady=8)

        self._populate_logs_combo()

    # ─────────────────────────── NETWORK TAB ──

    def _build_tab_network(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🌐  Networks  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Networks", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self.new_net_name = tk.Entry(
            tb, font=FONTS["mono_sm"], width=20,
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat", bd=3,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.new_net_name.insert(0, "my-network")
        self.new_net_name.pack(side="right", padx=4)

        for txt, cmd, color in [
            ("+ Create",   self._net_create,  COLORS["accent_green"]),
            ("📋 Inspect", self._net_inspect, COLORS["accent"]),
            ("🗑 Remove",  self._net_remove,  COLORS["accent_red"]),
            ("🧹 Prune",   self._net_prune,   COLORS["accent_orange"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        cols_cfg = [("ID", 120), ("Name", 160), ("Driver", 80),
                    ("Scope", 80), ("Subnet", 160)]
        self.networks_tree = make_tree(frame, cols_cfg)
        self.networks_tree.pack(fill="both", expand=True,
                                padx=16, pady=(0, 12))

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.networks_output = make_console(out_card, height=6)
        self.networks_output.pack(fill="x", padx=8, pady=8)

        self._refresh_networks()

    def _net_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.networks_output, text, clear))

    def _net_sel_name(self):
        tree = get_tree_widget(self.networks_tree)
        sel  = tree.selection() if tree else []
        return tree.item(sel[0])["values"][1] if sel else None

    def _net_create(self):
        n = self.new_net_name.get().strip()
        if n:
            network_create(self, n, self._net_output)

    def _net_inspect(self):
        n = self._net_sel_name()
        if n:
            network_inspect(self, n, self._net_output)

    def _net_remove(self):
        n = self._net_sel_name()
        if n and messagebox.askyesno("Remove Network",
                                      f"Remove network '{n}'?"):
            network_remove(self, n, self._net_output)

    def _net_prune(self):
        if messagebox.askyesno("Prune Networks",
                                "Remove all unused networks?"):
            network_prune(self, self._net_output)

    # ─────────────────────────── VOLUMES TAB ──

    def _build_tab_volumes(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  💾  Volumes  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Volumes", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self.new_vol_name = tk.Entry(
            tb, font=FONTS["mono_sm"], width=20,
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat", bd=3,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.new_vol_name.insert(0, "my-volume")
        self.new_vol_name.pack(side="right", padx=4)

        for txt, cmd, color in [
            ("+ Create",   self._vol_create,  COLORS["accent_green"]),
            ("📋 Inspect", self._vol_inspect, COLORS["accent"]),
            ("🗑 Remove",  self._vol_remove,  COLORS["accent_red"]),
            ("🧹 Prune",   self._vol_prune,   COLORS["accent_orange"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        cols_cfg = [("Name", 200), ("Driver", 100), ("Mountpoint", 400)]
        self.volumes_tree = make_tree(frame, cols_cfg)
        self.volumes_tree.pack(fill="both", expand=True,
                               padx=16, pady=(0, 12))

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.volumes_output = make_console(out_card, height=6)
        self.volumes_output.pack(fill="x", padx=8, pady=8)

        self._refresh_volumes()

    def _vol_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.volumes_output, text, clear))

    def _vol_sel_name(self):
        tree = get_tree_widget(self.volumes_tree)
        sel  = tree.selection() if tree else []
        return tree.item(sel[0])["values"][0] if sel else None

    def _vol_create(self):
        n = self.new_vol_name.get().strip()
        if n:
            volume_create(self, n, self._vol_output)

    def _vol_inspect(self):
        n = self._vol_sel_name()
        if n:
            volume_inspect(self, n, self._vol_output)

    def _vol_remove(self):
        n = self._vol_sel_name()
        if n and messagebox.askyesno(
            "Remove Volume", f"Remove volume '{n}'? Data will be lost!"
        ):
            volume_remove(self, n, self._vol_output)

    def _vol_prune(self):
        if messagebox.askyesno("Prune Volumes",
                                "Remove all unused volumes? Data will be lost!"):
            volume_prune(self, self._vol_output)

    # ─────────────────────────── ADVANCED TAB ──

    def _build_tab_advanced(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  ⚙  Advanced  ")

        tk.Label(frame, text="⚙  Advanced Power Tools",
                 font=FONTS["title"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(anchor="w", padx=24, pady=(18, 2))
        tk.Label(frame,
                 text="Direct command execution, Dockerfile builder, stats monitor",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(
                     anchor="w", padx=24, pady=(0, 12))

        style = ttk.Style()
        style.configure("Inner.TNotebook",
                        background=COLORS["bg_dark"], borderwidth=0)
        style.configure("Inner.TNotebook.Tab",
                        background=COLORS["bg_hover"],
                        foreground=COLORS["text_secondary"],
                        font=FONTS["ui_sm"], padding=[14, 6])
        style.map("Inner.TNotebook.Tab",
                  background=[("selected", COLORS["bg_card"])],
                  foreground=[("selected", COLORS["accent_purple"])])

        inner_nb = ttk.Notebook(frame, style="Inner.TNotebook")
        inner_nb.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._build_adv_terminal(inner_nb)
        self._build_adv_dockerfile(inner_nb)
        self._build_adv_stats(inner_nb)
        self._build_adv_registry(inner_nb)
        self._build_adv_misc(inner_nb)

    def _build_adv_terminal(self, nb):
        frame = tk.Frame(nb, bg=COLORS["bg_dark"])
        nb.add(frame, text="  💻  Terminal  ")

        tk.Label(frame, text="Execute any Docker command directly",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(anchor="w", padx=12, pady=8)

        cmd_row = tk.Frame(frame, bg=COLORS["bg_dark"])
        cmd_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(cmd_row, text="docker ", font=FONTS["mono"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["accent"]).pack(side="left")
        self.terminal_cmd = tk.Entry(
            cmd_row, font=FONTS["mono"],
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"], relief="flat", bd=4,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.terminal_cmd.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.terminal_cmd.bind("<Return>", lambda _: self._terminal_run())
        tk.Button(cmd_row, text="▶ Run", font=FONTS["ui"],
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=6,
                  cursor="hand2",
                  command=self._terminal_run).pack(side="left")

        quick_frame = tk.Frame(frame, bg=COLORS["bg_dark"])
        quick_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(quick_frame, text="Quick:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_dim"]).pack(side="left", padx=(0, 8))
        for cmd in ["info", "version", "system df",
                    "stats --no-stream", "ps -a", "images"]:
            tk.Button(quick_frame, text=cmd, font=FONTS["mono_sm"],
                      bg=COLORS["bg_hover"], fg=COLORS["text_secondary"],
                      relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                      command=lambda c=cmd: self._terminal_quick(c)).pack(
                          side="left", padx=2)

        out_card = make_card(frame, "Output")
        out_card.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        copy_row = tk.Frame(out_card, bg=COLORS["bg_card"])
        copy_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Button(copy_row, text="📋 Copy Output", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                  command=lambda: self._copy_console(
                      self.terminal_output)).pack(side="right")
        self.terminal_output = make_console(out_card, height=999)
        self.terminal_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_adv_dockerfile(self, nb):
        frame = tk.Frame(nb, bg=COLORS["bg_dark"])
        nb.add(frame, text="  🏗  Dockerfile Builder  ")

        pane = tk.Frame(frame, bg=COLORS["bg_dark"])
        pane.pack(fill="both", expand=True, padx=12, pady=12)
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)

        left = make_card(pane, "📝  Dockerfile")
        left.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        self.dockerfile_editor = scrolledtext.ScrolledText(
            left, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"],
            relief="flat", bd=4, wrap="none",
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.dockerfile_editor.insert("1.0", DOCKERFILE_TEMPLATE)
        self.dockerfile_editor.pack(fill="both", expand=True, padx=8, pady=8)

        btn_row = tk.Frame(left, bg=COLORS["bg_card"])
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        for txt, cmd, color in [
            ("🏗 Build Image", self._dockerfile_build, COLORS["accent_green"]),
            ("💾 Save",        self._dockerfile_save,  COLORS["accent"]),
            ("📂 Load",        self._dockerfile_load,  COLORS["accent"]),
        ]:
            tk.Button(btn_row, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        right = make_card(pane, "⚙️  Build Options & Output")
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        self.build_fields = {}
        for label, key, ph in [
            ("Image Tag:",     "build_tag",     "myapp:latest"),
            ("Build Context:", "build_context", "."),
            ("Build Args:",    "build_args",    "ARG1=value"),
        ]:
            row = tk.Frame(right, bg=COLORS["bg_card"])
            row.pack(fill="x", padx=12, pady=4)
            tk.Label(row, text=label, font=FONTS["ui_sm"], width=14,
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
            e = tk.Entry(row, font=FONTS["mono_sm"],
                         bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                         insertbackground=COLORS["accent"],
                         relief="flat", bd=3,
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            e.insert(0, ph)
            e.pack(side="right", fill="x", expand=True)
            self.build_fields[key] = e

        tk.Frame(right, bg=COLORS["border"], height=1).pack(
            fill="x", padx=12, pady=8)
        self.build_output = make_console(right, height=999)
        self.build_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_adv_stats(self, nb):
        frame = tk.Frame(nb, bg=COLORS["bg_dark"])
        nb.add(frame, text="  📊  Stats  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=12, pady=12)
        for txt, cmd, color in [
            ("▶ Start Monitor", self._stats_start, COLORS["accent_green"]),
            ("■ Stop Monitor",  self._stats_stop,  COLORS["accent_red"]),
            ("⟳ Refresh Once", self._stats_once,  COLORS["accent"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        cols_cfg = [
            ("Container", 160), ("CPU %", 80), ("MEM Usage", 120),
            ("MEM %", 80), ("NET I/O", 120), ("BLOCK I/O", 120), ("PIDs", 60),
        ]
        self.stats_tree = make_tree(frame, cols_cfg)
        self.stats_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_adv_registry(self, nb):
        frame = tk.Frame(nb, bg=COLORS["bg_dark"])
        nb.add(frame, text="  🔐  Registry  ")

        card = make_card(frame, "🔐  Registry Login & Push/Pull")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        self.reg_fields = {}
        for label, key, ph in [
            ("Registry URL:",  "reg_url",      "docker.io"),
            ("Username:",      "reg_user",     ""),
            ("Password:",      "reg_pass",     ""),
            ("Image to Push:", "reg_push_img", "myapp:latest"),
            ("Remote Tag:",    "reg_push_tag", "registry.io/user/myapp:latest"),
        ]:
            row = tk.Frame(card, bg=COLORS["bg_card"])
            row.pack(fill="x", padx=16, pady=4)
            tk.Label(row, text=label, font=FONTS["ui_sm"], width=16,
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
            show = "*" if "pass" in key else ""
            e = tk.Entry(row, font=FONTS["mono_sm"], show=show,
                         bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                         insertbackground=COLORS["accent"],
                         relief="flat", bd=3,
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            e.insert(0, ph)
            e.pack(side="right", fill="x", expand=True)
            self.reg_fields[key] = e

        btn_row = tk.Frame(card, bg=COLORS["bg_card"])
        btn_row.pack(fill="x", padx=16, pady=8)
        for txt, cmd, color in [
            ("🔑 Login",  self._reg_login,  COLORS["accent_green"]),
            ("🚪 Logout", self._reg_logout, COLORS["accent_red"]),
            ("⬆ Push",   self._reg_push,   COLORS["accent"]),
            ("⬇ Pull",   self._reg_pull,   COLORS["accent"]),
        ]:
            tk.Button(btn_row, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=12, pady=6,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        self.reg_output = make_console(card, height=10)
        self.reg_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _reg_output(self, text, clear=False):
        self.after(0, lambda: console_write(self.reg_output, text, clear))

    def _reg_login(self):
        url  = self.reg_fields["reg_url"].get().strip()
        user = self.reg_fields["reg_user"].get().strip()
        pwd  = self.reg_fields["reg_pass"].get()
        if not user or not pwd:
            messagebox.showwarning("Registry Login",
                                   "Username and password are required.")
            return
        # Wipe entry immediately before any async work
        self.reg_fields["reg_pass"].delete(0, "end")
        registry_login_exec(self, url, user, pwd, self._reg_output)

    def _reg_logout(self):
        url = self.reg_fields["reg_url"].get().strip()
        registry_logout_exec(self, url, self._reg_output)

    def _reg_push(self):
        src = self.reg_fields["reg_push_img"].get().strip()
        dst = self.reg_fields["reg_push_tag"].get().strip()
        try:
            src = validate_image_name(src)
            dst = validate_image_name(dst)
        except ValidationError as e:
            messagebox.showerror("Invalid Image Name", str(e))
            return
        registry_push_exec(self, src, dst, self._reg_output)

    def _reg_pull(self):
        img = self.reg_fields["reg_push_tag"].get().strip()
        try:
            img = validate_image_name(img)
        except ValidationError as e:
            messagebox.showerror("Invalid Image Name", str(e))
            return
        registry_pull_exec(self, img, self._reg_output)

    def _build_adv_misc(self, nb):
        frame = tk.Frame(nb, bg=COLORS["bg_dark"])
        nb.add(frame, text="  🔬  Misc Tools  ")

        card = make_card(frame, "🔬  Miscellaneous Docker Tools")
        card.pack(fill="both", expand=True, padx=12, pady=12)

        tools = [
            ("System DF (disk usage)",    ["system", "df"]),
            ("System Events (last 10m)",  ["events", "--since=10m", "--until=0m"]),
            ("List All Contexts",         ["context", "ls"]),
            ("Show Docker Version",       ["version"]),
            ("Show Docker Info",          ["info"]),
            ("Prune Build Cache",         ["builder", "prune", "-f"]),
            ("Prune Everything (force!)", ["system", "prune", "-af", "--volumes"]),
        ]
        btn_grid = tk.Frame(card, bg=COLORS["bg_card"])
        btn_grid.pack(fill="x", padx=12, pady=8)
        for i, (label, args) in enumerate(tools):
            tk.Button(btn_grid, text=label, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                      relief="flat", bd=0, padx=12, pady=7,
                      anchor="w", cursor="hand2",
                      command=lambda a=args: self._misc_run(a)).grid(
                          row=i // 2, column=i % 2,
                          padx=4, pady=3, sticky="ew")
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        tk.Frame(card, bg=COLORS["border"], height=1).pack(
            fill="x", padx=12, pady=8)
        self.misc_output = make_console(card, height=999)
        self.misc_output.pack(fill="both", expand=True, padx=8, pady=8)

    # ─────────────────────────── DOCKER + EVENTS ──

    def _check_docker(self):
        def _check():
            ok = docker_available()
            if ok:
                self.after(0, lambda: self.docker_status_label.configure(
                    text="● Docker running",
                    fg=COLORS["accent_green"]))
                self._set_status("Docker daemon is running")
            else:
                self.after(0, lambda: self.docker_status_label.configure(
                    text="● Docker not running",
                    fg=COLORS["accent_red"]))
                self._set_status("⚠  Docker not running")
                self._show_error_notification(
                    "Docker daemon is not running. Start Docker and refresh.",
                    icon="⚠", color=COLORS["accent_red"])
                self.after(0, self._show_install_wizard)
        safe_thread(_check)

    def _start_events_watcher(self):
        """
        P1 #2 — Real docker events JSON stream.
        Targeted refresh: only the affected view is refreshed,
        not a full blind poll of everything.
        """
        CONTAINER_ACTIONS = {
            "start", "stop", "die", "kill", "pause",
            "unpause", "destroy", "create", "rename",
        }
        IMAGE_ACTIONS   = {"pull", "push", "import", "delete", "tag", "untag"}
        VOLUME_ACTIONS  = {"create", "destroy", "prune", "mount", "unmount"}
        NETWORK_ACTIONS = {"create", "destroy", "connect", "disconnect", "prune"}

        self._events_stop.clear()

        def _watch():
            while not self._events_stop.is_set():
                try:
                    proc = subprocess.Popen(
                        ["docker", "events", "--format", "{{json .}}"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1,
                    )
                    for raw in proc.stdout:
                        if self._events_stop.is_set():
                            proc.terminate()
                            return
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw)
                            evt_type   = ev.get("Type", "")
                            evt_action = ev.get("Action", "")
                        except (json.JSONDecodeError, ValueError):
                            parts      = raw.split()
                            evt_type   = parts[0] if parts else ""
                            evt_action = parts[1] if len(parts) > 1 else ""

                        if evt_type == "container" and evt_action in CONTAINER_ACTIONS:
                            self.after(300, self._refresh_containers)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "image" and evt_action in IMAGE_ACTIONS:
                            self.after(300, self._refresh_images)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "volume" and evt_action in VOLUME_ACTIONS:
                            self.after(300, self._refresh_volumes)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "network" and evt_action in NETWORK_ACTIONS:
                            self.after(300, self._refresh_networks)
                            self.after(300, self._refresh_dashboard)
                    proc.wait()
                except Exception:
                    pass
                if not self._events_stop.is_set():
                    time.sleep(10)

        safe_thread(_watch)

    def _check_for_updates(self):
        """P2 #8 — GitHub API version check; shows toast if newer version found."""
        REPO = "anthropics/dockerdeck"  # replace with actual repo when published

        def _do():
            try:
                import urllib.request
                import urllib.error
                url = f"https://api.github.com/repos/{REPO}/releases/latest"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "DockerDeck"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    latest = data.get("tag_name", "").lstrip("v")
                if latest and latest != __version__:
                    msg = (f"Update available: v{latest}  "
                           f"(you have v{__version__})")
                    self.after(2000, lambda: self._show_error_notification(
                        msg, icon="⬆", color=COLORS["accent_cyan"]))
            except Exception:
                pass  # silently ignore network errors
        safe_thread(_do)

    def on_close(self):
        self._events_stop.set()
        self.log_stop_event.set()
        self._stats_stop_event.set()
        self.destroy()

    # ─────────────────────────── FIRST-RUN WIZARD ──

    def _show_install_wizard(self):
        dlg = tk.Toplevel(self)
        dlg.title("Docker Not Found")
        dlg.geometry("540x320")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="🐳  Docker Not Found",
                 font=FONTS["title"], bg=COLORS["bg_dark"],
                 fg=COLORS["accent_red"]).pack(pady=(24, 8))
        tk.Label(dlg,
                 text="DockerDeck requires Docker to be installed and running.\n"
                      "Please install Docker Desktop or Docker Engine and restart.",
                 font=FONTS["ui"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"], justify="center").pack(padx=24)

        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(
            fill="x", padx=32, pady=16)

        for platform, url, color in [
            ("🪟  Windows — Docker Desktop",
             "https://docs.docker.com/desktop/install/windows/",
             COLORS["accent"]),
            ("🍎  macOS  — Docker Desktop",
             "https://docs.docker.com/desktop/install/mac/",
             COLORS["accent"]),
            ("🐧  Linux  — Docker Engine",
             "https://docs.docker.com/engine/install/",
             COLORS["accent_green"]),
        ]:
            row = tk.Frame(dlg, bg=COLORS["bg_dark"])
            row.pack(fill="x", padx=32, pady=2)
            tk.Label(row, text=platform, font=FONTS["ui"],
                     bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                     width=34, anchor="w").pack(side="left")
            tk.Button(row, text="Open ↗", font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                      command=lambda u=url: webbrowser.open(u)).pack(
                          side="right")

        tk.Button(dlg, text="Dismiss", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_secondary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=16)

    # ─────────────────────────── REFRESH ──

    def _refresh_all(self):
        self._refresh_dashboard()
        self._refresh_containers()
        self._refresh_images()
        self._refresh_networks()
        self._refresh_volumes()
        self._populate_logs_combo()
        self._set_status("Refreshed all views")

    def _refresh_dashboard(self):
        def _do():
            out,  _, _ = run_docker(["ps", "-q"])
            running  = len([l for l in out.split("\n") if l.strip()]) if out else 0
            out2, _, _ = run_docker(["ps", "-aq"])
            total    = len([l for l in out2.split("\n") if l.strip()]) if out2 else 0
            out3, _, _ = run_docker(["images", "-q"])
            images   = len([l for l in out3.split("\n") if l.strip()]) if out3 else 0
            out4, _, _ = run_docker(["volume", "ls", "-q"])
            volumes  = len([l for l in out4.split("\n") if l.strip()]) if out4 else 0
            out5, _, _ = run_docker(["network", "ls", "-q"])
            networks = len([l for l in out5.split("\n") if l.strip()]) if out5 else 0
            stopped  = total - running

            def _upd():
                self.stat_cards["containers_running"]._value_label.configure(
                    text=str(running))
                self.stat_cards["containers_stopped"]._value_label.configure(
                    text=str(stopped))
                self.stat_cards["images_total"]._value_label.configure(
                    text=str(images))
                self.stat_cards["volumes_total"]._value_label.configure(
                    text=str(volumes))
                self.stat_cards["networks_total"]._value_label.configure(
                    text=str(networks))
                out6, _, _ = run_docker([
                    "ps", "--format",
                    "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
                ])
                console_write(self.dash_containers_text,
                              out6 or "(no running containers)", clear=True)
            self.after(0, _upd)
        safe_thread(_do)

    def _refresh_containers(self):
        tree = get_tree_widget(self.containers_tree)
        if not tree:
            return

        def _do():
            args = ["ps", "-a"] if self.show_all_var.get() else ["ps"]
            args += ["--format",
                     "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}"]
            out, _, _ = run_docker(args)

            def _upd():
                tree.delete(*tree.get_children())
                for line in out.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 6:
                        parts.append("")
                    iid = tree.insert("", "end", values=parts[:6])
                    status = parts[3].lower()
                    if "up" in status:
                        tree.item(iid, tags=("running",))
                    elif "exited" in status:
                        tree.item(iid, tags=("stopped",))
                tree.tag_configure("running",
                                   foreground=COLORS["accent_green"])
                tree.tag_configure("stopped",
                                   foreground=COLORS["accent_red"])
            self.after(0, _upd)
        safe_thread(_do)

    def _refresh_images(self):
        tree = get_tree_widget(self.images_tree)
        if not tree:
            return

        def _do():
            out, _, _ = run_docker([
                "images", "--format",
                "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}",
            ])

            def _upd():
                tree.delete(*tree.get_children())
                for line in out.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 5:
                        parts.append("")
                    tree.insert("", "end", values=parts[:5])
            self.after(0, _upd)
        safe_thread(_do)

    def _refresh_networks(self):
        tree = get_tree_widget(self.networks_tree)
        if not tree:
            return

        def _do():
            out, _, _ = run_docker([
                "network", "ls", "--format",
                "{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}",
            ])
            rows = []
            for line in out.split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                while len(parts) < 4:
                    parts.append("")
                isp_out, _, _ = run_docker([
                    "network", "inspect", parts[0],
                    "--format",
                    "{{range .IPAM.Config}}{{.Subnet}}{{end}}",
                ])
                parts.append(isp_out.strip()[:30] if isp_out else "")
                rows.append(parts[:5])

            def _upd():
                tree.delete(*tree.get_children())
                for r in rows:
                    tree.insert("", "end", values=r)
            self.after(0, _upd)
        safe_thread(_do)

    def _refresh_volumes(self):
        tree = get_tree_widget(self.volumes_tree)
        if not tree:
            return

        def _do():
            out, _, _ = run_docker([
                "volume", "ls", "--format",
                "{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}",
            ])

            def _upd():
                tree.delete(*tree.get_children())
                for line in out.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 3:
                        parts.append("")
                    tree.insert("", "end", values=parts[:3])
            self.after(0, _upd)
        safe_thread(_do)

    def _populate_logs_combo(self):
        def _do():
            out, _, _ = run_docker(
                ["ps", "-a", "--format", "{{.Names}}"])
            names = [n for n in out.split("\n") if n.strip()]

            def _upd():
                self.logs_container_combo["values"] = names
                if names and not self.logs_container_var.get():
                    self.logs_container_combo.set(names[0])
            self.after(0, _upd)
        safe_thread(_do)

    # ─────────────────────────── LOG ACTIONS ──

    def _fetch_logs(self):
        name = self.logs_container_var.get().strip()
        if not name:
            return
        tail = str(self.logs_tail.get())

        def _do():
            out, err, _ = run_docker(["logs", "--tail", tail, name])
            self.after(0, lambda: console_write(
                self.logs_text,
                f"=== logs {name} (tail={tail}) ===\n{out}\n{err}\n",
                clear=True))
        safe_thread(_do)

    def _follow_logs(self):
        name = self.logs_container_var.get().strip()
        if not name:
            return
        self.log_stop_event.clear()

        def _do():
            self.after(0, lambda: console_write(
                self.logs_text,
                f"=== Following logs: {name} ===\n", clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(
                    self.logs_text, l))
            run_docker_stream(
                ["logs", "-f", "--tail", "50", name], cb,
                stop_event=self.log_stop_event)
        safe_thread(_do)

    def _stop_follow(self):
        self.log_stop_event.set()

    def _clear_logs(self):
        console_write(self.logs_text, "", clear=True)

    # ─────────────────────────── ADVANCED ACTIONS ──

    def _terminal_run(self):
        cmd = self.terminal_cmd.get().strip()
        if not cmd:
            return

        def _do():
            self.after(0, lambda: console_write(
                self.terminal_output, f"$ docker {cmd}\n"))
            out, err, rc = run_docker(cmd.split(), timeout=60)
            self.after(0, lambda: console_write(
                self.terminal_output,
                f"{out}\n{err}\n[rc={rc}]\n{'─'*60}\n"))
        safe_thread(_do)

    def _terminal_quick(self, cmd: str):
        self.terminal_cmd.delete(0, "end")
        self.terminal_cmd.insert(0, cmd)
        self._terminal_run()

    def _dockerfile_build(self):
        tag     = self.build_fields["build_tag"].get().strip() or "myapp:latest"
        context = self.build_fields["build_context"].get().strip() or "."
        ba_raw  = self.build_fields["build_args"].get().strip()
        try:
            tag = validate_image_name(tag)
        except ValidationError as e:
            messagebox.showerror("Invalid Tag", str(e))
            return

        content = self.dockerfile_editor.get("1.0", "end")
        df_path = os.path.join(context, "Dockerfile.dockerdeck_tmp")
        try:
            with open(df_path, "w") as f:
                f.write(content)
        except Exception as e:
            console_write(self.build_output, f"Error saving Dockerfile: {e}\n")
            return

        args = ["build", "-t", tag, "-f", df_path]
        if ba_raw:
            for ba in ba_raw.split(","):
                args += ["--build-arg", ba.strip()]
        args.append(context)

        def _do():
            self.after(0, lambda: console_write(
                self.build_output,
                f"$ docker {' '.join(args)}\n\n", clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(
                    self.build_output, l))
            rc = run_docker_stream(args, cb)
            self.after(0, lambda: console_write(
                self.build_output, f"\n--- Done (rc={rc}) ---\n"))
            try:
                os.remove(df_path)
            except Exception:
                pass
        safe_thread(_do)

    def _dockerfile_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension="", initialfile="Dockerfile",
            filetypes=[("Dockerfile", "Dockerfile*"),
                       ("All files", "*.*")])
        if path:
            content = self.dockerfile_editor.get("1.0", "end")
            with open(path, "w") as f:
                f.write(content)
            self._show_success_notification(f"Dockerfile saved: {path}")

    def _dockerfile_load(self):
        path = filedialog.askopenfilename(
            title="Open Dockerfile",
            filetypes=[("Dockerfile", "Dockerfile*"),
                       ("All files", "*.*")])
        if path:
            with open(path) as f:
                content = f.read()
            self.dockerfile_editor.delete("1.0", "end")
            self.dockerfile_editor.insert("1.0", content)

    def _stats_once(self):
        tree = get_tree_widget(self.stats_tree)

        def _do():
            out, _, _ = run_docker([
                "stats", "--no-stream", "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
                "\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}",
            ])

            def _upd():
                tree.delete(*tree.get_children())
                for line in out.split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    while len(parts) < 7:
                        parts.append("")
                    tree.insert("", "end", values=parts[:7])
            self.after(0, _upd)
        safe_thread(_do)

    def _stats_start(self):
        self._stats_stop_event.clear()

        def _loop():
            while not self._stats_stop_event.is_set():
                self._stats_once()
                time.sleep(3)
        safe_thread(_loop)

    def _stats_stop(self):
        self._stats_stop_event.set()

    def _misc_run(self, args: list):
        def _do():
            self.after(0, lambda: console_write(
                self.misc_output, f"$ docker {' '.join(args)}\n"))
            out, err, rc = run_docker(args, timeout=60)
            self.after(0, lambda: console_write(
                self.misc_output,
                f"{out}\n{err}\n[rc={rc}]\n{'─'*60}\n"))
        safe_thread(_do)

    # ─────────────────────────── COMPOSE ACTIONS ──

    def _compose_run(self, base_args: list):
        path = self.compose_path.get().strip()
        if path and os.path.exists(path):
            cwd  = os.path.dirname(os.path.abspath(path))
            args = ["-f", os.path.basename(path)] + base_args
        else:
            cwd, args = None, base_args

        def _do():
            self.after(0, lambda: console_write(
                self.compose_output,
                f"$ docker {' '.join(args)}\n"
                f"  cwd: {cwd or '(not set)'}\n\n",
                clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(
                    self.compose_output, l))
            run_docker_stream(args, cb, cwd=cwd)
        safe_thread(_do)

    def _browse_compose(self):
        path = filedialog.askopenfilename(
            title="Select docker-compose.yml",
            filetypes=[("YAML files", "*.yml *.yaml"),
                       ("All files", "*.*")])
        if path:
            self.compose_path.set(path)
            with open(path) as f:
                content = f.read()
            self.compose_editor.delete("1.0", "end")
            self.compose_editor.insert("1.0", content)

    def _compose_save(self):
        path    = self.compose_path.get().strip()
        content = self.compose_editor.get("1.0", "end")
        try:
            with open(path, "w") as f:
                f.write(content)
            self._show_success_notification(f"Compose file saved: {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _compose_clear(self):
        self.compose_editor.delete("1.0", "end")

    # ─────────────────────────── QUICK ACTIONS ──

    def _quick_start(self):
        name = ask_input(self, "Start Container",
                         "Container name or ID:", "")
        if name:
            def _do():
                out, err, rc = run_docker(["start", name])
                self.after(0, lambda: console_write(
                    self.dash_containers_text,
                    f"[start {name}] {out or err}\n"))
            safe_thread(_do)

    def _quick_stop(self):
        name = ask_input(self, "Stop Container",
                         "Container name or ID:", "")
        if name:
            def _do():
                out, err, rc = run_docker(["stop", name])
                self.after(0, lambda: console_write(
                    self.dash_containers_text,
                    f"[stop {name}] {out or err}\n"))
            safe_thread(_do)

    def _quick_restart(self):
        name = ask_input(self, "Restart Container",
                         "Container name or ID:", "")
        if name:
            safe_thread(run_docker, ["restart", name])

    def _prune_stopped(self):
        if messagebox.askyesno("Prune Stopped",
                                "Remove all stopped containers?"):
            safe_thread(run_docker, ["container", "prune", "-f"])

    def _quick_pull(self):
        dlg = tk.Toplevel(self)
        dlg.title("Pull Image")
        dlg.geometry("400x130")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()
        tk.Label(dlg, text="Image name:tag", font=FONTS["ui"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(padx=20, pady=(16, 4))
        e = tk.Entry(dlg, font=FONTS["mono"], width=34,
                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                     insertbackground=COLORS["accent"],
                     relief="flat", bd=4,
                     highlightbackground=COLORS["border"],
                     highlightthickness=1)
        e.insert(0, "nginx:latest")
        e.pack(padx=20, fill="x")

        def do_pull():
            img = e.get().strip()
            dlg.destroy()
            if img:
                self.pull_entry.delete(0, "end")
                self.pull_entry.insert(0, img)
                self.nb.select(2)
                self._i_pull()

        e.bind("<Return>", lambda _: do_pull())
        tk.Button(dlg, text="Pull", font=FONTS["ui"],
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=6,
                  command=do_pull).pack(pady=10)

    def _system_prune(self):
        if messagebox.askyesno(
            "System Prune",
            "Remove all stopped containers, dangling images, unused networks?\n\n"
            "This cannot be undone!"
        ):
            def _do():
                run_docker(["system", "prune", "-f"])
                self._set_status("System prune complete")
            safe_thread(_do)

    # ─────────────────────────── UTILITY ──

    def _on_container_select(self, _):
        tree = get_tree_widget(self.containers_tree)
        sel  = tree.selection()
        if sel:
            self.selected_container.set(tree.item(sel[0])["values"][1])

    def _on_image_select(self, _):
        tree = get_tree_widget(self.images_tree)
        sel  = tree.selection()
        if sel:
            vals = tree.item(sel[0])["values"]
            self.selected_image.set(f"{vals[0]}:{vals[1]}")

    def _set_status(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.after(0, lambda: self.status_bar.configure(
            text=f"[{ts}]  {msg}"))

    def _copy_console(self, widget):
        widget.configure(state="normal")
        text = widget.get("1.0", "end")
        widget.configure(state="disabled")
        self.clipboard_clear()
        self.clipboard_append(text)
        self._show_success_notification("Output copied to clipboard.")

    def _show_about(self):
        dlg = tk.Toplevel(self)
        dlg.title("About DockerDeck")
        dlg.geometry("440x300")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="🐳  DockerDeck",
                 font=("Segoe UI", 20, "bold"),
                 bg=COLORS["bg_dark"],
                 fg=COLORS["accent"]).pack(pady=(24, 4))
        tk.Label(dlg, text=f"Version {__version__}",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack()
        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(
            fill="x", padx=32, pady=12)

        for lbl, val in [
            ("Platform", sys.platform),
            ("Python",   sys.version.split()[0]),
            ("Presets",  str(PRESETS_PATH)),
        ]:
            row = tk.Frame(dlg, bg=COLORS["bg_dark"])
            row.pack(fill="x", padx=32, pady=2)
            tk.Label(row, text=f"{lbl}:", font=FONTS["ui_sm"], width=10,
                     bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
            tk.Label(row, text=val, font=FONTS["mono_sm"],
                     bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                     anchor="w").pack(side="left")

        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(
            fill="x", padx=32, pady=12)
        tk.Label(dlg,
                 text="Production-grade Docker GUI\n"
                      "Pure Python stdlib — no pip required.",
                 font=FONTS["ui_sm"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"],
                 justify="center").pack(pady=(0, 8))
        tk.Button(dlg, text="Close", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=4)
