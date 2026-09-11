import asyncio
from unittest.mock import AsyncMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent as MessageEvent
from gateway.restart import GATEWAY_FATAL_CONFIG_EXIT_CODE
from gateway.run import GatewayRunner
from gateway.session import SessionSource as SessionSource, build_session_key as build_session_key


@pytest.fixture(autouse=True)
def _neutralize_eventbus_startup(monkeypatch):
    """Keep ``GatewayRunner.start()`` off the canonical ~/.hermes event bus.

    ``start()`` calls ``events.gateway_integration.startup()`` inline and
    synchronously, doing real I/O against the **canonical** ~/.hermes event bus
    (13 subscribers, tracker-intent-applier rehydrate, a jobops :4100 probe).
    Notification state is cross-profile, so a ``tmp_path`` HERMES_HOME does not
    redirect it. ``test_runner_requests_clean_exit_for_nonretryable_startup_conflict``
    reaches that call and paid ~134s on a loaded box for an assertion about
    clean-exit bookkeeping that says nothing about the event bus.
    """
    import events.gateway_integration as _ebi

    monkeypatch.setattr(_ebi, "startup", lambda *a, **k: None)


class _FatalAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="token"), Platform.TELEGRAM)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        self._set_fatal_error(
            "telegram_token_lock",
            "Another local Hermes gateway is already using this Telegram bot token.",
            retryable=False,
        )
        return False

    async def disconnect(self) -> None:
        self._mark_disconnected()

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        raise NotImplementedError

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


class _RuntimeRetryableAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="token"), Platform.WHATSAPP)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        self._mark_disconnected()

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        raise NotImplementedError

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


class _ReplacementDeliveryAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(
            PlatformConfig(enabled=True, token="token", typing_indicator=False),
            Platform.DISCORD,
        )
        self.sent: list[str] = []
        self.connected = True

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        self.sent.append(content)
        return SendResult(success=True, message_id=f"m-{len(self.sent)}")

    async def send_typing(self, chat_id, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


@pytest.mark.asyncio
async def test_runner_requests_clean_exit_for_nonretryable_startup_conflict(monkeypatch, tmp_path):
    """A non-retryable startup conflict must still exit the gateway cleanly.

    Telegram now connects in the BACKGROUND (``_BACKGROUND_CONNECT_PLATFORMS``,
    added so a DNS flap can't block boot), so the token-lock fatal lands *after*
    ``start()`` returns instead of inline — wait for it before asserting.

    The clean exit itself must survive that move. A token lock is not transient:
    another gateway already holds this bot token, so this process is a duplicate
    and must not linger running cron against the same config. It exits with
    EX_CONFIG (78) so the s6 finish script translates it to 125 — a permanent
    failure that is NOT restarted (#51228). Telegram is the only platform here,
    so nothing else is up to justify staying alive.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(enabled=True, token="token")
        },
        sessions_dir=tmp_path / "sessions",
    )
    runner = GatewayRunner(config)

    monkeypatch.setattr(runner, "_create_adapter", lambda platform, platform_config: _FatalAdapter())

    ok = await runner.start()

    assert ok is True

    for _ in range(300):  # ~3s ceiling
        if runner.should_exit_cleanly:
            break
        await asyncio.sleep(0.01)

    assert runner.should_exit_cleanly is True
    assert "already using this Telegram bot token" in runner.exit_reason
    assert runner.exit_code == GATEWAY_FATAL_CONFIG_EXIT_CODE


@pytest.mark.asyncio
async def test_runner_queues_retryable_runtime_fatal_for_reconnection(monkeypatch, tmp_path):
    """Retryable runtime fatal errors queue the platform for reconnection
    AND keep the gateway alive — the background reconnect watcher recovers
    the platform when the underlying issue clears.  (Previously this
    exited-with-failure to trigger a systemd restart; that converted
    transient failures into infinite restart loops.)
    """
    config = GatewayConfig(
        platforms={
            Platform.WHATSAPP: PlatformConfig(enabled=True, token="token")
        },
        sessions_dir=tmp_path / "sessions",
    )
    runner = GatewayRunner(config)
    adapter = _RuntimeRetryableAdapter()
    adapter._set_fatal_error(
        "whatsapp_bridge_exited",
        "WhatsApp bridge process exited unexpectedly (code 1).",
        retryable=True,
    )

    runner.adapters = {Platform.WHATSAPP: adapter}
    runner.delivery_router.adapters = runner.adapters
    runner.stop = AsyncMock()

    await runner._handle_adapter_fatal_error(adapter)

    # Gateway stays alive — watcher will retry in background
    runner.stop.assert_not_awaited()
    assert runner._exit_with_failure is False
    assert Platform.WHATSAPP in runner._failed_platforms
    assert runner._failed_platforms[Platform.WHATSAPP]["attempts"] == 0


@pytest.mark.asyncio
async def test_retryable_fatal_queues_reconnect_after_cancellation_swallowing_disconnect(
    monkeypatch, tmp_path
):
    """A wedged old adapter cannot block runner-owned reconnect recovery."""
    monkeypatch.setenv("HERMES_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT", "0.01")
    config = GatewayConfig(
        platforms={Platform.WHATSAPP: PlatformConfig(enabled=True, token="token")},
        sessions_dir=tmp_path / "sessions",
    )
    runner = GatewayRunner(config)
    adapter = _RuntimeRetryableAdapter()
    adapter._set_fatal_error("transport_stale", "transport stale", retryable=True)
    runner.adapters = {Platform.WHATSAPP: adapter}
    runner.delivery_router.adapters = runner.adapters

    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def swallow_cancellation():
        started.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue
        finished.set()

    monkeypatch.setattr(adapter, "disconnect", swallow_cancellation)
    operation = asyncio.create_task(runner._handle_adapter_fatal_error(adapter))
    await started.wait()
    done, _pending = await asyncio.wait({operation}, timeout=0.2)
    try:
        assert operation in done
        assert runner.adapters == {}
        assert Platform.WHATSAPP in runner._failed_platforms
        assert runner._failed_platforms[Platform.WHATSAPP]["attempts"] == 0
    finally:
        release.set()
        await asyncio.wait({operation}, timeout=0.2)
        await asyncio.wait_for(finished.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_retryable_fatal_queues_before_disconnect_returns(monkeypatch, tmp_path):
    """#80598: reconnect queue must populate before disconnect finishes.

    After a long network outage, Telegram disconnect can wedge on a half-dead
    socket. If the fatal handler only queues after disconnect returns, the
    watcher never learns about the failure and the gateway stays permanently
    deaf. Queue first; teardown is best-effort after.
    """
    config = GatewayConfig(
        platforms={Platform.WHATSAPP: PlatformConfig(enabled=True, token="token")},
        sessions_dir=tmp_path / "sessions",
    )
    runner = GatewayRunner(config)
    adapter = _RuntimeRetryableAdapter()
    adapter._set_fatal_error(
        "telegram_network_error",
        "Telegram polling could not reconnect after 10 network error retries.",
        retryable=True,
    )
    runner.adapters = {Platform.WHATSAPP: adapter}
    runner.delivery_router.adapters = runner.adapters
    runner.stop = AsyncMock()

    disconnect_entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_disconnect():
        # Disconnect has started — the platform must already be queued.
        assert Platform.WHATSAPP in runner._failed_platforms
        disconnect_entered.set()
        await release.wait()

    monkeypatch.setattr(adapter, "disconnect", blocking_disconnect)
    operation = asyncio.create_task(runner._handle_adapter_fatal_error(adapter))
    await asyncio.wait_for(disconnect_entered.wait(), timeout=0.5)
    try:
        assert runner.adapters == {}
        assert Platform.WHATSAPP in runner._failed_platforms
        assert runner._failed_platforms[Platform.WHATSAPP]["attempts"] == 0
        runner.stop.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(operation, timeout=0.5)


@pytest.mark.asyncio
async def test_fatal_handler_outer_timeout_still_queues_platform(monkeypatch, tmp_path):
    """#80598: outer deadline must queue even if the impl task never returns."""
    monkeypatch.setenv("HERMES_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT", "0.05")
    config = GatewayConfig(
        platforms={Platform.WHATSAPP: PlatformConfig(enabled=True, token="token")},
        sessions_dir=tmp_path / "sessions",
    )
    runner = GatewayRunner(config)
    adapter = _RuntimeRetryableAdapter()
    adapter._set_fatal_error("transport_stale", "transport stale", retryable=True)
    runner.adapters = {Platform.WHATSAPP: adapter}
    runner.delivery_router.adapters = runner.adapters
    runner.stop = AsyncMock()

    started = asyncio.Event()
    release = asyncio.Event()

    async def wedged_impl(_adapter):
        # Simulate a hang before/without reaching the reconnect queue.
        runner.adapters.pop(Platform.WHATSAPP, None)
        runner.delivery_router.adapters = runner.adapters
        started.set()
        await release.wait()

    monkeypatch.setattr(runner, "_handle_adapter_fatal_error_impl", wedged_impl)
    operation = asyncio.create_task(runner._handle_adapter_fatal_error(adapter))
    await started.wait()
    # Outer budget is disconnect_timeout + min(2, max(0.05, timeout)) ≈ 0.1s.
    done, _pending = await asyncio.wait({operation}, timeout=1.0)
    try:
        assert operation in done
        assert Platform.WHATSAPP in runner._failed_platforms
        runner.stop.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait({operation}, timeout=0.2)
