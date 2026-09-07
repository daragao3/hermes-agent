"""CriticSubscriber must not discard a spawned retro's failure signal.

THE SILENCE CLASS. Until 2026-09-07 the spawn threw away both halves of it:
``stderr=subprocess.DEVNULL`` discarded the traceback and nothing ever called
``wait()``/``poll()``, so the exit code went with it. ``critic_retro.main()``
runs mostly outside its own try/except, so an exception anywhere in it killed
the run before the retro file was written -- leaving no retro, no changelog
entry, no ``auto_apply_error`` and no bus event. The only observable difference
from a healthy cycle that found nothing was a MISSING file in
``profiles/critic/workspace/retros/``, and nothing checked for it.

THIS SIDE IS THE BACKSTOP, not the whole fix. ``critic_retro.py`` announces the
crashes a Python handler can catch (it has the traceback and the cluster
context) and prints ``CRASH_ANNOUNCED_MARKER`` to stderr when its own emit
SUCCEEDED. This subscriber covers what that handler structurally cannot see --
an import-time failure, a SyntaxError, a hard kill, or a bus that was down for
the child -- and stays quiet when the marker is present, so one crash pages
once.

REAPING LIVES IN ``poll()``, NOT ``handle()``. ``handle()`` runs only when
another AGENT_FAILURE_CLUSTER arrives, and clusters can be days apart; a crash
would sit unreported until the next one. ``poll()`` runs every
``poll_interval_seconds`` regardless. ``test_reaping_happens_without_any_new_event``
is the direction that matters and is the one a "simplification" would break.
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from events.bus import EventBus
from events.schema import EventType, Priority

CHILD_CRASH_SCRIPT = (
    "import sys\n"
    "sys.stderr.write('about to die' + chr(10))\n"
    "raise RuntimeError('synthetic crash')\n"
)


@pytest.fixture
def bus(tmp_path):
    return EventBus(db_path=tmp_path / "events" / "event_bus.db")


@pytest.fixture
def critic_script(tmp_path):
    script = tmp_path / "critic_retro.py"
    script.write_text("# stub")
    return script


@pytest.fixture
def sub(bus, critic_script, tmp_path):
    from events.subscribers.critic_trigger import CriticSubscriber

    return CriticSubscriber(
        bus,
        critic_script_path=critic_script,
        retro_log_dir=tmp_path / "retro-logs",
    )


class _FakeProc:
    """Minimal Popen stand-in: returncode is int-or-None, like the real one."""

    def __init__(self, rc=None):
        self._rc = rc

    def poll(self):
        return self._rc


def _emit_cluster(bus, source="scout", failure_type="captcha"):
    bus.emit(
        event_type=EventType.AGENT_FAILURE_CLUSTER,
        source=source,
        payload={
            "source": source,
            "failure_type": failure_type,
            "count": 3,
            "first_seen": "2026-09-07T10:00:00+00:00",
            "last_seen": "2026-09-07T10:10:00+00:00",
        },
        priority=Priority.HIGH,
    )


def _agent_errors(bus):
    return bus.query(event_type=EventType.AGENT_ERROR)


def _track(sub, rc, log_text=None, tmp_path=None, cluster="scout:captcha"):
    """Register a finished fake child, optionally with a captured log."""
    log_path = None
    if log_text is not None:
        log_path = tmp_path / "captured.log"
        log_path.write_text(log_text, encoding="utf-8")
    sub._inflight.append({
        "proc": _FakeProc(rc),
        "cluster_key": cluster,
        "log_path": log_path,
        "spawned_at": 0.0,
    })
    return log_path


# --- output is captured, not discarded -------------------------------------

class TestOutputCapture:
    def test_spawn_no_longer_sends_stderr_to_devnull(self, sub, bus):
        """The defect itself. DEVNULL here is what made a crash invisible."""
        _emit_cluster(bus)
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            sub.poll()
        kwargs = popen.call_args.kwargs
        assert kwargs["stderr"] is not subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.STDOUT
        assert kwargs["stdout"] is not subprocess.DEVNULL

    def test_a_log_file_is_created_for_the_invocation(self, sub, bus, tmp_path):
        _emit_cluster(bus)
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            sub.poll()
        logs = list((tmp_path / "retro-logs").glob("*.log"))
        assert len(logs) == 1
        assert "scout" in logs[0].name

    def test_the_child_is_tracked_for_reaping(self, sub, bus):
        _emit_cluster(bus)
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            sub.poll()
        assert len(sub._inflight) == 1
        assert sub._inflight[0]["cluster_key"] == "scout:captcha"

    def test_an_unusable_log_dir_does_not_stop_the_retro(
        self, bus, critic_script, tmp_path,
    ):
        """Capture is an improvement on discarding output, not a precondition."""
        from events.subscribers.critic_trigger import CriticSubscriber

        blocked = tmp_path / "not-a-dir"
        blocked.write_text("x", encoding="utf-8")
        s = CriticSubscriber(
            bus, critic_script_path=critic_script,
            retro_log_dir=blocked / "logs",
        )
        _emit_cluster(bus)
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            s.poll()
        assert popen.called
        assert popen.call_args.kwargs["stdout"] is subprocess.DEVNULL


# --- the exit code is read and announced -----------------------------------

class TestReaping:
    def test_nonzero_exit_emits_agent_error(self, sub, bus, tmp_path):
        _track(sub, rc=1, log_text="Traceback...\nValueError: boom\n",
               tmp_path=tmp_path)
        sub._reap_finished_retros()
        errors = _agent_errors(bus)
        assert len(errors) == 1, "a crashed retro was not announced"
        assert errors[0].source == "critic-retro"
        assert errors[0].priority is Priority.HIGH
        assert "exited 1" in errors[0].payload["error"]
        assert "ValueError: boom" in errors[0].payload["log_tail"]

    def test_zero_exit_emits_nothing(self, sub, bus, tmp_path):
        """A quiet cycle must stay quiet -- otherwise the signal is worthless."""
        _track(sub, rc=0, log_text="Retro written: x.md\n", tmp_path=tmp_path)
        sub._reap_finished_retros()
        assert _agent_errors(bus) == []

    def test_zero_exit_discards_the_log(self, sub, bus, tmp_path):
        log = _track(sub, rc=0, log_text="Retro written\n", tmp_path=tmp_path)
        sub._reap_finished_retros()
        assert not log.exists()

    def test_nonzero_exit_keeps_the_log_as_evidence(self, sub, bus, tmp_path):
        log = _track(sub, rc=2, log_text="ImportError: no module\n",
                     tmp_path=tmp_path)
        sub._reap_finished_retros()
        assert log.exists()
        assert _agent_errors(bus)[0].payload["log"] == str(log)

    def test_a_still_running_child_is_kept_not_judged(self, sub, bus):
        _track(sub, rc=None)
        sub._reap_finished_retros()
        assert len(sub._inflight) == 1
        assert _agent_errors(bus) == []

    def test_a_finished_child_is_only_reaped_once(self, sub, bus, tmp_path):
        _track(sub, rc=1, log_text="boom\n", tmp_path=tmp_path)
        sub._reap_finished_retros()
        sub._reap_finished_retros()
        assert len(_agent_errors(bus)) == 1
        assert sub._inflight == []

    def test_a_non_int_returncode_is_not_treated_as_a_failure(
        self, sub, bus, monkeypatch,
    ):
        """Guard against inventing failures from test doubles.

        A real Popen.returncode is int or None. A MagicMock compares != 0, so
        without the isinstance check every mocked spawn in the existing suite
        would announce a phantom crash.

        ASSERTED ON THE CALL, NOT ON THE BUS, and that is the point. Written the
        obvious way -- `assert _agent_errors(bus) == []` -- this test PASSED with
        the isinstance check mutated away: announcement was reached, the emit
        then died serializing a MagicMock, and `_reap_finished_retros`'s broad
        except swallowed it, so the bus looked clean for entirely the wrong
        reason. A guard that cannot fail is not a guard; caught by targeted
        mutation on 2026-09-07.
        """
        calls = []
        monkeypatch.setattr(
            sub, "_announce_retro_failure",
            lambda rec, rc: calls.append((rec, rc)),
        )
        sub._inflight.append({
            "proc": MagicMock(),
            "cluster_key": "scout:captcha",
            "log_path": None,
            "spawned_at": 0.0,
        })
        sub._reap_finished_retros()
        assert calls == [], "announced a crash for a non-int returncode"
        assert _agent_errors(bus) == []

    def test_reaping_happens_without_any_new_event(self, sub, bus, tmp_path):
        """poll(), not handle(). Clusters can be days apart.

        Nothing is on the bus here, so `handle()` never runs; the announcement
        must come out of poll() anyway.
        """
        _track(sub, rc=1, log_text="boom\n", tmp_path=tmp_path)
        assert sub.poll() == 0
        assert len(_agent_errors(bus)) == 1

    def test_a_reaping_failure_does_not_stop_event_processing(
        self, sub, bus, monkeypatch,
    ):
        """A bug in the new code must never wedge the subscriber."""
        def _explode():
            raise RuntimeError("reaper is broken")

        monkeypatch.setattr(sub, "_reap_finished_retros", _explode)
        _emit_cluster(bus)
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            processed = sub.poll()
        assert processed == 1
        assert popen.called

    def test_tracking_is_bounded(self, sub):
        from events.subscribers.critic_trigger import MAX_TRACKED_RETROS

        for _ in range(MAX_TRACKED_RETROS + 10):
            _track(sub, rc=None)
        assert len(sub._inflight) <= MAX_TRACKED_RETROS + 10
        sub._reap_finished_retros()
        assert len(sub._inflight) <= MAX_TRACKED_RETROS + 10


# --- the handshake: one crash pages once -----------------------------------

class TestHandshakeWithTheChild:
    def test_marker_in_the_log_suppresses_the_duplicate_announcement(
        self, sub, bus, tmp_path,
    ):
        from events.subscribers.critic_trigger import CRASH_ANNOUNCED_MARKER

        _track(sub, rc=1,
               log_text=f"Traceback\nValueError: boom\n{CRASH_ANNOUNCED_MARKER}\n",
               tmp_path=tmp_path)
        sub._reap_finished_retros()
        assert _agent_errors(bus) == [], "paged twice for one crash"

    def test_absent_marker_still_announces(self, sub, bus, tmp_path):
        """The case this side exists for: the child never got to announce.

        An import-time failure or a hard kill produces a non-zero exit with no
        marker, and this is then the ONLY announcement there will be.
        """
        _track(sub, rc=1,
               log_text="ImportError: cannot import name failure_cluster_eligible\n",
               tmp_path=tmp_path)
        sub._reap_finished_retros()
        assert len(_agent_errors(bus)) == 1

    def test_missing_log_file_still_announces(self, sub, bus):
        """No log means no marker; failing closed here means announcing."""
        _track(sub, rc=1, log_text=None)
        sub._reap_finished_retros()
        assert len(_agent_errors(bus)) == 1

    def test_marker_literal_is_pinned(self):
        """Tripwire for the cross-repo duplicate.

        `~/.hermes/profiles/critic/workspace/critic_retro.py` prints this exact
        string and pins the same literal on its own side. The two files are in
        different repositories so neither can import the other; changing one
        without the other silently re-enables double-paging.
        """
        from events.subscribers.critic_trigger import CRASH_ANNOUNCED_MARKER

        assert CRASH_ANNOUNCED_MARKER == "CRITIC_RETRO_CRASH_ANNOUNCED"


# --- end to end, with a real subprocess ------------------------------------

class TestEndToEndWithARealChild:
    """The tests above drive a fake process object.

    These spawn a REAL one, so the wiring the unit tests take on trust is
    actually exercised: the log handle reaching the child, stderr folded into
    stdout, the parent releasing its copy of the handle, and `returncode`
    arriving as an int.
    """

    def _spawn_and_reap(self, bus, tmp_path, body):
        from events.subscribers.critic_trigger import CriticSubscriber

        script = tmp_path / "critic_retro.py"
        script.write_text(body, encoding="utf-8")
        s = CriticSubscriber(
            bus, critic_script_path=script, retro_log_dir=tmp_path / "logs",
        )
        _emit_cluster(bus)
        s.poll()
        assert len(s._inflight) == 1, "the real child was not tracked"
        s._inflight[0]["proc"].wait(timeout=60)
        s._reap_finished_retros()
        return s

    def test_a_child_that_crashes_is_announced_with_its_traceback(
        self, bus, tmp_path,
    ):
        self._spawn_and_reap(bus, tmp_path, CHILD_CRASH_SCRIPT)
        errors = _agent_errors(bus)
        assert len(errors) == 1
        tail = errors[0].payload["log_tail"]
        assert "RuntimeError: synthetic crash" in tail, (
            "stderr was not captured -- the DEVNULL defect is back"
        )
        assert "about to die" in tail
        assert Path(errors[0].payload["log"]).exists()

    def test_a_child_that_announced_its_own_crash_is_not_announced_again(
        self, bus, tmp_path,
    ):
        from events.subscribers.critic_trigger import CRASH_ANNOUNCED_MARKER

        body = (
            "import sys\n"
            "sys.stderr.write({marker!r} + chr(10))\n"
            "sys.exit(1)\n"
        ).format(marker=CRASH_ANNOUNCED_MARKER)
        self._spawn_and_reap(bus, tmp_path, body)
        assert _agent_errors(bus) == [], "paged twice for one crash"

    def test_a_clean_child_is_silent_and_leaves_no_log(self, bus, tmp_path):
        s = self._spawn_and_reap(
            bus, tmp_path, "print('Retro written: x.md')\n",
        )
        assert _agent_errors(bus) == []
        assert list((tmp_path / "logs").glob("*.log")) == []
        assert s._inflight == []
