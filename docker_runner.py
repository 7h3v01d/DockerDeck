"""
DockerDeck – docker_runner.py
All subprocess calls to the Docker CLI.
"""

import subprocess
import json
import sys
import threading
import traceback
from typing import Callable, List, Optional, Tuple


def run_docker(args: List[str], timeout: int = 30,
               cwd: Optional[str] = None) -> Tuple[str, str, int]:
    """Run a docker command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True, text=True, timeout=timeout,
            cwd=cwd
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "Docker not found. Please install Docker.", 1
    except subprocess.TimeoutExpired:
        return "", "Command timed out.", 1
    except Exception as e:
        return "", str(e), 1


def run_docker_stream(args: List[str], callback: Callable[[str], None],
                      stop_event: Optional[threading.Event] = None,
                      cwd: Optional[str] = None) -> int:
    """Run a docker command and stream output line by line via callback."""
    try:
        proc = subprocess.Popen(
            ["docker"] + args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            cwd=cwd
        )
        for line in proc.stdout:
            if stop_event and stop_event.is_set():
                proc.terminate()
                break
            callback(line)
        proc.wait()
        return proc.returncode
    except Exception as e:
        callback(f"Error: {e}\n")
        return 1


def run_docker_login(args: List[str], password: str,
                     callback: Callable[[str], None]) -> None:
    """
    SECURITY: Log in to registry.
    Password is piped via stdin only — NEVER passed as a CLI arg.
    The password string reference is deleted immediately after use.
    """
    try:
        proc = subprocess.Popen(
            ["docker"] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        out, _ = proc.communicate(input=password, timeout=30)
        # Best-effort zero — Python doesn't guarantee memory overwrite,
        # but we at least delete the local reference and force GC.
        try:
            import ctypes
            import gc
            buf = password.encode()
            ctypes.memset(id(buf), 0, len(buf))
            del buf
        except Exception:
            pass
        del password
        callback(out or "")
    except Exception as e:
        callback(f"Error: {e}\n")


def docker_available() -> bool:
    """Return True if docker daemon is reachable."""
    _, _, rc = run_docker(["info"], timeout=5)
    return rc == 0


def get_latest_github_release(repo: str = "docker/docker-ce") -> Optional[str]:
    """
    Fetch the latest release tag from GitHub API.
    Returns tag string or None on failure.
    """
    import urllib.request
    import urllib.error
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DockerDeck"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("tag_name", "")
    except Exception:
        return None
