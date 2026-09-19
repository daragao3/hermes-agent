"""The residual product tree-kill sites no longer run ``taskkill /T`` (or ``/IM``) on Windows.

Follow-up to ``test_tree_kill_sites_no_taskkill.py`` (agent/deadline, _subprocess_compat,
update_cmd_windows). The same hazard lived on in ten more places; each is rewired onto
``hermes_cli._subprocess_compat``:

* ``cron.scheduler_script`` -- the HIGHEST priority one: ``_terminate_cron_script_process``
  was the fallback ``_terminate_cron_script_tree`` took when the unified kill reported no
  signal, which is exactly the exited-pid case, so the fallback re-introduced the bug for
  that shape. The script is now spawned suspended + captured into a job, the job is killed
  by membership, and the walk is the fallback.
* ``gateway.status.terminate_pid(force=True)`` -- root identity-guarded via centiseconds,
  children were not; the float creation time is now read BEFORE the guard and pinned into
  the walk.
* ``tools.process_registry._terminate_host_pid``, ``session_bridge.cli._kill_process_tree``,
  ``session_bridge.claude_registrar`` (PTY reclaim + ``_WinPtyProcess.terminate``),
  ``tools.browser_tool_lifecycle._legacy_kill_process_tree``,
  ``tools.tts_command_provider.terminate_command_process_tree``,
  ``plugins.platforms.whatsapp.adapter._terminate_bridge_process`` (graceful branch kept),
  ``tui_gateway.host_supervisor._force_kill_pid``.
* ``evals/browser_use/orchestrate.py`` killed by IMAGE NAME with ``/T`` -- now a pid-scoped
  kill of the cell it spawned, by job membership.
* ``optional-skills/finance/excel-author/scripts/recalc.py`` -- stdlib-only by contract, so
  it carries its own job object rather than importing the shared module.

Each site gets (1) a fake-record run through the REAL walk showing the 2026-09-17 orphans
(Canvas 26328, Control Center 16284, ParentProcessId=our root, born a day earlier) are
refused, (2) a mutant check: with the guard removed the same site adopts them, so the guard
is what the site relies on, and (3) a no-spawn fixture: any ``subprocess`` call from a kill
path fails the test. No real process is killed except, in the one live test, a process the
test spawned itself.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import _subprocess_compat as compat
from tests.timeout_budget import scaled

_REPO = Path(__file__).resolve().parents[2]


def _t(iso: str) -> float:
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))


ROOT_BORN = _t("2026-09-17T21:00:00")
STRANGER_BORN = _t("2026-09-17T19:00:00")


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


ORPHANS = {26328, 16284}


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


@pytest.fixture
def win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(compat, "IS_WINDOWS", True)


def _no_spawn_on(monkeypatch, *modules):
    def _boom(*args, **kwargs):  # pragma: no cover - only on regression
        raise AssertionError(f"kill path spawned a process: {args!r}")

    for mod in modules:
        monkeypatch.setattr(mod, "run", _boom)
        monkeypatch.setattr(mod, "Popen", _boom)
        monkeypatch.setattr(mod, "check_output", _boom)


class _FakeProc:
    def __init__(self, pid: int = 100, returncode: int | None = None):
        self.pid = pid
        self.returncode = returncode
        self._handle = 0x50
        self.killed = False
        self.terminated = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -1

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True


# --- site 1: cron/scheduler_script.py ------------------------------------------


@pytest.fixture
def sched(monkeypatch, win32):
    from cron import scheduler_script as sched_script

    _no_spawn_on(monkeypatch, sched_script.subprocess, compat.subprocess)
    return sched_script


def test_cron_tree_kill_terminates_by_job_membership_when_the_spawn_captured_one(sched, fake_host):
    proc = _FakeProc()
    sched._terminate_cron_script_tree(proc, compat.WindowsProcessTree(job=0x1234, root_created=ROOT_BORN))
    assert fake_host.jobs_terminated == [0x1234] and fake_host.snapshots == [] and proc.killed


def test_cron_tree_kill_without_a_job_walks_and_refuses_the_orphans(sched, fake_host):
    proc = _FakeProc()
    sched._terminate_cron_script_tree(proc, compat.WindowsProcessTree(job=None, root_created=ROOT_BORN))
    assert fake_host.killed == [300, 200, 100] and proc.killed
    assert not ORPHANS & set(fake_host.killed)


def test_cron_tree_kill_mutant_without_the_guard_adopts_the_services(sched, fake_host, mutant):
    sched._terminate_cron_script_tree(_FakeProc(), compat.WindowsProcessTree(job=None, root_created=ROOT_BORN))
    assert ORPHANS <= set(fake_host.killed)


def test_cron_tree_kill_never_consults_the_bare_pid_path_when_it_holds_a_tree(sched, fake_host, monkeypatch):
    """The 'no signal' fallback is not reachable from a captured spawn."""
    from agent import deadline

    monkeypatch.setattr(deadline, "kill_process_tree", lambda pid: (_ for _ in ()).throw(AssertionError("bare pid path")))
    sched._terminate_cron_script_tree(_FakeProc(), compat.WindowsProcessTree(job=0x1, root_created=ROOT_BORN))
    assert fake_host.jobs_terminated == [0x1]


def test_cron_fallback_on_the_exited_pid_shape_kills_nothing(sched, fake_host):
    """The incident shape exactly: the unified kill reported no signal because the pid had
    exited, and the old fallback ran ``taskkill /T`` on it. Now: no snapshot, no kill."""
    proc = _FakeProc(returncode=0)
    sched._terminate_cron_script_process(proc)
    assert fake_host.killed == [] and fake_host.snapshots == []


def test_cron_fallback_on_a_live_popen_walks_and_refuses_the_orphans(sched, fake_host):
    proc = _FakeProc()
    sched._terminate_cron_script_process(proc)
    assert fake_host.killed == [300, 200, 100] and proc.killed
    assert not ORPHANS & set(fake_host.killed)


def test_cron_fallback_mutant_without_the_guard_adopts_the_services(sched, fake_host, mutant):
    sched._terminate_cron_script_process(_FakeProc())
    assert ORPHANS <= set(fake_host.killed)


def test_cron_fallback_walk_failure_still_kills_the_root_and_never_raises(sched, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_popen_tree", lambda proc, tree=None: (_ for _ in ()).throw(OSError("ctypes")))
    proc = _FakeProc()
    sched._terminate_cron_script_process(proc)
    assert proc.killed


# --- site 2: gateway/status.py::terminate_pid ------------------------------------


@pytest.fixture
def status_win(monkeypatch, win32):
    from gateway import status

    monkeypatch.setattr(status, "_IS_WINDOWS", True)
    monkeypatch.setattr(status, "write_diag", lambda *a, **k: None)
    monkeypatch.setattr(status.os, "kill", lambda *a, **k: (_ for _ in ()).throw(AssertionError("os.kill on the force path")))
    monkeypatch.setattr(status, "_get_process_start_time", lambda pid: int(round(ROOT_BORN * 100)))
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: ROOT_BORN)
    monkeypatch.setattr(status, "_wait_for_pid_death", lambda pid, timeout: True)
    _no_spawn_on(monkeypatch, status.subprocess, compat.subprocess)
    return status


def test_terminate_pid_force_walks_pinned_and_refuses_the_orphans(status_win, fake_host):
    status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_terminate_pid_mutant_without_the_guard_adopts_the_services(status_win, fake_host, mutant):
    status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert ORPHANS <= set(fake_host.killed)


def test_terminate_pid_reads_the_pin_before_the_identity_guard(status_win, fake_host, monkeypatch):
    order = []
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: order.append("pin") or ROOT_BORN)
    monkeypatch.setattr(status_win, "_get_process_start_time", lambda pid: order.append("guard") or int(round(ROOT_BORN * 100)))
    status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert order == ["pin", "guard"]


def test_terminate_pid_pinned_root_worn_by_a_stranger_kills_nothing_and_raises(status_win, fake_host, monkeypatch):
    """Recycled between the pin and the snapshot: the walk refuses, and a stranger still
    wearing the pid is reported as a failed kill rather than a success."""
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: STRANGER_BORN)
    monkeypatch.setattr(status_win, "_wait_for_pid_death", lambda pid, timeout: False)
    with pytest.raises(OSError, match="still alive"):
        status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert fake_host.killed == []


def test_terminate_pid_identity_refusal_never_reaches_the_walk(status_win, fake_host):
    with pytest.raises(OSError, match="identity changed"):
        status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)) + 5)
    assert fake_host.snapshots == [] and fake_host.killed == []


def test_terminate_pid_unreadable_pin_on_a_gone_target_is_not_fatal(status_win, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: None)
    monkeypatch.setattr(status_win, "_pid_exists", lambda pid: False)
    status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert fake_host.snapshots == []


def test_terminate_pid_unreadable_pin_on_a_live_target_refuses(status_win, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: None)
    monkeypatch.setattr(status_win, "_pid_exists", lambda pid: True)
    with pytest.raises(OSError, match="creation time unreadable"):
        status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert fake_host.snapshots == []


def test_terminate_pid_walk_failure_surfaces_as_oserror(status_win, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, **kw: (_ for _ in ()).throw(RuntimeError("ctypes")))
    with pytest.raises(OSError, match="tree kill failed"):
        status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))


def test_terminate_pid_exited_root_that_is_gone_is_a_success(status_win, fake_host, monkeypatch):
    """The exited-pid shape: no snapshot row for the root; the target is gone; nothing else dies."""
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: None)
    status_win.terminate_pid(100, force=True, expected_start_time=int(round(ROOT_BORN * 100)))
    assert fake_host.killed == []


# --- site 3: tools/process_registry.py::_terminate_host_pid ------------------------


@pytest.fixture
def registry_win(monkeypatch, win32):
    from tools import process_registry as pr

    monkeypatch.setattr(pr, "_IS_WINDOWS", True)
    monkeypatch.setattr(pr.ProcessRegistry, "_host_pid_is_ours", classmethod(lambda cls, pid, exp: True))
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: ROOT_BORN)
    _no_spawn_on(monkeypatch, pr.subprocess, compat.subprocess)
    return pr


def test_terminate_host_pid_walks_pinned_and_refuses_the_orphans(registry_win, fake_host):
    registry_win.ProcessRegistry._terminate_host_pid(100, expected_start=int(round(ROOT_BORN * 100)))
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_terminate_host_pid_mutant_without_the_guard_adopts_the_services(registry_win, fake_host, mutant):
    registry_win.ProcessRegistry._terminate_host_pid(100, expected_start=int(round(ROOT_BORN * 100)))
    assert ORPHANS <= set(fake_host.killed)


def test_terminate_host_pid_pins_the_identity_read_before_the_ownership_probe(registry_win, fake_host, monkeypatch):
    """A pid recycled after ``_host_pid_is_ours`` passed: the walk is pinned to the
    creation time read before the probe, the snapshot's root no longer matches, nothing dies."""
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: STRANGER_BORN)
    registry_win.ProcessRegistry._terminate_host_pid(100, expected_start=int(round(ROOT_BORN * 100)))
    assert fake_host.killed == []


def test_terminate_host_pid_legacy_checkpoint_without_a_baseline_is_still_pinned(registry_win, fake_host):
    """``expected_start=None`` (no ``/proc``, legacy checkpoint) used to be a bare ``taskkill /T``."""
    registry_win.ProcessRegistry._terminate_host_pid(100)
    assert fake_host.killed == [300, 200, 100] and fake_host.snapshots == [100]


def test_terminate_host_pid_refused_by_the_probe_never_reaches_the_walk(registry_win, fake_host, monkeypatch):
    monkeypatch.setattr(registry_win.ProcessRegistry, "_host_pid_is_ours", classmethod(lambda cls, pid, exp: False))
    registry_win.ProcessRegistry._terminate_host_pid(100, expected_start=1)
    assert fake_host.snapshots == [] and fake_host.killed == []


def test_terminate_host_pid_unreadable_identity_kills_nothing(registry_win, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_process_created", lambda pid: None)
    registry_win.ProcessRegistry._terminate_host_pid(100)
    assert fake_host.snapshots == [] and fake_host.killed == []


def test_terminate_host_pid_walk_failure_falls_back_to_a_root_only_sigterm(registry_win, monkeypatch):
    sigterms = []
    monkeypatch.setattr(registry_win.os, "kill", lambda pid, sig: sigterms.append(pid))
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, **kw: (_ for _ in ()).throw(OSError("ctypes")))
    registry_win.ProcessRegistry._terminate_host_pid(100)
    assert sigterms == [100]


# --- site 4: session_bridge/cli.py and claude_registrar.py -----------------------------


@pytest.fixture
def bridge(monkeypatch, win32):
    from session_bridge import cli as bridge_cli
    from session_bridge import claude_registrar as registrar

    _no_spawn_on(monkeypatch, bridge_cli.subprocess, compat.subprocess)
    return SimpleNamespace(cli=bridge_cli, registrar=registrar)


def test_bridge_kill_process_tree_walks_and_refuses_the_orphans(bridge, fake_host):
    assert bridge.cli._kill_process_tree(100) is True
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_bridge_kill_process_tree_mutant_without_the_guard_adopts_the_services(bridge, fake_host, mutant):
    bridge.cli._kill_process_tree(100)
    assert ORPHANS <= set(fake_host.killed)


def test_bridge_kill_process_tree_on_an_exited_pid_is_false_and_kills_nothing(bridge, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: None)
    assert bridge.cli._kill_process_tree(100) is False
    assert fake_host.killed == []


def test_bridge_kill_process_tree_helper_failure_is_false_never_a_raise(bridge, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, **kw: (_ for _ in ()).throw(RuntimeError("ctypes")))
    assert bridge.cli._kill_process_tree(100) is False


class _ImmortalPty:
    """A PTY child that ignores terminate() and stays alive; the escalation target."""

    exitstatus = None

    def __init__(self, pid=100):
        self.pid = pid
        self.terminate_calls = 0

    def terminate(self, force: bool = False) -> bool:
        self.terminate_calls += 1
        return False

    def isalive(self) -> bool:
        return True


def test_winpty_terminate_escalates_to_the_guarded_walk_and_refuses_the_orphans(bridge, fake_host):
    result = bridge.registrar._WinPtyProcess(_ImmortalPty()).terminate(0.05)
    assert result is False  # still alive afterwards -- truthfully reported
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_winpty_terminate_mutant_without_the_guard_adopts_the_services(bridge, fake_host, mutant):
    bridge.registrar._WinPtyProcess(_ImmortalPty()).terminate(0.05)
    assert ORPHANS <= set(fake_host.killed)


def test_winpty_terminate_without_a_pid_never_walks(bridge, fake_host):
    assert bridge.registrar._WinPtyProcess(_ImmortalPty(pid=None)).terminate(0.05) is False
    assert fake_host.snapshots == []


def test_reclaim_unadapted_process_escalates_to_the_guarded_walk(bridge, fake_host):
    bridge.registrar._reclaim_unadapted_process(_ImmortalPty(), timeout=0.05)
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_reclaim_unadapted_process_mutant_without_the_guard_adopts_the_services(bridge, fake_host, mutant):
    bridge.registrar._reclaim_unadapted_process(_ImmortalPty(), timeout=0.05)
    assert ORPHANS <= set(fake_host.killed)


def test_registrar_quiet_kill_is_false_off_windows_and_on_helper_failure(bridge, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert bridge.registrar._windows_kill_tree_quietly(100) is False
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, **kw: (_ for _ in ()).throw(RuntimeError("ctypes")))
    assert bridge.registrar._windows_kill_tree_quietly(100) is False


# --- site 5: tools/browser_tool_lifecycle.py::_legacy_kill_process_tree --------------


@pytest.fixture
def lifecycle(monkeypatch, win32):
    from tools import browser_tool_lifecycle

    _no_spawn_on(monkeypatch, browser_tool_lifecycle.subprocess, compat.subprocess)
    return browser_tool_lifecycle


def test_browser_legacy_kill_walks_the_held_popen_and_refuses_the_orphans(lifecycle, fake_host):
    proc = _FakeProc()
    lifecycle._legacy_kill_process_tree(proc)
    assert fake_host.killed == [300, 200, 100] and proc.killed
    assert not ORPHANS & set(fake_host.killed)


def test_browser_legacy_kill_mutant_without_the_guard_adopts_the_services(lifecycle, fake_host, mutant):
    lifecycle._legacy_kill_process_tree(_FakeProc())
    assert ORPHANS <= set(fake_host.killed)


def test_browser_legacy_kill_on_an_exited_popen_kills_nothing(lifecycle, fake_host):
    proc = _FakeProc(returncode=0)
    lifecycle._legacy_kill_process_tree(proc)
    assert fake_host.killed == [] and fake_host.snapshots == []


def test_browser_legacy_kill_helper_failure_never_raises(lifecycle, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_popen_tree", lambda proc, tree=None: (_ for _ in ()).throw(OSError("ctypes")))
    lifecycle._legacy_kill_process_tree(_FakeProc())  # must not raise


# --- site 6: tools/tts_command_provider.py::terminate_command_process_tree ------------


@pytest.fixture
def tts(monkeypatch, win32):
    from tools import tts_command_provider

    _no_spawn_on(monkeypatch, tts_command_provider.subprocess, compat.subprocess)
    return tts_command_provider


def test_tts_terminate_walks_the_held_popen_and_refuses_the_orphans(tts, fake_host):
    proc = _FakeProc()
    tts.terminate_command_process_tree(proc)
    assert fake_host.killed == [300, 200, 100] and proc.killed
    assert not ORPHANS & set(fake_host.killed)


def test_tts_terminate_mutant_without_the_guard_adopts_the_services(tts, fake_host, mutant):
    tts.terminate_command_process_tree(_FakeProc())
    assert ORPHANS <= set(fake_host.killed)


def test_tts_terminate_on_an_exited_popen_kills_nothing(tts, fake_host):
    proc = _FakeProc(returncode=1)
    tts.terminate_command_process_tree(proc)
    assert fake_host.snapshots == [] and not proc.killed


# --- site 7: plugins/platforms/whatsapp/adapter.py::_terminate_bridge_process ---------


@pytest.fixture
def whatsapp(monkeypatch, win32):
    adapter = pytest.importorskip("plugins.platforms.whatsapp.adapter")
    monkeypatch.setattr(adapter, "_IS_WINDOWS", True)
    _no_spawn_on(monkeypatch, adapter.subprocess, compat.subprocess)
    return adapter


def test_whatsapp_force_walks_the_held_popen_and_refuses_the_orphans(whatsapp, fake_host):
    proc = _FakeProc()
    whatsapp._terminate_bridge_process(proc, force=True)
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_whatsapp_force_mutant_without_the_guard_adopts_the_services(whatsapp, fake_host, mutant):
    whatsapp._terminate_bridge_process(_FakeProc(), force=True)
    assert ORPHANS <= set(fake_host.killed)


def test_whatsapp_graceful_branch_walks_too_but_never_raises_on_a_miss(whatsapp, fake_host, monkeypatch):
    """Windows has no soft signal, so the graceful branch is the same guarded walk; only
    ``force`` verifies and raises."""
    proc = _FakeProc()
    whatsapp._terminate_bridge_process(proc, force=False)
    assert fake_host.killed == [300, 200, 100] and not ORPHANS & set(fake_host.killed)
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: [compat.ProcessRecord(999, 1, ROOT_BORN)])
    whatsapp._terminate_bridge_process(_FakeProc(), force=False)  # a miss is quiet here


def test_whatsapp_walk_failure_falls_back_to_the_root_only_primitive(whatsapp, monkeypatch):
    monkeypatch.setattr(compat, "windows_kill_popen_tree", lambda proc, tree=None: (_ for _ in ()).throw(OSError("ctypes")))
    soft, hard = _FakeProc(), _FakeProc()
    whatsapp._terminate_bridge_process(soft, force=False)
    whatsapp._terminate_bridge_process(hard, force=True)
    assert soft.terminated and not soft.killed and hard.killed and not hard.terminated


def test_whatsapp_force_that_misses_a_live_bridge_raises_oserror(whatsapp, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: [compat.ProcessRecord(999, 1, ROOT_BORN)])
    with pytest.raises(OSError, match="did not reach bridge"):
        whatsapp._terminate_bridge_process(_FakeProc(), force=True)


def test_whatsapp_force_on_an_exited_bridge_is_quiet(whatsapp, fake_host):
    whatsapp._terminate_bridge_process(_FakeProc(returncode=0), force=True)  # nothing to raise about
    assert fake_host.snapshots == []


# --- site 8: tui_gateway/host_supervisor.py::_force_kill_pid ------------------------


@pytest.fixture
def supervisor(monkeypatch, win32):
    from tui_gateway import host_supervisor as hs

    _no_spawn_on(monkeypatch, hs.subprocess, compat.subprocess)
    return hs


def test_supervisor_force_kill_walks_and_refuses_the_orphans(supervisor, fake_host):
    assert supervisor._force_kill_pid(100) is True
    assert fake_host.killed == [300, 200, 100]
    assert not ORPHANS & set(fake_host.killed)


def test_supervisor_force_kill_mutant_without_the_guard_adopts_the_services(supervisor, fake_host, mutant):
    supervisor._force_kill_pid(100)
    assert ORPHANS <= set(fake_host.killed)


def test_supervisor_force_kill_on_an_exited_pid_is_false(supervisor, fake_host, monkeypatch):
    monkeypatch.setattr(compat, "windows_tree_snapshot", lambda root_pid: None)
    assert supervisor._force_kill_pid(100) is False
    assert fake_host.killed == []


# --- site 9: evals/browser_use/orchestrate.py (a script; its helpers are exec'd) --------

_ORCHESTRATE = _REPO / "evals" / "browser_use" / "orchestrate.py"


def _orchestrate_helpers(monkeypatch, *, platform: str, popen=None):
    """Compile just the process helpers out of the script (argparse runs at import)."""
    tree = ast.parse(_ORCHESTRATE.read_text(encoding="utf-8"))
    wanted = {"_spawn_cell", "_kill_cell", "reset_browser_state"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "_last_cell" for t in n.targets)]
    assert {n.name for n in nodes if isinstance(n, ast.FunctionDef)} == wanted
    calls = SimpleNamespace(killed=[], closed=[], captured=[], run=[], killpg=[])

    def _run(argv, **kwargs):
        calls.run.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_subprocess = SimpleNamespace(
        run=_run, Popen=popen, PIPE=-1, CREATE_NEW_PROCESS_GROUP=0x200, TimeoutExpired=Exception)
    fake_os = SimpleNamespace(killpg=lambda pid, sig: calls.killpg.append(pid), path=os.path, environ={})
    ns = {
        "sys": SimpleNamespace(platform=platform, executable=sys.executable),
        "os": fake_os,
        "subprocess": fake_subprocess,
        "signal": SimpleNamespace(SIGKILL=9),
        "ENV": {},
        "windows_kill_popen_tree": lambda proc, tree=None: calls.killed.append((proc, tree)) or [],
        "windows_job_close": lambda job: calls.closed.append(job),
        "windows_suspended_spawn_flag": lambda: 0x4,
        "windows_tree_capture": lambda proc, suspended=False: calls.captured.append((proc, suspended))
        or compat.WindowsProcessTree(job=0x99, root_created=ROOT_BORN),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(_ORCHESTRATE), "exec"), ns)
    return ns, calls


def test_orchestrate_reset_kills_only_the_cell_it_spawned_by_job_membership(monkeypatch):
    ns, calls = _orchestrate_helpers(monkeypatch, platform="win32")
    proc = _FakeProc()
    tree = compat.WindowsProcessTree(job=0x99, root_created=ROOT_BORN)
    ns["_last_cell"] = (proc, tree)
    ns["reset_browser_state"]()
    assert calls.killed == [(proc, tree)] and proc.killed
    assert calls.closed == [0x99]
    assert ns["_last_cell"] is None
    # The only spawn left on the reset path is the cookie clear -- never a kill by image name.
    assert [argv[0] for argv in calls.run] == ["browser-use"]


def test_orchestrate_reset_with_no_previous_cell_kills_nothing(monkeypatch):
    ns, calls = _orchestrate_helpers(monkeypatch, platform="win32")
    ns["reset_browser_state"]()
    assert calls.killed == [] and calls.closed == []


def test_orchestrate_spawns_the_cell_frozen_and_captures_its_job(monkeypatch):
    spawned = []

    class _Popen:
        def __init__(self, argv, **kwargs):
            spawned.append(kwargs)
            self.pid = 100
            self._handle = 0x50

    ns, calls = _orchestrate_helpers(monkeypatch, platform="win32", popen=_Popen)
    proc, tree = ns["_spawn_cell"](["single_run.py"], env={})
    assert spawned[0]["creationflags"] == 0x200 | 0x4
    assert calls.captured == [(proc, True)] and tree.job == 0x99


def test_orchestrate_posix_kill_is_scoped_to_the_cells_own_session(monkeypatch):
    ns, calls = _orchestrate_helpers(monkeypatch, platform="linux")
    proc = _FakeProc(pid=4242)
    ns["_kill_cell"](proc, None)
    assert calls.killpg == [4242] and proc.killed and calls.run == []


# --- site 10: optional-skills/finance/excel-author/scripts/recalc.py -----------------------

_RECALC = _REPO / "optional-skills" / "finance" / "excel-author" / "scripts" / "recalc.py"


@pytest.fixture(scope="module")
def recalc():
    spec = importlib.util.spec_from_file_location("excel_author_recalc_treekill", _RECALC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recalc_tree_kill_terminates_by_job_membership_and_never_spawns(recalc, monkeypatch):
    monkeypatch.setattr(recalc, "_IS_WINDOWS", True)
    _no_spawn_on(monkeypatch, recalc.subprocess)
    terminated = []
    monkeypatch.setattr(recalc, "_windows_job_terminate", lambda job: terminated.append(job) or True)
    proc = _FakeProc()
    recalc._tree_kill(proc, 0x77)
    assert terminated == [0x77] and not proc.killed


def test_recalc_tree_kill_without_a_job_kills_only_the_launcher_it_holds(recalc, monkeypatch):
    """No membership to stand on: the launcher is the only process provably ours."""
    monkeypatch.setattr(recalc, "_IS_WINDOWS", True)
    _no_spawn_on(monkeypatch, recalc.subprocess)
    proc = _FakeProc()
    recalc._tree_kill(proc, None)
    assert proc.killed


def test_recalc_tree_kill_falls_back_to_the_launcher_when_the_job_kill_fails(recalc, monkeypatch):
    monkeypatch.setattr(recalc, "_IS_WINDOWS", True)
    monkeypatch.setattr(recalc, "_windows_job_terminate", lambda job: False)
    proc = _FakeProc()
    recalc._tree_kill(proc, 0x77)
    assert proc.killed


def test_recalc_job_helpers_leave_a_popen_without_a_handle_alone(recalc):
    class _Stub:
        pid = 100

    assert recalc._windows_job_for(_Stub()) is None


@pytest.mark.windows_only
@pytest.mark.timeout(scaled(120))
def test_recalc_timeout_reaps_the_grandchild_it_spawned(recalc, tmp_path):
    """Live, on processes this test spawned: the wedged grandchild (the ``soffice.bin``
    shape) is dead shortly after the timeout, by job membership -- no walk, no taskkill."""
    import psutil

    pid_file = tmp_path / "grandchild.pid"
    wedged = tmp_path / "wedged.py"
    wedged.write_text(
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    grandchild = None
    try:
        with pytest.raises(recalc.subprocess.TimeoutExpired):
            # Incidental start window (tests/timeout_budget rule 2): the wedged child and its
            # grandchild are two cold interpreter starts; 3 s was not enough under load.
            recalc._run_captured([sys.executable, str(wedged)], timeout=scaled(10))
        assert pid_file.exists(), "the wedged child never started its grandchild"
        grandchild = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and psutil.pid_exists(grandchild):
            time.sleep(0.1)
        assert not psutil.pid_exists(grandchild), "grandchild outlived the job kill"
    finally:
        if grandchild is not None and psutil.pid_exists(grandchild):  # pragma: no cover - our own leak
            try:
                psutil.Process(grandchild).kill()
            except Exception:
                pass


# --- source contract: taskkill /T and /IM stay out of every fixed site --------------------


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
    "cron/scheduler_script.py",
    "gateway/status.py",
    "tools/process_registry.py",
    "session_bridge/cli.py",
    "session_bridge/claude_registrar.py",
    "tools/browser_tool_lifecycle.py",
    "tools/tts_command_provider.py",
    "plugins/platforms/whatsapp/adapter.py",
    "tui_gateway/host_supervisor.py",
    "evals/browser_use/orchestrate.py",
    "optional-skills/finance/excel-author/scripts/recalc.py",
])
def test_no_taskkill_tree_argv_in_the_fixed_sites(rel):
    words = _argv_words(_REPO / rel)
    assert "/T" not in words and "/IM" not in words, rel
    # The whatsapp port sweep kept a single-pid ``taskkill /F`` after an identity check until
    # 2026-09-18 (7-9 s per spawn at 100% CPU); the binary is now gone from every site.
    assert "taskkill" not in words, rel
