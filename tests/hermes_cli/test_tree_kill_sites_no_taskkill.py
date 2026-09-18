"""The three product tree-kill sites no longer run ``taskkill /T`` on Windows.

* ``agent.deadline.kill_process_tree(pid)`` -- a bare pid that may already have
  exited (the timeout path): creation-time-guarded walk, exited pid kills nothing.
* ``hermes_cli._subprocess_compat`` -- ``_legacy_kill_process_tree`` /
  ``_tree_kill`` on a Popen we hold: job by membership when the spawn captured
  one (``run_text_capture``, ``bounded_probe_run``), else the guarded walk while
  the root is alive.
* ``hermes_cli.update_cmd_windows._stop_process_trees`` -- a leftover holder by
  bare pid with no spawn handle: fresh identity read, ``pid_is_hermes`` probe,
  then the guarded walk pinned to that identity.

Each site gets (1) a fake-record run through the REAL walk showing the
2026-09-17 orphans (Canvas 26328, Control Center 16284, ParentProcessId=our
root, born a day earlier) are refused, (2) a mutant check: with the guard
removed the same site adopts them, so the guard is what the site relies on,
and (3) a no-spawn fixture: any ``subprocess`` call from a kill path fails
the test. No real process is killed.
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import deadline
from hermes_cli import _subprocess_compat as compat
from hermes_cli import update_cmd
from hermes_cli import update_cmd_windows

_REPO = Path(__file__).resolve().parents[2]


def _t(iso: str) -> float:
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))


ROOT_BORN = _t("2026-09-17T21:00:00")


def _incident_snapshot(root_pid: int):
    """root -> 200 -> 300; Canvas and Control Center claim the root as parent
    but predate it (their real parent's pid was recycled onto the root)."""
    return [
        compat.ProcessRecord(root_pid, 1, ROOT_BORN),
        compat.ProcessRecord(200, root_pid, _t("2026-09-17T21:00:01")),
        compat.ProcessRecord(300, 200, _t("2026-09-17T21:00:02")),
        compat.ProcessRecord(26328, root_pid, _t("2026-09-16T13:23:47")),
        compat.ProcessRecord(16284, root_pid, _t("2026-09-16T13:19:29")),
    ]


@pytest.fixture
def no_spawn(monkeypatch):
    """Every module under test: a subprocess call from a kill path is the old bug."""

    def _boom(*args, **kwargs):  # pragma: no cover - only on regression
        raise AssertionError(f"kill path spawned a process: {args!r}")

    for mod in (compat.subprocess, update_cmd_windows.subprocess, update_cmd.subprocess):
        monkeypatch.setattr(mod, "run", _boom)
        monkeypatch.setattr(mod, "Popen", _boom)
        monkeypatch.setattr(mod, "check_output", _boom)


@pytest.fixture
def fake_host(monkeypatch):
    """The real walk over the incident snapshot; kills only record."""
    calls = SimpleNamespace(killed=[], snapshots=[], jobs_terminated=[])

    def _snapshot(root_pid):
        calls.snapshots.append(root_pid)
        return _incident_snapshot(root_pid)

    def _kill(pid, created):
        calls.killed.append(pid)
        return True

    monkeypatch.setattr(compat, "windows_tree_snapshot", _snapshot)
    monkeypatch.setattr(compat, "windows_kill_pid", _kill)
    monkeypatch.setattr(compat, "windows_job_terminate", lambda job: calls.jobs_terminated.append(job) or True)
    return calls


@pytest.fixture
def mutant(monkeypatch):
    """The guard removed: every ParentProcessId claim is believed (taskkill /T)."""
    monkeypatch.setattr(compat, "is_genuine_child", lambda child, parent: True)


class _FakeProc:
    def __init__(self, pid: int, returncode: int | None):
        self.pid = pid
        self.returncode = returncode
        self._handle = 0x50
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


# --- site 1: agent/deadline.py ----------------------------------------------


@pytest.fixture
def win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(compat, "IS_WINDOWS", True)


def test_deadline_refuses_the_recycled_orphans(win32, fake_host, no_spawn):
    assert deadline.kill_process_tree(100) is True
    assert fake_host.killed == [300, 200, 100]
    assert 26328 not in fake_host.killed and 16284 not in fake_host.killed


def test_deadline_mutant_without_the_guard_adopts_the_services(win32, fake_host, no_spawn, mutant):
    deadline.kill_process_tree(100)
    assert 26328 in fake_host.killed and 16284 in fake_host.killed


def test_deadline_exited_pid_kills_nothing_and_reports_no_signal(win32, fake_host, monkeypatch, no_spawn):
    """The timeout path on a pid that already exited (the incident shape)."""
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: None)
    assert deadline.kill_process_tree(100) is False
    assert fake_host.killed == []


def test_deadline_helper_failure_is_false_never_a_raise(win32, monkeypatch, no_spawn):
    def _boom(pid, **kw):
        raise RuntimeError("ctypes trouble")

    monkeypatch.setattr(compat, "windows_kill_process_tree", _boom)
    assert deadline.kill_process_tree(100) is False


# --- site 2: hermes_cli/_subprocess_compat.py --------------------------------


def test_legacy_kill_walks_the_held_popen_and_refuses_the_orphans(fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    proc = _FakeProc(pid=100, returncode=None)
    compat._legacy_kill_process_tree(proc)
    assert fake_host.killed == [300, 200, 100] and proc.killed
    assert fake_host.snapshots == [100]


def test_legacy_kill_mutant_without_the_guard_adopts_the_services(fake_host, no_spawn, monkeypatch, mutant):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    compat._legacy_kill_process_tree(_FakeProc(pid=100, returncode=None))
    assert 26328 in fake_host.killed and 16284 in fake_host.killed


def test_legacy_kill_on_an_exited_popen_kills_nothing(fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    proc = _FakeProc(pid=100, returncode=0)
    compat._legacy_kill_process_tree(proc)
    assert fake_host.killed == [] and fake_host.snapshots == [] and proc.killed


def test_tree_kill_terminates_by_job_membership_when_the_spawn_captured_one(fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    proc = _FakeProc(pid=100, returncode=None)
    compat._tree_kill(proc, compat.WindowsProcessTree(job=0x1234, root_created=ROOT_BORN))
    assert fake_host.jobs_terminated == [0x1234] and fake_host.snapshots == [] and proc.killed


def test_tree_kill_without_a_job_walks_and_refuses_the_orphans(fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    proc = _FakeProc(pid=100, returncode=None)
    compat._tree_kill(proc, compat.WindowsProcessTree(job=None, root_created=ROOT_BORN))
    assert fake_host.killed == [300, 200, 100] and proc.killed


def test_tree_kill_mutant_without_the_guard_adopts_the_services(fake_host, no_spawn, monkeypatch, mutant):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    compat._tree_kill(_FakeProc(pid=100, returncode=None), None)
    assert 26328 in fake_host.killed and 16284 in fake_host.killed


def test_tree_kill_with_a_pinned_root_worn_by_a_stranger_kills_nothing(fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    proc = _FakeProc(pid=100, returncode=None)
    compat._tree_kill(proc, compat.WindowsProcessTree(job=None, root_created=_t("2026-09-17T19:00:00")))
    assert fake_host.killed == [] and proc.killed


class _CapturingPopen:
    """Records the spawn, then behaves like a child that timed out."""

    instances: list = []

    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        self.pid = 100
        self.returncode = None
        self.killed = False
        self.args = argv
        _CapturingPopen.instances.append(self)

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        raise compat.subprocess.TimeoutExpired(self.argv, timeout)

    def communicate(self, timeout=None):
        if timeout == 1:
            return "", ""
        raise compat.subprocess.TimeoutExpired(self.argv, timeout)


@pytest.fixture
def captured_spawn(monkeypatch):
    """Windows spawn contract with everything host-bound stubbed: the child is
    created suspended, captured into job 0x99 with its creation time, thawed,
    and the job handle is closed exactly once on every exit path."""
    _CapturingPopen.instances = []
    calls = SimpleNamespace(captured=[], closed=[], kills=[])
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    monkeypatch.setattr(compat, "windows_hide_flags", lambda: compat._CREATE_NO_WINDOW)
    monkeypatch.setattr(compat, "windows_can_resume", lambda: True)
    monkeypatch.setattr(compat.subprocess, "Popen", _CapturingPopen)

    def _capture(proc, suspended=False):
        calls.captured.append((proc.pid, suspended))
        return compat.WindowsProcessTree(job=0x99, root_created=ROOT_BORN)

    monkeypatch.setattr(compat, "windows_tree_capture", _capture)
    monkeypatch.setattr(compat, "windows_job_close", lambda job: calls.closed.append(job))
    monkeypatch.setattr(compat, "windows_job_terminate", lambda job: calls.kills.append(("job", job)) or True)
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda pid: (_ for _ in ()).throw(AssertionError("walked with a job")))
    return calls


def test_run_text_capture_spawns_frozen_captures_and_kills_by_job_on_timeout(captured_spawn):
    with pytest.raises(compat.subprocess.TimeoutExpired):
        compat.run_text_capture(["wedged"], timeout=0.01)
    (proc,) = _CapturingPopen.instances
    assert proc.kwargs["creationflags"] & compat._CREATE_SUSPENDED
    assert proc.kwargs["creationflags"] & compat._CREATE_NO_WINDOW
    assert captured_spawn.captured == [(100, True)]
    assert captured_spawn.kills == [("job", 0x99)] and proc.killed
    assert captured_spawn.closed == [0x99]


def test_bounded_probe_spawns_frozen_captures_and_kills_by_job_on_timeout(captured_spawn):
    result, stalled = compat._bounded_probe_run_outcome(["wedged"], timeout=0.01)
    assert result is None and stalled is True
    (proc,) = _CapturingPopen.instances
    assert proc.kwargs["creationflags"] == compat._CREATE_NO_WINDOW | compat._CREATE_SUSPENDED
    assert captured_spawn.captured == [(100, True)]
    assert captured_spawn.kills == [("job", 0x99)] and proc.killed
    assert captured_spawn.closed == [0x99]


def test_spawns_are_not_frozen_when_the_thaw_is_unavailable(captured_spawn, monkeypatch):
    monkeypatch.setattr(compat, "windows_can_resume", lambda: False)
    with pytest.raises(compat.subprocess.TimeoutExpired):
        compat.run_text_capture(["wedged"], timeout=0.01)
    (proc,) = _CapturingPopen.instances
    assert not proc.kwargs["creationflags"] & compat._CREATE_SUSPENDED
    assert captured_spawn.captured == [(100, False)]


# --- site 3: hermes_cli/update_cmd_windows.py --------------------------------


@pytest.fixture
def holder(monkeypatch):
    """A leftover holder pid 100 whose identity reads consistently."""
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: int(round(ROOT_BORN * 100)))
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: ROOT_BORN)
    monkeypatch.setattr(compat, "pid_is_hermes", lambda pid, expected_start_time=None: True)


def test_stop_process_trees_walks_the_holder_and_refuses_the_orphans(holder, fake_host, no_spawn):
    update_cmd_windows._stop_process_trees([100])
    assert fake_host.killed == [300, 200, 100]
    assert 26328 not in fake_host.killed and 16284 not in fake_host.killed


def test_stop_process_trees_mutant_without_the_guard_adopts_the_services(holder, fake_host, no_spawn, mutant):
    update_cmd_windows._stop_process_trees([100])
    assert 26328 in fake_host.killed and 16284 in fake_host.killed


def test_stop_process_trees_pins_the_identity_read_before_the_probe(holder, fake_host, no_spawn, monkeypatch):
    """A pid recycled after ``pid_is_hermes`` passed: the walk is pinned to
    the creation time read before the probe, the snapshot's root no longer
    matches, nothing dies."""
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: _t("2026-09-17T19:00:00"))
    update_cmd_windows._stop_process_trees([100])
    assert fake_host.killed == []


def test_stop_process_trees_skips_when_the_probe_refuses(holder, fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "pid_is_hermes", lambda pid, expected_start_time=None: False)
    update_cmd_windows._stop_process_trees([100, (200, 5)])
    assert fake_host.killed == [] and fake_host.snapshots == []


def test_stop_process_trees_skips_an_unreadable_identity(holder, fake_host, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: None)
    update_cmd_windows._stop_process_trees([100])
    assert fake_host.killed == [] and fake_host.snapshots == []


def test_stop_process_trees_never_raises(holder, no_spawn, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, **kw: (_ for _ in ()).throw(OSError("boom")))
    update_cmd_windows._stop_process_trees([100])  # must not raise


# --- source contract: taskkill /T and /IM stay out of these three files -------


def _argv_words(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        elt.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for arg in node.args
        if isinstance(arg, ast.List)
        for elt in arg.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }


@pytest.mark.parametrize("rel", [
    "agent/deadline.py",
    "hermes_cli/_subprocess_compat.py",
    "hermes_cli/update_cmd_windows.py",
])
def test_no_taskkill_argv_in_the_fixed_sites(rel):
    words = _argv_words(_REPO / rel)
    assert "taskkill" not in words, rel
    assert "/T" not in words and "/IM" not in words, rel
