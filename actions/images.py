"""
DockerDeck – actions/images.py
Image actions: pure business logic. NO tkinter imports.
"""

from docker_runner import run_docker, run_docker_stream
from validation import validate_image_name, ValidationError
from utils import safe_thread


def image_pull_exec(root, image: str, output_fn, status_fn=None) -> None:
    """Pull an image. image must already be validated."""
    def _do():
        if status_fn:
            status_fn(f"Pulling {image}…")
        output_fn(f"Pulling {image}…\n", clear=True)
        def cb(line):
            root.after(0, lambda l=line: output_fn(l))
        run_docker_stream(["pull", image], cb)
        if status_fn:
            status_fn(f"Pull complete: {image}")
    safe_thread(_do)


def image_inspect_exec(root, image_id: str, output_fn) -> None:
    def _do():
        out, err, _ = run_docker(["inspect", image_id])
        root.after(0, lambda: output_fn(
            f"=== inspect {image_id} ===\n{out or err}\n\n"))
    safe_thread(_do)


def image_remove_exec(root, image_id: str, display_name: str,
                       output_fn) -> None:
    """Remove an image. Caller must confirm before calling."""
    def _do():
        out, err, rc = run_docker(["rmi", image_id])
        root.after(0, lambda: output_fn(
            f"[rmi {display_name}]  rc={rc}\n{out or err}\n\n"))
    safe_thread(_do)


def image_prune_exec(root, output_fn) -> None:
    """Prune dangling images. Caller must confirm."""
    def _do():
        out, err, rc = run_docker(["image", "prune", "-f"])
        root.after(0, lambda: output_fn(
            f"[image prune]\n{out or err}\n\n"))
    safe_thread(_do)
