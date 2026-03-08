"""
DockerDeck – actions/containers.py
Container actions: pure business logic.
NO tkinter imports — fully testable without a display.
UI callbacks (confirm dialogs, error messages) are passed in by app.py.
"""

from docker_runner import run_docker, run_docker_stream
from validation import validate_container_name, ValidationError
from utils import safe_thread


def get_selected_names(tree_widget) -> list:
    """Return list of container names for all selected tree rows."""
    return [tree_widget.item(s)["values"][1] for s in tree_widget.selection()]


def container_action(root, action: str, name: str,
                     output_fn, status_fn=None) -> None:
    """Run docker <action> <n> and deliver result to output_fn."""
    def _do():
        if status_fn:
            status_fn(f"Running: docker {action} {name}")
        out, err, rc = run_docker([action, name])
        msg = out or err or f"{action} completed"
        root.after(0, lambda: output_fn(
            f"[{action} {name}]  rc={rc}\n{msg}\n\n"))
    safe_thread(_do)


def container_start(root, names: list, output_fn) -> None:
    for n in names:
        container_action(root, "start", n, output_fn)


def container_stop(root, names: list, output_fn) -> None:
    for n in names:
        container_action(root, "stop", n, output_fn)


def container_restart(root, names: list, output_fn) -> None:
    for n in names:
        container_action(root, "restart", n, output_fn)


def container_stop_all(root, names: list, output_fn) -> None:
    """Bulk stop. Caller must confirm before calling."""
    def _do():
        for n in names:
            out, err, rc = run_docker(["stop", n])
            root.after(0, lambda n=n, out=out, err=err, rc=rc:
                output_fn(f"[stop {n}] rc={rc} {out or err}\n"))
    safe_thread(_do)


def container_inspect(root, name: str, output_fn) -> None:
    def _do():
        out, err, _ = run_docker(["inspect", name])
        root.after(0, lambda: output_fn(
            f"=== inspect {name} ===\n{out or err}\n\n"))
    safe_thread(_do)


def container_rename_exec(root, old_name: str, new_name: str,
                           output_fn) -> None:
    """Perform rename. Validation must be done before calling."""
    def _do():
        out, err, rc = run_docker(["rename", old_name, new_name])
        root.after(0, lambda: output_fn(
            f"[rename {old_name} → {new_name}] rc={rc} {out or err}\n\n"))
    safe_thread(_do)


def container_cp_exec(root, src: str, dst: str, output_fn) -> None:
    """Execute docker cp. Paths must be validated before calling."""
    def _do():
        out, err, rc = run_docker(["cp", src, dst])
        root.after(0, lambda: output_fn(
            f"[cp {src} → {dst}] rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def container_remove(root, names: list, output_fn) -> None:
    """Remove containers. Caller must confirm before calling."""
    def _do():
        for n in names:
            out, err, rc = run_docker(["rm", "-f", n])
            root.after(0, lambda n=n, out=out, err=err, rc=rc:
                output_fn(f"[rm {n}] rc={rc} {out or err}\n"))
    safe_thread(_do)


def get_shell_command(name: str) -> str:
    """Return the shell exec command string for display."""
    return f"docker exec -it {name} sh"
