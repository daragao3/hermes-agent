"""Operator stop requests for an in-flight cron run (cron.inflight, 2026-09-07).

``hermes cron pause`` stops SCHEDULING; it never touched a run already
executing. On 2026-09-06 job b74186b2eaa5 was paused at 18:14:34 while its
18:00 run was 14 minutes in; the run kept calling tools for 44 more minutes
and published 184 proposals, 116 of them fabricated, an hour after the
operator believed the lane was stopped. These tests cover the file-based
signal that lets the CLI reach the scheduler's ``agent.interrupt()`` kill
path, and the scheduler's watchdog loop honouring it.
"""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cron.inflight import (  # noqa: E402
    CronRunStoppedByOperator,
    clear_stop_request,
    consume_stop_request,
    read_stop_request,
    request_stop,
    stop_request_path,
)
from cron.scheduler import run_job  # noqa: E402


@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


class TestStopRequestFile:
    def test_request_then_read_roundtrip(self, tmp_cron_dir):
        payload = request_stop(
            "job1", session_id="cron_job1_20260906_180036", by="test", reason="why"
        )
        assert stop_request_path("job1") == tmp_cron_dir / "cron" / "stop-requests" / "job1.json"
        assert stop_request_path("job1").exists()
        read = read_stop_request("job1")
        assert read == payload
        assert read["session_id"] == "cron_job1_20260906_180036"
        assert read["by"] == "test"
        assert read["reason"] == "why"
        assert read["requested_at"]

    def test_consume_matching_session_returns_and_deletes(self, tmp_cron_dir):
        request_stop("job1", session_id="cron_job1_20260906_180036", by="test")
        got = consume_stop_request("job1", "cron_job1_20260906_180036")
        assert got is not None and got["session_id"] == "cron_job1_20260906_180036"
        assert not stop_request_path("job1").exists()
        # Second consume: nothing left.
        assert consume_stop_request("job1", "cron_job1_20260906_180036") is None

    def test_consume_other_session_leaves_the_request_in_place(self, tmp_cron_dir):
        """A request aimed at an earlier run must never stop a later one."""
        request_stop("job1", session_id="cron_job1_20260906_180036", by="test")
        assert consume_stop_request("job1", "cron_job1_20260907_000031") is None
        assert stop_request_path("job1").exists()

    def test_consume_session_agnostic_request_matches_any_run(self, tmp_cron_dir):
        request_stop("job1", by="test")
        got = consume_stop_request("job1", "cron_job1_20260907_000031")
        assert got is not None and got["session_id"] is None
        assert not stop_request_path("job1").exists()

    def test_missing_and_garbage_requests_read_as_none(self, tmp_cron_dir):
        assert read_stop_request("nope") is None
        assert clear_stop_request("nope") is False
        path = stop_request_path("bad")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert read_stop_request("bad") is None
        assert consume_stop_request("bad", "whatever") is None
        assert clear_stop_request("bad") is True

    def test_request_requires_a_job_id(self, tmp_cron_dir):
        with pytest.raises(ValueError):
            request_stop("")


def _active_summary():
    return {
        "last_activity_ts": time.time(),
        "last_activity_desc": "api_call_streaming",
        "seconds_since_activity": 0.0,
        "current_tool": "matcher_publish_score_batch",
        "api_call_count": 27,
        "max_iterations": 100,
    }


def _run(job, agent, tmp_path):
    with patch("cron.scheduler._hermes_home", tmp_path), \
         patch("cron.scheduler._CRON_RUN_POLL_INTERVAL_S", 0.05), \
         patch("cron.scheduler._resolve_origin", return_value=None), \
         patch("hermes_cli.env_loader.load_hermes_dotenv"), \
         patch("hermes_cli.env_loader.reset_secret_source_cache"), \
         patch("hermes_state.SessionDB", return_value=MagicMock()), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "test-key",
                 "base_url": "https://example.invalid/v1",
                 "provider": "openrouter",
                 "api_mode": "chat_completions",
             },
         ), \
         patch("run_agent.AIAgent", return_value=agent):
        return run_job(job)


class TestSchedulerHonoursStopRequest:
    JOB = {"id": "stopjob", "name": "stop me", "prompt": "hello"}

    def test_run_is_interrupted_and_recorded_as_operator_stop(self, tmp_cron_dir):
        agent = MagicMock()
        agent.get_activity_summary.side_effect = _active_summary
        released = threading.Event()

        def _interrupt(msg):
            released.set()

        def _run_conversation(prompt):
            # Filed from INSIDE the run, i.e. after the scheduler cleared any
            # stale request at session start -- the way an operator's request
            # arrives while the agent is mid-task.
            request_stop("stopjob", by="hermes_cli:cron_pause", reason="cutover")
            released.wait(timeout=10)
            return {"final_response": "should not be trusted"}

        agent.interrupt.side_effect = _interrupt
        agent.run_conversation.side_effect = _run_conversation

        success, output, final_response, error = _run(self.JOB, agent, tmp_cron_dir)

        assert success is False
        assert error is not None
        assert "CronRunStoppedByOperator" in error
        assert "stopped by operator" in error
        assert "hermes_cli:cron_pause" in error
        assert "cutover" in error
        agent.interrupt.assert_called_once_with("Cron run stopped by operator")
        assert released.is_set()
        # The request is consumed, not left to fire on the next run.
        assert read_stop_request("stopjob") is None
        assert "FAILED" in output

    def test_stale_request_from_an_earlier_run_is_cleared_at_start(self, tmp_cron_dir):
        request_stop("stopjob", session_id="cron_stopjob_19990101_000000", by="old")
        agent = MagicMock()
        agent.get_activity_summary.side_effect = _active_summary
        agent.run_conversation.return_value = {"final_response": "ok"}

        success, _output, final_response, error = _run(self.JOB, agent, tmp_cron_dir)

        assert success is True, error
        assert final_response == "ok"
        agent.interrupt.assert_not_called()
        assert read_stop_request("stopjob") is None

    def test_request_naming_another_session_does_not_stop_this_run(self, tmp_cron_dir):
        agent = MagicMock()
        agent.get_activity_summary.side_effect = _active_summary

        def _run_conversation(prompt):
            request_stop("stopjob", session_id="cron_stopjob_19990101_000000", by="x")
            time.sleep(0.4)  # several 0.05s polls see the mismatched request
            return {"final_response": "ok"}

        agent.run_conversation.side_effect = _run_conversation

        success, _output, final_response, error = _run(self.JOB, agent, tmp_cron_dir)

        assert success is True, error
        assert final_response == "ok"
        agent.interrupt.assert_not_called()
        # Left in place for its own session; harmless and visible.
        assert read_stop_request("stopjob") is not None

    def test_exception_type_is_a_runtime_error(self):
        assert issubclass(CronRunStoppedByOperator, RuntimeError)
