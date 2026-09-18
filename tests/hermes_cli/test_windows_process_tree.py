"""hermes_cli._subprocess_compat's Windows process-tree primitives -- the recycled-pid guard.

The incident (2026-09-17T21:30:08Z, Security 4689): ``taskkill /F /T /PID <pid>``
on a pid that had exited 3 ms earlier. ``/T`` adopts every process whose
recorded ParentProcessId equals that pid; long-lived services are orphans that
keep a dead parent's pid forever, and the box recycles pids within minutes.
Five unrelated interpreters (Hermes Canvas :9121 pid 26328, Control Center
:9120 pid 16284, three more) plus git/docker/cmd died in one 80 ms sweep.

These are the product-side copies of scripts/run_tests_parallel.py's
primitives (fce8860303, itself the port of memory-fabric d913d20): a child is
adopted only if it was created at or after its claimed parent, an unknown
creation time is not adopted, a root that has exited kills nothing, a job is
terminated by membership, and nothing is ever killed by image name. Fake
process records throughout; the live tests kill only children they spawned.
"""

from __future__ import annotations

import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from hermes_cli import _subprocess_compat as compat
from tests.timeout_budget import scaled


def _t(iso: str) -> float:
    """Epoch seconds for an ISO-ish timestamp; only the ordering matters."""
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))


def _rec(pid: int, ppid: int, born: str | None) -> compat.ProcessRecord:
    return compat.ProcessRecord(pid, ppid, None if born is None else _t(born))


@pytest.fixture
def genuine_tree():
    """root 100 -> 200 -> 300, plus 100 -> 201; 999 is unrelated."""
    return [
        _rec(100, 1, "2026-09-17T21:00:00"),
        _rec(200, 100, "2026-09-17T21:00:01"),
        _rec(300, 200, "2026-09-17T21:00:02"),
        _rec(201, 100, "2026-09-17T21:00:01"),
        _rec(999, 1, "2026-09-16T13:00:00"),
    ]


@pytest.fixture
def incident_tree(genuine_tree):
    """THE 2026-09-17 SHAPE: Canvas (26328) and Control Center (16284) claim
    ParentProcessId=100 -- their real parent's pid, recycled as our root --
    but were born a day before 100 existed."""
    return genuine_tree + [
        _rec(26328, 100, "2026-09-16T13:23:47"),
        _rec(16284, 100, "2026-09-16T13:19:29"),
    ]


def _pids(victims):
    return [v.pid for v in victims]


def _naive_walk(root: int, snapshot) -> list[int]:
    """The pre-fix walk (ParentProcessId only) -- what taskkill /T does."""
    out, queue = [], [root]
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        queue.extend(r.pid for r in snapshot if r.ppid == cur)
    return out


# --- the pure walk -----------------------------------------------------------


def test_genuine_tree_every_descendant_leaves_first_root_last(genuine_tree):
    assert _pids(compat.process_tree_victims(100, genuine_tree)) == [300, 201, 200, 100]


def test_orphans_of_a_recycled_pid_are_refused(incident_tree):
    victims = _pids(compat.process_tree_victims(100, incident_tree))
    assert victims == [300, 201, 200, 100]
    assert 26328 not in victims and 16284 not in victims


def test_falsifier_the_unguarded_walk_would_have_killed_both_services(incident_tree):
    naive = _naive_walk(100, incident_tree)
    assert 26328 in naive and 16284 in naive


def test_mutant_the_guard_is_load_bearing(incident_tree, monkeypatch):
    """Remove the creation-time guard from the live function and the same
    fixture adopts both services: the fixture discriminates, the guard is
    what refuses them."""
    monkeypatch.setattr(compat, "is_genuine_child", lambda child, parent: True)
    mutant = _pids(compat.process_tree_victims(100, incident_tree))
    assert 26328 in mutant and 16284 in mutant


def test_recycled_orphan_below_a_genuine_descendant_is_refused_too(genuine_tree):
    snapshot = genuine_tree + [_rec(555, 300, "2026-09-10T08:00:00")]
    assert _pids(compat.process_tree_victims(100, snapshot)) == [300, 201, 200, 100]


def test_child_born_in_the_same_instant_as_its_parent_is_still_a_child():
    snapshot = [_rec(100, 1, "2026-09-17T21:00:00"), _rec(200, 100, "2026-09-17T21:00:00")]
    assert _pids(compat.process_tree_victims(100, snapshot)) == [200, 100]


def test_dead_root_no_victims_at_all(incident_tree):
    assert compat.process_tree_victims(4242, incident_tree) == []


def test_unknown_creation_time_on_either_side_is_not_adopted():
    child_unknown = [_rec(100, 1, "2026-09-17T21:00:00"), _rec(200, 100, None)]
    assert _pids(compat.process_tree_victims(100, child_unknown)) == [100]
    parent_unknown = [_rec(100, 1, None), _rec(200, 100, "2026-09-17T21:00:01")]
    assert _pids(compat.process_tree_victims(100, parent_unknown)) == [100]


def test_root_that_is_a_different_process_than_we_spawned_is_not_ours(genuine_tree):
    """The pid we spawned, worn by a stranger: creation time pinned at spawn
    does not match the snapshot's -> nothing, not even the root."""
    ours = _t("2026-09-17T20:00:00")
    assert compat.process_tree_victims(100, genuine_tree, root_created=ours) == []
    theirs = _t("2026-09-17T21:00:00")
    assert _pids(compat.process_tree_victims(100, genuine_tree, root_created=theirs)) == [300, 201, 200, 100]


def test_same_process_tolerates_the_millisecond_and_nothing_more():
    assert compat.same_process(1.0, 1.0 + 0.0005)
    assert not compat.same_process(1.0, 1.0 + 0.01)
    assert not compat.same_process(None, 1.0) and not compat.same_process(1.0, None)


def test_a_cycle_in_recorded_ppids_terminates():
    """Recycled pids can make the recorded graph cyclic; the walk must not spin."""
    snapshot = [_rec(100, 200, "2026-09-17T21:00:00"), _rec(200, 100, "2026-09-17T21:00:01")]
    assert _pids(compat.process_tree_victims(100, snapshot)) == [200, 100]


# --- orchestration with fake records: no real kills --------------------------


class _FakeProc:
    """A Popen double. ``_handle`` marks a process we really spawned; without
    it the helpers must refuse to touch the pid at all."""

    def __init__(self, pid: int, returncode: int | None, handle: int | None = 0x50):
        self.pid = pid
        self.returncode = returncode
        self.killed = False
        if handle is not None:
            self._handle = handle

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def no_taskkill(monkeypatch):
    """Any subprocess spawn from a kill path is the old bug coming back."""

    def _boom(*args, **kwargs):  # pragma: no cover - only on regression
        raise AssertionError(f"kill path spawned a process: {args!r}")

    monkeypatch.setattr(compat.subprocess, "run", _boom)
    monkeypatch.setattr(compat.subprocess, "Popen", _boom)
    monkeypatch.setattr(compat.subprocess, "check_output", _boom)


@pytest.fixture
def recorder(monkeypatch, incident_tree):
    """Fake host: the incident snapshot, and kills that only record."""
    calls = SimpleNamespace(snapshots=0, killed=[], jobs_terminated=[])

    def _snapshot(root_pid):
        calls.snapshots += 1
        return incident_tree

    def _kill(pid, created):
        calls.killed.append(pid)
        return True

    monkeypatch.setattr(compat, "windows_tree_snapshot", _snapshot)
    monkeypatch.setattr(compat, "windows_kill_pid", _kill)
    monkeypatch.setattr(compat, "windows_job_terminate", lambda job: calls.jobs_terminated.append(job) or True)
    return calls


def test_bare_pid_walk_kills_the_guarded_tree_only(recorder, no_taskkill):
    assert compat.windows_kill_process_tree(100) == [300, 201, 200, 100]
    assert 26328 not in recorder.killed and 16284 not in recorder.killed


def test_bare_pid_walk_with_a_pinned_root_refuses_a_stranger(recorder, no_taskkill):
    assert compat.windows_kill_process_tree(100, root_created=_t("2026-09-17T19:00:00")) == []
    assert recorder.killed == []


def test_bare_pid_walk_on_an_exited_root_kills_nothing(recorder, monkeypatch, no_taskkill):
    """A root that is not in the snapshot has exited: no edge below it is provable."""
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: None)
    assert compat.windows_kill_process_tree(100) == []
    assert recorder.killed == []


def test_exited_popen_root_without_a_job_kills_nothing_and_takes_no_snapshot(recorder, no_taskkill):
    """(a) The incident shape: the child exited normally 3 ms ago."""
    proc = _FakeProc(pid=100, returncode=0)
    tree = compat.WindowsProcessTree(job=None, root_created=_t("2026-09-17T21:00:00"))
    assert compat.windows_kill_popen_tree(proc, tree) == []
    assert recorder.killed == [] and recorder.snapshots == 0


def test_exited_popen_root_with_no_tree_info_kills_nothing(recorder, no_taskkill):
    assert compat.windows_kill_popen_tree(_FakeProc(pid=100, returncode=0), None) == []
    assert recorder.killed == []


def test_live_popen_root_without_a_job_kills_the_guarded_tree_only(recorder, no_taskkill):
    """(b) Timeout path: root alive, walk over the snapshot, orphans refused."""
    proc = _FakeProc(pid=100, returncode=None)
    tree = compat.WindowsProcessTree(job=None, root_created=_t("2026-09-17T21:00:00"))
    assert compat.windows_kill_popen_tree(proc, tree) == [300, 201, 200, 100]
    assert recorder.killed == [300, 201, 200, 100] and recorder.snapshots == 1


def test_live_popen_root_whose_pid_now_belongs_to_a_stranger_kills_nothing(recorder, no_taskkill):
    proc = _FakeProc(pid=100, returncode=None)
    tree = compat.WindowsProcessTree(job=None, root_created=_t("2026-09-17T19:00:00"))
    assert compat.windows_kill_popen_tree(proc, tree) == []
    assert recorder.killed == []


def test_job_member_kill_takes_no_snapshot_and_names_no_pid(recorder, no_taskkill):
    """With a job, termination is by membership: no walk, no pid, no name."""
    proc = _FakeProc(pid=100, returncode=0)
    assert compat.windows_kill_popen_tree(proc, compat.WindowsProcessTree(job=0x1234)) == []
    assert recorder.jobs_terminated == [0x1234]
    assert recorder.snapshots == 0 and recorder.killed == []


def test_a_job_that_cannot_be_terminated_falls_back_to_the_guarded_walk(recorder, monkeypatch, no_taskkill):
    monkeypatch.setattr(compat, "windows_job_terminate", lambda job: False)
    proc = _FakeProc(pid=100, returncode=None)
    tree = compat.WindowsProcessTree(job=0x1234, root_created=_t("2026-09-17T21:00:00"))
    assert compat.windows_kill_popen_tree(proc, tree) == [300, 201, 200, 100]
    assert 26328 not in recorder.killed and 16284 not in recorder.killed


def test_kill_pid_refuses_a_recycled_pid(monkeypatch):
    """(c) The per-victim identity check: the pid the snapshot saw is now a
    different process -> not terminated."""
    psutil = pytest.importorskip("psutil")

    class _Other:
        def __init__(self, pid):
            self.pid = pid
            self.kills = 0

        def create_time(self):
            return _t("2026-09-17T22:00:00")

        def kill(self):
            self.kills += 1

    other = _Other(100)
    monkeypatch.setattr(psutil, "Process", lambda pid: other)
    assert compat.windows_kill_pid(100, _t("2026-09-17T21:00:00")) is False
    assert other.kills == 0
    assert compat.windows_kill_pid(100, _t("2026-09-17T22:00:00")) is True
    assert other.kills == 1


def test_a_popen_double_without_a_handle_is_never_touched(monkeypatch):
    """A test stub's pid can be anyone's: no job, no creation time read, no
    thaw, no kill -- the capture returns an empty tree and walks away."""
    real_job_for = compat.windows_job_for
    for name in ("windows_job_for", "windows_process_created", "windows_resume"):
        monkeypatch.setattr(compat, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"{name} touched a stub")))
    stub = _FakeProc(pid=4321, returncode=None, handle=None)
    tree = compat.windows_tree_capture(stub, suspended=True)
    assert tree.job is None and tree.root_created is None and not stub.killed
    assert real_job_for(stub) is None  # the real one, on a stub: no OpenProcess fallback


def test_a_frozen_child_that_cannot_be_thawed_is_killed_not_left_frozen(monkeypatch):
    monkeypatch.setattr(compat, "windows_job_for", lambda proc, **kw: 0x77)
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: 1.0)
    monkeypatch.setattr(compat, "windows_resume", lambda pid: False)
    proc = _FakeProc(pid=100, returncode=None)
    tree = compat.windows_tree_capture(proc, suspended=True)
    assert proc.killed and tree.job == 0x77 and tree.root_created == 1.0

    thawed = _FakeProc(pid=101, returncode=None)
    monkeypatch.setattr(compat, "windows_resume", lambda pid: True)
    compat.windows_tree_capture(thawed, suspended=True)
    assert not thawed.killed

    never_frozen = _FakeProc(pid=102, returncode=None)
    monkeypatch.setattr(compat, "windows_resume", lambda pid: (_ for _ in ()).throw(AssertionError("must not thaw")))
    compat.windows_tree_capture(never_frozen, suspended=False)
    assert not never_frozen.killed


def test_suspended_spawn_flag_is_offered_only_when_the_thaw_is(monkeypatch):
    monkeypatch.setattr(compat, "IS_WINDOWS", True)
    monkeypatch.setattr(compat, "windows_can_resume", lambda: True)
    assert compat.windows_suspended_spawn_flag() == compat._CREATE_SUSPENDED
    monkeypatch.setattr(compat, "windows_can_resume", lambda: False)
    assert compat.windows_suspended_spawn_flag() == 0
    monkeypatch.setattr(compat, "IS_WINDOWS", False)
    monkeypatch.setattr(compat, "windows_can_resume", lambda: True)
    assert compat.windows_suspended_spawn_flag() == 0


def test_job_close_tolerates_no_job():
    compat.windows_job_close(None)  # must not raise


# --- live (Windows only): kills only the children it spawned ------------------

_CHILD = (
    "import subprocess, sys, os, time;"
    "p = subprocess.Popen(['ping', '-n', '300', '127.0.0.1'], stdout=subprocess.DEVNULL);"
    "print(os.getpid(), p.pid, flush=True);"
    "time.sleep(300)"
)


def _spawn_tree():
    """The product's own spawn shape: frozen, captured, thawed."""
    flag = compat.windows_suspended_spawn_flag()
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD], stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=flag)
    tree = compat.windows_tree_capture(proc, suspended=bool(flag))
    inner, grandchild = (int(x) for x in proc.stdout.readline().split())
    return proc, tree, inner, grandchild


def _reap(proc, *pids):
    psutil = pytest.importorskip("psutil")
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass
    try:
        proc.kill()
    except OSError:
        pass


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
@pytest.mark.timeout(scaled(60))
def test_live_job_takes_the_grandchild_even_after_the_root_exited():
    """The venv launcher's own job lets grandchildren break away; ours does
    not. A decoy tree beside it lives."""
    psutil = pytest.importorskip("psutil")
    decoy, decoy_tree, decoy_inner, decoy_grandchild = _spawn_tree()
    proc, tree, inner, grandchild = _spawn_tree()
    try:
        if tree.job is None:
            pytest.skip("job assignment refused on this host (nested jobs forbidden)")
        psutil.Process(inner).kill()  # the worker is gone; the launcher relays its exit
        proc.wait(timeout=scaled(20))
        assert psutil.pid_exists(grandchild), "precondition: the grandchild outlived its parent"
        compat._tree_kill(proc, tree)
        deadline = time.monotonic() + scaled(10)
        while psutil.pid_exists(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(grandchild)
        assert decoy.poll() is None and psutil.pid_exists(decoy_grandchild)
    finally:
        compat.windows_job_close(tree.job)
        compat.windows_job_close(decoy_tree.job)
        _reap(proc, inner, grandchild)
        _reap(decoy, decoy_inner, decoy_grandchild)


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
@pytest.mark.timeout(scaled(60))
def test_live_closing_a_job_does_not_reap_its_members():
    """Product jobs are not kill-on-close: a grandchild the command left
    behind (agent-browser's daemon) survives the capture returning."""
    psutil = pytest.importorskip("psutil")
    proc, tree, inner, grandchild = _spawn_tree()
    try:
        if tree.job is None:
            pytest.skip("job assignment refused on this host (nested jobs forbidden)")
        compat.windows_job_close(tree.job)
        time.sleep(0.2)
        assert proc.poll() is None and psutil.pid_exists(inner) and psutil.pid_exists(grandchild)
    finally:
        _reap(proc, inner, grandchild)


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
@pytest.mark.timeout(scaled(60))
def test_live_guarded_walk_kills_the_tree_and_spares_a_decoy(monkeypatch):
    """Fallback path (no job): snapshot while the root is alive, leaves first."""
    psutil = pytest.importorskip("psutil")
    monkeypatch.setattr(compat, "windows_job_for", lambda proc, **kw: None)
    decoy, _, decoy_inner, decoy_grandchild = _spawn_tree()
    proc, tree, inner, grandchild = _spawn_tree()
    try:
        assert tree.job is None and tree.root_created is not None
        snapshot = compat.windows_tree_snapshot(proc.pid)
        assert snapshot is not None
        victims = compat.process_tree_victims(proc.pid, snapshot, root_created=tree.root_created)
        assert [v.pid for v in victims] == [grandchild, inner, proc.pid]
        killed = compat.windows_kill_popen_tree(proc, tree)
        assert killed == [grandchild, inner, proc.pid]
        proc.wait(timeout=scaled(20))
        deadline = time.monotonic() + scaled(10)
        while (psutil.pid_exists(grandchild) or psutil.pid_exists(inner)) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(grandchild) and not psutil.pid_exists(inner)
        assert decoy.poll() is None and psutil.pid_exists(decoy_grandchild)
    finally:
        _reap(proc, inner, grandchild)
        _reap(decoy, decoy_inner, decoy_grandchild)


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
@pytest.mark.timeout(scaled(60))
def test_live_bare_pid_walk_on_an_exited_root_kills_nothing():
    """The incident shape against the real host: the pid has exited; whatever
    now claims it as a parent is not ours to kill."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=scaled(20))
    assert compat.windows_kill_process_tree(proc.pid) == []
