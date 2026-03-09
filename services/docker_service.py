"""
DockerDeck – services/docker_service.py

Real command execution layer.

Responsibilities
----------------
- sync runner          run_sync()
- stream runner        run_stream()
- login runner         run_login()
- timeout policy       configurable per call
- cancellation policy  honours threading.Event on stream ops
- output normalisation returns OperationResult, never raw tuples
- structured logging   every call logs start/end/rc/duration

Import boundary: this module has NO tkinter dependency.
It may be used from any layer (actions, controllers, tests).
"""

from __future__ import annotations

import subprocess
import threading
import time
import logging
from typing import Callable, List, Optional

from services.result import OperationResult, ErrorKind, classify_error, timer

logger = logging.getLogger("dockerdeck.docker_service")

# ── Default timeouts (seconds) ───────────────
TIMEOUT_QUICK  = 10    # info, version, ps
TIMEOUT_NORMAL = 30    # most operations
TIMEOUT_LONG   = 120   # build, push, pull
TIMEOUT_LOGIN  = 30


def _docker_argv(args: List[str]) -> List[str]:
    return ["docker"] + args


# ─────────────────────────────────────────────
#  SYNC RUNNER
# ─────────────────────────────────────────────

def run_sync(args: List[str], *,
             timeout: int = TIMEOUT_NORMAL,
             cwd: Optional[str] = None) -> OperationResult:
    """
    Run a docker command synchronously.
    Always returns an OperationResult — never raises.

    Parameters
    ----------
    args     : docker sub-command args, e.g. ['ps', '-a']
    timeout  : seconds before TimeoutExpired is raised and mapped to TIMEOUT
    cwd      : working directory for the subprocess
    """
    argv = _docker_argv(args)
    logger.debug("run_sync start: %s", " ".join(argv))

    with timer() as t:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            rc     = proc.returncode
            kind   = classify_error(stderr, rc)

        except FileNotFoundError:
            stdout, stderr, rc = "", "Docker not found. Is it installed?", 1
            kind = ErrorKind.DOCKER_NOT_FOUND

        except subprocess.TimeoutExpired:
            stdout, stderr, rc = "", f"Command timed out after {timeout}s.", 1
            kind = ErrorKind.TIMEOUT

        except Exception as exc:
            stdout, stderr, rc = "", str(exc), 1
            kind = ErrorKind.UNKNOWN

    result = OperationResult(
        command=argv,
        stdout=stdout,
        stderr=stderr,
        rc=rc,
        error_kind=kind,
        duration_s=t.s,
    )
    logger.info(
        "run_sync end: cmd=%s rc=%d duration=%.2fs kind=%s",
        " ".join(argv[:4]), rc, t.s, kind.name,
    )
    return result


# ─────────────────────────────────────────────
#  STREAM RUNNER
# ─────────────────────────────────────────────

def run_stream(args: List[str],
               callback: Callable[[str], None],
               *,
               stop_event: Optional[threading.Event] = None,
               timeout: int = TIMEOUT_LONG,
               cwd: Optional[str] = None) -> OperationResult:
    """
    Run a docker command and stream output line-by-line via callback.

    Lifecycle contract
    ------------------
    - If stop_event is set before or during the run, the subprocess is
      terminated and OperationResult.cancelled is True.
    - On normal completion, rc reflects the subprocess return code.
    - Callback is called for every line of stdout+stderr (merged).
    - Callback is called from the calling thread (not the main thread).
      Callers that need to update UI must use root.after().
    """
    argv = _docker_argv(args)
    logger.debug("run_stream start: %s", " ".join(argv))
    lines: List[str] = []
    cancelled = False

    with timer() as t:
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd,
            )

            # Deadline watchdog thread
            _deadline_hit = threading.Event()

            def _watchdog():
                if not proc.poll() is None:
                    return
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        return
                    if stop_event and stop_event.is_set():
                        return
                    time.sleep(0.5)
                logger.warning("run_stream timeout after %ds: %s", timeout, " ".join(argv[:4]))
                _deadline_hit.set()
                try:
                    proc.terminate()
                except Exception:
                    pass

            wd = threading.Thread(target=_watchdog, daemon=True)
            wd.start()

            for line in proc.stdout:
                if stop_event and stop_event.is_set():
                    proc.terminate()
                    cancelled = True
                    break
                lines.append(line)
                try:
                    callback(line)
                except Exception:
                    pass

            proc.wait()
            wd.join(timeout=1)

            rc = proc.returncode if proc.returncode is not None else 1
            if _deadline_hit.is_set():
                rc = 1
                kind = ErrorKind.TIMEOUT
            elif cancelled:
                kind = ErrorKind.CANCELLED
            else:
                kind = classify_error("", rc)

        except FileNotFoundError:
            rc, kind = 1, ErrorKind.DOCKER_NOT_FOUND
        except Exception as exc:
            logger.exception("run_stream unexpected: %s", exc)
            rc, kind = 1, ErrorKind.UNKNOWN

    result = OperationResult(
        command=argv,
        rc=rc,
        error_kind=kind,
        cancelled=cancelled,
        duration_s=t.s,
        lines=lines,
    )
    logger.info(
        "run_stream end: cmd=%s rc=%d duration=%.2fs kind=%s cancelled=%s",
        " ".join(argv[:4]), rc, t.s, kind.name, cancelled,
    )
    return result


# ─────────────────────────────────────────────
#  LOGIN RUNNER
# ─────────────────────────────────────────────

def run_login(args: List[str], password: str,
              callback: Callable[[str], None]) -> OperationResult:
    """
    SECURITY: Log in to a registry.
    Password is piped via stdin ONLY — never in CLI args.
    The local password reference is deleted immediately after communicate().

    Best-effort memory zero: Python's GC/interning means we cannot guarantee
    the bytes are gone from RAM, but we remove our reference immediately.
    See threat model in SECURITY.md for the honest assessment.
    """
    argv = _docker_argv(args)
    logger.debug("run_login start: %s", " ".join(argv))  # password NOT logged

    with timer() as t:
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            out, _ = proc.communicate(input=password, timeout=TIMEOUT_LOGIN)
            rc = proc.returncode

            # Best-effort wipe
            try:
                import ctypes
                buf = password.encode("utf-8")
                ctypes.memset(id(buf), 0, len(buf))
                del buf
            except Exception:
                pass
            del password

            kind = classify_error(out, rc)
            try:
                callback(out or "")
            except Exception:
                pass

        except subprocess.TimeoutExpired:
            proc.kill()
            del password
            rc, kind, out = 1, ErrorKind.TIMEOUT, "Login timed out."
            callback(out)

        except FileNotFoundError:
            del password
            rc, kind, out = 1, ErrorKind.DOCKER_NOT_FOUND, "Docker not found."
            callback(out)

        except Exception as exc:
            del password
            rc, kind, out = 1, ErrorKind.UNKNOWN, str(exc)
            callback(out)

    result = OperationResult(
        command=argv, stdout=out, rc=rc,
        error_kind=kind, duration_s=t.s,
    )
    logger.info(
        "run_login end: rc=%d duration=%.2fs kind=%s",
        rc, t.s, kind.name,
    )
    return result


# ─────────────────────────────────────────────
#  AVAILABILITY CHECK
# ─────────────────────────────────────────────

def daemon_available() -> bool:
    """
    Return True if the Docker daemon is reachable.
    Uses a short timeout to avoid blocking the caller.
    """
    result = run_sync(["info"], timeout=TIMEOUT_QUICK)
    return result.ok
