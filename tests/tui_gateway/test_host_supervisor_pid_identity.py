"""Pid identity, orphan reconciliation and force-kill for the compute-host supervisor.

These cover three defects measured on Windows 2026-09-14 (loops
``host-supervisor-trampoline-pid-audit-20260914``):

* ``_pid_command`` had no Windows branch, so ``is_compute_host_identity`` was False for EVERY pid
  and ``reconcile_startup_orphan`` never reaped anything;
* ``_terminate_pid`` named ``signal.SIGKILL``, undefined on win32, raising out of ``start()``;
* the registry recorded only the spawned ``argv[0]`` pid, which under a uv-trampoline venv is a
  stub launcher rather than the interpreter running the host.

The first two masked each other: the identity probe short-circuited before the crash could fire.
So every probe here runs against a REAL process with a KNOWN-POSITIVE control -- asserting the
outcome string alone is what let the original defect sit behind a green test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from tui_gateway import host_supervisor as hs
from tui_gateway.host_supervisor import HostSupervisor

MARKER = "tui_gateway.compute_host"
_SLEEP = "import time; time.sleep(30)"


def _spawn(*extra_argv: str) -> subprocess.Popen:
    """A real, live process whose command line carries ``extra_argv``."""
    return subprocess.Popen([sys.executable, "-c", _SLEEP, *extra_argv],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


@pytest.fixture
def live_procs():
    """Register spawned processes so a failing assertion cannot strand one."""
    procs: list[subprocess.Popen] = []
    yield procs.append
    for proc in procs:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def _wait_dead(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not hs._pid_alive(pid):
            return True
        time.sleep(0.05)
    return not hs._pid_alive(pid)


def _supervisor(tmp_path, registry: dict):
    path = tmp_path / "dashboard-compute-host.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    supervisor = HostSupervisor(registry_path=path, argv=[sys.executable, "-c", ""],
                                autostart=False)
    return supervisor, path


# --------------------------------------------------------------------------- probes

def test_pid_command_reads_a_command_line_on_this_platform():
    """KNOWN-POSITIVE CONTROL. Before the psutil branch this returned "" on Windows -- silently,
    because ``_check_output`` suppresses every failure. A probe that can only fail closed makes
    every caller's negative result meaningless, so pin that it can produce a positive at all."""
    command = hs._pid_command(os.getpid())
    assert command, "_pid_command cannot read ANY command line on this platform"
    assert "python" in command.lower()


def test_pid_command_rejects_nonsense_pids():
    assert hs._pid_command(0) == ""
    assert hs._pid_command(-1) == ""


def test_identity_distinguishes_a_compute_host_from_a_stranger(live_procs):
    """Both directions against real processes: the negative alone is satisfied by a dead probe."""
    host_like = _spawn(MARKER)
    live_procs(host_like)
    stranger = _spawn("unrelated-workload")
    live_procs(stranger)

    assert hs.is_compute_host_identity(host_like.pid) is True
    assert hs.is_compute_host_identity(stranger.pid) is False


def test_pid_alive_does_not_signal_the_process_it_probes(live_procs):
    """``os.kill(pid, 0)`` is ``CTRL_C_EVENT`` on Windows (bpo-14484). Measured: 1 of 3 identical
    trials against a ``start_new_session=True`` child exited ``0xC000013A``
    (STATUS_CONTROL_C_EXIT), so this is INTERMITTENT -- probe repeatedly, and read a single green
    run as weak. A liveness check must not be able to interrupt its target."""
    proc = _spawn("liveness-probe-target")
    live_procs(proc)

    for _ in range(3):
        assert hs._pid_alive(proc.pid) is True
    time.sleep(0.5)
    assert proc.poll() is None, "_pid_alive killed the process it was asked about"


def test_pid_alive_reports_a_dead_pid_as_dead():
    proc = _spawn("soon-dead")
    proc.kill()
    proc.wait(timeout=10)
    assert _wait_dead(proc.pid)


# --------------------------------------------------------------------------- force kill

def test_force_kill_pid_kills_a_real_process_without_sigkill(live_procs):
    """REGRESSION: ``signal.SIGKILL`` is undefined on win32, so the escalation used to raise
    AttributeError instead of killing. Exercises the real helper on the real platform."""
    proc = _spawn("force-kill-target")
    live_procs(proc)

    assert hs._force_kill_pid(proc.pid) is True
    assert _wait_dead(proc.pid), "force kill did not take the process down"


def test_force_kill_pid_survives_a_pid_that_is_already_gone():
    proc = _spawn("already-gone")
    proc.kill()
    proc.wait(timeout=10)
    hs._force_kill_pid(proc.pid)  # must not raise on any platform


def test_terminate_pid_escalates_without_raising(monkeypatch, tmp_path):
    """The crash was at ARGUMENT EVALUATION of ``signal.SIGKILL``, before ``_signal_pid``'s own
    ``try``, so stubbing _signal_pid was never enough to hide it -- which is why this pins the
    escalation call rather than the kill itself."""
    escalated: list[int] = []
    monkeypatch.setattr(hs, "_signal_pid", lambda *_a, **_kw: True)
    monkeypatch.setattr(hs, "_pid_alive", lambda _pid: True)  # never dies -> deadline trips
    monkeypatch.setattr(hs, "_force_kill_pid", lambda pid: escalated.append(pid) or True)

    supervisor = HostSupervisor(registry_path=tmp_path / "r.json",
                                argv=[sys.executable, "-c", ""], autostart=False)
    supervisor._terminate_pid(4242, timeout=0.05)

    assert escalated == [4242]


def test_terminate_pid_returns_early_when_sigterm_finds_nothing(monkeypatch, tmp_path):
    """Control for the test above: with no process to signal, the escalation must NOT run."""
    escalated: list[int] = []
    monkeypatch.setattr(hs, "_signal_pid", lambda *_a, **_kw: False)
    monkeypatch.setattr(hs, "_force_kill_pid", lambda pid: escalated.append(pid) or True)

    supervisor = HostSupervisor(registry_path=tmp_path / "r.json",
                                argv=[sys.executable, "-c", ""], autostart=False)
    supervisor._terminate_pid(4242, timeout=0.05)

    assert escalated == []


# --------------------------------------------------------------------------- reconciliation

def test_reconcile_terminates_a_surviving_compute_host(tmp_path, live_procs):
    """The branch the pre-existing suite never reached. On Windows the identity probe returned ""
    for every pid, so this always came back ``pid-reuse-ignored`` and the orphan lived on."""
    orphan = _spawn(MARKER)
    live_procs(orphan)
    supervisor, path = _supervisor(tmp_path, {"host_pid": orphan.pid, "boot_id": "stale"})

    assert supervisor.reconcile_startup_orphan() == "terminated"
    assert _wait_dead(orphan.pid), "reconcile reported terminated but the host is still running"
    assert not path.exists()


def test_reconcile_still_refuses_a_recycled_pid(tmp_path, live_procs):
    """Unchanged guard, now meaningful: it must be the IDENTITY that rejects a live stranger, not
    a probe that fails closed for everyone."""
    stranger = _spawn("someones-browser")
    live_procs(stranger)
    supervisor, path = _supervisor(tmp_path, {"host_pid": stranger.pid, "boot_id": "stale"})

    assert supervisor.reconcile_startup_orphan() == "pid-reuse-ignored"
    time.sleep(0.5)
    assert stranger.poll() is None, "reconcile signalled a process that is not our host"
    assert not path.exists()


def test_reconcile_falls_back_to_host_os_pid_when_the_launcher_pid_was_recycled(
        tmp_path, live_procs):
    """Under a trampoline the two pids are different processes. If the launcher pid is recycled
    onto a stranger, the host is still reapable through the pid it reported for itself -- and it
    has to be, because reconcile deletes the registry on its way out either way."""
    stranger = _spawn("recycled-onto-a-stranger")
    live_procs(stranger)
    orphan = _spawn(MARKER)
    live_procs(orphan)
    supervisor, _path = _supervisor(
        tmp_path, {"host_pid": stranger.pid, "host_os_pid": orphan.pid, "boot_id": "stale"})

    assert supervisor.reconcile_startup_orphan() == "terminated"
    assert _wait_dead(orphan.pid)
    time.sleep(0.5)
    assert stranger.poll() is None, "the recycled pid was signalled"


def test_reconcile_handles_a_registry_without_host_os_pid(tmp_path):
    """Registries written before the field existed must keep working, not read 0 as a live pid."""
    supervisor, _path = _supervisor(tmp_path, {"host_pid": 0, "boot_id": "legacy"})
    assert supervisor.reconcile_startup_orphan() == "not-running"


def test_reconcile_reports_an_unreadable_registry(tmp_path):
    path = tmp_path / "dashboard-compute-host.json"
    path.write_text("{not json", encoding="utf-8")
    supervisor = HostSupervisor(registry_path=path, argv=[sys.executable, "-c", ""],
                                autostart=False)
    assert supervisor.reconcile_startup_orphan() == "invalid-registry"


def test_reconcile_reports_no_registry_at_all(tmp_path):
    supervisor = HostSupervisor(registry_path=tmp_path / "absent.json",
                                argv=[sys.executable, "-c", ""], autostart=False)
    assert supervisor.reconcile_startup_orphan() == "none"


# --------------------------------------------------------------------------- registry contents

def test_registry_records_both_the_signalling_pid_and_the_hosts_own_pid(tmp_path):
    path = tmp_path / "dashboard-compute-host.json"
    supervisor = HostSupervisor(registry_path=path, argv=[sys.executable, "-c", ""],
                                autostart=False)

    class _Proc:
        pid = 31337

    supervisor._proc = _Proc()
    supervisor._hello = {"host_pid": 4242, "boot_id": "b", "build_sha": "s"}
    supervisor._persist_registry()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["host_pid"] == 31337, "host_pid must stay the handle we can signal"
    assert payload["host_os_pid"] == 4242, "the host's own pid must be recorded for attribution"


def test_host_os_pid_is_zero_before_the_hello_handshake(tmp_path):
    supervisor = HostSupervisor(registry_path=tmp_path / "r.json",
                                argv=[sys.executable, "-c", ""], autostart=False)
    assert supervisor.host_os_pid == 0
    supervisor._hello = {"host_pid": "not-a-number"}
    assert supervisor.host_os_pid == 0
