"""The codex app-server schema probe must actually time out.

``session_bridge.characterize._codex_schema_advertises_archive`` runs
``codex app-server generate-json-schema --out <dir>`` to decide whether the
characterization thread can be archived. It used
``subprocess.run(capture_output=True, text=True, timeout=60)``.

That bound never fires on Windows when codex is the npm shim:
``resolve_codex_command`` returns ``codex.cmd`` verbatim once the
Desktop-shipped codex is absent (explicit-path and PATH branches alike), so
cmd.exe is the direct child and node.exe the grandchild holding the capture
pipe. ``subprocess.run`` raises ``TimeoutExpired`` at 60 s and its except path
calls ``communicate()`` with NO timeout, joining the reader threads until the
grandchild exits on its own — the class ``_file_backed_claude_run`` was
converted for (``test_characterize_file_backed_capture.py``).

The probe now goes through ``hermes_cli._subprocess_compat.run_text_capture``
(temp-file stdio, tree-kill on timeout). Tests stub THAT helper, never
``subprocess.run``, and keep the ``except (OSError, SubprocessError,
ValueError) -> False`` contract.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import hermes_cli._subprocess_compat as _spc
import session_bridge.characterize as characterize_module

CODEX = ("C:/Users/x/AppData/Roaming/npm/codex.cmd",)


def _forbid_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "subprocess.run(capture_output=True) reached: the codex schema probe "
            "must run through run_text_capture"
        )

    monkeypatch.setattr(subprocess, "run", boom)


def _schema_writer(
    calls: list[tuple[list[str], dict[str, Any]]],
    *,
    strings: list[str],
    returncode: int = 0,
) -> Any:
    """A ``run_text_capture`` stand-in that writes ``ClientRequest.json``.

    The probe reads the schema from the ``--out`` directory it created, so the
    stub has to honour the argv it was handed, exactly as codex would.
    """

    def fake_capture(argv: list[str], **kwargs: Any) -> Any:
        calls.append((list(argv), dict(kwargs)))
        out_dir = Path(argv[argv.index("--out") + 1])
        assert out_dir.is_dir(), out_dir
        (out_dir / "ClientRequest.json").write_text(
            json.dumps({"oneOf": [{"properties": {"method": {"enum": strings}}}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(list(argv), returncode, stdout="", stderr="")

    return fake_capture


def test_schema_probe_runs_through_file_backed_capture_with_the_probe_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        _spc, "run_text_capture", _schema_writer(calls, strings=["thread/archive"])
    )

    assert characterize_module._codex_schema_advertises_archive(CODEX) is True

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:4] == [CODEX[0], "app-server", "generate-json-schema", "--out"]
    assert len(argv) == 5
    assert Path(argv[4]).name.startswith("hermes-codex-schema-")
    # The temp directory is torn down with the probe.
    assert not Path(argv[4]).exists()
    assert kwargs == {
        "timeout": 60.0,
        "stdin": subprocess.DEVNULL,
        "shell": False,
        "text": True,
    }


def test_schema_probe_is_false_without_the_archive_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        _spc, "run_text_capture", _schema_writer(calls, strings=["thread/start"])
    )

    assert characterize_module._codex_schema_advertises_archive(CODEX) is False
    assert len(calls) == 1


def test_schema_probe_is_false_on_a_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess_run(monkeypatch)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        _spc,
        "run_text_capture",
        _schema_writer(calls, strings=["thread/archive"], returncode=1),
    )

    assert characterize_module._codex_schema_advertises_archive(CODEX) is False


@pytest.mark.parametrize(
    "raised",
    [
        subprocess.TimeoutExpired(cmd=list(CODEX), timeout=60.0),
        FileNotFoundError(CODEX[0]),
        ValueError("embedded null byte"),
    ],
    ids=["timeout", "not-installed", "value-error"],
)
def test_schema_probe_maps_helper_failures_to_false(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    """The helper raises the same ``TimeoutExpired`` / ``FileNotFoundError`` as
    ``subprocess.run`` did, so the existing ``-> False`` contract is unchanged:
    a probe that times out means ``manual_archive_required``, not a crash."""
    _forbid_subprocess_run(monkeypatch)
    calls: list[list[str]] = []

    def failing(argv: list[str], **kwargs: Any) -> Any:
        calls.append(list(argv))
        raise raised

    monkeypatch.setattr(_spc, "run_text_capture", failing)

    assert characterize_module._codex_schema_advertises_archive(CODEX) is False
    assert calls == [[CODEX[0], "app-server", "generate-json-schema", "--out", calls[0][4]]]
