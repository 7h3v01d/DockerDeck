"""
DockerDeck – ui_components.py
Reusable widget factory helpers used across all tabs.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from utils import COLORS, FONTS


def make_card(parent, title: str = "") -> tk.Frame:
    """Return a styled card frame, with optional header title."""
    outer = tk.Frame(
        parent, bg=COLORS["bg_card"],
        highlightbackground=COLORS["border"],
        highlightthickness=1
    )
    if title:
        hdr = tk.Frame(outer, bg=COLORS["bg_card"])
        hdr.pack(fill="x")
        tk.Label(
            hdr, text=title, font=FONTS["heading"],
            bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
        ).pack(side="left", padx=12, pady=6)
        tk.Frame(outer, bg=COLORS["border"], height=1).pack(fill="x")
    return outer


def make_console(parent, height: int = 8) -> scrolledtext.ScrolledText:
    """Return a styled read-only console ScrolledText."""
    txt = scrolledtext.ScrolledText(
        parent, font=FONTS["mono_sm"], height=height,
        bg=COLORS["bg_input"], fg=COLORS["text_primary"],
        insertbackground=COLORS["accent"],
        selectbackground=COLORS["accent"],
        relief="flat", bd=4, state="normal",
        highlightbackground=COLORS["border"], highlightthickness=1
    )
    return txt


def make_tree(parent, columns: list, multiselect: bool = False) -> tk.Frame:
    """
    Return a styled Treeview wrapped in a Frame with scrollbars.
    columns: list of (name, width) tuples.
    """
    style = ttk.Style()
    style.configure(
        "DockerTree.Treeview",
        background=COLORS["bg_card"],
        fieldbackground=COLORS["bg_card"],
        foreground=COLORS["text_primary"],
        font=FONTS["mono_sm"],
        rowheight=26,
        borderwidth=0,
        relief="flat"
    )
    style.configure(
        "DockerTree.Treeview.Heading",
        background=COLORS["bg_hover"],
        foreground=COLORS["text_secondary"],
        font=FONTS["ui_sm"],
        relief="flat"
    )
    style.map(
        "DockerTree.Treeview",
        background=[("selected", COLORS["accent"])],
        foreground=[("selected", "white")]
    )

    frame = tk.Frame(
        parent, bg=COLORS["bg_dark"],
        highlightbackground=COLORS["border"],
        highlightthickness=1
    )
    col_ids = [c[0] for c in columns]
    sel_mode = "extended" if multiselect else "browse"
    tree = ttk.Treeview(
        frame, columns=col_ids, show="headings",
        style="DockerTree.Treeview",
        selectmode=sel_mode
    )
    for col_name, width in columns:
        tree.heading(col_name, text=col_name)
        tree.column(col_name, width=width, minwidth=40)

    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame


def get_tree_widget(frame_or_tree) -> ttk.Treeview:
    """Extract the Treeview widget from a frame wrapper."""
    if isinstance(frame_or_tree, ttk.Treeview):
        return frame_or_tree
    for child in frame_or_tree.winfo_children():
        if isinstance(child, ttk.Treeview):
            return child
    return None


def make_stat_card(parent, label: str, value: str, color: str) -> tk.Frame:
    """Return a dashboard stat card widget. Exposes ._value_label for updates."""
    card = tk.Frame(
        parent, bg=COLORS["bg_card"],
        highlightbackground=COLORS["border"],
        highlightthickness=1
    )
    tk.Label(
        card, text=label, font=FONTS["ui_sm"],
        bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
    ).pack(anchor="w", padx=14, pady=(10, 2))
    val_lbl = tk.Label(
        card, text=value, font=("Segoe UI", 26, "bold"),
        bg=COLORS["bg_card"], fg=color
    )
    val_lbl.pack(anchor="w", padx=14, pady=(0, 10))
    card._value_label = val_lbl
    return card


def console_write(widget: scrolledtext.ScrolledText,
                  text: str, clear: bool = False) -> None:
    """Append (or replace) text in a ScrolledText console widget."""
    widget.configure(state="normal")
    if clear:
        widget.delete("1.0", "end")
    widget.insert("end", text)
    widget.see("end")
    widget.configure(state="disabled")


def make_icon_button(parent, text: str, command, color: str,
                     font=None, padx: int = 10, pady: int = 5) -> tk.Button:
    """Return a flat styled button."""
    return tk.Button(
        parent, text=text,
        font=font or FONTS["ui_sm"],
        bg=COLORS["bg_hover"], fg=color,
        relief="flat", bd=0,
        padx=padx, pady=pady,
        cursor="hand2",
        activebackground=COLORS["border"],
        activeforeground=color,
        command=command
    )


def ask_input(root, title: str, prompt: str, default: str = "") -> str:
    """
    Show a modal single-line input dialog.
    Returns the entered string, or None if cancelled.
    """
    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.geometry("420x130")
    dlg.configure(bg=COLORS["bg_dark"])
    dlg.grab_set()
    result = {"value": None}

    tk.Label(
        dlg, text=prompt, font=FONTS["ui"],
        bg=COLORS["bg_dark"], fg=COLORS["text_primary"]
    ).pack(padx=20, pady=(14, 4))

    e = tk.Entry(
        dlg, font=FONTS["mono"], width=34,
        bg=COLORS["bg_input"], fg=COLORS["text_primary"],
        insertbackground=COLORS["accent"],
        relief="flat", bd=4,
        highlightbackground=COLORS["border"],
        highlightthickness=1
    )
    e.insert(0, default)
    e.select_range(0, "end")
    e.pack(padx=20, fill="x")

    def ok():
        result["value"] = e.get().strip()
        dlg.destroy()

    e.bind("<Return>", lambda _: ok())
    tk.Button(
        dlg, text="OK", font=FONTS["ui"],
        bg=COLORS["accent"], fg="white",
        relief="flat", bd=0, padx=16, pady=5,
        command=ok
    ).pack(pady=10)

    dlg.wait_window()
    return result["value"]
