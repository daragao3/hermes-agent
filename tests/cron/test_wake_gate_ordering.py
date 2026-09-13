"""The wake gate must run before any model-session machinery exists.

A cron tick whose pre-check script says there is nothing to do must not pay
for -- or leave behind -- a SessionDB row or an AIAgent. These tests assert
ordering by observing what got constructed, driving the real ``run_job`` seam.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def hermes_env(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "scripts").mkdir()
    (home / "cron").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    import hermes_constants
    importlib.reload(hermes_constants)
    import cron.jobs
    importlib.reload(cron.jobs)
    import cron.scheduler
    importlib.reload(cron.scheduler)
    return home


@pytest.fixture
def session_db_calls(monkeypatch):
    """Count the post-gate session-store seam and stop before model I/O."""
    calls = []
    from cron import scheduler

    def _open(_job):
        calls.append(1)
        return None

    monkeypatch.setattr(scheduler, "_open_cron_session_db", _open)
    monkeypatch.setattr(
        scheduler,
        "_construct_cron_agent",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("stop after session seam")),
    )
    return calls


@pytest.fixture
def healthy_preflight(monkeypatch):
    """Let proceed paths reach SessionDB without real provider side effects."""
    from cron import scheduler

    monkeypatch.setattr(scheduler, "_preflight_or_block", lambda *_a, **_k: None)
    monkeypatch.setattr(
        scheduler,
        "_resolve_job_runtime",
        lambda *_a, **_k: (
            {
                "provider": "custom",
                "requested_provider": "custom",
                "api_key": "test",
                "base_url": "http://127.0.0.1:1/v1",
                "api_mode": "chat_completions",
                "request_overrides": {},
                "command": None,
                "args": None,
            },
            "test-model",
        ),
    )
    monkeypatch.setattr(scheduler, "_load_credential_pool", lambda *_a, **_k: None)
    monkeypatch.setattr(scheduler, "_init_cron_mcp_tools", lambda *_a, **_k: None)


def _gated_job(hermes_env, body):
    from cron.jobs import create_job

    script = hermes_env / "scripts" / "probe.sh"
    script.write_text(f"#!/bin/bash\n{body}\n")
    return create_job(
        prompt="do work",
        schedule="every 5m",
        script="probe.sh",
        deliver="local",
    )


def test_wake_gate_false_creates_no_session_or_agent(hermes_env, session_db_calls):
    from unittest.mock import patch

    from cron.scheduler import SILENT_MARKER, run_job

    job = _gated_job(hermes_env, "echo '{\"wakeAgent\": false}'")

    with patch("run_agent.AIAgent") as agent_cls:
        ok, _doc, final, error = run_job(job)

    assert ok is True and error is None
    assert final == SILENT_MARKER
    agent_cls.assert_not_called()
    assert session_db_calls == [], "no model-session state may exist before the gate"


def test_wake_gate_true_still_builds_session(
    hermes_env, session_db_calls, healthy_preflight, monkeypatch,
):
    from cron import scheduler
    from cron.scheduler import run_job

    monkeypatch.setattr(scheduler, "_build_job_prompt", lambda *_a, **_k: "work")
    job = _gated_job(hermes_env, "echo '{\"wakeAgent\": true}'")

    # The run may fail later (no provider configured in the test env); the
    # assertion is only about what the gate allowed to be constructed.
    run_job(job)

    assert session_db_calls == [1]


def test_gate_false_runs_the_script_exactly_once(hermes_env, session_db_calls):
    """Reordering must not reintroduce a double script execution."""
    from cron import scheduler
    from cron.scheduler import run_job

    runs = []
    original = scheduler._run_job_script_with_claim_heartbeat

    def _counting(job, script_path, **kwargs):
        runs.append(script_path)
        return original(job, script_path, **kwargs)

    scheduler._run_job_script_with_claim_heartbeat = _counting
    try:
        run_job(_gated_job(hermes_env, "echo '{\"wakeAgent\": false}'"))
    finally:
        scheduler._run_job_script_with_claim_heartbeat = original

    assert len(runs) == 1


def test_scriptless_job_still_reaches_the_session(
    hermes_env, session_db_calls, healthy_preflight, monkeypatch,
):
    """A job with no pre-check script has no gate and must proceed."""
    from cron import scheduler
    from cron.jobs import create_job
    from cron.scheduler import run_job

    monkeypatch.setattr(scheduler, "_build_job_prompt", lambda *_a, **_k: "work")
    job = create_job(prompt="do work", schedule="every 5m", deliver="local")

    run_job(job)

    assert session_db_calls == [1]


def test_silent_script_output_skips_the_model_call(hermes_env, session_db_calls):
    """Interim contract for a hybrid job whose script went silent.

    Empty stdout is NOT a wakeAgent:false gate, so the gate lets the run
    proceed -- but _build_job_prompt then returns None and the tick ends
    silently with no model call and no delivery. This is the behavior that
    ships before the (separately gated) no_agent conversion.
    """
    from unittest.mock import patch

    from cron.scheduler import SILENT_MARKER, run_job

    job = _gated_job(hermes_env, "# prints nothing")

    with patch("run_agent.AIAgent") as agent_cls:
        ok, _doc, final, error = run_job(job)

    assert ok is True and error is None
    assert final == SILENT_MARKER, "a silent script must not deliver"
    # A silent script must not cost a model call.
    agent_cls.assert_not_called()
