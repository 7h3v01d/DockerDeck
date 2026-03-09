"""
DockerDeck – tests/test_architecture.py

Architectural enforcement tests.

These tests automatically verify the import boundary contract:
  - services/* and actions/* must NEVER import tkinter
  - controllers/* must NEVER import subprocess directly
  - services/* must NEVER import tkinter
  - All action modules must stay tkinter-free

These tests run without a Docker daemon and without a display.
If any test here fails, it means a boundary violation was introduced
and must be fixed before merging.
"""

import ast
import sys
from pathlib import Path

# Root of the repo
ROOT = Path(__file__).parent.parent


def _get_imports(path: Path) -> set[str]:
    """
    Parse a Python file and return the set of top-level module names imported.
    Handles both `import X` and `from X import Y` forms.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree   = ast.parse(source, filename=str(path))
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def _py_files(directory: str) -> list[Path]:
    return sorted((ROOT / directory).rglob("*.py"))


# ─────────────────────────────────────────────
#  RULE 1: services/* must NOT import tkinter
# ─────────────────────────────────────────────

class TestServicesNoTkinter:
    def test_result_no_tkinter(self):
        imports = _get_imports(ROOT / "services" / "result.py")
        assert "tkinter" not in imports, \
            "services/result.py must not import tkinter"

    def test_docker_service_no_tkinter(self):
        imports = _get_imports(ROOT / "services" / "docker_service.py")
        assert "tkinter" not in imports, \
            "services/docker_service.py must not import tkinter"

    def test_state_store_no_tkinter(self):
        imports = _get_imports(ROOT / "services" / "state_store.py")
        assert "tkinter" not in imports, \
            "services/state_store.py must not import tkinter"

    def test_notifications_no_tkinter(self):
        imports = _get_imports(ROOT / "services" / "notifications_service.py")
        assert "tkinter" not in imports, \
            "services/notifications_service.py must not import tkinter"

    def test_settings_no_tkinter(self):
        imports = _get_imports(ROOT / "services" / "settings_service.py")
        assert "tkinter" not in imports, \
            "services/settings_service.py must not import tkinter"


# ─────────────────────────────────────────────
#  RULE 2: actions/* must NOT import tkinter
# ─────────────────────────────────────────────

class TestActionsNoTkinter:
    def test_containers_action_no_tkinter(self):
        imports = _get_imports(ROOT / "actions" / "containers.py")
        assert "tkinter" not in imports, \
            "actions/containers.py must not import tkinter"

    def test_images_action_no_tkinter(self):
        imports = _get_imports(ROOT / "actions" / "images.py")
        assert "tkinter" not in imports, \
            "actions/images.py must not import tkinter"

    def test_deploy_action_no_tkinter(self):
        imports = _get_imports(ROOT / "actions" / "deploy.py")
        assert "tkinter" not in imports, \
            "actions/deploy.py must not import tkinter"

    def test_network_volume_action_no_tkinter(self):
        imports = _get_imports(ROOT / "actions" / "network_volume.py")
        assert "tkinter" not in imports, \
            "actions/network_volume.py must not import tkinter"

    def test_registry_action_no_tkinter(self):
        imports = _get_imports(ROOT / "actions" / "registry.py")
        assert "tkinter" not in imports, \
            "actions/registry.py must not import tkinter"


# ─────────────────────────────────────────────
#  RULE 3: validation.py must NOT import tkinter or subprocess
# ─────────────────────────────────────────────

class TestValidationBoundary:
    def test_validation_no_tkinter(self):
        imports = _get_imports(ROOT / "validation.py")
        assert "tkinter" not in imports, \
            "validation.py must not import tkinter"

    def test_validation_no_subprocess(self):
        imports = _get_imports(ROOT / "validation.py")
        assert "subprocess" not in imports, \
            "validation.py must not import subprocess"


# ─────────────────────────────────────────────
#  RULE 4: controllers/* must NOT import subprocess directly
#          (must go through services.docker_service)
# ─────────────────────────────────────────────

class TestControllersNoDirectSubprocess:
    def test_containers_controller_no_subprocess(self):
        imports = _get_imports(
            ROOT / "controllers" / "containers_controller.py")
        assert "subprocess" not in imports, \
            "controllers/containers_controller.py must not import subprocess directly"

    def test_images_controller_no_subprocess(self):
        imports = _get_imports(ROOT / "controllers" / "images_controller.py")
        assert "subprocess" not in imports, \
            "controllers/images_controller.py must not import subprocess directly"

    def test_deploy_controller_no_subprocess(self):
        imports = _get_imports(ROOT / "controllers" / "deploy_controller.py")
        assert "subprocess" not in imports, \
            "controllers/deploy_controller.py must not import subprocess directly"

    def test_registry_controller_no_subprocess(self):
        imports = _get_imports(
            ROOT / "controllers" / "registry_controller.py")
        assert "subprocess" not in imports, \
            "controllers/registry_controller.py must not import subprocess directly"

    def test_network_volume_controller_no_subprocess(self):
        imports = _get_imports(
            ROOT / "controllers" / "network_volume_controller.py")
        assert "subprocess" not in imports, \
            "controllers/network_volume_controller.py must not import subprocess directly"


# ─────────────────────────────────────────────
#  RULE 5: services/* must NOT import actions/* or controllers/*
# ─────────────────────────────────────────────

class TestServicesNoCrossImports:
    def test_docker_service_no_actions(self):
        src = (ROOT / "services" / "docker_service.py").read_text()
        assert "from actions" not in src and "import actions" not in src, \
            "services/docker_service.py must not import from actions/"

    def test_state_store_no_controllers(self):
        src = (ROOT / "services" / "state_store.py").read_text()
        assert "from controllers" not in src, \
            "services/state_store.py must not import from controllers/"

    def test_notifications_no_controllers(self):
        src = (ROOT / "services" / "notifications_service.py").read_text()
        assert "from controllers" not in src, \
            "services/notifications_service.py must not import from controllers/"


# ─────────────────────────────────────────────
#  RULE 6: OperationResult invariants
# ─────────────────────────────────────────────

class TestOperationResultInvariants:
    def test_success_is_ok(self):
        from services.result import OperationResult
        r = OperationResult.success(["docker", "ps"])
        assert r.ok

    def test_failure_is_not_ok(self):
        from services.result import OperationResult
        r = OperationResult.failure(["docker", "ps"], rc=1)
        assert not r.ok

    def test_cancelled_is_not_ok(self):
        from services.result import OperationResult
        r = OperationResult.cancelled_result(["docker", "ps"])
        assert not r.ok
        assert r.cancelled

    def test_daemon_down_classified(self):
        from services.result import OperationResult, ErrorKind
        r = OperationResult.failure(
            ["docker", "info"],
            stderr="Cannot connect to the Docker daemon",
            rc=1,
        )
        assert r.error_kind == ErrorKind.DAEMON_DOWN

    def test_auth_failure_classified(self):
        from services.result import OperationResult, ErrorKind
        r = OperationResult.failure(
            ["docker", "login"],
            stderr="unauthorized: incorrect username or password",
            rc=1,
        )
        assert r.error_kind == ErrorKind.AUTH_FAILURE

    def test_unique_op_ids(self):
        from services.result import OperationResult
        ids = {OperationResult(command=["docker", "ps"]).op_id for _ in range(20)}
        assert len(ids) == 20, "op_ids must be unique"

    def test_failure_message_never_raises(self):
        from services.result import OperationResult, ErrorKind
        for kind in ErrorKind:
            r = OperationResult(command=["docker"], rc=1, error_kind=kind)
            msg = r.failure_message()   # must not raise
            assert isinstance(msg, str)


# ─────────────────────────────────────────────
#  RULE 7: StateStore thread-safety smoke test
# ─────────────────────────────────────────────

class TestStateStore:
    def test_daemon_status_transitions(self):
        from services.state_store import AppStateStore, DaemonStatus
        store = AppStateStore()
        received = []
        store.subscribe("daemon_status", received.append)

        store.set_daemon_status(DaemonStatus.RUNNING)
        store.set_daemon_status(DaemonStatus.RUNNING)    # no-op, same state
        store.set_daemon_status(DaemonStatus.UNAVAILABLE)

        assert received == [DaemonStatus.RUNNING, DaemonStatus.UNAVAILABLE], \
            "Should only emit on actual state change"

    def test_operation_tracking(self):
        from services.state_store import AppStateStore, ActiveOperation
        import threading
        store = AppStateStore()
        ev = threading.Event()
        op = ActiveOperation(op_id=1, label="test op", cancel=ev)

        store.register_operation(op)
        assert store.active_operation_count == 1

        store.cancel_operation(1)
        assert ev.is_set()

        store.complete_operation(1)
        assert store.active_operation_count == 0
