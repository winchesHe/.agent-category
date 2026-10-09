from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.rs.cli import main
from scripts.rs.errors import Interrupted
from scripts.rs.models import CommandResult


class _SignalOnFirstWrite(io.StringIO):
    def __init__(self, signum: int) -> None:
        super().__init__()
        self._signum = signum
        self._sent = False

    def write(self, value: str) -> int:
        if not self._sent:
            self._sent = True
            os.kill(os.getpid(), self._signum)
        return super().write(value)


@pytest.mark.parametrize(
    ("signum", "expected_exit"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_process_signal_returns_control_envelope(signum: int, expected_exit: int) -> None:
    root = Path(__file__).parents[1]
    program = textwrap.dedent(
        """
        import sys
        import time
        from scripts.rs.cli import main

        def block(args, state):
            sys.stderr.write("READY\\n")
            sys.stderr.flush()
            time.sleep(30)

        raise SystemExit(main(["doctor"], dispatcher=block, environ={}))
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stderr is not None
    assert process.stderr.readline() == "READY\n"
    process.send_signal(signum)
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == expected_exit
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "command": "doctor",
        "error": {
            "category": "control",
            "code": "interrupted",
            "retryClass": "never",
        },
    }


def test_signal_during_final_write_returns_control_envelope() -> None:
    stdout = _SignalOnFirstWrite(signal.SIGTERM)

    code = main(
        ["doctor"],
        dispatcher=lambda _args, _state: CommandResult(data={"status": "ok"}),
        stdout=stdout,
        stderr=io.StringIO(),
        environ={},
    )

    assert code == 143
    assert json.loads(stdout.getvalue()) == {
        "schemaVersion": 1,
        "ok": False,
        "command": "doctor",
        "error": {
            "category": "control",
            "code": "interrupted",
            "retryClass": "never",
        },
    }


@pytest.mark.parametrize(
    ("artifact_state", "output_ref", "details"),
    [
        ("temp_created", None, None),
        ("final_link_created", None, {"artifactState": "may_exist"}),
        (
            "durable_published",
            "results.ndjson",
            {"artifactState": "published", "outputRef": "results.ndjson"},
        ),
    ],
)
def test_interruption_reports_only_proven_artifact_state(
    artifact_state: str, output_ref: str | None, details: dict | None
) -> None:
    stdout = io.StringIO()

    def interrupt(args, state):
        state.artifact_state = artifact_state
        state.output_ref = output_ref
        raise Interrupted(signal.SIGTERM)

    code = main(
        ["query", "--sql", "SELECT 1"],
        dispatcher=interrupt,
        stdout=stdout,
        stderr=io.StringIO(),
        environ={},
        install_signal_handlers=False,
    )
    assert code == 143
    error = json.loads(stdout.getvalue())["error"]
    if details is None:
        assert "details" not in error
    else:
        assert error["details"] == details


def test_interruption_preserves_remote_execution_state() -> None:
    stdout = io.StringIO()

    def interrupt(_args, _state):
        raise Interrupted(
            signal.SIGTERM,
            {"stage": "user", "executionState": "may_be_running"},
        )

    code = main(
        ["query", "--sql", "SELECT 1"],
        dispatcher=interrupt,
        stdout=stdout,
        stderr=io.StringIO(),
        environ={},
        install_signal_handlers=False,
    )

    assert code == 143
    assert json.loads(stdout.getvalue())["error"]["details"] == {
        "stage": "user",
        "executionState": "may_be_running",
    }
