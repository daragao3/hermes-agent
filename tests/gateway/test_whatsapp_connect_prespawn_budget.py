"""The first WhatsApp connect after a ``--replace`` must spawn bridge.js before the runner's budget can cancel it.

Observed 2026-09-18 (evidence/agent-src-acceptance-20260918c/reload.json, ``platform_reconnect_note``): after
the ceremony's ``--replace`` to 715097981e on a host at 100% CPU, connect attempts 1-5 (15:34-15:48Z) all
ended in "whatsapp connect timed out after 30s" with NO node process ever created. The gateway log shows
each attempt spending 9-19 s before ``_preflight``'s "Bridge found at" line (a ``node --version`` spawn on a
loop other tasks were also blocking) and the 30 s timer firing 40-48 s after the attempt began; the
cancellation then landed at the first await — ``_reuse_running_bridge``'s health probe — with ``Popen``
still ahead. Attempt 6 connected in 22 s once the host eased.

Three changes, each pinned here as a code path (never a wall-clock):

* ``_port_is_free`` (one bind on 127.0.0.1:port) gates the adopt/kill/release probes: with the port free
  there is nothing to adopt, kill or wait for, and the path from ``connect()`` to ``Popen`` has no await
  left for a late cancellation to land on.
* ``check_whatsapp_requirements`` caches a node binary that answered ``--version`` (keyed by path, size,
  mtime) so the next attempt in the same process does not pay the spawn again.
* ``WhatsAppAdapter.connect_timeout_secs`` declares the budget its own phases need (90 s); the runner
  honours it in place of the 30 s platform default, still under the env override.

Mutant checks (each reverts one change; the named test goes red):
  - drop the ``if not _port_is_free(...)`` gate in ``connect()``  -> TestPortGate, TestSlowProbes
  - drop ``_node_probe_ok.add(...)``                                 -> TestNodeProbeCache
  - drop ``adapter=adapter`` / the declared lookup in the runner    -> TestDeclaredBudget
"""

import asyncio
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.run import GatewayRunner
from plugins.platforms.whatsapp import adapter as wa


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _adapter(tmp_path, monkeypatch, trace):
    """A real adapter whose every pre-spawn seam is stubbed and traced; ``Popen`` records "spawn"."""
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "session_path": str(tmp_path / "session"), "bridge_script": str(tmp_path / "bridge.js"),
        "bridge_port": _free_port()}))
    for name in ["_preflight", "_ensure_bridge_deps", "_acquire_platform_lock"]:
        monkeypatch.setattr(adapter, name, Mock(return_value=True))

    async def reuse(bridge_path):
        trace.append("reuse")
        await asyncio.sleep(0.01)  # the real probe awaits the network: a late cancellation lands HERE
        return False

    async def wait(port):
        trace.append("wait")
        return True

    monkeypatch.setattr(adapter, "_reuse_running_bridge", reuse)
    monkeypatch.setattr(wa, "_kill_stale_bridge_by_pidfile", lambda path: trace.append("pidfile"))
    monkeypatch.setattr(wa, "_kill_port_process", lambda port: trace.append("kill"))
    monkeypatch.setattr(wa, "_wait_for_port_release", wait)
    monkeypatch.setattr(wa, "_rotate_bridge_log_if_large", lambda path: None)
    monkeypatch.setattr(wa.subprocess, "Popen", lambda *a, **k: (trace.append("spawn"), SimpleNamespace(pid=456))[1])
    monkeypatch.setattr(wa, "_write_bridge_pidfile", Mock())
    monkeypatch.setattr(wa, "find_node_executable", lambda name: "fake-node.exe")
    monkeypatch.setattr(adapter, "_wait_for_bridge", AsyncMock(return_value=True))
    monkeypatch.setattr(adapter, "_attach_to_bridge", lambda proc: setattr(adapter, "_running", True))
    monkeypatch.setattr(adapter, "_wire_plugin_handlers", Mock())
    return adapter


class TestPortIsFree:
    def test_free_port_binds(self):
        assert wa._port_is_free(_free_port()) is True

    def test_listening_port_is_bound(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            assert wa._port_is_free(holder.getsockname()[1]) is False
        finally:
            holder.close()

    @pytest.mark.asyncio
    async def test_wait_for_port_release_polls_the_same_probe(self, monkeypatch):
        answers = iter([False, False, True])
        monkeypatch.setattr(wa, "_port_is_free", lambda port: next(answers))
        monkeypatch.setattr(wa.asyncio, "sleep", AsyncMock())
        assert await wa._wait_for_port_release(1, timeout_s=60.0) is True
        assert wa.asyncio.sleep.await_count == 2


class TestPortGate:
    @pytest.mark.asyncio
    async def test_free_port_goes_straight_to_spawn(self, tmp_path, monkeypatch):
        """No adopt probe, no listener scan, no release wait: pidfile reap then Popen."""
        trace = []
        adapter = _adapter(tmp_path, monkeypatch, trace)
        monkeypatch.setattr(wa, "_port_is_free", lambda port: True)
        try:
            assert await adapter.connect() is True
        finally:
            adapter._close_bridge_log()
        assert trace == ["pidfile", "spawn"]

    @pytest.mark.asyncio
    async def test_bound_port_keeps_the_adopt_kill_release_order(self, tmp_path, monkeypatch):
        trace = []
        adapter = _adapter(tmp_path, monkeypatch, trace)
        monkeypatch.setattr(wa, "_port_is_free", lambda port: False)
        try:
            assert await adapter.connect() is True
        finally:
            adapter._close_bridge_log()
        assert trace == ["reuse", "pidfile", "kill", "wait", "spawn"]

    @pytest.mark.asyncio
    async def test_gate_asks_the_configured_port(self, tmp_path, monkeypatch):
        trace, asked = [], []
        adapter = _adapter(tmp_path, monkeypatch, trace)
        monkeypatch.setattr(wa, "_port_is_free", lambda port: (asked.append(port), True)[1])
        try:
            await adapter.connect()
        finally:
            adapter._close_bridge_log()
        assert asked == [adapter._bridge_port]


class TestSlowProbes:
    """Slow pre-spawn probes must not starve the spawn of the runner's budget.

    The budget is shrunk to 50 ms and the two probes the incident measured — the ``node --version``
    spawn and the listener scan — block synchronously for 4x that. Each sleep can only ever be LONGER
    under load, so the mutant (no port gate) is red on any host: its first await after the deadline is
    the adopt probe, which sits before ``Popen``. With the gate, nothing between ``connect()`` and
    ``Popen`` yields, so the spawn is recorded whether or not the runner then reports a timeout.
    """

    @pytest.mark.asyncio
    async def test_spawn_happens_before_the_budget_can_cancel(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT", raising=False)
        budget = 0.05
        trace = []
        adapter = _adapter(tmp_path, monkeypatch, trace)
        adapter.connect_timeout_secs = budget

        def slow_preflight():
            time.sleep(budget * 4)  # node --version on a saturated host, on the loop thread
            trace.append("preflight")
            return True

        def slow_scan(port):
            time.sleep(budget * 4)  # the psutil/netstat listener walk
            trace.append("kill")

        monkeypatch.setattr(adapter, "_preflight", slow_preflight)
        monkeypatch.setattr(wa, "_kill_port_process", slow_scan)
        monkeypatch.setattr(wa, "_port_is_free", lambda port: True)
        runner = GatewayRunner(GatewayConfig(platforms={}, sessions_dir=tmp_path / "sessions"))
        try:
            try:
                await runner._connect_adapter_with_timeout(adapter, Platform.WHATSAPP, initial=True)
            except TimeoutError:
                pass  # the budget may still expire AFTER the spawn; that is the runner's call, not a lost bridge
        finally:
            adapter._close_bridge_log()
        assert "spawn" in trace, trace
        assert "kill" not in trace, "a free port must not pay the listener scan"


class TestNodeProbeCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        wa._node_probe_ok.clear()
        yield
        wa._node_probe_ok.clear()

    def _node_on_disk(self, tmp_path, monkeypatch, spawns, *, returncode=0, raise_timeout=False):
        node = tmp_path / "node.exe"
        node.write_bytes(b"#!node\n")
        monkeypatch.setattr(wa, "find_node_executable", lambda _name: str(node))

        def _run(cmd, **kwargs):
            spawns.append(cmd)
            if raise_timeout:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 60))
            return subprocess.CompletedProcess(cmd, returncode, stdout="v24.14.0", stderr="")

        monkeypatch.setattr(wa.subprocess, "run", _run)
        return node

    def test_second_attempt_does_not_spawn_again(self, tmp_path, monkeypatch):
        spawns = []
        self._node_on_disk(tmp_path, monkeypatch, spawns)
        assert wa.check_whatsapp_requirements() is True
        assert wa.check_whatsapp_requirements() is True
        assert len(spawns) == 1

    def test_changed_binary_is_probed_again(self, tmp_path, monkeypatch):
        spawns = []
        node = self._node_on_disk(tmp_path, monkeypatch, spawns)
        assert wa.check_whatsapp_requirements() is True
        node.write_bytes(b"#!node v25\n")  # size and mtime move: a different install
        assert wa.check_whatsapp_requirements() is True
        assert len(spawns) == 2

    def test_failed_probe_is_not_cached(self, tmp_path, monkeypatch):
        spawns = []
        self._node_on_disk(tmp_path, monkeypatch, spawns, returncode=1)
        assert wa.check_whatsapp_requirements() is False
        assert wa.check_whatsapp_requirements() is False
        assert len(spawns) == 2

    def test_timed_out_probe_is_not_cached(self, tmp_path, monkeypatch):
        """A timeout still reads as present (the host is loaded, not node-less) but proves nothing."""
        spawns = []
        self._node_on_disk(tmp_path, monkeypatch, spawns, raise_timeout=True)
        assert wa.check_whatsapp_requirements() is True
        assert wa.check_whatsapp_requirements() is True
        assert len(spawns) == 2

    def test_unstatable_node_is_probed_every_time(self, tmp_path, monkeypatch):
        spawns = []
        monkeypatch.setattr(wa, "find_node_executable", lambda _name: str(tmp_path / "missing-node"))
        monkeypatch.setattr(wa.subprocess, "run",
                            lambda cmd, **kw: (spawns.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
        assert wa.check_whatsapp_requirements() is True
        assert wa.check_whatsapp_requirements() is True
        assert len(spawns) == 2 and not wa._node_probe_ok


class TestDeclaredBudget:
    def _runner(self, tmp_path):
        return GatewayRunner(GatewayConfig(platforms={}, sessions_dir=tmp_path / "sessions"))

    def test_whatsapp_declares_more_than_the_platform_default(self):
        from gateway.run import _PLATFORM_CONNECT_TIMEOUT_SECS_DEFAULT
        assert wa.WhatsAppAdapter.connect_timeout_secs > _PLATFORM_CONNECT_TIMEOUT_SECS_DEFAULT
        # pre-spawn on a bound port (2 s probe + kill + 15 s release) + _wait_for_bridge's 2 x 15 polls
        assert wa.WhatsAppAdapter.connect_timeout_secs >= 60.0

    def test_declared_budget_replaces_the_default_for_initial_and_reconnect(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT", raising=False)
        runner = self._runner(tmp_path)
        adapter = SimpleNamespace(connect_timeout_secs=77.0)
        assert runner._platform_connect_timeout_secs(Platform.WHATSAPP, adapter=adapter) == 77.0
        assert runner._platform_connect_timeout_secs(Platform.WHATSAPP, initial=True, adapter=adapter) == 77.0

    def test_env_override_still_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT", "12")
        runner = self._runner(tmp_path)
        assert runner._platform_connect_timeout_secs(
            Platform.WHATSAPP, adapter=SimpleNamespace(connect_timeout_secs=77.0)) == 12.0

    @pytest.mark.parametrize("declared", [None, 0, -5, "soon", object()])
    def test_unusable_declaration_keeps_the_default(self, tmp_path, monkeypatch, declared):
        from gateway.run import _PLATFORM_CONNECT_TIMEOUT_SECS_DEFAULT
        monkeypatch.delenv("HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT", raising=False)
        runner = self._runner(tmp_path)
        adapter = SimpleNamespace(connect_timeout_secs=declared)
        assert runner._platform_connect_timeout_secs(Platform.WHATSAPP, adapter=adapter) == _PLATFORM_CONNECT_TIMEOUT_SECS_DEFAULT
        assert runner._platform_connect_timeout_secs(Platform.WHATSAPP, adapter=None) == _PLATFORM_CONNECT_TIMEOUT_SECS_DEFAULT

    def test_telegram_budgets_unchanged(self, tmp_path, monkeypatch):
        from gateway.run import _TELEGRAM_CONNECT_TIMEOUT_SECS_DEFAULT, _TELEGRAM_INITIAL_CONNECT_TIMEOUT_SECS_DEFAULT
        monkeypatch.delenv("HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT", raising=False)
        runner = self._runner(tmp_path)
        adapter = SimpleNamespace()  # no declaration
        assert runner._platform_connect_timeout_secs(Platform.TELEGRAM, adapter=adapter) == _TELEGRAM_CONNECT_TIMEOUT_SECS_DEFAULT
        assert runner._platform_connect_timeout_secs(Platform.TELEGRAM, initial=True, adapter=adapter) == _TELEGRAM_INITIAL_CONNECT_TIMEOUT_SECS_DEFAULT

    @pytest.mark.asyncio
    async def test_connect_with_timeout_passes_the_adapter_through(self, tmp_path, monkeypatch):
        runner = self._runner(tmp_path)
        seen = {}

        def budget(platform=None, *, initial=False, adapter=None):
            seen["adapter"] = adapter
            return 5.0

        monkeypatch.setattr(runner, "_platform_connect_timeout_secs", budget)
        adapter = SimpleNamespace(connect=AsyncMock(return_value=True))
        assert await runner._connect_adapter_with_timeout(adapter, Platform.WHATSAPP) is True
        assert seen["adapter"] is adapter
