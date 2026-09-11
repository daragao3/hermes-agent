"""Fatal gateway startup preserves diagnostics before the existing exit backstop."""
from unittest.mock import Mock
import pytest
from gateway import run, status


@pytest.mark.parametrize("error, expected", [(RuntimeError("boom"), 1), (KeyboardInterrupt(), 0)])
def test_main_exit_backstop_and_fatal_sidecar(tmp_path, monkeypatch, error, expected):
    monkeypatch.setattr(run, "_guard_corrupt_user_config", Mock())
    monkeypatch.setattr(run, "_best_effort", Mock())
    monkeypatch.setattr(run.sys, "argv", ["gateway"])
    def crash(coro):
        coro.close()
        raise error
    monkeypatch.setattr(run.asyncio, "run", crash)
    exit_backstop = Mock()
    monkeypatch.setattr(run, "_exit_after_graceful_shutdown", exit_backstop)
    monkeypatch.setattr(status, "_get_pid_path", lambda: tmp_path / "gateway.pid")
    emit = Mock()
    monkeypatch.setattr("events.gateway_integration.emit_gateway_stopped", emit)
    run.main()
    exit_backstop.assert_called_once_with(expected)
    sidecar = tmp_path / "gateway.fatal"
    if expected:
        assert "RuntimeError: boom" in sidecar.read_text(encoding="utf-8")
        assert emit.call_args.args[0]["exit_reason"] == "fatal_exception"
    else:
        assert not sidecar.exists()
        emit.assert_not_called()
