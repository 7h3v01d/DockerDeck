"""
DockerDeck – actions/network_volume.py
Network and Volume actions: pure business logic. NO tkinter imports.
"""

from docker_runner import run_docker
from utils import safe_thread


# ── NETWORKS ──────────────────────────────────

def network_create(root, name: str, output_fn) -> None:
    def _do():
        out, err, rc = run_docker(["network", "create", name])
        root.after(0, lambda: output_fn(
            f"[network create {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def network_inspect(root, name: str, output_fn) -> None:
    def _do():
        out, err, _ = run_docker(["network", "inspect", name])
        root.after(0, lambda: output_fn(
            f"=== inspect {name} ===\n{out or err}\n\n"))
    safe_thread(_do)


def network_remove(root, name: str, output_fn) -> None:
    """Caller must confirm before calling."""
    def _do():
        out, err, rc = run_docker(["network", "rm", name])
        root.after(0, lambda: output_fn(
            f"[network rm {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def network_prune(root, output_fn) -> None:
    """Caller must confirm before calling."""
    def _do():
        out, err, rc = run_docker(["network", "prune", "-f"])
        root.after(0, lambda: output_fn(
            f"[network prune]\n{out or err}\n\n"))
    safe_thread(_do)


# ── VOLUMES ───────────────────────────────────

def volume_create(root, name: str, output_fn) -> None:
    def _do():
        out, err, rc = run_docker(["volume", "create", name])
        root.after(0, lambda: output_fn(
            f"[volume create {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def volume_inspect(root, name: str, output_fn) -> None:
    def _do():
        out, err, _ = run_docker(["volume", "inspect", name])
        root.after(0, lambda: output_fn(
            f"=== inspect {name} ===\n{out or err}\n\n"))
    safe_thread(_do)


def volume_remove(root, name: str, output_fn) -> None:
    """Caller must confirm before calling."""
    def _do():
        out, err, rc = run_docker(["volume", "rm", name])
        root.after(0, lambda: output_fn(
            f"[volume rm {name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def volume_prune(root, output_fn) -> None:
    """Caller must confirm before calling."""
    def _do():
        out, err, rc = run_docker(["volume", "prune", "-f"])
        root.after(0, lambda: output_fn(
            f"[volume prune]\n{out or err}\n\n"))
    safe_thread(_do)
