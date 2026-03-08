"""
DockerDeck – actions/registry.py
Registry login/push/pull: pure business logic. NO tkinter imports.
SECURITY: passwords never in CLI args, zeroed from memory after use.
"""

from docker_runner import run_docker, run_docker_stream, run_docker_login
from validation import validate_image_name, ValidationError
from utils import safe_thread


def registry_login_exec(root, url: str, user: str, password: str,
                          output_fn) -> None:
    """
    SECURITY: Password piped via stdin only.
    The caller MUST wipe the entry widget before calling this.
    """
    args = (["login", url, "-u", user, "--password-stdin"] if url and url != "docker.io"
            else ["login", "-u", user, "--password-stdin"])

    def _do():
        def cb(text):
            root.after(0, lambda t=text: output_fn(t))
        run_docker_login(args, password, cb)
    safe_thread(_do)


def registry_logout_exec(root, url: str, output_fn) -> None:
    def _do():
        out, err, rc = run_docker(["logout", url])
        root.after(0, lambda: output_fn(f"{out or err}\n"))
    safe_thread(_do)


def registry_push_exec(root, src: str, dst: str, output_fn) -> None:
    """Both src and dst must be pre-validated image names."""
    def _do():
        if src != dst:
            out, err, rc = run_docker(["tag", src, dst])
            root.after(0, lambda: output_fn(f"[tag] {out or err}\n"))
        root.after(0, lambda: output_fn(f"Pushing {dst}…\n"))
        def cb(line):
            root.after(0, lambda l=line: output_fn(l))
        run_docker_stream(["push", dst], cb)
    safe_thread(_do)


def registry_pull_exec(root, img: str, output_fn) -> None:
    """img must be a pre-validated image name."""
    def _do():
        def cb(line):
            root.after(0, lambda l=line: output_fn(l))
        run_docker_stream(["pull", img], cb)
    safe_thread(_do)
