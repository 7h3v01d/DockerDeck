"""
DockerDeck – app.py
Main application window and all tab builders.
"""

import os
import sys
import json
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from utils import (
    __version__, __app_name__, COLORS, FONTS,
    safe_thread, set_error_callback,
    log_notification, get_notification_log,
    COMPOSE_TEMPLATE, DOCKERFILE_TEMPLATE, Debouncer
)
from docker_runner import run_docker, run_docker_stream, docker_available, run_docker_login
from validation import ValidationError
from ui_components import (
    make_card, make_console, make_tree, get_tree_widget,
    make_stat_card, console_write, make_icon_button, ask_input
)
from actions.containers import (
    get_selected_containers, get_selected_container,
    container_start, container_stop, container_restart,
    container_stop_all, container_inspect,
    container_rename, container_cp, container_shell, container_remove
)
from actions.images import (
    image_pull, image_inspect, image_run, image_remove, image_prune
)
from actions.deploy import (
    validate_field, validate_all_fields, build_run_command,
    deploy_container, load_presets, save_presets,
    preset_save, preset_load, preset_delete, FIELD_VALIDATORS
)
from actions.network_volume import (
    network_create, network_inspect, network_remove, network_prune,
    volume_create, volume_inspect, volume_remove, volume_prune
)
from actions.registry import (
    registry_login, registry_logout, registry_push, registry_pull
)


class DockerDeck(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(f"DockerDeck v{__version__}  —  Docker Package & Deploy Suite")
        self.geometry("1280x840")
        self.minsize(960, 640)
        self.configure(bg=COLORS["bg_dark"])

        # Register global error callback
        set_error_callback(self._show_error_notification)

        # State
        self.selected_container = tk.StringVar()
        self.selected_image = tk.StringVar()
        self.log_stop_event = threading.Event()
        self._stats_stop_event = threading.Event()
        self._events_stop = threading.Event()

        # Presets
        self.presets = load_presets()

        # Build UI
        self._build_ui()
        self._check_docker()
        self._check_for_updates()          # P2 #8: version check
        self._start_events_watcher()       # P1 #2: real docker events
        self._setup_shortcuts()            # P3: keyboard shortcuts
        self._refresh_all()

    # ── BUILD UI ──────────────────────────────

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
            hdr, text="● Checking…",
            font=FONTS["ui_sm"],
            bg=COLORS["bg_card"], fg=COLORS["accent_orange"])
        self.docker_status_label.pack(side="left", padx=6)

        # View Log button (P2 #6)
        tk.Button(hdr, text="📋 Log",
                  font=FONTS["ui_sm"], bg=COLORS["bg_hover"],
                  fg=COLORS["text_secondary"], relief="flat",
                  bd=0, padx=10, cursor="hand2",
                  activebackground=COLORS["border"],
                  command=self._show_log_history).pack(side="right", padx=6, pady=12)

        tk.Button(hdr, text="ℹ  About",
                  font=FONTS["ui_sm"], bg=COLORS["bg_hover"],
                  fg=COLORS["text_secondary"], relief="flat",
                  bd=0, padx=10, cursor="hand2",
                  activebackground=COLORS["border"],
                  command=self._show_about).pack(side="right", padx=6, pady=12)

        tk.Button(hdr, text="⟳  Refresh All",
                  font=FONTS["ui"], bg=COLORS["bg_hover"],
                  fg=COLORS["text_primary"], relief="flat",
                  bd=0, padx=12, cursor="hand2",
                  activebackground=COLORS["accent"],
                  activeforeground="white",
                  command=self._refresh_all).pack(side="right", padx=6, pady=10)

        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x")

    # ── NOTIFICATION BAR (P2 #6) ──────────────

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
        """Thread-safe notification bar update. Also logs to history."""
        color = color or COLORS["accent_orange"]
        level = "error" if icon == "⚠" else "success"
        log_notification(message, level)

        def _show():
            self._notif_icon.configure(text=icon, fg=color)
            self._notif_label.configure(text=message)
            self._notif_frame.pack(fill="x")
        self.after(0, _show)

    def _show_success_notification(self, message: str):
        self._show_error_notification(message, icon="✓", color=COLORS["accent_green"])

    def _hide_notification(self):
        self._notif_frame.pack_forget()

    # ── LOG HISTORY VIEWER (P2 #6) ────────────

    def _show_log_history(self):
        dlg = tk.Toplevel(self)
        dlg.title("Notification Log History")
        dlg.geometry("700x450")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="📋  Notification History  (newest first)",
                 font=FONTS["heading"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(
                     anchor="w", padx=16, pady=(12, 4))

        txt = scrolledtext.ScrolledText(
            dlg, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text_primary"],
            relief="flat", bd=4,
            highlightbackground=COLORS["border"], highlightthickness=1)
        txt.pack(fill="both", expand=True, padx=12, pady=8)

        entries = get_notification_log()
        if not entries:
            txt.insert("end", "(no log entries yet)\n")
        else:
            for e in entries:
                icon = "✓" if e["level"] == "success" else "⚠"
                txt.insert("end", f"[{e['ts']}]  {icon}  {e['msg']}\n")
        txt.configure(state="disabled")

        tk.Button(dlg, text="Close", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=8)

    def _build_status_bar(self):
        self.status_bar = tk.Label(
            self, text="Ready",
            font=FONTS["mono_sm"],
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
                        font=FONTS["ui"], padding=[18, 8],
                        borderwidth=0)
        style.map("Custom.TNotebook.Tab",
                  background=[("selected", COLORS["bg_dark"])],
                  foreground=[("selected", COLORS["tab_active"])],
                  expand=[("selected", [0, 0, 0, 0])])

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

    # ── KEYBOARD SHORTCUTS (P3) ───────────────

    def _setup_shortcuts(self):
        self.bind_all("<Control-r>", lambda _: self._refresh_all())
        self.bind_all("<F5>", lambda _: self._refresh_all())

    # ── DASHBOARD TAB ─────────────────────────

    def _build_tab_dashboard(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🏠  Dashboard  ")

        tk.Label(frame, text="System Overview",
                 font=FONTS["title"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(
                     anchor="w", padx=24, pady=(18, 6))
        tk.Label(frame, text="Real-time status of your Docker environment",
                 font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(
                     anchor="w", padx=24, pady=(0, 16))

        # Stats row
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

        # Two-column layout
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
            b = tk.Button(right, text=txt, font=FONTS["ui"],
                          bg=COLORS["bg_hover"], fg=color,
                          relief="flat", bd=0, padx=16, pady=9,
                          anchor="w", cursor="hand2",
                          activebackground=COLORS["border"],
                          activeforeground=color,
                          command=cmd)
            b.pack(fill="x", padx=12, pady=3)

    # ── CONTAINERS TAB ────────────────────────

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
                       font=FONTS["ui_sm"],
                       bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
                       selectcolor=COLORS["bg_card"],
                       activebackground=COLORS["bg_dark"],
                       command=self._refresh_containers).pack(side="left", padx=16)

        for txt, cmd, color in [
            ("▶ Start",      lambda: container_start(self, self.containers_tree, self.containers_output),    COLORS["accent_green"]),
            ("■ Stop",       lambda: container_stop(self, self.containers_tree, self.containers_output),     COLORS["accent_red"]),
            ("🔄 Restart",   lambda: container_restart(self, self.containers_tree, self.containers_output),  COLORS["accent_orange"]),
            ("✏ Rename",     lambda: container_rename(self, self.containers_tree, self.containers_output),   COLORS["accent_purple"]),
            ("📂 Copy File", lambda: container_cp(self, self.containers_tree, self.containers_output),       COLORS["accent"]),
            ("📋 Inspect",   lambda: container_inspect(self, self.containers_tree, self.containers_output),  COLORS["accent"]),
            ("🖥 Shell Cmd", lambda: container_shell(self, self.containers_tree),                            COLORS["accent_purple"]),
            ("⛔ Stop All",  lambda: container_stop_all(self, self.containers_tree, self.containers_output), COLORS["accent_red"]),
            ("🗑 Remove",    lambda: container_remove(self, self.containers_tree, self.containers_output),   COLORS["accent_red"]),
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
        tree = get_tree_widget(self.containers_tree)
        tree.bind("<<TreeviewSelect>>", self._on_container_select)

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.containers_output = make_console(out_card, height=5)
        self.containers_output.pack(fill="x", padx=8, pady=8)

        self._refresh_containers()

    # ── IMAGES TAB ────────────────────────────

    def _build_tab_images(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🗂  Images  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Images", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.pull_entry = tk.Entry(tb, font=FONTS["mono"], width=28,
                                   bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                                   insertbackground=COLORS["accent"],
                                   relief="flat", bd=4,
                                   highlightbackground=COLORS["border"],
                                   highlightthickness=1)
        self.pull_entry.insert(0, "image:tag")
        self.pull_entry.pack(side="right", padx=(4, 0))
        tk.Label(tb, text="Pull:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(side="right")

        for txt, cmd, color in [
            ("⬇ Pull",    lambda: image_pull(self, self.pull_entry, self.images_output, self._set_status),    COLORS["accent"]),
            ("📋 Inspect", lambda: image_inspect(self, self.images_tree, self.images_output),                 COLORS["accent"]),
            ("▶ Run",     lambda: image_run(self, self.images_tree, self.deploy_fields, self._validate_deploy_field, self.nb, 3), COLORS["accent_green"]),
            ("🗑 Remove", lambda: image_remove(self, self.images_tree, self.images_output),                  COLORS["accent_red"]),
            ("🧹 Prune",  lambda: image_prune(self, self.images_output),                                     COLORS["accent_orange"]),
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

    # ── DEPLOY TAB ────────────────────────────

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
        self.deploy_fields = {}
        self._deploy_indicators = {}
        self._field_debouncers = {}

        for label, key, placeholder in fields_cfg:
            row = tk.Frame(form_card, bg=COLORS["bg_card"])
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, font=FONTS["ui_sm"], width=16,
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
            dot = tk.Label(row, text="●", font=FONTS["ui_sm"],
                           bg=COLORS["bg_card"], fg=COLORS["text_dim"])
            dot.pack(side="right", padx=(4, 0))
            e = tk.Entry(row, font=FONTS["mono_sm"], width=20,
                         bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                         insertbackground=COLORS["accent"],
                         relief="flat", bd=3,
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)
            e.insert(0, placeholder)
            e.pack(side="right", fill="x", expand=True)
            self.deploy_fields[key] = e
            self._deploy_indicators[key] = dot

            # Debounced validation on keystroke (P3 debounce)
            db = Debouncer(self, lambda k=key: self._validate_deploy_field(k), 250)
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

        # Presets row
        preset_row = tk.Frame(form_card, bg=COLORS["bg_card"])
        preset_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(preset_row, text="Preset:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]).pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_row, textvariable=self.preset_var,
                                          font=FONTS["mono_sm"], width=16)
        self.preset_combo.pack(side="left", padx=4)
        self._refresh_presets_combo()

        tk.Button(preset_row, text="💾 Save", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
                  command=self._deploy_save_preset).pack(side="left", padx=2)
        tk.Button(preset_row, text="📂 Load", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
                  command=self._deploy_load_preset).pack(side="left", padx=2)
        tk.Button(preset_row, text="🗑 Del", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent_red"],
                  relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
                  command=self._deploy_delete_preset).pack(side="left", padx=2)

        tk.Button(form_card, text="🚀  Deploy Container",
                  font=("Segoe UI", 11, "bold"),
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=10,
                  cursor="hand2",
                  command=self._deploy_container).pack(fill="x", padx=12, pady=8)

        # Preview command card
        preview_card = make_card(form_card, "Preview Command")
        preview_card.pack(fill="x", padx=12, pady=(0, 6))
        copy_row = tk.Frame(preview_card, bg=COLORS["bg_card"])
        copy_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Button(copy_row, text="📋 Copy", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                  command=self._copy_deploy_command).pack(side="right")
        self.deploy_preview = make_console(preview_card, height=3)
        self.deploy_preview.pack(fill="x", padx=8, pady=8)

        for key in self.deploy_fields:
            self._validate_deploy_field(key)

        right_card = make_card(pane, "📡  Deploy Output")
        right_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        self.deploy_output = make_console(right_card, height=999)
        self.deploy_output.pack(fill="both", expand=True, padx=8, pady=8)

    # ── COMPOSE TAB ───────────────────────────

    def _build_tab_compose(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🎼  Compose  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Docker Compose", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.compose_path = tk.StringVar(value="docker-compose.yml")
        path_entry = tk.Entry(tb, textvariable=self.compose_path,
                              font=FONTS["mono_sm"], width=30,
                              bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                              insertbackground=COLORS["accent"],
                              relief="flat", bd=3,
                              highlightbackground=COLORS["border"],
                              highlightthickness=1)
        path_entry.pack(side="right", padx=(4, 0))
        tk.Label(tb, text="File:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(side="right")
        tk.Button(tb, text="📂 Browse", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
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
            ("💾 Save",  self._compose_save,  COLORS["accent"]),
            ("📂 Load",  self._browse_compose, COLORS["accent"]),
            ("🗑 Clear", self._compose_clear,  COLORS["accent_red"]),
        ]:
            tk.Button(editor_btns, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        right = make_card(pane, "⚙️  Compose Actions")
        right.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        for label, args, color in [
            ("⬆  Up (start all)",   ["compose", "up", "-d"],              COLORS["accent_green"]),
            ("⬆  Up (with build)",  ["compose", "up", "-d", "--build"],   COLORS["accent_green"]),
            ("⬇  Down (stop all)",  ["compose", "down"],                  COLORS["accent_red"]),
            ("⬇  Down (rm volumes)", ["compose", "down", "-v"],           COLORS["accent_red"]),
            ("🔄  Restart",         ["compose", "restart"],               COLORS["accent_orange"]),
            ("📋  PS (status)",     ["compose", "ps"],                    COLORS["accent"]),
            ("📜  Logs",            ["compose", "logs", "--tail=50"],     COLORS["accent"]),
            ("🏗  Build",           ["compose", "build"],                 COLORS["accent_purple"]),
            ("📦  Pull",            ["compose", "pull"],                  COLORS["accent"]),
        ]:
            tk.Button(right, text=label, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=14, pady=7,
                      anchor="w", cursor="hand2",
                      command=lambda a=args: self._compose_run(a)).pack(
                          fill="x", padx=8, pady=2)

        tk.Frame(right, bg=COLORS["border"], height=1).pack(fill="x", padx=8, pady=6)
        tk.Label(right, text="Output:", font=FONTS["heading"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]).pack(anchor="w", padx=8)
        self.compose_output = make_console(right, height=999)
        self.compose_output.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # ── LOGS TAB ──────────────────────────────

    def _build_tab_logs(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  📜  Logs  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Container Logs", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.logs_container_var = tk.StringVar()
        self.logs_container_combo = ttk.Combobox(
            tb, textvariable=self.logs_container_var,
            font=FONTS["mono_sm"], width=28)
        self.logs_container_combo.pack(side="right", padx=(4, 0))
        tk.Label(tb, text="Container:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(side="right")

        self.logs_tail = tk.IntVar(value=100)
        tk.Spinbox(tb, from_=10, to=10000, increment=10,
                   textvariable=self.logs_tail, width=6,
                   font=FONTS["mono_sm"],
                   bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                   buttonbackground=COLORS["bg_hover"]).pack(side="right", padx=4)
        tk.Label(tb, text="Tail:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(side="right")

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

    # ── NETWORK TAB ───────────────────────────

    def _build_tab_network(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  🌐  Networks  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Networks", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.new_net_name = tk.Entry(tb, font=FONTS["mono_sm"], width=20,
                                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                                     insertbackground=COLORS["accent"],
                                     relief="flat", bd=3,
                                     highlightbackground=COLORS["border"],
                                     highlightthickness=1)
        self.new_net_name.insert(0, "my-network")
        self.new_net_name.pack(side="right", padx=4)

        for txt, cmd, color in [
            ("+ Create",   lambda: network_create(self, self.new_net_name, self.networks_output),   COLORS["accent_green"]),
            ("📋 Inspect", lambda: network_inspect(self, self.networks_tree, self.networks_output),  COLORS["accent"]),
            ("🗑 Remove",  lambda: network_remove(self, self.networks_tree, self.networks_output),   COLORS["accent_red"]),
            ("🧹 Prune",   lambda: network_prune(self, self.networks_output),                       COLORS["accent_orange"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        cols_cfg = [("ID", 120), ("Name", 160), ("Driver", 80), ("Scope", 80), ("Subnet", 160)]
        self.networks_tree = make_tree(frame, cols_cfg)
        self.networks_tree.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.networks_output = make_console(out_card, height=6)
        self.networks_output.pack(fill="x", padx=8, pady=8)

        self._refresh_networks()

    # ── VOLUMES TAB ───────────────────────────

    def _build_tab_volumes(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  💾  Volumes  ")

        tb = tk.Frame(frame, bg=COLORS["bg_dark"])
        tb.pack(fill="x", padx=16, pady=12)
        tk.Label(tb, text="Volumes", font=FONTS["ui_lg"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(side="left")

        self.new_vol_name = tk.Entry(tb, font=FONTS["mono_sm"], width=20,
                                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                                     insertbackground=COLORS["accent"],
                                     relief="flat", bd=3,
                                     highlightbackground=COLORS["border"],
                                     highlightthickness=1)
        self.new_vol_name.insert(0, "my-volume")
        self.new_vol_name.pack(side="right", padx=4)

        for txt, cmd, color in [
            ("+ Create",   lambda: volume_create(self, self.new_vol_name, self.volumes_output),   COLORS["accent_green"]),
            ("📋 Inspect", lambda: volume_inspect(self, self.volumes_tree, self.volumes_output),   COLORS["accent"]),
            ("🗑 Remove",  lambda: volume_remove(self, self.volumes_tree, self.volumes_output),    COLORS["accent_red"]),
            ("🧹 Prune",   lambda: volume_prune(self, self.volumes_output),                       COLORS["accent_orange"]),
        ]:
            tk.Button(tb, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=5,
                      cursor="hand2", command=cmd).pack(side="right", padx=3)

        cols_cfg = [("Name", 200), ("Driver", 100), ("Mountpoint", 400)]
        self.volumes_tree = make_tree(frame, cols_cfg)
        self.volumes_tree.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        out_card = make_card(frame, "Output")
        out_card.pack(fill="x", padx=16, pady=(0, 12))
        self.volumes_output = make_console(out_card, height=6)
        self.volumes_output.pack(fill="x", padx=8, pady=8)

        self._refresh_volumes()

    # ── ADVANCED TAB ──────────────────────────

    def _build_tab_advanced(self):
        frame = tk.Frame(self.nb, bg=COLORS["bg_dark"])
        self.nb.add(frame, text="  ⚙  Advanced  ")

        tk.Label(frame, text="⚙  Advanced Power Tools",
                 font=FONTS["title"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(
                     anchor="w", padx=24, pady=(18, 2))
        tk.Label(frame, text="Direct command execution, Dockerfile builder, stats monitor",
                 font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(
                     anchor="w", padx=24, pady=(0, 12))

        style = ttk.Style()
        style.configure("Inner.TNotebook", background=COLORS["bg_dark"], borderwidth=0)
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
                 font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack(
                     anchor="w", padx=12, pady=8)

        cmd_row = tk.Frame(frame, bg=COLORS["bg_dark"])
        cmd_row.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(cmd_row, text="docker ", font=FONTS["mono"],
                 bg=COLORS["bg_dark"], fg=COLORS["accent"]).pack(side="left")
        self.terminal_cmd = tk.Entry(cmd_row, font=FONTS["mono"],
                                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                                     insertbackground=COLORS["accent"],
                                     relief="flat", bd=4,
                                     highlightbackground=COLORS["border"],
                                     highlightthickness=1)
        self.terminal_cmd.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.terminal_cmd.bind("<Return>", lambda _: self._terminal_run())
        tk.Button(cmd_row, text="▶ Run", font=FONTS["ui"],
                  bg=COLORS["accent"], fg="white",
                  relief="flat", bd=0, padx=16, pady=6,
                  cursor="hand2", command=self._terminal_run).pack(side="left")

        quick_frame = tk.Frame(frame, bg=COLORS["bg_dark"])
        quick_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(quick_frame, text="Quick:", font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_dim"]).pack(side="left", padx=(0, 8))
        for cmd in ["info", "version", "system df", "stats --no-stream", "ps -a", "images"]:
            tk.Button(quick_frame, text=cmd, font=FONTS["mono_sm"],
                      bg=COLORS["bg_hover"], fg=COLORS["text_secondary"],
                      relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                      command=lambda c=cmd: self._terminal_quick(c)).pack(side="left", padx=2)

        out_card = make_card(frame, "Output")
        out_card.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        # P3: "Copy command" button
        copy_row = tk.Frame(out_card, bg=COLORS["bg_card"])
        copy_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Button(copy_row, text="📋 Copy Output", font=FONTS["ui_sm"],
                  bg=COLORS["bg_hover"], fg=COLORS["accent"],
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                  command=lambda: self._copy_console_text(self.terminal_output)
                  ).pack(side="right")
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
            ("Image Tag:",    "build_tag",     "myapp:latest"),
            ("Build Context:", "build_context", "."),
            ("Build Args:",   "build_args",    "ARG1=value"),
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
                         highlightbackground=COLORS["border"], highlightthickness=1)
            e.insert(0, ph)
            e.pack(side="right", fill="x", expand=True)
            self.build_fields[key] = e

        tk.Frame(right, bg=COLORS["border"], height=1).pack(fill="x", padx=12, pady=8)
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
            ("MEM %", 80), ("NET I/O", 120), ("BLOCK I/O", 120), ("PIDs", 60)
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
                         highlightbackground=COLORS["border"], highlightthickness=1)
            e.insert(0, ph)
            e.pack(side="right", fill="x", expand=True)
            self.reg_fields[key] = e

        btn_row = tk.Frame(card, bg=COLORS["bg_card"])
        btn_row.pack(fill="x", padx=16, pady=8)
        for txt, cmd, color in [
            ("🔑 Login",  lambda: registry_login(self, self.reg_fields, self.reg_output),  COLORS["accent_green"]),
            ("🚪 Logout", lambda: registry_logout(self, self.reg_fields, self.reg_output), COLORS["accent_red"]),
            ("⬆ Push",   lambda: registry_push(self, self.reg_fields, self.reg_output),   COLORS["accent"]),
            ("⬇ Pull",   lambda: registry_pull(self, self.reg_fields, self.reg_output),   COLORS["accent"]),
        ]:
            tk.Button(btn_row, text=txt, font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=12, pady=6,
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        self.reg_output = make_console(card, height=10)
        self.reg_output.pack(fill="both", expand=True, padx=8, pady=8)

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
                          row=i // 2, column=i % 2, padx=4, pady=3, sticky="ew")
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        tk.Frame(card, bg=COLORS["border"], height=1).pack(fill="x", padx=12, pady=8)
        self.misc_output = make_console(card, height=999)
        self.misc_output.pack(fill="both", expand=True, padx=8, pady=8)

    # ── DOCKER CHECK & EVENTS (P1 #2) ─────────

    def _check_docker(self):
        def _check():
            ok = docker_available()
            if ok:
                self.after(0, lambda: self.docker_status_label.configure(
                    text="● Docker running", fg=COLORS["accent_green"]))
                self._set_status("Docker daemon is running")
            else:
                self.after(0, lambda: self.docker_status_label.configure(
                    text="● Docker not running", fg=COLORS["accent_red"]))
                self._set_status("⚠  Docker daemon is not running or not installed")
                self._show_error_notification(
                    "Docker daemon is not running. Start Docker and click Refresh All.",
                    icon="⚠", color=COLORS["accent_red"])
                # P3: first-run wizard
                if not docker_available():
                    self.after(0, self._show_install_wizard)
        safe_thread(_check)

    def _start_events_watcher(self):
        """
        P1 #2: Real docker events watcher.
        Parses JSON events; calls targeted refresh only on relevant events.
        Falls back to plain-text format if JSON unavailable.
        """
        REFRESH_CONTAINER_EVENTS = {
            "start", "stop", "die", "kill", "pause", "unpause",
            "destroy", "create", "rename",
        }
        REFRESH_IMAGE_EVENTS = {"pull", "push", "import", "delete", "tag", "untag"}
        REFRESH_VOLUME_EVENTS = {"create", "destroy", "prune", "mount", "unmount"}
        REFRESH_NETWORK_EVENTS = {"create", "destroy", "connect", "disconnect", "prune"}

        self._events_stop.clear()

        def _watch():
            while not self._events_stop.is_set():
                try:
                    proc = subprocess.Popen(
                        ["docker", "events", "--format", "{{json .}}"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1
                    )
                    for line in proc.stdout:
                        if self._events_stop.is_set():
                            proc.terminate()
                            return
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            evt_type   = event.get("Type", "")
                            evt_action = event.get("Action", "")
                        except (json.JSONDecodeError, ValueError):
                            # Fallback plain-text parsing
                            parts = line.split()
                            evt_type   = parts[0] if len(parts) > 0 else ""
                            evt_action = parts[1] if len(parts) > 1 else ""

                        # Targeted refresh based on event type+action
                        if evt_type == "container" and evt_action in REFRESH_CONTAINER_EVENTS:
                            self.after(300, self._refresh_containers)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "image" and evt_action in REFRESH_IMAGE_EVENTS:
                            self.after(300, self._refresh_images)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "volume" and evt_action in REFRESH_VOLUME_EVENTS:
                            self.after(300, self._refresh_volumes)
                            self.after(300, self._refresh_dashboard)
                        elif evt_type == "network" and evt_action in REFRESH_NETWORK_EVENTS:
                            self.after(300, self._refresh_networks)
                            self.after(300, self._refresh_dashboard)
                    proc.wait()
                except Exception:
                    pass
                # Docker daemon stopped — wait and retry
                if not self._events_stop.is_set():
                    time.sleep(10)

        safe_thread(_watch)

    # ── VERSION CHECK (P2 #8) ─────────────────

    def _check_for_updates(self):
        """Fetch latest DockerDeck release tag from GitHub and show toast if newer."""
        REPO = "docker/docker-ce"  # replace with actual DockerDeck repo
        def _do():
            try:
                from docker_runner import get_latest_github_release
                latest = get_latest_github_release(REPO)
                if latest and latest.lstrip("v") != __version__:
                    msg = f"Update available: {latest}  (you have v{__version__})"
                    self.after(2000, lambda: self._show_error_notification(
                        msg, icon="⬆", color=COLORS["accent_cyan"]))
            except Exception:
                pass
        safe_thread(_do)

    def on_close(self):
        self._events_stop.set()
        self.log_stop_event.set()
        self._stats_stop_event.set()
        self.destroy()

    # ── FIRST-RUN WIZARD (P3) ─────────────────

    def _show_install_wizard(self):
        dlg = tk.Toplevel(self)
        dlg.title("Docker Not Found")
        dlg.geometry("540x320")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()

        tk.Label(dlg, text="🐳  Docker Not Found",
                 font=FONTS["title"],
                 bg=COLORS["bg_dark"], fg=COLORS["accent_red"]).pack(pady=(24, 8))
        tk.Label(dlg,
                 text="DockerDeck requires Docker to be installed and running.\n"
                      "Please install Docker Desktop or Docker Engine and restart.",
                 font=FONTS["ui"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                 justify="center").pack(padx=24)

        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(fill="x", padx=32, pady=16)

        for platform, url, color in [
            ("🪟  Windows — Docker Desktop", "https://docs.docker.com/desktop/install/windows/", COLORS["accent"]),
            ("🍎  macOS  — Docker Desktop",  "https://docs.docker.com/desktop/install/mac/",     COLORS["accent"]),
            ("🐧  Linux  — Docker Engine",   "https://docs.docker.com/engine/install/",          COLORS["accent_green"]),
        ]:
            btn_row = tk.Frame(dlg, bg=COLORS["bg_dark"])
            btn_row.pack(fill="x", padx=32, pady=2)
            tk.Label(btn_row, text=platform, font=FONTS["ui"],
                     bg=COLORS["bg_dark"], fg=COLORS["text_primary"],
                     width=34, anchor="w").pack(side="left")
            tk.Button(btn_row, text="Open ↗", font=FONTS["ui_sm"],
                      bg=COLORS["bg_hover"], fg=color,
                      relief="flat", bd=0, padx=10, pady=4,
                      cursor="hand2",
                      command=lambda u=url: self._open_url(u)).pack(side="right")

        tk.Button(dlg, text="Dismiss", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_secondary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=16)

    def _open_url(self, url: str):
        import webbrowser
        webbrowser.open(url)

    # ── REFRESH METHODS ───────────────────────

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
            running = len([l for l in out.split("\n") if l.strip()]) if out else 0
            out2, _, _ = run_docker(["ps", "-aq"])
            total   = len([l for l in out2.split("\n") if l.strip()]) if out2 else 0
            stopped = total - running
            out3, _, _ = run_docker(["images", "-q"])
            images  = len([l for l in out3.split("\n") if l.strip()]) if out3 else 0
            out4, _, _ = run_docker(["volume", "ls", "-q"])
            volumes = len([l for l in out4.split("\n") if l.strip()]) if out4 else 0
            out5, _, _ = run_docker(["network", "ls", "-q"])
            networks = len([l for l in out5.split("\n") if l.strip()]) if out5 else 0

            def _upd():
                self.stat_cards["containers_running"]._value_label.configure(text=str(running))
                self.stat_cards["containers_stopped"]._value_label.configure(text=str(stopped))
                self.stat_cards["images_total"]._value_label.configure(text=str(images))
                self.stat_cards["volumes_total"]._value_label.configure(text=str(volumes))
                self.stat_cards["networks_total"]._value_label.configure(text=str(networks))
                out6, _, _ = run_docker(["ps", "--format",
                                         "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])
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
                tree.tag_configure("running", foreground=COLORS["accent_green"])
                tree.tag_configure("stopped", foreground=COLORS["accent_red"])
            self.after(0, _upd)
        safe_thread(_do)

    def _refresh_images(self):
        tree = get_tree_widget(self.images_tree)
        if not tree:
            return
        def _do():
            out, _, _ = run_docker(["images", "--format",
                                    "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}"])
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
            out, _, _ = run_docker(["network", "ls", "--format",
                                    "{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}"])
            rows = []
            for line in out.split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                while len(parts) < 4:
                    parts.append("")
                isp_out, _, _ = run_docker(["network", "inspect", parts[0],
                                             "--format",
                                             "{{range .IPAM.Config}}{{.Subnet}}{{end}}"])
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
            out, _, _ = run_docker(["volume", "ls", "--format",
                                    "{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}"])
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
            out, _, _ = run_docker(["ps", "-a", "--format", "{{.Names}}"])
            names = [n for n in out.split("\n") if n.strip()]
            def _upd():
                self.logs_container_combo["values"] = names
                if names and not self.logs_container_var.get():
                    self.logs_container_combo.set(names[0])
            self.after(0, _upd)
        safe_thread(_do)

    # ── DEPLOY FIELD VALIDATION ───────────────

    def _validate_deploy_field(self, key: str) -> bool:
        ok = validate_field(key, self.deploy_fields, self._deploy_indicators)
        self._update_deploy_preview()
        return ok

    def _update_deploy_preview(self):
        try:
            cmd = build_run_command(self.deploy_fields, self.deploy_detach.get())
            console_write(self.deploy_preview, " ".join(cmd), clear=True)
        except Exception:
            pass

    def _copy_deploy_command(self):
        try:
            cmd = build_run_command(self.deploy_fields, self.deploy_detach.get())
            self.clipboard_clear()
            self.clipboard_append(" ".join(cmd))
            self._show_success_notification("Command copied to clipboard.")
        except Exception:
            pass

    def _copy_console_text(self, widget):
        widget.configure(state="normal")
        text = widget.get("1.0", "end")
        widget.configure(state="disabled")
        self.clipboard_clear()
        self.clipboard_append(text)
        self._show_success_notification("Output copied to clipboard.")

    def _deploy_container(self):
        deploy_container(self, self.deploy_fields, self.deploy_detach,
                         self.deploy_output, self._set_status)

    # ── PRESETS ───────────────────────────────

    def _refresh_presets_combo(self):
        if hasattr(self, "preset_combo"):
            self.preset_combo["values"] = list(self.presets.keys())

    def _deploy_save_preset(self):
        preset_save(self, self.presets, self.deploy_fields,
                    self.deploy_detach, self._refresh_presets_combo,
                    ask_input, self._show_success_notification)

    def _deploy_load_preset(self):
        preset_load(self, self.presets, self.preset_var,
                    self.deploy_fields, self.deploy_detach,
                    self._validate_deploy_field)

    def _deploy_delete_preset(self):
        preset_delete(self.presets, self.preset_var, self._refresh_presets_combo)

    # ── COMPOSE ACTIONS ───────────────────────

    def _compose_run(self, base_args: list):
        path = self.compose_path.get().strip()
        if path and os.path.exists(path):
            cwd  = os.path.dirname(os.path.abspath(path))
            args = ["-f", os.path.basename(path)] + base_args
        else:
            cwd  = None
            args = base_args

        def _do():
            self.after(0, lambda: console_write(
                self.compose_output,
                f"$ docker {' '.join(args)}\n  cwd: {cwd or '(not set)'}\n\n",
                clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(self.compose_output, l))
            run_docker_stream(args, cb, cwd=cwd)
        safe_thread(_do)

    def _browse_compose(self):
        path = filedialog.askopenfilename(
            title="Select docker-compose.yml",
            filetypes=[("YAML files", "*.yml *.yaml"), ("All files", "*.*")])
        if path:
            self.compose_path.set(path)
            with open(path) as f:
                content = f.read()
            self.compose_editor.delete("1.0", "end")
            self.compose_editor.insert("1.0", content)

    def _compose_save(self):
        path = self.compose_path.get().strip()
        content = self.compose_editor.get("1.0", "end")
        try:
            with open(path, "w") as f:
                f.write(content)
            self._show_success_notification(f"Compose file saved: {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _compose_clear(self):
        self.compose_editor.delete("1.0", "end")

    # ── LOGS ACTIONS ──────────────────────────

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
                self.logs_text, f"=== Following logs: {name} ===\n", clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(self.logs_text, l))
            run_docker_stream(["logs", "-f", "--tail", "50", name], cb,
                              stop_event=self.log_stop_event)
        safe_thread(_do)

    def _stop_follow(self):
        self.log_stop_event.set()

    def _clear_logs(self):
        console_write(self.logs_text, "", clear=True)

    # ── ADVANCED ──────────────────────────────

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
        from validation import validate_image_name
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
            self.after(0, lambda: console_write(
                self.build_output, f"Error saving Dockerfile: {e}\n"))
            return

        args = ["build", "-t", tag, "-f", df_path]
        if ba_raw:
            for ba in ba_raw.split(","):
                args += ["--build-arg", ba.strip()]
        args.append(context)

        def _do():
            self.after(0, lambda: console_write(
                self.build_output, f"$ docker {' '.join(args)}\n\n", clear=True))
            def cb(line):
                self.after(0, lambda l=line: console_write(self.build_output, l))
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
            filetypes=[("Dockerfile", "Dockerfile*"), ("All files", "*.*")])
        if path:
            content = self.dockerfile_editor.get("1.0", "end")
            with open(path, "w") as f:
                f.write(content)
            self._show_success_notification(f"Dockerfile saved: {path}")

    def _dockerfile_load(self):
        path = filedialog.askopenfilename(
            title="Open Dockerfile",
            filetypes=[("Dockerfile", "Dockerfile*"), ("All files", "*.*")])
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
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"
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

    # ── QUICK DASHBOARD ACTIONS ───────────────

    def _quick_start(self):
        name = ask_input(self, "Start Container", "Container name or ID:", "")
        if name:
            def _do():
                out, err, rc = run_docker(["start", name])
                self.after(0, lambda: console_write(
                    self.dash_containers_text, f"[start {name}] {out or err}\n"))
            safe_thread(_do)

    def _quick_stop(self):
        name = ask_input(self, "Stop Container", "Container name or ID:", "")
        if name:
            def _do():
                out, err, rc = run_docker(["stop", name])
                self.after(0, lambda: console_write(
                    self.dash_containers_text, f"[stop {name}] {out or err}\n"))
            safe_thread(_do)

    def _quick_restart(self):
        name = ask_input(self, "Restart Container", "Container name or ID:", "")
        if name:
            safe_thread(run_docker, ["restart", name])

    def _prune_stopped(self):
        if messagebox.askyesno("Prune Stopped", "Remove all stopped containers?"):
            safe_thread(run_docker, ["container", "prune", "-f"])

    def _quick_pull(self):
        dlg = tk.Toplevel(self)
        dlg.title("Pull Image")
        dlg.geometry("400x130")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.grab_set()
        tk.Label(dlg, text="Image name:tag", font=FONTS["ui"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_primary"]).pack(padx=20, pady=(16, 4))
        e = tk.Entry(dlg, font=FONTS["mono"], width=34,
                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                     insertbackground=COLORS["accent"], relief="flat", bd=4,
                     highlightbackground=COLORS["border"], highlightthickness=1)
        e.insert(0, "nginx:latest")
        e.pack(padx=20, fill="x")
        def do_pull():
            img = e.get().strip()
            dlg.destroy()
            if img:
                self.pull_entry.delete(0, "end")
                self.pull_entry.insert(0, img)
                self.nb.select(2)
                image_pull(self, self.pull_entry, self.images_output, self._set_status)
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
                out, err, rc = run_docker(["system", "prune", "-f"])
                self._set_status("System prune complete")
            safe_thread(_do)

    # ── EVENT HANDLERS ────────────────────────

    def _on_container_select(self, _):
        tree = get_tree_widget(self.containers_tree)
        sel = tree.selection()
        if sel:
            self.selected_container.set(tree.item(sel[0])["values"][1])

    def _on_image_select(self, _):
        tree = get_tree_widget(self.images_tree)
        sel = tree.selection()
        if sel:
            vals = tree.item(sel[0])["values"]
            self.selected_image.set(f"{vals[0]}:{vals[1]}")

    # ── UTILITIES ─────────────────────────────

    def _set_status(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.after(0, lambda: self.status_bar.configure(text=f"[{ts}]  {msg}"))

    # ── ABOUT DIALOG ──────────────────────────

    def _show_about(self):
        dlg = tk.Toplevel(self)
        dlg.title("About DockerDeck")
        dlg.geometry("440x300")
        dlg.configure(bg=COLORS["bg_dark"])
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="🐳  DockerDeck",
                 font=("Segoe UI", 20, "bold"),
                 bg=COLORS["bg_dark"], fg=COLORS["accent"]).pack(pady=(24, 4))
        tk.Label(dlg, text=f"Version {__version__}",
                 font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"]).pack()
        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(fill="x", padx=32, pady=12)

        from actions.deploy import PRESETS_PATH
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

        tk.Frame(dlg, bg=COLORS["border"], height=1).pack(fill="x", padx=32, pady=12)
        tk.Label(dlg,
                 text="Production-grade Docker GUI\nPure Python stdlib — no pip required.",
                 font=FONTS["ui_sm"],
                 bg=COLORS["bg_dark"], fg=COLORS["text_secondary"],
                 justify="center").pack(pady=(0, 8))
        tk.Button(dlg, text="Close", font=FONTS["ui"],
                  bg=COLORS["bg_hover"], fg=COLORS["text_primary"],
                  relief="flat", bd=0, padx=20, pady=6,
                  command=dlg.destroy).pack(pady=4)
