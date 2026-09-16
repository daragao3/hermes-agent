"""Behavioral coverage for the SR-471 agent-loop fault boundary."""

from types import SimpleNamespace
import traceback
from unittest.mock import MagicMock, patch

from agent import turn_api_error


def _agent(**overrides):
    values = {
        "provider": "openai",
        "model": "gpt-5.5",
        "log_prefix": "",
        "session_id": "session-471",
        "thinking_callback": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _handle_kwargs(api_error):
    agent = _agent()
    agent._extract_api_error_context = MagicMock(return_value={})
    return agent, {
        "api_error": api_error,
        "_retry": SimpleNamespace(),
        "thinking_spinner": None,
        "messages": [],
        "api_messages": [],
        "api_kwargs": {},
        "system_message": None,
        "active_system_prompt": "system",
        "conversation_history": [],
        "approx_tokens": 0,
        "retry_count": 0,
        "max_retries": 1,
        "compression_attempts": 0,
        "max_compression_attempts": 1,
        "api_call_count": 1,
        "api_request_id": "request-471",
        "api_start_time": 0,
        "effective_task_id": "task-471",
        "turn_id": "turn-471",
    }


def test_api_boundary_reports_exception_once_even_when_classification_raises():
    """The fault is emitted exactly once per error. Since 2026-09-15 it is emitted AFTER the
    recovery decision (so a fallback-recovered turn can withhold it), which means a handler
    that crashes mid-classification must still emit on its way out."""
    api_error = ValueError("non-retryable local validation failure")
    agent, kwargs = _handle_kwargs(api_error)
    order = []

    def report(*args, **call_kwargs):
        order.append("emit")
        assert args == (agent, api_error)
        assert call_kwargs == {"correlation_id": "task-471"}

    def classify(*args, **call_kwargs):
        order.append("classify")
        raise AssertionError("classification blew up")

    with (
        patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=report),
        patch.object(turn_api_error, "recover_before_classification", return_value=(False, "system")),
        patch.object(turn_api_error, "classify_api_error", side_effect=classify),
        patch("tools.interpreter_shutdown.interpreter_shutting_down", return_value=False),
    ):
        try:
            turn_api_error.handle_api_error(agent, **kwargs)
        except AssertionError as exc:
            assert str(exc) == "classification blew up"

    assert order == ["classify", "emit"]


def _verdict(action):
    return turn_api_error.ApiErrorVerdict(
        action=action, thinking_spinner=None, messages=[], active_system_prompt="system",
        conversation_history=[], approx_tokens=0, retry_count=0, max_retries=1,
        compression_attempts=0, _provider_overflow_recovery_pending=False, result=None,
    )


def test_fault_not_emitted_when_a_fallback_recovers_the_turn():
    """A ``"break"`` verdict with ``_fallback_index`` advanced = the turn continues on another
    backend. That was the 2026-09-15 storm: every cron fire on the exhausted Codex primary
    paged once although DeepSeek answered the turn."""
    api_error = RuntimeError("429 usage_limit_reached")
    agent, kwargs = _handle_kwargs(api_error)
    agent._fallback_index = 0
    reports = []

    def inner(agent_, **_kw):
        agent_._fallback_index = 1  # try_activate_fallback advanced the chain
        return _verdict("break")

    with (
        patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=lambda *a, **k: reports.append(k)),
        patch.object(turn_api_error, "_handle_api_error_inner", side_effect=inner),
    ):
        verdict = turn_api_error.handle_api_error(agent, **kwargs)

    assert verdict.action == "break"
    assert reports == [], "a fallback-recovered error must not emit agent_loop_fault"


def test_fault_still_emitted_when_break_is_not_a_fallback_or_the_turn_retries():
    api_error = RuntimeError("500 upstream")
    agent, kwargs = _handle_kwargs(api_error)
    agent._fallback_index = 0
    reports = []

    # "break" without the chain advancing: a redirect/rebuild, not a fallback -> emit.
    with (
        patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=lambda *a, **k: reports.append(k)),
        patch.object(turn_api_error, "_handle_api_error_inner", return_value=_verdict("break")),
    ):
        turn_api_error.handle_api_error(agent, **kwargs)
    # "continue" (plain retry) with the chain advanced elsewhere earlier this turn -> emit.
    agent._fallback_index = 2
    with (
        patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=lambda *a, **k: reports.append(k)),
        patch.object(turn_api_error, "_handle_api_error_inner", return_value=_verdict("continue")),
    ):
        turn_api_error.handle_api_error(agent, **kwargs)

    assert [r["correlation_id"] for r in reports] == ["task-471", "task-471"]


def test_boundary_log_redacts_exception_without_losing_original_frames(caplog):
    agent = _agent()
    try:
        raise ValueError("OPENAI_API_KEY=dummy")
    except ValueError as exc:
        with (
            patch("events.loop_fault.emit_agent_loop_fault"),
            caplog.at_level("WARNING", logger="agent.conversation_loop"),
        ):
            turn_api_error._report_agent_loop_fault(
                agent, exc, correlation_id="task-471"
            )

    record = next(
        item for item in caplog.records
        if "Agent loop stream/API boundary caught" in item.getMessage()
    )
    logged_traceback = "".join(traceback.format_exception(*record.exc_info))
    assert "dummy" not in logged_traceback
    assert "OPENAI_API_KEY=***" in logged_traceback
    assert "test_boundary_log_redacts_exception_without_losing_original_frames" in logged_traceback


def test_emitter_failure_is_swallowed():
    agent = _agent()
    exc = ValueError("bad response")

    with patch(
        "events.loop_fault.emit_agent_loop_fault",
        side_effect=RuntimeError("event bus unavailable"),
    ):
        turn_api_error._report_agent_loop_fault(agent, exc, correlation_id="task-471")


def test_api_boundary_prefers_turn_id_then_session_id_for_correlation():
    api_error = TimeoutError("backend timeout")
    agent, kwargs = _handle_kwargs(api_error)
    kwargs["effective_task_id"] = None
    seen = []

    def report(*args, **call_kwargs):
        seen.append(call_kwargs["correlation_id"])
        raise RuntimeError("stop")

    with patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=report):
        try:
            turn_api_error.handle_api_error(agent, **kwargs)
        except RuntimeError:
            pass

    kwargs["turn_id"] = None
    with patch.object(turn_api_error, "_report_agent_loop_fault", side_effect=report):
        try:
            turn_api_error.handle_api_error(agent, **kwargs)
        except RuntimeError:
            pass

    assert seen == ["turn-471", "session-471"]
