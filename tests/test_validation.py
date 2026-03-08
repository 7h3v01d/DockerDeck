"""
DockerDeck – tests/test_validation.py
pytest: 25 validation function tests.
No tkinter required — pure logic only.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from validation import (
    validate_image_name, validate_container_name,
    validate_ports, validate_env_vars,
    validate_volumes, validate_extra_args,
    ValidationError,
)

class TestValidateImageName:
    def test_valid_simple(self):         assert validate_image_name("nginx") == "nginx"
    def test_valid_with_tag(self):       assert validate_image_name("nginx:latest") == "nginx:latest"
    def test_valid_registry_path(self):  assert validate_image_name("ghcr.io/u/app:1.0") == "ghcr.io/u/app:1.0"
    def test_strips_whitespace(self):    assert validate_image_name("  nginx  ") == "nginx"
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
    def test_spaces_invalid(self):
        with pytest.raises(ValidationError):
            validate_image_name("my image name")

class TestValidateContainerName:
    def test_valid(self):             assert validate_container_name("my-container") == "my-container"
    def test_empty_ok(self):          assert validate_container_name("") == ""
    def test_alphanumeric(self):      assert validate_container_name("app123") == "app123"
    def test_dash_start_invalid(self):
        with pytest.raises(ValidationError):
            validate_container_name("-badname")
    def test_injection_raises(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_container_name("name;drop")

class TestValidatePorts:
    def test_single(self):    assert validate_ports("8080:80") == ["8080:80"]
    def test_multiple(self):  assert validate_ports("8080:80,443:443") == ["8080:80","443:443"]
    def test_protocol(self):  assert validate_ports("8080:80/tcp") == ["8080:80/tcp"]
    def test_empty(self):     assert validate_ports("") == []
    def test_bad_fmt(self):
        with pytest.raises(ValidationError, match="format"):
            validate_ports("8080")
    def test_injection(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_ports("8080:80;rm")

class TestValidateEnvVars:
    def test_single(self):   assert validate_env_vars("KEY=value") == ["KEY=value"]
    def test_multiple(self): assert validate_env_vars("FOO=bar,BAZ=qux") == ["FOO=bar","BAZ=qux"]
    def test_empty(self):    assert validate_env_vars("") == []
    def test_no_equals(self):
        with pytest.raises(ValidationError, match="KEY=value"):
            validate_env_vars("BADVAR")
    def test_digit_key(self):
        with pytest.raises(ValidationError):
            validate_env_vars("1BAD=value")
    def test_injection(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_env_vars("KEY=value;rm")

class TestValidateVolumes:
    def test_simple(self):  assert validate_volumes("./data:/app") == ["./data:/app"]
    def test_mode(self):    assert validate_volumes("./data:/app:ro") == ["./data:/app:ro"]
    def test_empty(self):   assert validate_volumes("") == []
    def test_no_colon(self):
        with pytest.raises(ValidationError, match="SOURCE:DEST"):
            validate_volumes("justpath")

class TestValidateExtraArgs:
    def test_memory_flag(self):  assert validate_extra_args("--memory 512m") == ["--memory","512m"]
    def test_rm_bool(self):      assert validate_extra_args("--rm") == ["--rm"]
    def test_eq_form(self):      assert validate_extra_args("--memory=512m") == ["--memory=512m"]
    def test_empty(self):        assert validate_extra_args("") == []
    def test_unknown_flag(self):
        with pytest.raises(ValidationError, match="allowlist"):
            validate_extra_args("--unknown-flag")
    def test_injection_in_value(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_extra_args("--memory 512m;rm -rf /")
