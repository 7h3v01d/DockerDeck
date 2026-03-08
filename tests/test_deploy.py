"""
DockerDeck – tests/test_deploy.py
pytest: 15 tests for deploy logic.
All pure functions — no tkinter, no subprocess.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from actions.deploy import (
    validate_field, validate_all_fields, build_run_command,
)
from validation import ValidationError


def fv(**overrides):
    """Return a plain dict of field values (no tkinter Entry objects)."""
    base = dict(
        deploy_image="nginx:latest",
        deploy_name="my-container",
        deploy_ports="8080:80",
        deploy_env="KEY=value",
        deploy_volumes="./data:/data",
        deploy_network="bridge",
        deploy_restart="unless-stopped",
        deploy_extra="",
    )
    base.update(overrides)
    return base


class TestValidateField:
    def test_valid_image(self):
        ok, msg = validate_field("deploy_image", "nginx:latest")
        assert ok is True and msg == ""

    def test_invalid_image(self):
        ok, msg = validate_field("deploy_image", "bad image!")
        assert ok is False and msg

    def test_empty_optional_ok(self):
        # Empty value for optional field should be valid
        ok, _ = validate_field("deploy_image", "")
        assert ok is True

    def test_no_validator_field(self):
        ok, msg = validate_field("deploy_network", "mynet")
        assert ok is True and msg == ""

    def test_bad_port(self):
        ok, _ = validate_field("deploy_ports", "notaport")
        assert ok is False


class TestValidateAllFields:
    def test_all_valid(self):
        ok, msg = validate_all_fields(fv())
        assert ok is True

    def test_bad_image_fails(self):
        ok, msg = validate_all_fields(fv(deploy_image="bad img!"))
        assert ok is False and "deploy_image" in msg

    def test_bad_port_fails(self):
        ok, msg = validate_all_fields(fv(deploy_ports="notaport"))
        assert ok is False


class TestBuildRunCommand:
    def test_structure(self):
        cmd = build_run_command(fv(), True)
        assert cmd[0] == "docker" and cmd[1] == "run"

    def test_detach_flag_present(self):
        assert "-d" in build_run_command(fv(), True)

    def test_no_detach(self):
        assert "-d" not in build_run_command(fv(), False)

    def test_name(self):
        cmd = build_run_command(fv(), True)
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "my-container"

    def test_port_mapping(self):
        cmd = build_run_command(fv(), True)
        assert "-p" in cmd
        assert cmd[cmd.index("-p") + 1] == "8080:80"

    def test_env_var(self):
        cmd = build_run_command(fv(), True)
        assert "-e" in cmd and "KEY=value" in cmd

    def test_volume(self):
        assert "-v" in build_run_command(fv(), True)

    def test_network(self):
        cmd = build_run_command(fv(), True)
        assert "--network" in cmd
        assert cmd[cmd.index("--network") + 1] == "bridge"

    def test_restart(self):
        cmd = build_run_command(fv(), True)
        assert "--restart" in cmd

    def test_image_is_last(self):
        assert build_run_command(fv(), True)[-1] == "nginx:latest"

    def test_empty_optionals_omitted(self):
        cmd = build_run_command(fv(
            deploy_name="", deploy_ports="", deploy_env="",
            deploy_volumes="", deploy_network="", deploy_restart="",
        ), True)
        for flag in ("--name", "-p", "-e", "-v", "--network", "--restart"):
            assert flag not in cmd

    def test_invalid_image_raises(self):
        with pytest.raises(ValidationError):
            build_run_command(fv(deploy_image="bad image!"), True)

    def test_extra_args_allowed(self):
        cmd = build_run_command(fv(deploy_extra="--memory 256m"), True)
        assert "--memory" in cmd and "256m" in cmd

    def test_extra_args_blocked(self):
        with pytest.raises(ValidationError, match="allowlist"):
            build_run_command(fv(deploy_extra="--unknown-flag"), True)
