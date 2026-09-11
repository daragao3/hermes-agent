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
         patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
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

        def _run_conversation(prompt, **kwargs):
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

        def _run_conversation(prompt, **kwargs):
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


# ---------------------------------------------------------------------------
# The stop (and the two timeouts) must also kill the tool SUBPROCESS the run
# is blocked in -- independently of the agent (2026-09-07 follow-up).
#
# ``agent.interrupt()`` sets a per-thread flag that the terminal tool's wait
# loop polls and honours by killing its process tree; live fire on
# 2026-09-07 measured ~1.2s from stop to ``[Command interrupted]``. These
# tests use a fake agent whose ``interrupt`` is a MagicMock -- i.e. that
# route is absent -- and block in a REAL subprocess, so what they prove is
# the scheduler's own kill (cron.inflight.kill_run_tool_subprocesses via the
# per-thread registry in tools.environments.base).
# ---------------------------------------------------------------------------

import shlex  # noqa: E402

from cron.inflight import kill_run_tool_subprocesses, run_tool_thread_ids  # noqa: E402


def _python_for_bash() -> str:
    # Forward slashes: the local backend runs commands under bash (MSYS on
    # Windows), where a backslashed path is an escape sequence.
    return shlex.quote(sys.executable.replace("\\", "/"))


def _sleeper_command(pid_file: Path, seconds: int = 120) -> str:
    pid_path = str(pid_file).replace("\\", "/")
    code = (
        "import os,time,sys; "
        f"open({pid_path!r},'w').write(str(os.getpid())); "
        f"time.sleep({seconds})"
    )
    return f"{_python_for_bash()} -c {shlex.quote(code)}"


def _wait_for_file(path: Path, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text().strip()
            if text:
                return int(text)
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _pid_alive(psutil, pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_dead(psutil, pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(psutil, pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(psutil, pid)


def _reap(psutil, pid):
    try:
        psutil.Process(pid).kill()
    except Exception:
        pass


@pytest.fixture()
def local_env(tmp_path):
    from tools.environments.local import LocalEnvironment

    env = LocalEnvironment(cwd=str(tmp_path), timeout=120)
    try:
        yield env
    finally:
        try:
            env.cleanup()
        except Exception:
            pass


class TestStopKillsInflightToolSubprocess:
    JOB = {"id": "stopjob", "name": "stop me", "prompt": "hello"}

    def _blocking_agent(self, env, pid_file, state):
        """A fake agent that blocks in a real subprocess and cannot be
        interrupted -- its ``interrupt`` is a plain MagicMock."""
        agent = MagicMock()
        agent.get_activity_summary.side_effect = _active_summary

        def _run_conversation(prompt, **kwargs):
            state["result"] = env.execute(_sleeper_command(pid_file), timeout=120)
            return {"final_response": "should not be trusted"}

        agent.run_conversation.side_effect = _run_conversation
        return agent

    def test_operator_stop_kills_the_subprocess_the_run_is_blocked_in(
        self, tmp_cron_dir, local_env
    ):
        psutil = pytest.importorskip("psutil")
        pid_file = tmp_cron_dir / "child.pid"
        state = {}
        agent = self._blocking_agent(local_env, pid_file, state)
        child = {}

        def _stop_once_child_is_up():
            child["pid"] = _wait_for_file(pid_file)
            # Filed only once the subprocess is provably running, the way an
            # operator's request arrives mid-tool-call.
            request_stop("stopjob", by="hermes_cli:cron_pause", reason="kill it")

        stopper = threading.Thread(target=_stop_once_child_is_up, daemon=True)
        stopper.start()
        try:
            success, output, _final, error = _run(self.JOB, agent, tmp_cron_dir)
            stopper.join(timeout=30)
            assert "pid" in child, "child never started"
            assert success is False
            assert "CronRunStoppedByOperator" in error
            # The subprocess is gone -- not merely the run recorded as failed.
            assert _wait_dead(psutil, child["pid"]), (
                f"child {child['pid']} survived the operator stop"
            )
            # And the tool call itself unwound (the wait loop saw the kill).
            deadline = time.monotonic() + 10
            while "result" not in state and time.monotonic() < deadline:
                time.sleep(0.05)
            assert "result" in state, "env.execute never returned after the kill"
            assert state["result"]["returncode"] != 0
            agent.interrupt.assert_called_once_with("Cron run stopped by operator")
        finally:
            if "pid" in child:
                _reap(psutil, child["pid"])

    @pytest.mark.parametrize(
        "env_var, value, expected_error",
        [
            ("HERMES_CRON_HARD_TIMEOUT", "1", "wall-clock"),
            ("HERMES_CRON_TIMEOUT", "1", "idle for"),
        ],
    )
    def test_timeouts_kill_the_subprocess_too(
        self, tmp_cron_dir, local_env, monkeypatch, env_var, value, expected_error
    ):
        psutil = pytest.importorskip("psutil")
        monkeypatch.delenv("HERMES_CRON_HARD_TIMEOUT", raising=False)
        monkeypatch.delenv("HERMES_CRON_TIMEOUT", raising=False)
        monkeypatch.setenv(env_var, value)
        pid_file = tmp_cron_dir / "child.pid"
        state = {}
        agent = self._blocking_agent(local_env, pid_file, state)
        if env_var == "HERMES_CRON_TIMEOUT":
            # Report the run as idle past the limit; the wall-clock limit is
            # off, so only the inactivity branch can fire.
            def _idle_summary():
                s = _active_summary()
                s["seconds_since_activity"] = 999.0
                return s
            agent.get_activity_summary.side_effect = _idle_summary
        child = {}
        try:
            success, _output, _final, error = _run(self.JOB, agent, tmp_cron_dir)
            child["pid"] = _wait_for_file(pid_file, timeout=5)
            assert success is False
            assert expected_error in error
            assert _wait_dead(psutil, child["pid"]), (
                f"child {child['pid']} survived the {env_var} timeout"
            )
        finally:
            if "pid" in child:
                _reap(psutil, child["pid"])

    def test_stop_does_not_kill_another_threads_subprocess(
        self, tmp_cron_dir, local_env
    ):
        """Scoping: a command in flight on some OTHER thread -- another
        session sharing the same LocalEnvironment, as every top-level agent
        in the gateway does -- must survive this run's stop."""
        psutil = pytest.importorskip("psutil")
        other_pid_file = tmp_cron_dir / "other.pid"
        other_state = {}

        def _other_session():
            other_state["result"] = local_env.execute(
                _sleeper_command(other_pid_file), timeout=120
            )

        other = threading.Thread(target=_other_session, daemon=True)
        other.start()
        other_pid = _wait_for_file(other_pid_file)
        try:
            agent = MagicMock()
            agent.get_activity_summary.side_effect = _active_summary
            released = threading.Event()
            agent.interrupt.side_effect = lambda msg: released.set()

            def _run_conversation(prompt, **kwargs):
                request_stop("stopjob", by="test")
                released.wait(timeout=10)
                return {"final_response": "x"}

            agent.run_conversation.side_effect = _run_conversation
            success, _o, _f, error = _run(self.JOB, agent, tmp_cron_dir)
            assert success is False and "CronRunStoppedByOperator" in error
            time.sleep(0.5)
            assert _pid_alive(psutil, other_pid), "sibling thread's command was killed"
            assert "result" not in other_state
        finally:
            _reap(psutil, other_pid)
            other.join(timeout=10)

    def test_kill_helper_is_a_noop_with_nothing_in_flight(self):
        agent = MagicMock()  # every attribute a mock, none of them an int
        assert run_tool_thread_ids(agent, None) == set()
        assert kill_run_tool_subprocesses(agent, None) == 0
        me = threading.current_thread().ident
        assert run_tool_thread_ids(agent, me) == {me}
        assert kill_run_tool_subprocesses(agent, me) == 0

    def test_thread_ids_include_agent_execution_and_worker_threads(self):
        agent = MagicMock()
        agent._execution_thread_id = 11
        agent._tool_worker_threads = {12, 13}
        agent._tool_worker_threads_lock = threading.Lock()
        assert run_tool_thread_ids(agent, 10) == {10, 11, 12, 13}
        agent._execution_thread_id = None
        agent._tool_worker_threads = MagicMock()  # not a set: ignored
        assert run_tool_thread_ids(agent, 10) == {10}


# ---------------------------------------------------------------------------
# The stop (and the two timeouts) must also abort a tool call that is NEITHER
# polling the interrupt bit NOR blocked in a subprocess -- an HTTP request, an
# MCP call, an async handler, a plugin loop (2026-09-07, third leg).
#
# The 2026-09-06 shape: job b74186b2eaa5 paused at 18:14 kept publishing until
# 18:58. ``agent.interrupt()`` is a MagicMock here, i.e. the agent's own route
# is absent; what these prove is the scheduler-owned cancel by CALL FRAME
# (cron.inflight.cancel_run_tool_calls -> tools.inflight_call), reaching a
# real ``ToolRegistry.dispatch`` on the run's pool worker thread, and that the
# cancel dies with the call (no recycled-tid poisoning).
# ---------------------------------------------------------------------------

import json  # noqa: E402

from cron.inflight import cancel_run_tool_calls  # noqa: E402
from tools.inflight_call import (  # noqa: E402
    inflight_call,
    inflight_call_threads,
    is_call_cancelled,
)
from tools.interrupt import is_interrupted  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402


def _wait_until(pred, timeout=10.0, step=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


def _blocking_call_registry(entered: threading.Event) -> ToolRegistry:
    """A registry with one tool that blocks until its call is cancelled.

    Stands in for a publish loop / HTTP client: it does not know about cron
    and polls nothing but ``is_interrupted()``, which now reports the
    scheduler's per-call cancel on this thread.
    """
    reg = ToolRegistry()

    def _publish(args, **kwargs):
        entered.set()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if is_interrupted():
                return json.dumps({"aborted": True})
            time.sleep(0.02)
        return json.dumps({"aborted": False})

    reg.register(
        name="fake_publish_batch", toolset="t",
        schema={"name": "fake_publish_batch"}, handler=_publish,
    )
    return reg


class TestStopCancelsInflightToolCall:
    JOB = {"id": "stopjob", "name": "stop me", "prompt": "hello"}

    def _agent_blocked_in_tool(self, reg, state):
        agent = MagicMock()
        agent.get_activity_summary.side_effect = _active_summary

        def _run_conversation(prompt, **kwargs):
            state["tid"] = threading.current_thread().ident
            state["result"] = reg.dispatch("fake_publish_batch", {})
            state["returned_at"] = time.monotonic()
            return {"final_response": "should not be trusted"}

        agent.run_conversation.side_effect = _run_conversation
        return agent

    def test_operator_stop_cancels_the_call_the_run_is_blocked_in(self, tmp_cron_dir):
        entered = threading.Event()
        state = {}
        reg = _blocking_call_registry(entered)
        agent = self._agent_blocked_in_tool(reg, state)

        def _stop_once_in_tool():
            assert entered.wait(timeout=10), "tool never entered"
            request_stop("stopjob", by="hermes_cli:cron_pause", reason="abort it")
            state["stop_at"] = time.monotonic()

        stopper = threading.Thread(target=_stop_once_in_tool, daemon=True)
        stopper.start()
        success, output, _final, error = _run(self.JOB, agent, tmp_cron_dir)
        stopper.join(timeout=15)

        assert success is False
        assert "CronRunStoppedByOperator" in error
        # The tool call itself unwound -- not merely the run recorded failed.
        assert _wait_until(lambda: "result" in state), "dispatch never returned"
        assert json.loads(state["result"]) == {"aborted": True}
        assert state["returned_at"] - state["stop_at"] < 10
        # The agent's own route was a MagicMock; the scheduler's cancel did it.
        agent.interrupt.assert_called_once_with("Cron run stopped by operator")
        # And the cancel died with the call: the worker tid is clean.
        assert state["tid"] not in inflight_call_threads()
        assert not is_call_cancelled(state["tid"])
        assert "FAILED" in output

    @pytest.mark.parametrize(
        "env_var, value, expected_error",
        [
            ("HERMES_CRON_HARD_TIMEOUT", "1", "wall-clock"),
            ("HERMES_CRON_TIMEOUT", "1", "idle for"),
        ],
    )
    def test_timeouts_cancel_the_call_too(
        self, tmp_cron_dir, monkeypatch, env_var, value, expected_error
    ):
        monkeypatch.delenv("HERMES_CRON_HARD_TIMEOUT", raising=False)
        monkeypatch.delenv("HERMES_CRON_TIMEOUT", raising=False)
        monkeypatch.setenv(env_var, value)
        entered = threading.Event()
        state = {}
        reg = _blocking_call_registry(entered)
        agent = self._agent_blocked_in_tool(reg, state)
        if env_var == "HERMES_CRON_TIMEOUT":
            def _idle_summary():
                s = _active_summary()
                s["seconds_since_activity"] = 999.0
                return s
            agent.get_activity_summary.side_effect = _idle_summary

        t0 = time.monotonic()
        success, _output, _final, error = _run(self.JOB, agent, tmp_cron_dir)
        assert entered.is_set(), "tool never entered"
        assert success is False
        assert expected_error in error
        assert _wait_until(lambda: "result" in state), "dispatch never returned"
        assert json.loads(state["result"]) == {"aborted": True}
        assert state["returned_at"] - t0 < 15
        assert state["tid"] not in inflight_call_threads()

    def test_stop_does_not_cancel_another_threads_call(self, tmp_cron_dir):
        """Scoping: a call in flight on some OTHER thread -- another session
        in the same gateway -- must not see this run's stop."""
        other_in = threading.Event()
        release = threading.Event()
        other_seen = {}

        def _other_session():
            with inflight_call("other_sessions_tool"):
                other_in.set()
                release.wait(timeout=30)
                other_seen["cancelled"] = is_call_cancelled()
                other_seen["interrupted"] = is_interrupted()

        other = threading.Thread(target=_other_session, daemon=True)
        other.start()
        assert other_in.wait(timeout=5)
        try:
            agent = MagicMock()
            agent.get_activity_summary.side_effect = _active_summary
            released = threading.Event()
            agent.interrupt.side_effect = lambda msg: released.set()

            def _run_conversation(prompt, **kwargs):
                request_stop("stopjob", by="test")
                released.wait(timeout=10)
                return {"final_response": "x"}

            agent.run_conversation.side_effect = _run_conversation
            success, _o, _f, error = _run(self.JOB, agent, tmp_cron_dir)
            assert success is False and "CronRunStoppedByOperator" in error
            assert not is_call_cancelled(other.ident)
        finally:
            release.set()
            other.join(timeout=10)
        assert other_seen == {"cancelled": False, "interrupted": False}

    def test_cancel_helper_is_a_noop_with_nothing_in_flight(self):
        agent = MagicMock()
        assert cancel_run_tool_calls(agent, None) == 0
        me = threading.current_thread().ident
        assert cancel_run_tool_calls(agent, me) == 0
        assert not is_call_cancelled(me)

    def test_cancel_helper_reaches_a_frame_on_the_named_thread(self):
        entered = threading.Event()
        release = threading.Event()
        seen = {}

        def _worker():
            with inflight_call("some_tool") as frame:
                entered.set()
                release.wait(timeout=10)
                seen["reason"] = frame.cancel_reason
                seen["interrupted"] = is_interrupted()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        assert entered.wait(timeout=5)
        try:
            agent = MagicMock()  # no int attributes: only the worker tid counts
            assert cancel_run_tool_calls(
                agent, t.ident, reason="operator stop (by=test)", label="unit"
            ) == 1
            assert is_call_cancelled(t.ident)
        finally:
            release.set()
            t.join(timeout=5)
        assert seen == {"reason": "operator stop (by=test)", "interrupted": True}
        assert not is_call_cancelled(t.ident)
