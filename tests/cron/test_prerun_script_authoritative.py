"""A failed pre-run script must fail the RUN, after the agent turn.

An agent job's ``script:`` slot runs before the model turn. Until 2026-09-02
its result was consumed by exactly one thing -- the wakeAgent gate -- and only
when it SUCCEEDED. A failed pre-run script was merely prepended to the prompt
as "## Script Error" and the run's status came solely from the agent turn, so
``last_status`` stayed ``ok`` unless the model volunteered ``reason=error``.

That is what hid the 2026-08-19/20 profile-race "Script not found" failures
(loops ``applier-cron-script-profile-race-20260820``): the trigger was fixed by
6cfcf524fb, the HIDING MECHANISM was not. It is also wider than a missing file
-- ``_run_job_script`` returns failure for a nonzero exit code, a timeout, and
any exec exception, and all of them were equally invisible.

The structured-workload gates (64ed479556, a8f2d166c5) do not cover this: both
require the AGENT to declare failure, and a script that died never reaches
them. These tests assert the two halves that matter together -- the run is
recorded as FAILED, and the agent still ran and its report is still delivered.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cron.scheduler import SILENT_MARKER, run_job


def _job(**overrides):
    job = {
        "id": "prerun-test",
        "name": "prerun test",
        "prompt": "hello",
        "model": None,
        "provider": None,
        "provider_snapshot": None,
        "base_url": None,
    }
    job.update(overrides)
    return job


def _drive(job, hermes_home):
    """Run ``job`` through the real run_job seam with a mocked agent.

    Returns (success, output, final_response, error, agent_constructed).
    """
    fake_db = MagicMock()
    with patch("cron.scheduler._hermes_home", hermes_home), \
         patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
         patch("hermes_cli.env_loader.load_hermes_dotenv"), \
         patch("hermes_cli.env_loader.reset_secret_source_cache"), \
         patch("hermes_state.SessionDB", return_value=fake_db), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "test-key",
                 "base_url": "https://example.invalid/v1",
                 "provider": "openrouter",
                 "api_mode": "chat_completions",
             },
         ), \
         patch("run_agent.AIAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = {
            "final_response": "I am reporting the script error"
        }
        mock_agent_cls.return_value = mock_agent

        success, output, final_response, error = run_job(job)
        agent_constructed = mock_agent_cls.called

    return success, output, final_response, error, agent_constructed


def _scripts_dir(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_missing_prerun_script_fails_the_run(tmp_path):
    """The canonical applier case: Script not found must not record success."""
    _scripts_dir(tmp_path)
    job = _job(script="definitely_absent.py")

    success, _output, _final, error, agent_constructed = _drive(job, tmp_path)

    assert success is False, "a dead pre-run script must not be recorded as ok"
    assert error is not None
    assert "Pre-run script failed" in error
    assert "definitely_absent.py" in error, "the error must name the script"
    assert "Script not found" in error, "the underlying cause must survive"
    # The other half of the contract: the agent still ran, so the user still
    # gets a written report about the failure.
    assert agent_constructed is True


def test_failed_prerun_still_delivers_the_agent_report(tmp_path):
    """Delivery is unchanged -- only the recorded status flips."""
    _scripts_dir(tmp_path)
    job = _job(script="definitely_absent.py")

    success, output, final_response, _error, _built = _drive(job, tmp_path)

    assert success is False
    assert final_response == "I am reporting the script error", \
        "the agent's response must be returned untouched for delivery"
    assert output, "the run document must still be produced"
    assert final_response != SILENT_MARKER


def test_nonzero_exit_prerun_fails_the_run(tmp_path):
    """Wider than 'not found': a nonzero exit was equally invisible."""
    script = _scripts_dir(tmp_path) / "boom.sh"
    script.write_text("#!/bin/bash\necho 'partial output'\nexit 3\n")
    job = _job(script="boom.sh")

    success, _output, _final, error, agent_constructed = _drive(job, tmp_path)

    assert success is False
    assert error is not None and "Pre-run script failed" in error
    assert "boom.sh" in error
    assert agent_constructed is True


def test_successful_prerun_still_succeeds(tmp_path):
    """No false positives: a healthy script must leave the run green."""
    script = _scripts_dir(tmp_path) / "fine.sh"
    script.write_text("#!/bin/bash\necho 'real data'\n")
    job = _job(script="fine.sh")

    success, _output, final_response, error, agent_constructed = \
        _drive(job, tmp_path)

    assert success is True
    assert error is None
    assert final_response == "I am reporting the script error"
    assert agent_constructed is True


def test_scriptless_job_unaffected(tmp_path):
    """A job with no script: slot has no pre-run result to fail on."""
    _scripts_dir(tmp_path)
    job = _job()

    success, _output, _final, error, agent_constructed = _drive(job, tmp_path)

    assert success is True
    assert error is None
    assert agent_constructed is True


def test_wake_gate_false_still_skips_silently(tmp_path):
    """Regression guard: the gate only reads a SUCCESSFUL script.

    wakeAgent=false is not a failure, so it must keep its silent-success
    contract and must not be swept into the new failure path.
    """
    script = _scripts_dir(tmp_path) / "gate.sh"
    script.write_text('#!/bin/bash\necho \'{"wakeAgent": false}\'\n')
    job = _job(script="gate.sh")

    success, _output, final_response, error, agent_constructed = \
        _drive(job, tmp_path)

    assert success is True
    assert error is None
    assert final_response == SILENT_MARKER
    assert agent_constructed is False, "a closed gate must cost no model call"
