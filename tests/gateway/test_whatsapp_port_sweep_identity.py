"""The bound-port ``--replace`` sweep: identity check, creation-time pin, no spawns.

On 2026-09-18 ``_kill_port_process(3000)`` measured 7.4 / 0.2 / 9.4 s at 100% CPU and once logged
"Not killing PID 28356 ... (or identity unverifiable)" against the live bridge. Reproduced on node
children the session spawned itself: the psutil identity primitives were 0.0-0.2 ms; the seconds
were the ``taskkill /F`` spawn (7.4 s, 8.7 s) and the netstat spawn the listener scan fell through to
on an empty psutil result (13 s for the first scan after a kill). The refusal was of a pid whose
LISTEN row outlived the process. These tests pin the shape that replaced it: a deterministic fake
psutil for every outcome of the identity check, the creation time read BEFORE the identity check and
passed to the pinned walk, no ``taskkill`` and no netstat on an empty Windows scan.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from hermes_cli import _subprocess_compat as compat
from plugins.platforms.whatsapp import adapter as wa


NODE_EXE = r"C:\Program Files\nodejs\node.exe"


class _FakeProc:
    """One psutil.Process stand-in: ``name``/``cmdline`` return, raise, or record."""

    instances: list = []

    def __init__(self, pid, *, name="node.exe", cmdline=(NODE_EXE, "bridge.js"), name_raises=None, cmdline_raises=None):
        self.pid = pid
        self._name, self._cmdline = name, list(cmdline)
        self._name_raises, self._cmdline_raises = name_raises, cmdline_raises
        self.calls: list = []

    class _Oneshot:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    def oneshot(self):
        self.calls.append("oneshot")
        return self._Oneshot()

    def name(self):
        self.calls.append("name")
        if self._name_raises:
            raise self._name_raises
        return self._name

    def cmdline(self):
        self.calls.append("cmdline")
        if self._cmdline_raises:
            raise self._cmdline_raises
        return self._cmdline


def _install(monkeypatch, factory):
    """``psutil.Process(pid)`` -> ``factory(pid)``; the real module keeps its exception classes."""
    made = []

    def _process(pid):
        proc = factory(pid)
        if isinstance(proc, BaseException):
            raise proc
        made.append(proc)
        return proc

    monkeypatch.setattr(psutil, "Process", _process)
    return made


# --- _pid_looks_like_node_bridge: every outcome, deterministic ---------------------------------


def test_node_executable_is_the_bridge_and_cmdline_is_never_consulted(monkeypatch):
    made = _install(monkeypatch, lambda pid: _FakeProc(pid, name="node.exe"))
    assert wa._pid_looks_like_node_bridge(456) is True
    assert made[0].calls == ["oneshot", "name"]


def test_argv0_with_spaces_in_the_path_is_recognised(monkeypatch):
    """The old first-whitespace-token parse read ``C:\\Program Files\\nodejs\\node.exe`` as ``C:\\Program``."""
    _install(monkeypatch, lambda pid: _FakeProc(pid, name="cmd.exe", cmdline=(NODE_EXE, "bridge.js")))
    assert wa._pid_looks_like_node_bridge(456) is True
    old_shape = " ".join([NODE_EXE, "bridge.js"]).lower().split(" ", 1)[0]
    assert "node" not in old_shape  # the shape the previous implementation compared


@pytest.mark.parametrize("name, cmdline", [
    ("python.exe", ["python", "server.py"]),
    ("svchost.exe", []),
    ("", []),
    ("chrome.exe", [r"C:\x\chrome.exe", "--app=http://localhost:3000"]),  # 'node' nowhere in argv[0]
])
def test_stranger_is_refused(monkeypatch, name, cmdline):
    _install(monkeypatch, lambda pid: _FakeProc(pid, name=name, cmdline=cmdline))
    assert wa._pid_looks_like_node_bridge(456) is False


@pytest.mark.parametrize("gone", [psutil.NoSuchProcess, psutil.ZombieProcess])
def test_exited_pid_is_refused_and_logged_as_gone_not_as_a_stranger(monkeypatch, caplog, gone):
    """The LISTEN row outlives the process by a moment; that refusal is the common one
    (``ZombieProcess`` is a ``NoSuchProcess`` in psutil: dead either way)."""
    _install(monkeypatch, lambda pid: gone(pid))
    with caplog.at_level(logging.DEBUG, logger=wa.logger.name):
        assert wa._pid_looks_like_node_bridge(456) is False
    assert any("exited before" in r.getMessage() for r in caplog.records)
    assert not any("unverifiable" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("exc", [
    psutil.AccessDenied(456),
    OSError(5, "boom"),
    RuntimeError("partial psutil"),
])
def test_unverifiable_identity_is_refused(monkeypatch, exc, caplog):
    _install(monkeypatch, lambda pid: _FakeProc(pid, name_raises=exc))
    with caplog.at_level(logging.DEBUG, logger=wa.logger.name):
        assert wa._pid_looks_like_node_bridge(456) is False
    assert any("unverifiable" in r.getMessage() for r in caplog.records)


def test_denied_name_but_readable_cmdline_still_refuses(monkeypatch):
    """A name lookup that raises never falls through to a cmdline guess."""
    _install(monkeypatch, lambda pid: _FakeProc(pid, name_raises=psutil.AccessDenied(456), cmdline=(NODE_EXE,)))
    assert wa._pid_looks_like_node_bridge(456) is False


def test_cmdline_raising_after_a_non_node_name_refuses(monkeypatch):
    _install(monkeypatch, lambda pid: _FakeProc(pid, name="cmd.exe", cmdline_raises=psutil.AccessDenied(456)))
    assert wa._pid_looks_like_node_bridge(456) is False


def test_missing_psutil_refuses(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)  # ``import psutil`` -> ImportError
    assert wa._pid_looks_like_node_bridge(456) is False


# --- _kill_port_process on Windows: pinned walk, no spawn ------------------------------------


@pytest.fixture
def win32(monkeypatch):
    monkeypatch.setattr(wa, "_IS_WINDOWS", True)
    run = Mock(side_effect=AssertionError("the port sweep spawned a process"))
    monkeypatch.setattr(wa.subprocess, "run", run)
    return run


@pytest.fixture
def host(monkeypatch):
    """Records the order of creation-time reads, identity checks and walks."""
    calls = SimpleNamespace(order=[], walks=[], created={456: 1789765314.239069}, identity={456: True})

    def _created(pid):
        calls.order.append(("created", pid))
        return calls.created.get(pid)

    def _identity(pid):
        calls.order.append(("identity", pid))
        return calls.identity.get(pid, False)

    def _walk(pid, *, root_created=None):
        calls.order.append(("walk", pid))
        calls.walks.append((pid, root_created))
        return [pid]

    monkeypatch.setattr(compat, "windows_process_created", _created)
    monkeypatch.setattr(compat, "windows_kill_process_tree", _walk)
    monkeypatch.setattr(wa, "_pid_looks_like_node_bridge", _identity)
    return calls


def test_bridge_listener_is_killed_through_the_pinned_walk(win32, host, monkeypatch):
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    wa._kill_port_process(9999)
    assert host.walks == [(456, 1789765314.239069)]
    win32.assert_not_called()


def test_creation_time_is_read_before_the_identity_check(win32, host, monkeypatch):
    """The pin must predate the check: a pid recycled between the two is refused by the walk."""
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    wa._kill_port_process(9999)
    assert host.order == [("created", 456), ("identity", 456), ("walk", 456)]


def test_unreadable_creation_time_refuses_even_a_node_listener(win32, host, monkeypatch, caplog):
    host.created.clear()
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    with caplog.at_level(logging.WARNING, logger=wa.logger.name):
        wa._kill_port_process(9999)
    assert host.walks == []
    assert any("creation time unreadable" in r.getMessage() for r in caplog.records)


def test_non_bridge_listener_is_never_walked(win32, host, monkeypatch, caplog):
    host.identity[456] = False
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    with caplog.at_level(logging.WARNING, logger=wa.logger.name):
        wa._kill_port_process(9999)
    assert host.walks == []
    assert any("not a node bridge" in r.getMessage() for r in caplog.records)


def test_a_walk_that_raises_does_not_abort_the_sweep(win32, host, monkeypatch):
    host.created[789] = 1789765400.0
    host.identity[789] = True
    seen = []

    def _walk(pid, *, root_created=None):
        seen.append(pid)
        if pid == 456:
            raise OSError("snapshot failed")
        return [pid]

    monkeypatch.setattr(compat, "windows_kill_process_tree", _walk)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456, 789])
    wa._kill_port_process(9999)
    assert seen == [456, 789]


def test_walk_missing_the_root_is_logged_not_raised(win32, host, monkeypatch, caplog):
    monkeypatch.setattr(compat, "windows_kill_process_tree", lambda pid, *, root_created=None: [])
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    with caplog.at_level(logging.INFO, logger=wa.logger.name):
        wa._kill_port_process(9999)
    assert any("left the walk untouched" in r.getMessage() for r in caplog.records)


def test_posix_branch_still_sigterms(monkeypatch, host):
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    kills = []
    monkeypatch.setattr(wa.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    wa._kill_port_process(9999)
    assert kills == [(456, wa.signal.SIGTERM)]
    assert host.walks == [] and ("created", 456) not in host.order


# --- _listener_pids_on_port: a completed Windows scan is the answer ---------------------------


def _conn(port, pid, status=psutil.CONN_LISTEN):
    return SimpleNamespace(status=status, laddr=SimpleNamespace(port=port), pid=pid)


def test_empty_windows_scan_never_spawns_netstat(monkeypatch):
    monkeypatch.setattr(wa, "_IS_WINDOWS", True)
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": [_conn(30000, 55555)])
    run = Mock(side_effect=AssertionError("netstat spawned on an empty psutil scan"))
    monkeypatch.setattr(wa.subprocess, "run", run)
    assert wa._listener_pids_on_port(3000) == []
    run.assert_not_called()


def test_windows_scan_that_raises_still_falls_back_to_netstat(monkeypatch):
    monkeypatch.setattr(wa, "_IS_WINDOWS", True)
    monkeypatch.setattr(psutil, "net_connections", Mock(side_effect=OSError("no table")))
    run = Mock(return_value=subprocess.CompletedProcess(
        [], 0, "  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       12345\n", ""))
    monkeypatch.setattr(wa.subprocess, "run", run)
    assert wa._listener_pids_on_port(3000) == [12345]
    assert run.call_args.args[0][0] == "netstat"


def test_empty_posix_scan_keeps_the_lsof_fallback(monkeypatch):
    """``/proc/net/tcp`` cannot attribute another user's socket; POSIX still asks lsof."""
    monkeypatch.setattr(wa, "_IS_WINDOWS", False)
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": [])
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "4242\n", ""))
    monkeypatch.setattr(wa.subprocess, "run", run)
    assert wa._listener_pids_on_port(3000) == [4242]
    assert run.call_args.args[0][0] == "lsof"


# --- source contract: no taskkill anywhere in the adapter ------------------------------------


def test_adapter_has_no_taskkill_argv():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(wa.__file__).read_text(encoding="utf-8"))
    words = {
        elt.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for arg in node.args
        if isinstance(arg, ast.List)
        for elt in arg.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert "taskkill" not in words
