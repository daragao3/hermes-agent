"""Integration boundaries between local credit fallback and upstream cache/scopes."""
from types import SimpleNamespace

import pytest

from tools import web_result_cache as cache
from tools import web_tools, web_tools_extract as extract
from tools.web_tools_truncate import _trim_results

CREDIT = {"provider": "firecrawl", "code": "provider_credits_exhausted",
          "scope": "account", "retryable": False}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "search_memo", cache.SearchMemo())
    (tmp_path / "web").mkdir()
    monkeypatch.setattr(cache, "_cache_dir", lambda: tmp_path / "web")
    monkeypatch.setattr(cache, "_web_config", lambda: {})
    monkeypatch.setattr("tools.website_policy.check_website_access", lambda url: None)
    monkeypatch.setattr(extract, "check_website_access", lambda url: None)


def test_search_credit_alternate_never_becomes_primary_cache_entry(monkeypatch):
    calls = []
    def search(query, limit):
        calls.append((query, limit))
        if len(calls) == 1:
            return {"success": False, "error": "credits", "error_info": CREDIT}
        return {"success": True, "data": {"web": [{"url": "https://primary.test"}]}}
    primary = SimpleNamespace(name="firecrawl", search=search)
    fallback = SimpleNamespace(search=lambda query, limit: {
        "success": True, "data": {"web": [{"url": "https://fallback.test"}]}})
    monkeypatch.setattr(web_tools, "_resolve_run_fallback", lambda capability: fallback)
    def forbidden_rescue(provider):
        raise AssertionError("typed credit exhaustion entered generic rescue")
    monkeypatch.setattr(web_tools, "_rescue_eligible", forbidden_rescue)
    first = web_tools._memoized_search(primary, "same", 3)
    second = web_tools._memoized_search(primary, "same", 3)
    third = web_tools._memoized_search(primary, "same", 3)
    assert first["data"]["web"][0]["url"] == "https://fallback.test"
    assert second == third
    assert second["data"]["web"][0]["url"] == "https://primary.test"
    assert calls == [("same", 10), ("same", 10)]


@pytest.mark.asyncio
async def test_extract_only_primary_success_is_cached_after_partial_credit_fallback(monkeypatch):
    good, exhausted = "https://example.com/good", "https://example.com/credit"
    calls = []
    async def primary_extract(urls, **kwargs):
        calls.append(list(urls))
        return [{"url": u, "content": "primary"} if u == good else
                {"url": u, "error": "credits", "error_info": CREDIT} for u in urls]
    async def alternate_extract(urls, **kwargs):
        return [{"url": u, "content": "alternate"} for u in urls]
    provider = SimpleNamespace(name="firecrawl", extract=primary_extract)
    alternate = SimpleNamespace(name="alternate", extract=alternate_extract)
    monkeypatch.setattr(extract, "_resolve_run_fallback", lambda capability: alternate)
    def forbidden_rescue(provider):
        raise AssertionError("typed credit exhaustion entered generic rescue")
    monkeypatch.setattr(extract, "_rescue_eligible", forbidden_rescue)
    first = await extract._extract_safe_urls(provider, [good, exhausted], None)
    second = await extract._extract_safe_urls(provider, [good, exhausted], None)
    assert [r["content"] for r in first] == ["primary", "alternate"]
    assert [r["content"] for r in second] == ["primary", "alternate"]
    assert calls == [[good, exhausted], [exhausted]]
    assert cache.extract_cache_get(exhausted, provider="firecrawl") is None


def test_public_credit_diagnostics_drop_vendor_payload():
    result = _trim_results([{"url": "https://example.com", "error_info": {
        **CREDIT, "response_body": "private-body", "api_key": "private-key"}}])[0]
    assert result["error_info"] == CREDIT
    assert "private" not in repr(result)


def test_fallback_uses_active_scoped_override_without_cross_profile_leak(monkeypatch):
    from agent import provider_registry as engine, web_search_registry as registry
    def provider(name):
        return SimpleNamespace(name=name, supports_search=lambda: True,
                               supports_extract=lambda: True, is_available=lambda: True)
    global_provider, profile_a, profile_b = [provider("parallel") for _ in range(3)]
    active = ["profile-a"]
    monkeypatch.setattr(engine, "hermes_home_key", lambda: active[0])
    monkeypatch.setattr(registry._registry, "_providers", {"parallel": global_provider})
    monkeypatch.setattr(registry._registry, "_scoped_providers", {
        "profile-a": {"parallel": profile_a}, "profile-b": {"parallel": profile_b}})
    monkeypatch.setattr(registry, "_read_config_key", lambda *path: "parallel")
    assert registry.get_fallback_provider("extract") is profile_a
    active[0] = "profile-b"
    assert registry.get_fallback_provider("extract") is profile_b
    active[0] = "profile-c"
    assert registry.get_fallback_provider("extract") is global_provider


def test_httpx_payment_error_classification_is_sanitized():
    import httpx
    from plugins.web.firecrawl.provider import _credit_error_info
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(402, request=request, text="private-vendor-body")
    error = httpx.HTTPStatusError("private-diagnostic", request=request, response=response)
    assert _credit_error_info(error) == CREDIT
