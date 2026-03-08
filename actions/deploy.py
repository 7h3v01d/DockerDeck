"""
DockerDeck – actions/deploy.py
Deploy tab logic: field validation, command building, container deployment, presets.
"""

import json
from pathlib import Path
from tkinter import messagebox

from docker_runner import run_docker_stream
from validation import (
    validate_image_name, validate_container_name,
    validate_ports, validate_env_vars, validate_volumes,
    validate_extra_args, ValidationError
)
from utils import safe_thread, COLORS
from ui_components import console_write

PRESETS_PATH = Path.home() / ".dockerdeck_presets.json"

# Field key → validator function (None = no validation)
FIELD_VALIDATORS = {
    "deploy_image":   validate_image_name,
    "deploy_name":    validate_container_name,
    "deploy_ports":   validate_ports,
    "deploy_env":     validate_env_vars,
    "deploy_volumes": validate_volumes,
    "deploy_network": None,
    "deploy_restart": None,
    "deploy_extra":   validate_extra_args,
}


def validate_field(key: str, deploy_fields: dict,
                   indicators: dict) -> bool:
    """
    Validate a single deploy field.
    Updates the indicator dot color.
    Returns True if valid, False if invalid.
    """
    e    = deploy_fields[key]
    dot  = indicators[key]
    vfn  = FIELD_VALIDATORS.get(key)
    val  = e.get().strip()

    if vfn is None or not val:
        dot.configure(fg=COLORS["text_dim"])
        e.configure(highlightbackground=COLORS["border"])
        return True
    try:
        vfn(val)
        dot.configure(fg=COLORS["accent_green"])
        e.configure(highlightbackground=COLORS["border"])
        return True
    except ValidationError:
        dot.configure(fg=COLORS["accent_red"])
        e.configure(highlightbackground=COLORS["accent_red"])
        return False


def validate_all_fields(deploy_fields: dict) -> tuple:
    """Validate all deploy fields. Returns (ok: bool, error_msg: str)."""
    for key, vfn in FIELD_VALIDATORS.items():
        if vfn is None:
            continue
        val = deploy_fields[key].get().strip()
        if not val:
            continue
        try:
            vfn(val)
        except ValidationError as e:
            return False, f"Field validation failed:\n{e}"
    return True, ""


def build_run_command(deploy_fields: dict, detach: bool) -> list:
    """
    Build the 'docker run …' argument list from form fields.
    Raises ValidationError on any invalid input.
    Returns a list starting with 'docker'.
    """
    f = deploy_fields
    cmd = ["docker", "run"]
    if detach:
        cmd.append("-d")

    name = validate_container_name(f["deploy_name"].get())
    if name:
        cmd += ["--name", name]

    ports_raw = f["deploy_ports"].get().strip()
    if ports_raw:
        for p in validate_ports(ports_raw):
            cmd += ["-p", p]

    env_raw = f["deploy_env"].get().strip()
    if env_raw:
        for e in validate_env_vars(env_raw):
            cmd += ["-e", e]

    vol_raw = f["deploy_volumes"].get().strip()
    if vol_raw:
        for v in validate_volumes(vol_raw):
            cmd += ["-v", v]

    net = f["deploy_network"].get().strip()
    if net:
        cmd += ["--network", net]

    restart = f["deploy_restart"].get().strip()
    if restart:
        cmd += ["--restart", restart]

    extra_raw = f["deploy_extra"].get().strip()
    if extra_raw:
        cmd += validate_extra_args(extra_raw)

    image_raw = f["deploy_image"].get().strip()
    if image_raw:
        cmd.append(validate_image_name(image_raw))

    return cmd


def deploy_container(root, deploy_fields: dict, detach_var,
                     output_widget, status_fn=None) -> None:
    """Validate → confirm → execute docker run."""
    ok, err_msg = validate_all_fields(deploy_fields)
    if not ok:
        messagebox.showerror("Validation Error", err_msg, parent=root)
        return

    try:
        cmd = build_run_command(deploy_fields, detach_var.get())
    except ValidationError as e:
        messagebox.showerror("Validation Error", str(e), parent=root)
        return

    # Confirmation with full command preview
    preview = " ".join(cmd)
    if not messagebox.askyesno(
        "Confirm Deploy",
        f"Execute this command?\n\n{preview}\n\nEnsure you trust all input values.",
        parent=root
    ):
        return

    docker_args = cmd[1:]  # strip 'docker' prefix for run_docker_stream

    def _do():
        if status_fn:
            status_fn("Deploying container…")
        root.after(0, lambda: console_write(
            output_widget,
            f"$ {' '.join(cmd)}\n\n", clear=True))
        def cb(line):
            root.after(0, lambda l=line: console_write(output_widget, l))
        rc = run_docker_stream(docker_args, cb)
        root.after(0, lambda: console_write(
            output_widget, f"\n--- Done (rc={rc}) ---\n"))
        if status_fn:
            status_fn("Deploy complete")
    safe_thread(_do)


# ── PRESETS ───────────────────────────────────

def load_presets() -> dict:
    if PRESETS_PATH.exists():
        try:
            return json.loads(PRESETS_PATH.read_text())
        except Exception:
            pass
    return {}


def save_presets(presets: dict) -> None:
    try:
        PRESETS_PATH.write_text(json.dumps(presets, indent=2))
    except Exception as e:
        messagebox.showerror("Preset Error", f"Could not save presets: {e}")


def preset_save(root, presets: dict, deploy_fields: dict,
                detach_var, combo_refresh_fn,
                ask_input_fn, success_fn=None) -> None:
    name = ask_input_fn(root, "Save Preset", "Preset name:", "")
    if not name:
        return
    presets[name] = {k: e.get() for k, e in deploy_fields.items()}
    presets[name]["__detach"] = detach_var.get()
    save_presets(presets)
    combo_refresh_fn()
    if success_fn:
        success_fn(f"Preset '{name}' saved.")


def preset_load(root, presets: dict, preset_var,
                deploy_fields: dict, detach_var, validate_fn) -> None:
    name = preset_var.get()
    if name not in presets:
        messagebox.showinfo("Presets",
                            "Select a preset from the dropdown first.", parent=root)
        return
    data = presets[name]
    for k, e in deploy_fields.items():
        e.delete(0, "end")
        e.insert(0, data.get(k, ""))
        if validate_fn:
            validate_fn(k)
    detach_var.set(data.get("__detach", True))


def preset_delete(presets: dict, preset_var,
                  combo_refresh_fn) -> None:
    name = preset_var.get()
    if name in presets:
        del presets[name]
        save_presets(presets)
        combo_refresh_fn()
        preset_var.set("")
