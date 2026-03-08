"""
DockerDeck – actions/deploy.py
Deploy logic: validation, command building, presets.
NO tkinter imports — fully testable without a display.
"""

import json
from pathlib import Path

from docker_runner import run_docker_stream
from validation import (
    validate_image_name, validate_container_name,
    validate_ports, validate_env_vars, validate_volumes,
    validate_extra_args, ValidationError,
)
from utils import safe_thread

PRESETS_PATH = Path.home() / ".dockerdeck_presets.json"

# Map field key -> validator (None = free text, no validation)
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


def validate_field(key: str, value: str) -> tuple:
    """
    Validate a single deploy field value.
    Returns (is_valid: bool, error_msg: str).
    Pure function — no side effects, no UI.
    """
    vfn = FIELD_VALIDATORS.get(key)
    if vfn is None or not value.strip():
        return True, ""
    try:
        vfn(value.strip())
        return True, ""
    except ValidationError as e:
        return False, str(e)


def validate_all_fields(field_values: dict) -> tuple:
    """
    Validate all deploy fields.
    field_values: {key: str_value}
    Returns (ok: bool, error_msg: str).
    """
    for key, vfn in FIELD_VALIDATORS.items():
        if vfn is None:
            continue
        val = field_values.get(key, "").strip()
        if not val:
            continue
        try:
            vfn(val)
        except ValidationError as e:
            return False, f"Field '{key}' invalid:\n{e}"
    return True, ""


def build_run_command(field_values: dict, detach: bool) -> list:
    """
    Build ['docker', 'run', …] arg list from a plain dict of string values.
    Raises ValidationError on any invalid input.
    Pure function — no UI, no side effects.
    """
    f = field_values
    cmd = ["docker", "run"]
    if detach:
        cmd.append("-d")

    name = validate_container_name(f.get("deploy_name", ""))
    if name:
        cmd += ["--name", name]

    ports_raw = f.get("deploy_ports", "").strip()
    if ports_raw:
        for p in validate_ports(ports_raw):
            cmd += ["-p", p]

    env_raw = f.get("deploy_env", "").strip()
    if env_raw:
        for e in validate_env_vars(env_raw):
            cmd += ["-e", e]

    vol_raw = f.get("deploy_volumes", "").strip()
    if vol_raw:
        for v in validate_volumes(vol_raw):
            cmd += ["-v", v]

    net = f.get("deploy_network", "").strip()
    if net:
        cmd += ["--network", net]

    restart = f.get("deploy_restart", "").strip()
    if restart:
        cmd += ["--restart", restart]

    extra_raw = f.get("deploy_extra", "").strip()
    if extra_raw:
        cmd += validate_extra_args(extra_raw)

    image_raw = f.get("deploy_image", "").strip()
    if image_raw:
        cmd.append(validate_image_name(image_raw))

    return cmd


def deploy_exec(root, docker_args: list, output_fn, status_fn=None) -> None:
    """
    Execute docker run in a background thread.
    docker_args: everything after 'docker' (i.e. ['run', '-d', ...])
    output_fn(text, clear=False): called on main thread to write output.
    """
    full_cmd = ["docker"] + docker_args

    def _do():
        if status_fn:
            status_fn("Deploying container…")
        root.after(0, lambda: output_fn(
            f"$ {' '.join(full_cmd)}\n\n", clear=True))
        def cb(line):
            root.after(0, lambda l=line: output_fn(l))
        rc = run_docker_stream(docker_args, cb)
        root.after(0, lambda: output_fn(f"\n--- Done (rc={rc}) ---\n"))
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
    """Save presets to disk. Raises OSError on failure."""
    PRESETS_PATH.write_text(json.dumps(presets, indent=2))


def get_field_values(deploy_fields: dict) -> dict:
    """Extract {key: str} from a dict of tkinter Entry widgets."""
    return {k: e.get() for k, e in deploy_fields.items()}
