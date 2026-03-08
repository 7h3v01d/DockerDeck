"""
DockerDeck – tests/test_validation.py
pytest suite: ~20 tests for all validation functions.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from validation import (
    validate_image_name,
    validate_container_name,
    validate_ports,
    validate_env_vars,
    validate_volumes,
    validate_extra_args,
    ValidationError,
)

# ── validate_image_name ───────────────────────

class TestValidateImageName:

    def test_valid_simple(self):
        assert validate_image_name("nginx") == "nginx"

    def test_valid_with_tag(self):
        assert validate_image_name("nginx:latest") == "nginx:latest"

    def test_valid_registry_path(self):
        assert validate_image_name("registry.io/user/myapp:1.0") == "registry.io/user/myapp:1.0"

    def test_strips_whitespace(self):
        assert validate_image_name("  nginx:latest  ") == "nginx:latest"

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_image_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_image_name("   ")

    def test_injection_semicolon(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_image_name("nginx;rm -rf /")

    def test_injection_pipe(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_image_name("nginx|cat /etc/passwd")

    def test_injection_backtick(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_image_name("nginx`whoami`")

    def test_injection_dollar(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_image_name("nginx${IFS}rm")

    def test_invalid_format_spaces(self):
        with pytest.raises(ValidationError):
            validate_image_name("my image name")


# ── validate_container_name ───────────────────

class TestValidateContainerName:

    def test_valid_simple(self):
        assert validate_container_name("my-container") == "my-container"

    def test_empty_returns_empty(self):
        # Optional field — empty is allowed
        assert validate_container_name("") == ""

    def test_valid_alphanumeric(self):
        assert validate_container_name("myapp123") == "myapp123"

    def test_invalid_starts_with_dash(self):
        with pytest.raises(ValidationError):
            validate_container_name("-badname")

    def test_injection_raises(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_container_name("name;drop")


# ── validate_ports ────────────────────────────

class TestValidatePorts:

    def test_single_port(self):
        assert validate_ports("8080:80") == ["8080:80"]

    def test_multiple_ports_comma(self):
        result = validate_ports("8080:80,443:443")
        assert result == ["8080:80", "443:443"]

    def test_with_protocol(self):
        assert validate_ports("8080:80/tcp") == ["8080:80/tcp"]

    def test_empty_returns_empty_list(self):
        assert validate_ports("") == []

    def test_bad_format_raises(self):
        with pytest.raises(ValidationError, match="format"):
            validate_ports("8080")   # missing container port

    def test_injection_in_port(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_ports("8080:80;rm -rf /")


# ── validate_env_vars ─────────────────────────

class TestValidateEnvVars:

    def test_single_env(self):
        assert validate_env_vars("KEY=value") == ["KEY=value"]

    def test_multiple_envs(self):
        result = validate_env_vars("FOO=bar,BAZ=qux")
        assert result == ["FOO=bar", "BAZ=qux"]

    def test_empty_returns_empty_list(self):
        assert validate_env_vars("") == []

    def test_bad_format_no_equals(self):
        with pytest.raises(ValidationError, match="KEY=value"):
            validate_env_vars("BADVAR")

    def test_bad_key_starts_with_digit(self):
        with pytest.raises(ValidationError):
            validate_env_vars("1BAD=value")

    def test_injection_in_value(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_env_vars("KEY=value;rm")


# ── validate_volumes ──────────────────────────

class TestValidateVolumes:

    def test_simple_volume(self):
        assert validate_volumes("./data:/app/data") == ["./data:/app/data"]

    def test_with_mode(self):
        result = validate_volumes("./data:/app:ro")
        assert result == ["./data:/app:ro"]

    def test_empty_returns_empty_list(self):
        assert validate_volumes("") == []

    def test_bad_format_no_colon(self):
        with pytest.raises(ValidationError, match="SOURCE:DEST"):
            validate_volumes("justpath")


# ── validate_extra_args ───────────────────────

class TestValidateExtraArgs:

    def test_valid_memory(self):
        assert validate_extra_args("--memory 512m") == ["--memory", "512m"]

    def test_valid_rm_flag(self):
        assert validate_extra_args("--rm") == ["--rm"]

    def test_empty_returns_empty_list(self):
        assert validate_extra_args("") == []

    def test_unknown_flag_raises(self):
        with pytest.raises(ValidationError, match="allowlist"):
            validate_extra_args("--unknown-flag")

    def test_injection_in_arg(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_extra_args("--memory 512m;rm -rf /")
