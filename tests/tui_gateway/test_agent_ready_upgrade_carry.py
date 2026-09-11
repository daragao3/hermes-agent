import threading
import types
import pytest
from tui_gateway import server

@pytest.fixture(autouse=True)
def no_external_startup(monkeypatch):
    monkeypatch.setattr("tui_gateway.entry.ensure_mcp_discovery_started", lambda: None)
    monkeypatch.setattr("agent.credits_tracker.seed_credits_at_session_start", lambda *a: None)

def test_start_agent_build_is_ready_before_session_info_emit(monkeypatch):
    """Transport backpressure after callback wiring must not define readiness."""
    emit_started = threading.Event()
    release_emit = threading.Event()
    post_ready_failure_logged = threading.Event()

    class FakeWorker:
        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    agent = types.SimpleNamespace(model="claude-sonnet-4.6")

    def blocking_emit(event, *_args, **_kwargs):
        if event == "session.info":
            emit_started.set()
            release_emit.wait(timeout=3)
            raise RuntimeError("transport closed after readiness")

    monkeypatch.setattr(server, "_set_session_context", lambda target: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda tokens: None)
    monkeypatch.setattr(server, "_make_agent", lambda *_a, **_k: agent)
    monkeypatch.setattr(server, "_config_model_target", lambda: "claude-sonnet-4.6")
    monkeypatch.setattr(server, "_SlashWorker", FakeWorker)
    monkeypatch.setattr(server, "_attach_worker", lambda *a, **k: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_load_memory_notifications", lambda: False)
    monkeypatch.setattr(server, "_emit", blocking_emit)
    monkeypatch.setattr(server, "_session_info", lambda *a, **k: {})
    monkeypatch.setattr(server, "_start_notification_poller", lambda *a, **k: None)
    monkeypatch.setattr(server, "_notify_session_boundary", lambda *a, **k: None)
    monkeypatch.setattr(server, "_probe_config_health", lambda *_a: None)
    monkeypatch.setattr(server, "_schedule_mcp_late_refresh", lambda *a, **k: None)
    monkeypatch.setattr(
        server.logger,
        "warning",
        lambda *_a, **_k: post_ready_failure_logged.set(),
    )

    sid = "build-ready-before-emit"
    session = {
        "agent": None,
        "agent_ready": threading.Event(),
        "session_key": "k-ready",
        "profile_home": None,
    }
    server._sessions[sid] = session
    try:
        server._start_agent_build(sid, session)
        assert emit_started.wait(timeout=3), "agent build never reached session.info emit"
        assert session["agent"] is agent
        assert session["agent_ready"].wait(timeout=0.2), (
            "agent readiness still depends on session.info transport completion"
        )
        release_emit.set()
        assert post_ready_failure_logged.wait(timeout=3)
        assert not session.get("agent_error")
    finally:
        release_emit.set()
        session["agent_ready"].wait(timeout=3)
        server._sessions.clear()


def test_start_agent_build_failure_is_ready_before_error_emit(monkeypatch):
    """A blocked error notification must not hide the initialization error."""
    emit_started = threading.Event()
    release_emit = threading.Event()

    def fail_agent_build(*_args, **_kwargs):
        raise RuntimeError("agent construction failed")

    def blocking_emit(event, *_args, **_kwargs):
        if event == "error":
            emit_started.set()
            release_emit.wait(timeout=3)

    monkeypatch.setattr(server, "_set_session_context", lambda target: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda tokens: None)
    monkeypatch.setattr(server, "_make_agent", fail_agent_build)
    monkeypatch.setattr(server, "_emit", blocking_emit)

    sid = "build-failure-before-emit"
    session = {
        "agent": None,
        "agent_ready": threading.Event(),
        "session_key": "k-failure",
        "profile_home": None,
    }
    server._sessions[sid] = session
    try:
        server._start_agent_build(sid, session)
        assert emit_started.wait(timeout=3), "agent build never emitted its failure"
        assert session["agent_ready"].wait(timeout=0.2), (
            "agent failure remained hidden behind transport backpressure"
        )
        assert session["agent_error"] == "agent construction failed"
    finally:
        release_emit.set()
        server._sessions.clear()


