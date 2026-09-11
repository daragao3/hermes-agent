from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from agent import firecrawl_run_state as state
from plugins.browser.firecrawl.provider import FirecrawlBrowserProvider


def test_402_opens_run_circuit_but_keeps_cleanup_available(monkeypatch):
    provider = FirecrawlBrowserProvider()
    monkeypatch.setattr(provider, "_headers", lambda *args: {})
    post = Mock(return_value=SimpleNamespace(ok=False, status_code=402))
    monkeypatch.setattr(provider, "_post_create", post)
    release = Mock(return_value=SimpleNamespace(status_code=200))
    monkeypatch.setattr(provider, "_release", release)
    run, token = state.install_firecrawl_run()
    try:
        with pytest.raises(state.FirecrawlCreditsExhaustedError):
            provider.create_session("fixture")
        assert run.circuit_open
        with pytest.raises(state.FirecrawlCircuitOpenError):
            provider.create_session("fixture")
        post.assert_called_once()
        assert provider.close_session("owned-fixture") is True
        release.assert_called_once()
    finally:
        state.reset_firecrawl_run(token)
