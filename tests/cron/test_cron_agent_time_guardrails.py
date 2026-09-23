"""Cron agent time guardrails (loops cron-agent-job-timeouts-20260923).

Cron agent jobs hit their 3600 s wall clock because the agent slept and polled without knowing
how long it had left (ats-url-resolve slept 300-1380 s at a time; tracker/tailor polled long
runners). Two cron-scoped guardrails:

(a) every tool result in a cron session carries a short "[cron time budget]" note with the
    wall-clock time left, and a stronger wrap-up instruction under 10 minutes;
(b) in cron sessions a single terminal sleep / process wait longer than 120 s is REFUSED with an
    explanatory tool error (never silently truncated), so the agent adapts.

Interactive sessions must be unaffected by both.
"""

import json
import time
from types import SimpleNamespace

import pytest


def _tool_msgs(text="result"):
    return [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": []},
            {"role": "tool", "content": text, "tool_call_id": "t1"}]


# ---- (a) the time-left note ----------------------------------------------------------------

def test_interactive_agent_gets_no_note():
    from agent.conversation_loop import _maybe_inject_cron_time_note
    msgs = _tool_msgs()
    assert _maybe_inject_cron_time_note(SimpleNamespace(), msgs) is False
    assert msgs[-1]["content"] == "result"


def test_cron_agent_gets_minutes_left_on_the_newest_tool_result():
    from agent.conversation_loop import CRON_TIME_NOTE_MARKER, _maybe_inject_cron_time_note
    agent = SimpleNamespace(_cron_time_remaining=lambda: 1500.0)
    msgs = _tool_msgs()
    assert _maybe_inject_cron_time_note(agent, msgs) is True
    content = msgs[-1]["content"]
    assert content.startswith("result\n\n" + CRON_TIME_NOTE_MARKER)
    assert "About 25 min" in content
    assert "WRAP UP" not in content


def test_under_ten_minutes_the_note_says_wrap_up():
    from agent.conversation_loop import _maybe_inject_cron_time_note
    agent = SimpleNamespace(_cron_time_remaining=lambda: 420.0)
    msgs = _tool_msgs()
    _maybe_inject_cron_time_note(agent, msgs)
    assert "About 7 min" in msgs[-1]["content"]
    assert "WRAP UP NOW" in msgs[-1]["content"]


def test_one_note_per_tool_result_and_a_fresh_one_on_the_next():
    from agent.conversation_loop import CRON_TIME_NOTE_MARKER, _maybe_inject_cron_time_note
    agent = SimpleNamespace(_cron_time_remaining=lambda: 1500.0)
    msgs = _tool_msgs()
    assert _maybe_inject_cron_time_note(agent, msgs) is True
    assert _maybe_inject_cron_time_note(agent, msgs) is False  # both hook sites ran
    assert msgs[-1]["content"].count(CRON_TIME_NOTE_MARKER) == 1
    msgs += [{"role": "assistant", "content": "", "tool_calls": []},
             {"role": "tool", "content": "second", "tool_call_id": "t2"}]
    assert _maybe_inject_cron_time_note(agent, msgs) is True
    assert CRON_TIME_NOTE_MARKER in msgs[-1]["content"]


def test_persisted_tool_rows_are_never_rewritten():
    from agent.context_compressor import _DB_PERSISTED_MARKER
    from agent.conversation_loop import _maybe_inject_cron_time_note
    agent = SimpleNamespace(_cron_time_remaining=lambda: 1500.0)
    msgs = _tool_msgs()
    msgs[-1][_DB_PERSISTED_MARKER] = True
    assert _maybe_inject_cron_time_note(agent, msgs) is False
    assert msgs[-1]["content"] == "result"


def test_scheduler_attaches_the_watchdog_clock():
    import cron.scheduler as sched
    box = {"execution_started_monotonic": time.monotonic() - 600, "timeout_s": 3600.0}
    agent = SimpleNamespace()
    sched._attach_cron_time_budget(agent, box)
    assert 2990 <= agent._cron_time_remaining() <= 3000
    bare = SimpleNamespace()
    sched._attach_cron_time_budget(bare, None)
    assert not hasattr(bare, "_cron_time_remaining")


def test_tool_executor_flush_injects_before_persisting():
    """The wiring: the note must be in the row BEFORE it is flushed to the session DB."""
    from agent.conversation_loop import CRON_TIME_NOTE_MARKER
    from agent.tool_executor import _flush_session_db_after_tool_progress

    seen_at_flush = []
    agent = SimpleNamespace(
        _cron_time_remaining=lambda: 1500.0, run_budget_seconds=None, budget_warning_ratio=None,
        iteration_budget=None, valid_tool_names=(),
        _flush_messages_to_session_db=lambda m: seen_at_flush.append(m[-1]["content"]) or True)
    msgs = _tool_msgs()
    _flush_session_db_after_tool_progress(agent, msgs, stage="test")
    assert seen_at_flush and CRON_TIME_NOTE_MARKER in seen_at_flush[0]


# ---- (b) sleep / wait cap -------------------------------------------------------------------

@pytest.fixture
def cron_session(monkeypatch):
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")


@pytest.fixture
def ran(monkeypatch):
    import tools.terminal_tool as tt
    calls = []
    monkeypatch.setattr(tt, "terminal_tool", lambda **kw: calls.append(kw) or json.dumps({"ok": True}))
    return calls


@pytest.mark.parametrize("command", [
    "sleep 300", "sleep 5m", "cd x && sleep 170 && tail out.log",
    "Start-Sleep -Seconds 900", "Start-Sleep -Milliseconds 300000", "timeout /t 200",
])
def test_cron_session_refuses_a_long_sleep_with_an_explanation(cron_session, ran, command):
    import tools.terminal_tool as tt
    out = json.loads(tt._handle_terminal({"command": command}))
    assert "error" in out
    assert "cron session" in out["error"] and "120" in out["error"]
    assert ran == [], "a refused sleep must not run (and must not be silently truncated)"


@pytest.mark.parametrize("command", ["sleep 60", "sleep 120", "echo sleepy 900", "ls -la"])
def test_cron_session_allows_short_sleeps_and_normal_commands(cron_session, ran, command):
    import tools.terminal_tool as tt
    tt._handle_terminal({"command": command})
    assert len(ran) == 1


def test_interactive_session_long_sleep_is_unchanged(monkeypatch, ran):
    import tools.terminal_tool as tt
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    tt._handle_terminal({"command": "sleep 300"})
    assert len(ran) == 1


def test_cron_session_background_command_is_not_a_sleep(cron_session, ran):
    import tools.terminal_tool as tt
    tt._handle_terminal({"command": "sleep 600 && ./poll.sh", "background": True})
    assert len(ran) == 1


@pytest.fixture
def waited(monkeypatch):
    import tools.process_registry as pr
    calls = []
    monkeypatch.setattr(pr.process_registry, "wait",
                        lambda sid, timeout=None: calls.append(timeout) or {"status": "exited"})
    return calls


def test_cron_session_refuses_a_long_process_wait(cron_session, waited):
    import tools.process_registry as pr
    out = json.loads(pr._handle_process({"action": "wait", "session_id": "p1", "timeout": 600}))
    assert "error" in out and "process wait" in out["error"]
    assert waited == []


def test_cron_session_bare_wait_defaults_above_the_cap_and_is_refused(cron_session, waited, monkeypatch):
    import tools.process_registry as pr
    monkeypatch.setenv("TERMINAL_TIMEOUT", "180")
    out = json.loads(pr._handle_process({"action": "wait", "session_id": "p1"}))
    assert "error" in out
    assert waited == []


def test_cron_session_short_wait_and_interactive_long_wait_pass(waited, monkeypatch):
    import tools.process_registry as pr
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    pr._handle_process({"action": "wait", "session_id": "p1", "timeout": 90})
    monkeypatch.delenv("HERMES_CRON_SESSION")
    pr._handle_process({"action": "wait", "session_id": "p1", "timeout": 600})
    assert waited == [90, 600]
