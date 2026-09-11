"""Sticky recovery uses the upstream immediate-reset/pool-generation owner."""
import httpx
import pytest
from unittest.mock import AsyncMock
from plugins.platforms.telegram import telegram_network as net


@pytest.mark.asyncio
async def test_failed_sticky_route_resets_immediately_and_releases_pool(monkeypatch):
    pools = []
    def factory(**kwargs):
        pool = AsyncMock()
        pool.handle_async_request.side_effect = httpx.ConnectError("offline")
        pools.append(pool)
        return pool
    monkeypatch.setattr(net.httpx, "AsyncHTTPTransport", factory)
    monkeypatch.setattr(net, "_resolve_proxy_url", lambda **kw: None)
    transport = net.TelegramFallbackTransport(["149.154.167.220"])
    transport._sticky_ip = "149.154.167.220"
    with pytest.raises(httpx.ConnectError):
        await transport.handle_async_request(httpx.Request("GET", "https://api.telegram.org/botFAKE/getMe"))
    assert transport._sticky_ip is net._UNSET
    assert transport._fallbacks == {}
    pools[0].aclose.assert_awaited_once()
    pools[1].aclose.assert_awaited_once()
    await transport.aclose()


@pytest.mark.asyncio
async def test_successful_sticky_route_remains_first_without_pool_churn(monkeypatch):
    pools = []
    def factory(**kwargs):
        pool = AsyncMock()
        pool.handle_async_request.return_value = httpx.Response(200)
        pools.append(pool)
        return pool
    monkeypatch.setattr(net.httpx, "AsyncHTTPTransport", factory)
    monkeypatch.setattr(net, "_resolve_proxy_url", lambda **kw: None)
    transport = net.TelegramFallbackTransport(["149.154.167.220", "149.154.167.221"])
    transport._sticky_ip = "149.154.167.221"
    request = httpx.Request("GET", "https://api.telegram.org/botFAKE/getMe")
    await transport.handle_async_request(request)
    await transport.handle_async_request(request)
    assert transport._attempt_order()[0] == "149.154.167.221"
    assert len(pools) == 2
    assert pools[1].handle_async_request.await_count == 2
    pools[0].handle_async_request.assert_not_awaited()
    pools[1].aclose.assert_not_awaited()
    await transport.aclose()
