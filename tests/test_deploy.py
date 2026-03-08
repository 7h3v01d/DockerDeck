"""
DockerDeck – tests/test_deploy.py
pytest suite: 10 tests for build_run_command() variants.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from actions.deploy import build_run_command
from validation import ValidationError


def make_fields(**overrides):
    """Build a mock deploy_fields dict with sane defaults."""
    defaults = {
        "deploy_image":   "nginx:latest",
        "deploy_name":    "my-container",
        "deploy_ports":   "8080:80",
        "deploy_env":     "KEY=value",
        "deploy_volumes": "./data:/data",
        "deploy_network": "bridge",
        "deploy_restart": "unless-stopped",
        "deploy_extra":   "",
    }
    defaults.update(overrides)
    fields = {}
    for k, v in defaults.items():
        mock = MagicMock()
        mock.get.return_value = v
        fields[k] = mock
    return fields


class TestBuildRunCommand:

    def test_basic_command_structure(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert cmd[0] == "docker"
        assert cmd[1] == "run"
        assert "-d" in cmd

    def test_no_detach(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=False)
        assert "-d" not in cmd

    def test_name_arg(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "my-container"

    def test_port_mapping(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert "-p" in cmd
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "8080:80"

    def test_env_var(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert "-e" in cmd
        e_idx = cmd.index("-e")
        assert cmd[e_idx + 1] == "KEY=value"

    def test_volume_mount(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert "-v" in cmd

    def test_network(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert "--network" in cmd
        n_idx = cmd.index("--network")
        assert cmd[n_idx + 1] == "bridge"

    def test_restart_policy(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert "--restart" in cmd

    def test_image_is_last(self):
        fields = make_fields()
        cmd = build_run_command(fields, detach=True)
        assert cmd[-1] == "nginx:latest"

    def test_empty_optional_fields_omitted(self):
        fields = make_fields(
            deploy_name="",
            deploy_ports="",
            deploy_env="",
            deploy_volumes="",
            deploy_network="",
            deploy_restart="",
        )
        cmd = build_run_command(fields, detach=True)
        assert "--name" not in cmd
        assert "-p" not in cmd
        assert "-e" not in cmd
        assert "-v" not in cmd
        assert "--network" not in cmd
        assert "--restart" not in cmd
        assert cmd[-1] == "nginx:latest"

    def test_invalid_image_raises(self):
        fields = make_fields(deploy_image="bad image!")
        with pytest.raises(ValidationError):
            build_run_command(fields, detach=True)

    def test_extra_args_allowed(self):
        fields = make_fields(deploy_extra="--memory 256m")
        cmd = build_run_command(fields, detach=True)
        assert "--memory" in cmd
        assert "256m" in cmd

    def test_extra_args_blocked(self):
        fields = make_fields(deploy_extra="--unknown-flag")
        with pytest.raises(ValidationError, match="allowlist"):
            build_run_command(fields, detach=True)
