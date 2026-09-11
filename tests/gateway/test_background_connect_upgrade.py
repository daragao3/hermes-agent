"""A blocked messaging transport must not delay independent startup services."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import Platform
from gateway.run_startup import GatewayStartupMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.WHATSAPP])
async def test_slow_messaging_connect_releases_startup(platform):
    runner = GatewayStartupMixin()
    entered, release = asyncio.Event(), asyncio.Event()
    background = set()
    adapter = SimpleNamespace()
    runner._running = False
    runner._abort_startup_if_shutdown_requested = AsyncMock(return_value=False)
    runner._startup_should_abort = lambda: False
    runner._update_platform_runtime_status = Mock()
    runner._startup_teardown_adapter = AsyncMock()
    runner._safe_adapter_disconnect = AsyncMock()

    async def connect(adp, which, **kwargs):
        if which == platform:
            entered.set()
            await release.wait()
        return True

    def retain(task):
        background.add(task)
        task.add_done_callback(background.discard)
        return task

    runner._connect_initial_adapter_with_timeout = connect
    runner._retain_background_task = retain
    pending = asyncio.create_task(runner._start_connect_pending([(platform, None, adapter)]))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        done, _ = await asyncio.wait({pending}, timeout=0.2)
        assert pending in done, "messaging connect still gates gateway startup"
        assert pending.result() == []
        assert background, "outstanding connect has no shutdown owner"
    finally:
        pending.cancel()
        for task in list(background):
            task.cancel()
        release.set()
        await asyncio.gather(pending, *list(background), return_exceptions=True)
    runner._startup_teardown_adapter.assert_awaited()
    assert not background


def _settlement_runner(monkeypatch):
    runner = GatewayStartupMixin()
    runner._running = True
    runner._startup_background_connects = set()
    runner._startup_restore_in_progress = False
    runner.adapters = {}
    runner._failed_platforms = {}
    runner.delivery_router = SimpleNamespace(adapters={})
    runner._startup_should_abort = lambda: False
    runner._startup_teardown_adapter = AsyncMock()
    runner._safe_adapter_disconnect = AsyncMock()
    runner._update_platform_runtime_status = Mock()
    runner._startup_fail_fatal_config = Mock()
    runner._startup_retry_entry = lambda *a, **kw: {"retry": True}
    order = []
    runner._publish_primary_adapter = lambda p, a: runner.adapters.update({p: a})
    async def directory(adapters):
        order.append("directory")
    async def redeliver():
        order.append("redelivery")
    monkeypatch.setattr("gateway.channel_directory.build_channel_directory", directory)
    runner._redeliver_pending_obligations = redeliver
    runner._schedule_resume_pending_sessions = lambda **kw: order.append("resume")
    return runner, order


@pytest.mark.asyncio
@pytest.mark.parametrize("restoring", [False, True])
async def test_background_success_preserves_redelivery_before_resume(monkeypatch, restoring):
    runner, order = _settlement_runner(monkeypatch)
    runner._startup_restore_in_progress = restoring
    adapter = SimpleNamespace(send_path_degraded=True, DEGRADED_STATUS_MESSAGE="warming")
    result = asyncio.get_running_loop().create_future()
    result.set_result((Platform.TELEGRAM, adapter, None, "ok", None))
    await runner._finish_background_startup_connect(result, Platform.TELEGRAM, adapter)
    assert runner.adapters[Platform.TELEGRAM] is adapter
    assert runner.delivery_router.adapters is runner.adapters
    assert order == (["directory", "redelivery"] if restoring else ["directory", "redelivery", "resume"])
    assert runner._update_platform_runtime_status.call_args.kwargs["platform_state"] == "retrying"


@pytest.mark.asyncio
async def test_background_success_after_shutdown_is_torn_down(monkeypatch):
    runner, order = _settlement_runner(monkeypatch)
    runner._startup_should_abort = lambda: True
    adapter = SimpleNamespace()
    result = asyncio.get_running_loop().create_future()
    result.set_result((Platform.TELEGRAM, adapter, None, "ok", None))
    await runner._finish_background_startup_connect(result, Platform.TELEGRAM, adapter)
    runner._startup_teardown_adapter.assert_awaited_once_with(adapter, Platform.TELEGRAM)
    assert not runner.adapters and order == []


@pytest.mark.asyncio
@pytest.mark.parametrize("other_pending", [False, True])
async def test_background_fatal_does_not_kill_another_pending_connect(monkeypatch, other_pending):
    runner, _ = _settlement_runner(monkeypatch)
    if other_pending:
        runner._startup_background_connects.add(object())
    adapter = SimpleNamespace(has_fatal_error=True, fatal_error_retryable=False,
                              fatal_error_code="bad_auth", fatal_error_message="invalid token")
    result = asyncio.get_running_loop().create_future()
    result.set_result((Platform.TELEGRAM, adapter, None, "failed", None))
    await runner._finish_background_startup_connect(result, Platform.TELEGRAM, adapter)
    assert runner._startup_fail_fatal_config.call_count == (0 if other_pending else 1)
    assert not runner._failed_platforms


@pytest.mark.asyncio
async def test_initial_takeover_authority_survives_global_phase_end_but_is_cleared():
    from gateway.run_adapters import GatewayAdapterLifecycleMixin
    runner = SimpleNamespace(_platform_lock_takeover_on_start=False)
    adapter = SimpleNamespace()
    async def connect(adp, platform, **kwargs):
        assert adp._platform_lock_takeover_allowed is True
        raise RuntimeError("connect failed")
    runner._connect_adapter_with_timeout = connect
    with pytest.raises(RuntimeError, match="connect failed"):
        await GatewayAdapterLifecycleMixin._connect_initial_adapter_with_timeout(
            runner, adapter, Platform.TELEGRAM, takeover_allowed=True)
    assert adapter._platform_lock_takeover_allowed is False


@pytest.mark.asyncio
async def test_foreground_connect_still_gates_startup_until_ready():
    runner = GatewayStartupMixin()
    entered, release = asyncio.Event(), asyncio.Event()
    runner._abort_startup_if_shutdown_requested = AsyncMock(return_value=False)
    runner._startup_should_abort = lambda: False
    runner._update_platform_runtime_status = Mock()
    runner._startup_teardown_adapter = AsyncMock()
    adapter = object()
    async def connect(adp, platform):
        entered.set()
        await release.wait()
        return True
    runner._connect_initial_adapter_with_timeout = connect
    task = asyncio.create_task(runner._start_connect_pending([(Platform.DISCORD, None, adapter)]))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not task.done()
        release.set()
        assert await asyncio.wait_for(task, 1) == [(Platform.DISCORD, adapter, None, "ok", None)]
        assert not runner._startup_background_connects
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
