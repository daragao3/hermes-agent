"""The disposable Claude session's runners must actually time out.

``session_bridge/characterize.py`` drives the disposable session twice — the
create turn through ``ClaudeTargetAdapter.create_placeholder`` (runner
``_run_creation``) and the resume turn in ``_resume_claude_characterization``.
Both used ``subprocess.run(capture_output=True, text=True, timeout=180)``.

That bound never fires on Windows once the session has started the project's
MCP servers (cwd is the project under characterization; observed 2026-09-18:
agent-src's codegraph ``node.exe … serve --mcp``). The server inherits the
capture pipe handles and outlives ``claude.exe``; the pipe never reaches EOF,
``subprocess.run`` raises ``TimeoutExpired`` at 180 s, and its except path
calls ``communicate()`` with NO timeout, joining the reader threads until the
grandchild dies on its own (~30 min per turn). py-spy of the wedged run:
``join <- _communicate <- communicate <- run <- _resume_claude_characterization``.

Both sites now go through ``hermes_cli._subprocess_compat.run_text_capture``
(temp-file stdio, tree-kill on timeout) via ``_file_backed_claude_run``. Tests
stub THAT helper, never ``subprocess.run``; the last test proves the bound with
a real process tree.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hermes_cli._subprocess_compat as _spc
import session_bridge.characterize as characterize_module
from session_bridge.characterize import PlaceholderCreationError
from session_bridge.models import OriginKind
from tests.timeout_budget import scaled

CLAUDE_ID = "22222222-2222-4222-8222-222222222222"
NONCE = "c" * 32


def _forbid_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "subprocess.run(capture_output=True) reached: the disposable Claude "
            "session must run through run_text_capture"
        )

    monkeypatch.setattr(subprocess, "run", boom)


def _baseline_projection() -> Any:
    return SimpleNamespace(
        native_id=CLAUDE_ID,
        origin_kind=OriginKind.BRIDGE_PLACEHOLDER,
        origin_bridge_id="bridge-1",
        native_cursor="cursor-before",
        native_hash="hash-before",
        messages=[
            SimpleNamespace(
                native_event_id="registration",
                ordinal=0,
                role="user",
                content="registration metadata",
            )
        ],
    )


class _NothingFoundSource:
    """A Claude source that never discovers the resumed transcript.

    With ``verification_timeout=0`` the resume step then surfaces the process
    failure it recorded, which is the code under test here.
    """

    def __init__(self) -> None:
        self.find_calls: list[str] = []

    def find_native_session(self, native_id: str) -> Path | None:
        self.find_calls.append(native_id)
        return None

    def parse(self, path: Path) -> Any:  # pragma: no cover - never reached
        raise AssertionError(f"parse called for {path}")


def _resume(source: Any, *, executable: str, cwd: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "baseline_projection": _baseline_projection(),
        "native_id": CLAUDE_ID,
        "bridge_id": "bridge-1",
        "resume_nonce": NONCE,
        "executable": executable,
        "cwd": cwd,
    }
    kwargs.update(overrides)
    return characterize_module._resume_claude_characterization(source, **kwargs)


# ---------------------------------------------------------------------------
# The shared runner
# ---------------------------------------------------------------------------


def test_file_backed_claude_run_forwards_the_runner_shape_to_run_text_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    completed = subprocess.CompletedProcess(["claude"], 0, stdout="{}", stderr="")

    def fake_capture(argv: list[str], **kwargs: Any) -> Any:
        calls.append((list(argv), dict(kwargs)))
        return completed

    monkeypatch.setattr(_spc, "run_text_capture", fake_capture)

    result = characterize_module._file_backed_claude_run(
        ("claude", "--print", "hi"),
        capture_output=True,
        text=True,
        timeout=180.0,
        stdin=subprocess.DEVNULL,
        shell=False,
        check=False,
        cwd=str(tmp_path),
    )

    assert result is completed
    assert calls == [
        (
            ["claude", "--print", "hi"],
            {
                "timeout": 180.0,
                "cwd": str(tmp_path),
                "env": None,
                "stdin": subprocess.DEVNULL,
                "shell": False,
                "text": True,
            },
        )
    ]


@pytest.mark.parametrize(
    "kwargs", [{"capture_output": False}, {"check": True}], ids=["no-capture", "check"]
)
def test_file_backed_claude_run_refuses_shapes_the_helper_cannot_honour(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    _forbid_subprocess_run(monkeypatch)

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("run_text_capture must not be reached")

    monkeypatch.setattr(_spc, "run_text_capture", never)
    with pytest.raises(ValueError):
        characterize_module._file_backed_claude_run(["claude"], timeout=1.0, **kwargs)


# ---------------------------------------------------------------------------
# The resume turn
# ---------------------------------------------------------------------------


def test_resume_step_defaults_to_file_backed_capture_and_keeps_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    stdout = json.dumps({
        "subtype": "error_max_budget_usd",
        "total_cost_usd": 0.25,
        "duration_ms": 640,
        "num_turns": 1,
    })

    def fake_capture(argv: list[str], **kwargs: Any) -> Any:
        calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(list(argv), 1, stdout=stdout, stderr="")

    monkeypatch.setattr(_spc, "run_text_capture", fake_capture)

    with pytest.raises(PlaceholderCreationError) as exc_info:
        _resume(
            _NothingFoundSource(),
            executable="C:/bin/claude.cmd",
            cwd=tmp_path,
            verification_timeout=0.0,
        )

    # The process-failure classification and its metrics still read the
    # helper's decoded stdout, so the existing codes and diagnostics survive.
    assert exc_info.value.code == "claude_resume_error_max_budget_usd"
    assert exc_info.value.observed_cost_usd == 0.25
    assert exc_info.value.duration_ms == 640.0
    assert exc_info.value.num_turns == 1
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:1] == ["C:/bin/claude.cmd"]
    assert argv.count("--resume") == 1 and CLAUDE_ID in argv
    assert argv[:-1] == [
        "C:/bin/claude.cmd",
        "--print",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--resume",
        CLAUDE_ID,
        "--tools",
        "",
        "--permission-mode",
        "dontAsk",
        "--max-budget-usd",
        "0.50",
        "--output-format",
        "json",
    ]
    assert kwargs["timeout"] == 180.0
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["shell"] is False
    assert kwargs["text"] is True


def test_resume_step_maps_the_helper_timeout_to_the_existing_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess_run(monkeypatch)

    def timed_out(argv: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=kwargs["timeout"])

    monkeypatch.setattr(_spc, "run_text_capture", timed_out)

    with pytest.raises(PlaceholderCreationError) as exc_info:
        _resume(
            _NothingFoundSource(),
            executable="C:/bin/claude.cmd",
            cwd=tmp_path,
            verification_timeout=0.0,
        )
    assert exc_info.value.code == "claude_resume_timeout"


# ---------------------------------------------------------------------------
# The create turn
# ---------------------------------------------------------------------------


def test_create_step_runs_the_placeholder_through_file_backed_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def not_installed(argv: list[str], **kwargs: Any) -> Any:
        calls.append((list(argv), dict(kwargs)))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(_spc, "run_text_capture", not_installed)
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    status: dict[str, Any] = {}
    # A native path: resolve_claude_command refuses an explicit .cmd shim (in
    # production `claude` resolves to the Desktop-shipped claude.exe, and the
    # MCP server it starts is the grandchild).
    executable = str(tmp_path / "bin" / "claude.exe")

    with pytest.raises(PlaceholderCreationError) as exc_info:
        characterize_module._characterize_claude(
            status,
            characterization_id="char-1",
            title="[Hermes Bridge Characterization] char-1",
            marker_secret=b"secret-material-for-the-test",
            projects_root=projects_root,
            report_root=tmp_path / "reports",
            executable=executable,
            cwd=tmp_path,
        )

    assert exc_info.value.code == "claude_executable_not_found"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:1] == [executable]
    assert argv.count("--session-id") == 1
    assert status["native_id"] in argv
    assert kwargs["timeout"] == 180.0
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["shell"] is False
    assert status["cleanup"] == "not_moved_safety_check"


# ---------------------------------------------------------------------------
# The bound, against a real process tree
# ---------------------------------------------------------------------------


def _wedged_claude_shim(directory: Path) -> str:
    """A ``claude`` stand-in whose child outlives any budget used here.

    Windows: a ``.cmd`` shim — cmd.exe is the direct child and ``ping`` its
    grandchild, both holding the inherited stdio (60 pings ~= 59 s). Same
    tree shape as ``claude.exe`` + the MCP server it starts. POSIX: ``sh``
    running a ``sleep`` child. The resume step takes the path verbatim
    (``_immutable_argv_prefix``), so a shim is usable here.
    """
    if sys.platform == "win32":
        shim = directory / "claude.cmd"
        shim.write_bytes(b"@echo off\r\nping -n 60 127.0.0.1\r\n")
        return str(shim)
    shim = directory / "claude"
    shim.write_bytes(b"#!/bin/sh\nsleep 60; exit 0\n")
    shim.chmod(0o755)
    return str(shim)


@pytest.mark.timeout(scaled(180))
def test_resume_step_times_out_with_a_grandchild_holding_the_pipe(
    tmp_path: Path,
) -> None:
    """``process_timeout=2`` must bound the resume turn even though the shim's
    grandchild holds the capture handles for ~59 s.

    Under ``subprocess.run(capture_output=True)`` this call lasted as long as
    the grandchild (the memory of the 2026-09-18 wedge: ~30 min per turn).
    The 30 s ceiling is the assertion itself — 2 s budget plus the synchronous
    tree-kill — and is deliberately not scaled.
    """
    executable = _wedged_claude_shim(tmp_path)
    source = _NothingFoundSource()

    started = time.monotonic()
    with pytest.raises(PlaceholderCreationError) as exc_info:
        _resume(
            source,
            executable=executable,
            cwd=tmp_path,
            process_timeout=2.0,
            verification_timeout=0.0,
        )
    elapsed = time.monotonic() - started

    assert exc_info.value.code == "claude_resume_timeout"
    assert source.find_calls == [CLAUDE_ID]
    assert elapsed < 30, (
        f"resume turn took {elapsed:.1f}s against a 2s budget: the runner is "
        "waiting on a capture pipe the grandchild still holds open"
    )
