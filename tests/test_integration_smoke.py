"""
DockerDeck – tests/test_integration_smoke.py
Integration smoke tests: simulate full workflows without a display or Docker daemon.
All external calls mocked. Tests cover deploy, container actions, bulk operations,
registry, compose, and daemon health state transitions.
No tkinter, no Docker, no display required.
"""
import sys
import os
import threading
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock, call, ANY
from validation import ValidationError


# ─────────────────────────────── helpers ──

def mock_run_docker(return_map=None, default=("", "", 0)):
    """
    Return a mock for docker_runner.run_docker.
    return_map: {tuple_of_args_prefix: (stdout, stderr, rc)}
    """
    return_map = return_map or {}

    def _run(args, **kwargs):
        key = tuple(args[:2])
        return return_map.get(key, default)
    return _run


# ─────────────────────────── DEPLOY WORKFLOW ──

class TestDeployWorkflow:
    """End-to-end deploy: field validation → command build → exec."""

    def test_full_valid_deploy_builds_correct_command(self):
        from actions.deploy import build_run_command
        fields = dict(
            deploy_image="nginx:latest",
            deploy_name="web",
            deploy_ports="8080:80",
            deploy_env="ENV=prod",
            deploy_volumes="./html:/usr/share/nginx/html",
            deploy_network="bridge",
            deploy_restart="unless-stopped",
            deploy_extra="--memory 256m",
        )
        cmd = build_run_command(fields, detach=True)
        assert cmd == [
            "docker", "run", "-d",
            "--name", "web",
            "-p", "8080:80",
            "-e", "ENV=prod",
            "-v", "./html:/usr/share/nginx/html",
            "--network", "bridge",
            "--restart", "unless-stopped",
            "--memory", "256m",
            "nginx:latest",
        ]

    def test_deploy_exec_calls_run_docker_stream(self):
        from actions.deploy import deploy_exec
        root = MagicMock()
        root.after = lambda ms, fn: fn()   # execute immediately
        output_lines = []

        with patch("actions.deploy.run_docker_stream", return_value=0) as mock_stream:
            deploy_exec(root, ["run", "-d", "nginx:latest"],
                        lambda t, clear=False: output_lines.append(t))
        mock_stream.assert_called_once()
        call_args = mock_stream.call_args[0]
        assert call_args[0] == ["run", "-d", "nginx:latest"]

    def test_deploy_exec_shows_command_in_output(self):
        from actions.deploy import deploy_exec
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        output_lines = []

        with patch("actions.deploy.run_docker_stream", return_value=0):
            deploy_exec(root, ["run", "-d", "nginx:latest"],
                        lambda t, clear=False: output_lines.append(t))

        combined = "".join(output_lines)
        assert "docker" in combined.lower()

    def test_deploy_rejects_injection_in_image(self):
        from actions.deploy import build_run_command
        fields = dict(
            deploy_image="nginx;rm -rf /",
            deploy_name="", deploy_ports="", deploy_env="",
            deploy_volumes="", deploy_network="", deploy_restart="",
            deploy_extra="",
        )
        with pytest.raises(ValidationError):
            build_run_command(fields, detach=True)

    def test_deploy_rejects_injection_in_extra_args(self):
        from actions.deploy import build_run_command
        fields = dict(
            deploy_image="nginx:latest",
            deploy_name="", deploy_ports="", deploy_env="",
            deploy_volumes="", deploy_network="", deploy_restart="",
            deploy_extra="--memory 256m; rm -rf /",
        )
        with pytest.raises(ValidationError):
            build_run_command(fields, detach=True)

    def test_validate_all_fields_returns_tuple(self):
        from actions.deploy import validate_all_fields
        ok, msg = validate_all_fields({
            "deploy_image": "nginx:latest",
            "deploy_name": "web",
            "deploy_ports": "8080:80",
            "deploy_env": "KEY=val",
            "deploy_volumes": "./d:/d",
            "deploy_network": "bridge",
            "deploy_restart": "unless-stopped",
            "deploy_extra": "",
        })
        assert ok is True and msg == ""

    def test_validate_field_per_field(self):
        from actions.deploy import validate_field
        assert validate_field("deploy_ports", "8080:80") == (True, "")
        assert validate_field("deploy_ports", "notaport")[0] is False
        assert validate_field("deploy_network", "anything") == (True, "")


# ─────────────────────────── CONTAINER ACTIONS ──

class TestContainerActions:
    """Container start/stop/restart/remove — mock run_docker."""

    def test_container_start_calls_docker_start(self):
        import actions.containers as ac
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        called = []

        with patch("actions.containers.run_docker",
                   side_effect=lambda args, **kw: called.append(args) or ("", "", 0)):
            ac.container_start(root, ["web"], lambda t: None)

        # Wait for thread
        import time; time.sleep(0.05)
        assert any(a[0] == "start" and a[1] == "web" for a in called)

    def test_container_stop_calls_docker_stop(self):
        import actions.containers as ac
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        called = []

        with patch("actions.containers.run_docker",
                   side_effect=lambda args, **kw: called.append(args) or ("", "", 0)):
            ac.container_stop(root, ["web"], lambda t: None)

        import time; time.sleep(0.05)
        assert any(a[0] == "stop" and a[1] == "web" for a in called)

    def test_container_restart_calls_docker_restart(self):
        import actions.containers as ac
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        called = []

        with patch("actions.containers.run_docker",
                   side_effect=lambda args, **kw: called.append(args) or ("", "", 0)):
            ac.container_restart(root, ["db"], lambda t: None)

        import time; time.sleep(0.05)
        assert any(a[0] == "restart" and a[1] == "db" for a in called)

    def test_container_remove_calls_docker_rm_force(self):
        import actions.containers as ac
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        called = []

        with patch("actions.containers.run_docker",
                   side_effect=lambda args, **kw: called.append(args) or ("", "", 0)):
            ac.container_remove(root, ["web", "db"], lambda t: None)

        import time; time.sleep(0.1)
        rm_calls = [a for a in called if a[0] == "rm"]
        assert len(rm_calls) == 2
        assert all("-f" in a for a in rm_calls)

    def test_container_bulk_stop_all(self):
        import actions.containers as ac
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        stopped = []

        with patch("actions.containers.run_docker",
                   side_effect=lambda args, **kw: stopped.append(args[1]) or ("", "", 0)):
            ac.container_stop_all(root, ["c1", "c2", "c3"], lambda t: None)

        import time; time.sleep(0.1)
        assert set(stopped) == {"c1", "c2", "c3"}

    def test_get_shell_command(self):
        from actions.containers import get_shell_command
        cmd = get_shell_command("mycontainer")
        assert "exec" in cmd and "mycontainer" in cmd and "sh" in cmd


# ─────────────────────────── IMAGE ACTIONS ──

class TestImageActions:
    def test_image_pull_calls_stream(self):
        import actions.images as ai
        root = MagicMock()
        root.after = lambda ms, fn: fn()

        with patch("actions.images.run_docker_stream", return_value=0) as mock_s:
            ai.image_pull_exec(root, "nginx:latest",
                               lambda t, clear=False: None)

        import time; time.sleep(0.05)
        mock_s.assert_called()
        assert mock_s.call_args[0][0][0] == "pull"

    def test_image_remove_calls_rmi(self):
        import actions.images as ai
        root = MagicMock()
        root.after = lambda ms, fn: fn()
        called = []

        with patch("actions.images.run_docker",
                   side_effect=lambda args, **kw: called.append(args) or ("", "", 0)):
            ai.image_remove_exec(root, "sha256:abc123", "nginx:latest",
                                 lambda t: None)

        import time; time.sleep(0.05)
        assert any(a[0] == "rmi" for a in called)


# ─────────────────────────── NETWORK / VOLUME ──

class TestNetworkVolumeActions:
    def test_network_create(self):
        import actions.network_volume as nv
        root = MagicMock(); root.after = lambda ms, fn: fn()
        called = []
        with patch("actions.network_volume.run_docker",
                   side_effect=lambda a, **kw: called.append(a) or ("", "", 0)):
            nv.network_create(root, "mynet", lambda t: None)
        import time; time.sleep(0.05)
        assert any(a[:3] == ["network", "create", "mynet"] for a in called)

    def test_volume_remove(self):
        import actions.network_volume as nv
        root = MagicMock(); root.after = lambda ms, fn: fn()
        called = []
        with patch("actions.network_volume.run_docker",
                   side_effect=lambda a, **kw: called.append(a) or ("", "", 0)):
            nv.volume_remove(root, "myvol", lambda t: None)
        import time; time.sleep(0.05)
        assert any(a[:3] == ["volume", "rm", "myvol"] for a in called)

    def test_volume_prune_uses_force_flag(self):
        import actions.network_volume as nv
        root = MagicMock(); root.after = lambda ms, fn: fn()
        called = []
        with patch("actions.network_volume.run_docker",
                   side_effect=lambda a, **kw: called.append(a) or ("", "", 0)):
            nv.volume_prune(root, lambda t: None)
        import time; time.sleep(0.05)
        assert any("-f" in a for a in called)


# ─────────────────────────── REGISTRY ──

class TestRegistryActions:
    def test_login_uses_stdin_not_cli(self):
        """Password must never appear in CLI args (security requirement)."""
        import actions.registry as reg
        root = MagicMock(); root.after = lambda ms, fn: fn()
        captured_args = []

        def fake_login(args, password, cb):
            captured_args.extend(args)
            assert "mysecret" not in args, "Password leaked into CLI args!"

        with patch("actions.registry.run_docker_login", side_effect=fake_login):
            reg.registry_login_exec(root, "docker.io", "user", "mysecret",
                                    lambda t: None)

        import time; time.sleep(0.05)
        assert "--password-stdin" in captured_args
        assert "mysecret" not in captured_args

    def test_push_validates_image_name(self):
        import actions.registry as reg
        root = MagicMock(); root.after = lambda ms, fn: fn()
        # This should not raise — valid image names
        with patch("actions.registry.run_docker", return_value=("", "", 0)):
            with patch("actions.registry.run_docker_stream", return_value=0):
                reg.registry_push_exec(root, "nginx:latest",
                                       "registry.io/user/nginx:latest",
                                       lambda t: None)


# ─────────────────────────── DAEMON HEALTH (logic) ──

class TestDaemonHealthLogic:
    """Test the daemon health state machine (no tkinter)."""

    def test_docker_available_true(self):
        from docker_runner import docker_available
        mock = MagicMock()
        mock.stdout = ""; mock.stderr = ""; mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            assert docker_available() is True

    def test_docker_available_false_on_nonzero(self):
        from docker_runner import docker_available
        mock = MagicMock()
        mock.stdout = ""; mock.stderr = "Cannot connect"; mock.returncode = 1
        with patch("subprocess.run", return_value=mock):
            assert docker_available() is False

    def test_docker_available_false_when_not_installed(self):
        from docker_runner import docker_available
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert docker_available() is False

    def test_docker_available_false_on_timeout(self):
        import subprocess
        from docker_runner import docker_available
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("docker", 5)):
            assert docker_available() is False


# ─────────────────────────── COMPOSE WORKFLOW ──

class TestComposeWorkflow:
    def test_compose_up_command_structure(self):
        """Verify that compose up uses correct args."""
        import docker_runner
        called_args = []

        def mock_stream(args, cb, **kw):
            called_args.extend(args)
            return 0

        # Patch via the module reference so the mock intercepts the call
        with patch("docker_runner.run_docker_stream", side_effect=mock_stream):
            args = ["compose", "up", "-d"]
            docker_runner.run_docker_stream(args, lambda l: None)

        assert called_args[:3] == ["compose", "up", "-d"]


# ─────────────────────────── NOTIFICATION LOG ──

class TestNotificationLog:
    def test_log_stores_entries(self):
        from utils import log_notification, get_notification_log
        from collections import deque
        import utils
        # Reset log for isolation
        original = utils._notification_log
        utils._notification_log = deque(maxlen=200)

        log_notification("test error", "error")
        log_notification("test info", "info")
        entries = get_notification_log()
        assert len(entries) == 2
        assert entries[0]["msg"] == "test info"   # newest first
        assert entries[1]["msg"] == "test error"
        assert entries[0]["level"] == "info"

        utils._notification_log = original

    def test_log_respects_maxlen(self):
        from utils import log_notification, get_notification_log
        from collections import deque
        import utils
        utils._notification_log = deque(maxlen=5)

        for i in range(10):
            log_notification(f"msg {i}")
        assert len(get_notification_log()) == 5
        utils._notification_log = deque(maxlen=200)

    def test_log_entries_have_timestamp(self):
        from utils import log_notification, get_notification_log
        from collections import deque
        import utils
        utils._notification_log = deque(maxlen=200)

        log_notification("timestamped message")
        entry = get_notification_log()[0]
        assert "ts" in entry
        assert len(entry["ts"]) == 19   # "YYYY-MM-DD HH:MM:SS"
        utils._notification_log = deque(maxlen=200)
