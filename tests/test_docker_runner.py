"""
DockerDeck – tests/test_docker_runner.py
pytest: smoke tests for docker_runner using mocked subprocess.
No Docker daemon required.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import subprocess
import threading
import pytest
from unittest.mock import patch, MagicMock
from docker_runner import run_docker, run_docker_stream, docker_available


class TestRunDocker:
    def test_returns_stdout(self):
        mock = MagicMock()
        mock.stdout = "abc\n"; mock.stderr = ""; mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            out, err, rc = run_docker(["ps"])
        assert rc == 0 and out == "abc"

    def test_docker_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _, err, rc = run_docker(["ps"])
        assert rc == 1 and "Docker not found" in err

    def test_timeout(self):
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("docker", 30)):
            _, err, rc = run_docker(["ps"])
        assert rc == 1 and "timed out" in err

    def test_returncode_passed_through(self):
        mock = MagicMock()
        mock.stdout = ""; mock.stderr = "error"; mock.returncode = 1
        with patch("subprocess.run", return_value=mock):
            _, err, rc = run_docker(["ps"])
        assert rc == 1


class TestRunDockerStream:
    def test_streams_lines(self):
        received = []
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n", "line2\n"])
        mock_proc.wait = MagicMock(); mock_proc.returncode = 0
        with patch("subprocess.Popen", return_value=mock_proc):
            run_docker_stream(["logs", "c"], received.append)
        assert "line1\n" in received and "line2\n" in received

    def test_stop_event_terminates(self):
        stop = threading.Event(); stop.set()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n"])
        mock_proc.wait = MagicMock()
        with patch("subprocess.Popen", return_value=mock_proc):
            run_docker_stream(["logs", "-f", "c"], lambda _: None,
                              stop_event=stop)
        mock_proc.terminate.assert_called()


class TestDockerAvailable:
    def test_true_on_zero(self):
        mock = MagicMock()
        mock.stdout = ""; mock.stderr = ""; mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            assert docker_available() is True

    def test_false_on_nonzero(self):
        mock = MagicMock()
        mock.stdout = ""; mock.stderr = "err"; mock.returncode = 1
        with patch("subprocess.run", return_value=mock):
            assert docker_available() is False

    def test_false_when_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert docker_available() is False
