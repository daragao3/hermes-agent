"""scripts/run_tests_parallel.py::_kill_tree on Windows -- the recycled-pid guard.

The incident (2026-09-17T21:30:08Z, Security 4689): the runner's happy path
ran ``taskkill /F /T /PID <pid>`` on a pytest launcher pid that had exited
3 ms earlier. ``/T`` adopts every process whose recorded ParentProcessId
equals that pid; long-lived services are orphans that keep a dead parent's
pid forever, and the box recycles pids within minutes. Five unrelated
interpreters (Hermes Canvas :9121 pid 26328, Control Center :9120 pid 16284,
three more) plus git/docker/cmd died in one 80 ms sweep.

The port of memory-fabric d913d20 (Get-ProcessTreeVictims): a child is
adopted only if it was created at or after its claimed parent, an unknown
creation time is not adopted, a root that has exited (and is in no job of
ours) kills nothing, and nothing is ever killed by image name. These tests
drive the pure walk and the orchestration with fake process records -- no
real process is killed except in the one live test, which kills only the
children it spawned itself.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.timeout_budget import scaled

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_tests_parallel.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("run_tests_parallel_kill_tree_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _t(iso: str) -> float:
    """Epoch seconds for an ISO-ish timestamp; only the ordering matters."""
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))


def _rec(harness, pid: int, ppid: int, born: str | None):
    return harness._ProcRecord(pid, ppid, None if born is None else _t(born))


@pytest.fixture
def genuine_tree(harness):
    """root 100 -> 200 -> 300, plus 100 -> 201; 999 is unrelated."""
    return [
        _rec(harness, 100, 1, "2026-09-17T21:00:00"),
        _rec(harness, 200, 100, "2026-09-17T21:00:01"),
        _rec(harness, 300, 200, "2026-09-17T21:00:02"),
        _rec(harness, 201, 100, "2026-09-17T21:00:01"),
        _rec(harness, 999, 1, "2026-09-16T13:00:00"),
    ]


@pytest.fixture
def incident_tree(harness, genuine_tree):
    """THE 2026-09-17 SHAPE: Canvas (26328) and Control Center (16284) claim
    ParentProcessId=100 -- their real parent's pid, recycled as our root --
    but were born a day before 100 existed."""
    return genuine_tree + [
        _rec(harness, 26328, 100, "2026-09-16T13:23:47"),
        _rec(harness, 16284, 100, "2026-09-16T13:19:29"),
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


def test_genuine_tree_every_descendant_leaves_first_root_last(harness, genuine_tree):
    assert _pids(harness._process_tree_victims(100, genuine_tree)) == [300, 201, 200, 100]


def test_orphans_of_a_recycled_pid_are_refused(harness, incident_tree):
    victims = _pids(harness._process_tree_victims(100, incident_tree))
    assert victims == [300, 201, 200, 100]
    assert 26328 not in victims and 16284 not in victims


def test_falsifier_the_unguarded_walk_would_have_killed_both_services(incident_tree):
    naive = _naive_walk(100, incident_tree)
    assert 26328 in naive and 16284 in naive


def test_mutant_the_guard_is_load_bearing(harness, incident_tree, monkeypatch):
    """Remove the creation-time guard from the live function and the same
    fixture adopts both services: the fixture discriminates, the guard is
    what refuses them."""
    monkeypatch.setattr(harness, "_is_genuine_child", lambda child, parent: True)
    mutant = _pids(harness._process_tree_victims(100, incident_tree))
    assert 26328 in mutant and 16284 in mutant


def test_recycled_orphan_below_a_genuine_descendant_is_refused_too(harness, genuine_tree):
    snapshot = genuine_tree + [_rec(harness, 555, 300, "2026-09-10T08:00:00")]
    assert _pids(harness._process_tree_victims(100, snapshot)) == [300, 201, 200, 100]


def test_child_born_in_the_same_instant_as_its_parent_is_still_a_child(harness):
    snapshot = [_rec(harness, 100, 1, "2026-09-17T21:00:00"), _rec(harness, 200, 100, "2026-09-17T21:00:00")]
    assert _pids(harness._process_tree_victims(100, snapshot)) == [200, 100]


def test_dead_root_no_victims_at_all(harness, incident_tree):
    assert harness._process_tree_victims(4242, incident_tree) == []


def test_unknown_creation_time_on_either_side_is_not_adopted(harness):
    child_unknown = [_rec(harness, 100, 1, "2026-09-17T21:00:00"), _rec(harness, 200, 100, None)]
    assert _pids(harness._process_tree_victims(100, child_unknown)) == [100]
    parent_unknown = [_rec(harness, 100, 1, None), _rec(harness, 200, 100, "2026-09-17T21:00:01")]
    assert _pids(harness._process_tree_victims(100, parent_unknown)) == [100]


def test_root_that_is_a_different_process_than_we_spawned_is_not_ours(harness, genuine_tree):
    """The pid we spawned, worn by a stranger: creation time pinned at spawn
    does not match the snapshot's -> nothing, not even the root."""
    ours = _t("2026-09-17T20:00:00")
    assert harness._process_tree_victims(100, genuine_tree, root_created=ours) == []
    theirs = _t("2026-09-17T21:00:00")
    assert _pids(harness._process_tree_victims(100, genuine_tree, root_created=theirs)) == [300, 201, 200, 100]


def test_a_cycle_in_recorded_ppids_terminates(harness):
    """Recycled pids can make the recorded graph cyclic; the walk must not spin."""
    snapshot = [
        _rec(harness, 100, 200, "2026-09-17T21:00:00"),
        _rec(harness, 200, 100, "2026-09-17T21:00:01"),
    ]
    assert _pids(harness._process_tree_victims(100, snapshot)) == [200, 100]


# --- orchestration: _win_kill_tree with fake records, no real kills -----------


class _FakeProc:
    def __init__(self, pid: int, returncode: int | None):
        self.pid = pid
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def no_taskkill(harness, monkeypatch):
    """Any subprocess spawn from the kill path is the old bug coming back."""

    def _boom(*args, **kwargs):  # pragma: no cover - only on regression
        raise AssertionError(f"kill path spawned a process: {args!r}")

    monkeypatch.setattr(harness.subprocess, "run", _boom)
    monkeypatch.setattr(harness.subprocess, "Popen", _boom)
    monkeypatch.setattr(harness.subprocess, "check_output", _boom)


@pytest.fixture
def recorder(harness, monkeypatch, incident_tree):
    """Fake host: the incident snapshot, and kills that only record."""
    calls = SimpleNamespace(snapshots=0, killed=[], jobs_terminated=[])

    def _snapshot(root_pid):
        calls.snapshots += 1
        return incident_tree

    def _kill(pid, created):
        calls.killed.append(pid)
        return True

    monkeypatch.setattr(harness, "_win_tree_snapshot", _snapshot)
    monkeypatch.setattr(harness, "_win_kill_pid", _kill)
    monkeypatch.setattr(harness, "_win_job_terminate", lambda job: calls.jobs_terminated.append(job) or True)
    return calls


def test_exited_root_without_a_job_kills_nothing_and_takes_no_snapshot(harness, recorder, no_taskkill):
    """(a) The incident shape: the launcher exited normally 3 ms ago."""
    proc = _FakeProc(pid=100, returncode=0)
    assert harness._win_kill_tree(proc, harness._WinTree(job=None, root_created=_t("2026-09-17T21:00:00"))) == []
    assert recorder.killed == [] and recorder.snapshots == 0


def test_exited_root_with_no_tree_info_at_all_kills_nothing(harness, recorder, no_taskkill):
    proc = _FakeProc(pid=100, returncode=0)
    assert harness._win_kill_tree(proc, None) == []
    assert recorder.killed == []


def test_live_root_without_a_job_kills_the_guarded_tree_only(harness, recorder, no_taskkill):
    """(b) Timeout path: root alive, walk over the snapshot, orphans refused."""
    proc = _FakeProc(pid=100, returncode=None)
    tree = harness._WinTree(job=None, root_created=_t("2026-09-17T21:00:00"))
    assert harness._win_kill_tree(proc, tree) == [300, 201, 200, 100]
    assert recorder.killed == [300, 201, 200, 100]
    assert recorder.snapshots == 1


def test_live_root_whose_pid_now_belongs_to_a_stranger_kills_nothing(harness, recorder, no_taskkill):
    proc = _FakeProc(pid=100, returncode=None)
    tree = harness._WinTree(job=None, root_created=_t("2026-09-17T19:00:00"))
    assert harness._win_kill_tree(proc, tree) == []
    assert recorder.killed == []


def test_job_member_kill_takes_no_snapshot_and_names_no_pid(harness, recorder, no_taskkill):
    """With a job, termination is by membership: no walk, no pid, no name."""
    proc = _FakeProc(pid=100, returncode=0)
    assert harness._win_kill_tree(proc, harness._WinTree(job=0x1234, root_created=None)) == []
    assert recorder.jobs_terminated == [0x1234]
    assert recorder.snapshots == 0 and recorder.killed == []


def test_unavailable_snapshot_kills_nothing(harness, recorder, monkeypatch, no_taskkill):
    monkeypatch.setattr(harness, "_win_tree_snapshot", lambda root_pid: None)
    proc = _FakeProc(pid=100, returncode=None)
    assert harness._win_kill_tree(proc, harness._WinTree(job=None, root_created=None)) == []
    assert recorder.killed == []


def test_kill_tree_on_win32_never_spawns_and_still_kills_the_popen_handle(harness, recorder, no_taskkill, monkeypatch):
    monkeypatch.setattr(harness.sys, "platform", "win32")
    proc = _FakeProc(pid=100, returncode=0)
    harness._kill_tree(proc, tree=harness._WinTree(job=None, root_created=None))
    assert recorder.killed == []
    assert proc.killed  # Popen.kill() acts on the handle we hold: identity-safe


def test_kill_pid_refuses_a_recycled_pid(harness, monkeypatch):
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
    assert harness._win_kill_pid(100, _t("2026-09-17T21:00:00")) is False
    assert other.kills == 0
    assert harness._win_kill_pid(100, _t("2026-09-17T22:00:00")) is True
    assert other.kills == 1


def test_the_runner_never_calls_taskkill_or_kills_by_image_name():
    """Source contract: ``taskkill`` (and its ``/T`` ppid walk, and ``/IM``)
    do not come back into the kill path."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    argv_words = {
        elt.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for arg in node.args
        if isinstance(arg, ast.List)
        for elt in arg.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert "taskkill" not in argv_words
    assert "/T" not in argv_words and "/IM" not in argv_words


def test_spawn_site_starts_the_child_frozen_captures_the_tree_and_closes_the_job(harness):
    """The spawn site creates the child suspended (so it joins the job before
    its first instruction), hands ``_kill_tree`` the tree captured then on
    every exit path, and closes the job when the attempt is over."""
    src = inspect.getsource(harness._spawn_pytest)
    assert "creationflags=_CREATE_SUSPENDED if suspended else 0" in src
    assert "tree = _win_tree_capture(proc, suspended=suspended)" in src
    assert src.count("_kill_tree(proc, pgid=pgid, tree=tree)") == 3
    assert "_win_job_close(tree.job)" in src


def test_a_frozen_child_that_cannot_be_thawed_is_killed_not_left_frozen(harness, monkeypatch):
    monkeypatch.setattr(harness, "_win_job_for", lambda proc: 0x77)
    monkeypatch.setattr(harness, "_win_process_created", lambda pid: 1.0)
    monkeypatch.setattr(harness, "_win_resume", lambda pid: False)
    proc = _FakeProc(pid=100, returncode=None)
    tree = harness._win_tree_capture(proc, suspended=True)
    assert proc.killed and tree.job == 0x77 and tree.root_created == 1.0

    thawed = _FakeProc(pid=101, returncode=None)
    monkeypatch.setattr(harness, "_win_resume", lambda pid: True)
    harness._win_tree_capture(thawed, suspended=True)
    assert not thawed.killed

    never_frozen = _FakeProc(pid=102, returncode=None)
    monkeypatch.setattr(harness, "_win_resume", lambda pid: (_ for _ in ()).throw(AssertionError("must not thaw")))
    harness._win_tree_capture(never_frozen, suspended=False)
    assert not never_frozen.killed


def test_a_job_that_cannot_be_terminated_falls_back_to_the_guarded_walk(harness, recorder, monkeypatch, no_taskkill):
    monkeypatch.setattr(harness, "_win_job_terminate", lambda job: False)
    proc = _FakeProc(pid=100, returncode=None)
    tree = harness._WinTree(job=0x1234, root_created=_t("2026-09-17T21:00:00"))
    assert harness._win_kill_tree(proc, tree) == [300, 201, 200, 100]
    assert 26328 not in recorder.killed and 16284 not in recorder.killed


# --- live (Windows only): kills only the children it spawned ------------------

_CHILD = (
    "import subprocess, sys, os, time;"
    "p = subprocess.Popen(['ping', '-n', '300', '127.0.0.1'], stdout=subprocess.DEVNULL);"
    "print(os.getpid(), p.pid, flush=True);"
    "time.sleep(300)"
)


def _spawn_tree(harness):
    """The runner's own spawn shape: frozen, captured, thawed."""
    suspended = harness._win_can_resume()
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=harness._CREATE_SUSPENDED if suspended else 0,
    )
    tree = harness._win_tree_capture(proc, suspended=suspended)
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
def test_live_job_takes_the_grandchild_even_after_the_root_exited(harness):
    """Happy path on Windows: the venv launcher's own job lets grandchildren
    break away, the runner's job does not. A decoy tree beside it lives."""
    psutil = pytest.importorskip("psutil")
    decoy, _, decoy_inner, decoy_grandchild = _spawn_tree(harness)
    proc, tree, inner, grandchild = _spawn_tree(harness)
    try:
        if tree.job is None:
            pytest.skip("job assignment refused on this host (nested jobs forbidden)")
        psutil.Process(inner).kill()  # the worker is gone; the launcher relays its exit
        proc.wait(timeout=scaled(20))
        assert psutil.pid_exists(grandchild), "precondition: the grandchild outlived its parent"
        harness._kill_tree(proc, tree=tree)
        deadline = time.monotonic() + scaled(10)
        while psutil.pid_exists(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(grandchild)
        assert decoy.poll() is None and psutil.pid_exists(decoy_grandchild)
    finally:
        if tree.job is not None:
            harness._win_job_close(tree.job)
        _reap(proc, inner, grandchild)
        _reap(decoy, decoy_inner, decoy_grandchild)


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
@pytest.mark.timeout(scaled(60))
def test_live_guarded_walk_kills_the_tree_and_spares_a_decoy(harness, monkeypatch):
    """Fallback path (no job): snapshot while the root is alive, leaves first."""
    psutil = pytest.importorskip("psutil")
    monkeypatch.setattr(harness, "_win_job_for", lambda proc: None)
    decoy, _, decoy_inner, decoy_grandchild = _spawn_tree(harness)
    proc, tree, inner, grandchild = _spawn_tree(harness)
    try:
        assert tree.job is None and tree.root_created is not None
        snapshot = harness._win_tree_snapshot(proc.pid)
        assert snapshot is not None
        victims = harness._process_tree_victims(proc.pid, snapshot, root_created=tree.root_created)
        assert [v.pid for v in victims] == [grandchild, inner, proc.pid]
        killed = harness._win_kill_tree(proc, tree)
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
