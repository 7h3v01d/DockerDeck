"""
DockerDeck – services/result.py

Typed result model for all Docker operations.
Replaces loose (stdout, stderr, rc) tuples and ad-hoc callback plumbing.

All action functions return or deliver an OperationResult.  The UI layer
inspects .ok / .error_kind to decide how to render; it never parses raw
stderr strings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


# ─────────────────────────────────────────────
#  ERROR TAXONOMY
# ─────────────────────────────────────────────

class ErrorKind(Enum):
    """
    Every failure maps to exactly one kind.
    The UI uses this to choose phrasing, retry logic, and icon.
    """
    NONE             = auto()   # success
    DOCKER_NOT_FOUND = auto()   # docker binary missing
    DAEMON_DOWN      = auto()   # docker daemon unreachable
    TIMEOUT          = auto()   # subprocess timed out
    AUTH_FAILURE     = auto()   # registry login rejected
    VALIDATION       = auto()   # input failed allowlist checks
    COMMAND_MISUSE   = auto()   # wrong args / flags for the command
    PARTIAL_FAILURE  = auto()   # bulk op: some succeeded, some failed
    CANCELLED        = auto()   # user-initiated cancellation
    UNKNOWN          = auto()   # catch-all for unexpected runtime errors


# Map common stderr fragments → ErrorKind (checked in order)
_STDERR_PATTERNS: list[tuple[str, ErrorKind]] = [
    ("Cannot connect to the Docker daemon",          ErrorKind.DAEMON_DOWN),
    ("Is the docker daemon running",                 ErrorKind.DAEMON_DOWN),
    ("docker: not found",                            ErrorKind.DOCKER_NOT_FOUND),
    ("executable file not found",                    ErrorKind.DOCKER_NOT_FOUND),
    ("unauthorized",                                 ErrorKind.AUTH_FAILURE),
    ("authentication required",                      ErrorKind.AUTH_FAILURE),
    ("incorrect username or password",               ErrorKind.AUTH_FAILURE),
    ("timed out",                                    ErrorKind.TIMEOUT),
    ("unknown flag",                                 ErrorKind.COMMAND_MISUSE),
    ("invalid reference format",                     ErrorKind.VALIDATION),
]


def classify_error(stderr: str, rc: int) -> ErrorKind:
    """Infer ErrorKind from stderr text and return code."""
    if rc == 0:
        return ErrorKind.NONE
    low = stderr.lower()
    for fragment, kind in _STDERR_PATTERNS:
        if fragment.lower() in low:
            return kind
    return ErrorKind.UNKNOWN


# ─────────────────────────────────────────────
#  OPERATION RESULT
# ─────────────────────────────────────────────

@dataclass
class OperationResult:
    """
    Single typed result for every Docker operation.

    Fields
    ------
    command     Full argv list that was executed (e.g. ['docker', 'ps', '-a'])
    stdout      Combined stdout from the subprocess
    stderr      Combined stderr from the subprocess
    rc          Return code (0 == success)
    error_kind  Classified failure reason (NONE when rc == 0)
    duration_s  Wall-clock seconds the operation took
    cancelled   True when the operation was explicitly cancelled by the user
    op_id       Unique monotonic ID for deduplication / job tracking
    user_msg    Short human-readable summary for toasts / status bar
    lines       Accumulated streaming lines (filled by stream operations)
    """
    command:    List[str]
    stdout:     str        = ""
    stderr:     str        = ""
    rc:         int        = 0
    error_kind: ErrorKind  = ErrorKind.NONE
    duration_s: float      = 0.0
    cancelled:  bool       = False
    op_id:      int        = field(default_factory=lambda: OperationResult._next_id())
    user_msg:   str        = ""
    lines:      List[str]  = field(default_factory=list)

    _counter: int = 0          # class-level monotonic counter (not a dataclass field)

    @staticmethod
    def _next_id() -> int:
        OperationResult._counter += 1
        return OperationResult._counter

    # ── convenience properties ──

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.cancelled

    @property
    def output(self) -> str:
        """Prefer stdout; fall back to accumulated stream lines; fall back to stderr."""
        if self.stdout:
            return self.stdout
        if self.lines:
            return "".join(self.lines)
        return self.stderr

    def short_cmd(self) -> str:
        """'docker ps -a' style string for display."""
        return " ".join(self.command)

    def failure_message(self) -> str:
        """
        Human-readable failure reason.
        Used by the UI layer — never expose raw stderr directly.
        """
        if self.cancelled:
            return "Operation was cancelled."
        messages = {
            ErrorKind.DOCKER_NOT_FOUND: (
                "Docker is not installed or not on PATH.\n"
                "Install Docker Desktop or Docker Engine and restart DockerDeck."
            ),
            ErrorKind.DAEMON_DOWN: (
                "Docker daemon is not responding.\n"
                "Check that Docker is running, then press Ctrl+R to reconnect."
            ),
            ErrorKind.TIMEOUT: (
                "The command took too long and was cancelled.\n"
                "The Docker daemon may be overloaded. Try again."
            ),
            ErrorKind.AUTH_FAILURE: (
                "Registry authentication failed.\n"
                "Check your username and password, then try again."
            ),
            ErrorKind.VALIDATION: (
                f"Invalid input: {self.stderr or self.user_msg}"
            ),
            ErrorKind.COMMAND_MISUSE: (
                f"Command failed — unexpected flag or argument.\n{self.stderr[:200]}"
            ),
            ErrorKind.PARTIAL_FAILURE: (
                f"Some operations failed. Review the output for details.\n{self.user_msg}"
            ),
            ErrorKind.UNKNOWN: (
                f"Unexpected error (rc={self.rc}).\n"
                f"{self.stderr[:300] or 'No details available.'}"
            ),
        }
        return messages.get(self.error_kind,
                            f"Error (rc={self.rc}): {self.stderr[:200]}")

    # ── factory helpers ──

    @classmethod
    def success(cls, command: list, stdout: str = "",
                duration_s: float = 0.0, user_msg: str = "") -> "OperationResult":
        return cls(command=command, stdout=stdout, rc=0,
                   error_kind=ErrorKind.NONE, duration_s=duration_s,
                   user_msg=user_msg)

    @classmethod
    def failure(cls, command: list, stderr: str = "", rc: int = 1,
                error_kind: Optional[ErrorKind] = None,
                duration_s: float = 0.0, user_msg: str = "") -> "OperationResult":
        kind = error_kind or classify_error(stderr, rc)
        return cls(command=command, stderr=stderr, rc=rc,
                   error_kind=kind, duration_s=duration_s,
                   user_msg=user_msg)

    @classmethod
    def cancelled_result(cls, command: list) -> "OperationResult":
        return cls(command=command, rc=1,
                   error_kind=ErrorKind.CANCELLED, cancelled=True,
                   user_msg="Cancelled by user.")


# ─────────────────────────────────────────────
#  TIMING CONTEXT MANAGER
# ─────────────────────────────────────────────

class timer:
    """Simple wall-clock timer for wrapping operations."""
    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *_):
        self.elapsed = time.monotonic() - self._start

    @property
    def s(self) -> float:
        return getattr(self, "elapsed", 0.0)
