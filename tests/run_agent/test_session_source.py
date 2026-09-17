import pytest

from gateway.session_context import _UNSET, _VAR_MAP, clear_session_vars, set_session_vars
from run_agent import _session_source_for_agent


@pytest.fixture(autouse=True)
def _reset_contextvars():
    for var in _VAR_MAP.values():
        var.set(_UNSET)
    yield
    for var in _VAR_MAP.values():
        var.set(_UNSET)


def test_session_source_context_overrides_platform(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_SOURCE", raising=False)

    tokens = set_session_vars(source="tool")
    try:
        assert _session_source_for_agent("tui") == "tool"
    finally:
        clear_session_vars(tokens)


def test_session_source_falls_back_to_platform(monkeypatch):
    monkeypatch.delenv("HERMES_SESSION_SOURCE", raising=False)

    assert _session_source_for_agent("tui") == "tui"




def test_persistence_source_on_bare_agent_without_platform(monkeypatch):
    """A bare ``AIAgent.__new__`` instance (98 tests build one; init_agent never ran) has no
    ``platform`` attribute. The persistence source must resolve to "cli" like a CLI agent, not
    raise AttributeError from every persistence seam that calls it (turn_facade, turn_usage,
    codex_runtime)."""
    monkeypatch.delenv("HERMES_SESSION_SOURCE", raising=False)
    from run_agent import AIAgent

    agent = AIAgent.__new__(AIAgent)
    assert not hasattr(agent, "platform")

    assert agent._session_source_for_persistence() == "cli"

    agent.platform = "telegram"
    assert agent._session_source_for_persistence() == "telegram"


def test_turn_facade_accounting_source_tolerates_stand_in_without_method(monkeypatch):
    """``AIAgent.run_conversation`` is also driven with a ``SimpleNamespace`` as ``self``
    (tests/hermes_cli/test_relay_shared_metrics_runtime.py). Every other read on the
    accounting-context line is a getattr; the source must fall back to ``platform`` the way
    agent.turn_context does rather than fail on the missing method."""
    from types import SimpleNamespace

    import agent.aux_accounting as aux_accounting
    from run_agent import AIAgent

    seen: dict = {}

    def fake_set_accounting_context(session_db, session_id, *, source=None, model_config=None):
        seen.update(session_db=session_db, session_id=session_id, source=source)
        return object()

    # turn_facade imports these inside run_conversation, so patch the defining module.
    monkeypatch.setattr(aux_accounting, "set_accounting_context", fake_set_accounting_context)
    monkeypatch.setattr(aux_accounting, "reset_accounting_context", lambda _token: None)
    monkeypatch.setattr(
        "agent.conversation_loop.run_conversation",
        lambda *_args, **_kwargs: {"final_response": "done", "completed": True, "interrupted": False},
    )

    stand_in = SimpleNamespace(
        session_id="child",
        platform="subagent",
        _session_db=None,
        _conversation_root_id=lambda: "parent",
    )
    AIAgent.run_conversation(stand_in, "hi")

    assert seen["source"] == "subagent"
    assert seen["session_id"] == "child"
