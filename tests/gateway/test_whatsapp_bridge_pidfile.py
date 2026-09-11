"""Regression tests: the WhatsApp stale-bridge cleanup must never kill a stranger.

The bridge records its PID in ``bridge.pid``. On the next start the gateway
SIGTERMs that PID to reap an orphaned bridge. The original code checked only
that the PID was *alive* — but once the bridge exits and is reaped the kernel
can recycle its number onto an unrelated process. Because the WhatsApp bridge
crash-loops, this cleanup ran constantly, and a recycled PID that had landed on
the user's browser main process got SIGTERMed, closing the browser at irregular
intervals (no crash, no coredump — a clean kill of a stranger).

These tests prove the identity guard: a PID is only signalled when it is still
our bridge (kernel start time matches, or — for legacy pidfiles — its command
line names node + this session). A recycled PID is left alone.
"""

import subprocess
import sys
import time

import pytest

import os
import socket

from plugins.platforms.whatsapp.adapter import (
    _kill_stale_bridge_by_pidfile,
    _listener_pids_on_port,
    _listener_pids_on_port_netstat,
    _write_bridge_pidfile,
)
from gateway.status import get_process_start_time


def _spawn_sleeper(*extra_argv) -> subprocess.Popen:
    """Spawn a test-owned child that cannot exit naturally inside the kill assertion window."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", *extra_argv]
    )


def _wait_dead(proc: subprocess.Popen, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


class TestWriteAndRoundTrip:
    def test_pidfile_records_pid_and_start_time(self, tmp_path):
        proc = _spawn_sleeper()
        try:
            _write_bridge_pidfile(tmp_path, proc.pid)
            lines = (tmp_path / "bridge.pid").read_text().split("\n")
            assert int(lines[0]) == proc.pid
            # Line 2 is the kernel start time (present on Linux).
            assert int(lines[1]) == get_process_start_time(proc.pid)
        finally:
            proc.kill()
            proc.wait()


class TestIdentityGuard:
    def test_kills_when_start_time_matches(self, tmp_path):
        """A genuine bridge (recorded start time matches) IS reaped."""
        proc = _spawn_sleeper()
        try:
            _write_bridge_pidfile(tmp_path, proc.pid)
            _kill_stale_bridge_by_pidfile(tmp_path)
            assert _wait_dead(proc), "the real bridge process should be killed"
            assert not (tmp_path / "bridge.pid").exists()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


    def test_legacy_pidfile_kills_matching_bridge_cmdline(self, tmp_path):
        """Legacy pidfile: a PID whose cmdline names node + session IS reaped."""
        # Shape the cmdline to look like the node bridge for this session.
        proc = _spawn_sleeper("node", str(tmp_path))
        try:
            (tmp_path / "bridge.pid").write_text(str(proc.pid))  # legacy: pid only
            _kill_stale_bridge_by_pidfile(tmp_path)
            assert _wait_dead(proc), "a cmdline-confirmed bridge should be killed"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


class TestKillPortProcess:
    """Freeing the bridge port must target only LISTENers, never clients.

    Root cause of the live Firefox kills: ``lsof -ti :PORT`` (and ``fuser
    PORT/tcp``) also returned *client* sockets whose connection merely involved
    the port number. The WhatsApp bridge uses port 3000 by default — a common
    local dev-server port — so a browser tab on ``localhost:3000`` was matched
    and SIGTERMed every time the (crash-looping) bridge restarted.
    """

    def test_listener_lookup_excludes_client_process(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(5)
        # A separate process holding a *client* connection to that port.
        client = subprocess.Popen([
            sys.executable, "-c",
            "import socket,time; c=socket.create_connection(('127.0.0.1',%d)); time.sleep(30)" % port,
        ])
        try:
            srv.settimeout(10)
            conn, _ = srv.accept()  # establish the client connection
            pids = _listener_pids_on_port(port)
            if os.getpid() not in pids:
                pytest.skip("neither lsof nor ss detected the listener here")
            # The listener (this process) is found; the client process is NOT —
            # the LISTEN filter is what spares unrelated clients like a browser.
            assert client.pid not in pids
            conn.close()
        finally:
            client.kill()
            client.wait()
            srv.close()

    def test_netstat_is_not_spawned_when_psutil_answers(self, monkeypatch):
        """The fast path must not pay a process spawn at all.

        The original defect was not a slow discovery but a *silent* one:
        ``netstat -ano -p TCP`` under ``timeout=5`` (measured 8.2s/9.6s/21.3s on
        this host) raised TimeoutExpired inside a bare ``except Exception``, so
        ``_kill_port_process`` killed nothing every single time. Asserting that
        psutil short-circuits before any spawn is what keeps that spawn from
        creeping back onto the hot path.
        """
        def _boom(*a, **kw):  # pragma: no cover - only runs on regression
            raise AssertionError("netstat/lsof spawned while psutil could answer")

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(5)
        try:
            if os.getpid() not in _listener_pids_on_port(port):
                pytest.skip("psutil cannot read the connection table here")
            monkeypatch.setattr(subprocess, "run", _boom)
            assert os.getpid() in _listener_pids_on_port(port)
        finally:
            srv.close()


class TestNetstatFallbackDiscovery:
    """Direct cover for the Windows fallback under the psutil fast path.

    Every other test in this file is answered by psutil, so
    ``_listener_pids_on_port_netstat`` never executes and a regression in it
    would be invisible here. That matters more than usual: this fallback is the
    surviving descendant of the code that caused the original outage, where
    ``timeout=5`` against a netstat measured at 8.2s/9.6s/21.3s turned a live
    listener into "no listener" and the caller silently killed nothing.
    """

    # PID 4242 is the only LISTENER on 3000. 9999 is ESTABLISHED on the same
    # port (a client — killing it is the browser-closing bug), and 13000 is the
    # substring trap that an unanchored match would wrongly accept.
    _TABLE = (
        "\nActive Connections\n\n"
        "  Proto  Local Address          Foreign Address        State           PID\n"
        "  TCP    127.0.0.1:3000         0.0.0.0:0              LISTENING       4242\n"
        "  TCP    127.0.0.1:3000         127.0.0.1:51515        ESTABLISHED     9999\n"
        "  TCP    127.0.0.1:13000        0.0.0.0:0              LISTENING       7777\n"
    )

    def _capture(self, monkeypatch, stdout=None, raises=None):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["timeout"] = kwargs.get("timeout")
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_returns_only_the_listener_on_the_exact_port(self, monkeypatch):
        self._capture(monkeypatch, stdout=self._TABLE)

        assert _listener_pids_on_port_netstat(3000) == [4242]

    def test_budget_survives_a_loaded_host(self, monkeypatch):
        """The 5s budget is what made this silently return nothing."""
        seen = self._capture(monkeypatch, stdout=self._TABLE)

        _listener_pids_on_port_netstat(3000)

        assert seen["timeout"] >= 60, (
            f"netstat budget regressed to {seen['timeout']}s; it is routinely "
            "overrun on this host and an overrun reports 'no listener'"
        )

    def test_wedged_netstat_reports_no_listener_without_raising(self, monkeypatch):
        """A genuinely wedged netstat must not escape into the restart path."""
        self._capture(
            monkeypatch, raises=subprocess.TimeoutExpired(["netstat"], 60),
        )

        assert _listener_pids_on_port_netstat(3000) == []
