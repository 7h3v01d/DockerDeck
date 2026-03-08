"""
DockerDeck – tests/test_docker_runner.py
Smoke tests for docker_runner: mocked subprocess calls.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
import subprocess


class TestRunDocker:

    def test_returns_tuple(self):
        from docker_runner import run_docker
        mock_result = MagicMock()
        mock_result.stdout = "container_id\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            stdout, stderr, rc = run_docker(["ps"])
        assert rc == 0
        assert stdout == "container_id"

    def test_docker_not_found(self):
        from docker_runner import run_docker
        with patch("subprocess.run", side_effect=FileNotFoundError):
            stdout, stderr, rc = run_docker(["ps"])
        assert rc == 1
        assert "Docker not found" in stderr

    def test_timeout(self):
        from docker_runner import run_docker
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 30)):
            stdout, stderr, rc = run_docker(["ps"])
        assert rc == 1
        assert "timed out" in stderr


class TestRunDockerStream:

    def test_streams_lines(self):
        from docker_runner import run_docker_stream
        lines_received = []

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n", "line2\n"])
        mock_proc.returncode = 0
        mock_proc.wait = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc):
            rc = run_docker_stream(["logs", "container"], lines_received.append)

        assert "line1\n" in lines_received
        assert "line2\n" in lines_received

    def test_stop_event_terminates(self):
        import threading
        from docker_runner import run_docker_stream

        stop = threading.Event()
        stop.set()  # immediately set

        received = []
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n"])
        mock_proc.wait = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc):
            run_docker_stream(["logs", "-f", "container"],
                              received.append, stop_event=stop)

        # Terminate should have been called
        mock_proc.terminate.assert_called()


class TestDockerAvailable:

    def test_returns_true_on_rc_zero(self):
        from docker_runner import docker_available
        mock_result = MagicMock()
        mock_result.stdout = "..."
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert docker_available() is True

    def test_returns_false_on_nonzero(self):
        from docker_runner import docker_available
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"
        with patch("subprocess.run", return_value=mock_result):
            assert docker_available() is False

    def test_returns_false_when_not_installed(self):
        from docker_runner import docker_available
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert docker_available() is False
