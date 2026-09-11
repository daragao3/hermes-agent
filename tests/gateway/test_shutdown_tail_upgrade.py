"""A failure exit verdict must not skip owned runtime cleanup."""
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from gateway import run


@pytest.mark.asyncio
async def test_failure_verdict_still_stops_cron_and_watchers(monkeypatch):
    monkeypatch.setattr(run, "_exit_with_failure_verdict", lambda runner: True)
    monkeypatch.setattr(run, "_resolve_gateway_exit_verdict", lambda *a: True)
    monkeypatch.setattr(run, "_stop_cron_provider", Mock())
    monkeypatch.setattr(run, "_await_thread_exit", AsyncMock(return_value=True))
    monkeypatch.setattr(run, "_shutdown_mcp_servers_nonblocking", AsyncMock())
    monkeypatch.setattr("hermes_cli.nous_auth_keepalive.stop_nous_auth_keepalive", Mock())
    eventbus_stop = Mock()
    monkeypatch.setattr("events.gateway_integration.shutdown", eventbus_stop)
    control = SimpleNamespace(stop=AsyncMock())
    cron_stop, watcher_stop = threading.Event(), threading.Event()
    watcher = SimpleNamespace(join=Mock())
    assert await run._start_gateway_shutdown_tail(
        SimpleNamespace(_eventbus_cleanup_needed=True), control, cron_stop, object(), object(), object(), watcher_stop, watcher, [False]) is False
    assert cron_stop.is_set() and watcher_stop.is_set()
    control.stop.assert_awaited_once()
    watcher.join.assert_called_once()
    run._await_thread_exit.assert_awaited()
    run._shutdown_mcp_servers_nonblocking.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["pid_claim", "start_raises", "start_false", "after_cron"])
async def test_boot_failures_retire_owned_watchers_and_control(monkeypatch, failure):
    import asyncio
    runner = SimpleNamespace(config=object(), start=AsyncMock(return_value=False),
                             _eventbus_cleanup_needed=failure != "pid_claim")
    if failure == "start_raises":
        runner.start.side_effect = RuntimeError("boot failed")
    if failure == "after_cron":
        runner.start.return_value = True
        runner.should_exit_cleanly = False
        runner._running = True
        runner._start_systemd_watchdog = Mock()
        runner.wait_for_shutdown = AsyncMock(side_effect=RuntimeError("boot failed"))
    cron_stop = threading.Event()
    monkeypatch.setattr(run, "_start_gateway_start_cron_and_housekeeping",
                        lambda runner: (cron_stop, object(), object(), object()))
    stop_provider = Mock()
    monkeypatch.setattr(run, "_stop_cron_provider", stop_provider)
    monkeypatch.setattr(run, "_await_thread_exit", AsyncMock(return_value=True))
    monkeypatch.setattr(run, "_shutdown_mcp_servers_nonblocking", AsyncMock())
    eventbus_stop = Mock()
    monkeypatch.setattr("events.gateway_integration.shutdown", eventbus_stop)
    monkeypatch.setattr("gateway.shutdown_flush.recover_pending_to_db", lambda: 0)

    monkeypatch.setattr(run, "GatewayRunner", lambda config: runner)
    monkeypatch.setattr("gateway.status.get_running_pid", lambda: None)
    monkeypatch.setattr("gateway.code_skew.record_boot_fingerprint", Mock())
    monkeypatch.setattr("hermes_cli.resource_limits.apply_nofile_soft_limit", Mock())
    monkeypatch.setattr(run, "_start_gateway_configure_logging", Mock())
    monkeypatch.setattr(run, "_enable_multiplex_log_routing", Mock())
    monkeypatch.setattr(run, "_start_gateway_make_shutdown_signal_handler", lambda *a: Mock())
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", Mock())
    monkeypatch.setattr(run, "_start_gateway_claim_pid_file", lambda: failure != "pid_claim")
    monkeypatch.setattr(run, "_ensure_windows_gateway_venv_imports", Mock())
    monkeypatch.setattr(run, "_discover_gateway_mcp_tools", AsyncMock())
    monkeypatch.setattr("gateway.lifecycle_ledger.record_startup", Mock())
    monkeypatch.setattr("hermes_cli.nous_auth_keepalive.start_nous_auth_keepalive", Mock())
    stop_keepalive = Mock()
    monkeypatch.setattr(run, "_stop_nous_keepalive_quietly", stop_keepalive)
    health = Mock()
    monkeypatch.setattr(run, "_shutdown_gateway_health_export", health)
    control = SimpleNamespace(stop=AsyncMock())
    monkeypatch.setattr(run, "_start_gateway_start_control_socket", AsyncMock(return_value=control))
    threads = []
    def thread_factory(**kwargs):
        event = kwargs["args"][0]
        thread = SimpleNamespace(start=Mock(), join=Mock(side_effect=lambda **kw: event.is_set()))
        threads.append((event, thread))
        return thread
    monkeypatch.setattr(run.threading, "Thread", thread_factory)
    heartbeat_stops = []
    def heartbeat(stop):
        heartbeat_stops.append(stop)
        return SimpleNamespace(join=Mock())
    monkeypatch.setattr(run, "start_early_boot_heartbeat", heartbeat)
    if failure in {"start_raises", "after_cron"}:
        with pytest.raises(RuntimeError, match="boot failed"):
            await run.start_gateway()
    else:
        assert await run.start_gateway() is False
    assert len(threads) == 1
    event, thread = threads[0]
    assert event.is_set()
    thread.join.assert_called_once()
    assert health.called
    if failure == "pid_claim":
        control.stop.assert_not_awaited()
        runner.start.assert_not_awaited()
        run._shutdown_mcp_servers_nonblocking.assert_not_awaited()
    else:
        control.stop.assert_awaited_once()
        stop_keepalive.assert_called_once()
        assert heartbeat_stops and heartbeat_stops[0].is_set()
        run._shutdown_mcp_servers_nonblocking.assert_awaited_once()

    if failure == "after_cron":
        assert cron_stop.is_set()
        stop_provider.assert_called_once()
        assert run._await_thread_exit.await_count == 2

    assert eventbus_stop.call_count == (0 if failure == "pid_claim" else 1)
