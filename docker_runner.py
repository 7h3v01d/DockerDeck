"""
DockerDeck – docker_runner.py

Backward-compatibility shim.
New code should import from services.docker_service directly.

This module delegates to services.docker_service and translates
OperationResult -> the old (stdout, stderr, rc) tuple interface so
that existing tests and action modules continue to work unchanged.
"""

from typing import Callable, List, Optional, Tuple
import threading

from services.docker_service import (
    run_sync   as _run_sync,
    run_stream as _run_stream,
    run_login  as _run_login,
    daemon_available,
)

# Re-export legacy name
docker_available = daemon_available


def run_docker(args: List[str], timeout: int = 30,
               cwd: Optional[str] = None) -> Tuple[str, str, int]:
    """Legacy tuple-returning runner. Prefer services.docker_service.run_sync."""
    result = _run_sync(args, timeout=timeout, cwd=cwd)
    return result.stdout, result.stderr, result.rc


def run_docker_stream(args: List[str], callback: Callable[[str], None],
                      stop_event: Optional[threading.Event] = None,
                      cwd: Optional[str] = None) -> int:
    """Legacy stream runner. Prefer services.docker_service.run_stream."""
    result = _run_stream(args, callback, stop_event=stop_event, cwd=cwd)
    return result.rc


def run_docker_login(args: List[str], password: str,
                     callback: Callable[[str], None]) -> None:
    """Legacy login runner. Prefer services.docker_service.run_login."""
    _run_login(args, password, callback)


def get_latest_github_release(repo: str = "docker/docker-ce") -> Optional[str]:
    import json
    import urllib.request
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DockerDeck"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("tag_name", "")
    except Exception:
        return None
