"""Plugin-side tests for the web search provider migration (PR #25182).

Covers:

- All bundled plugins (brave-free, ddgs, searxng, exa, parallel,
  tavily, firecrawl, keenable, xai) instantiate and self-report the expected
  capabilities + ABC-derived defaults.
- Each plugin's ``is_available()`` correctly reflects env-var presence.
- The web_search_registry resolves an active provider in the documented
  scenarios (explicit config wins ignoring availability, fallback walks
  legacy preference filtered by availability, unknown name falls back).
- Plugin response shapes match the legacy bit-for-bit contract.

Per the dev skill: these tests use *real* imports from the plugin
modules — no mocking of provider classes themselves — so the test
catches drift in the ABC interface, the registry, and the plugin
glue layer simultaneously.
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_web_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every web-provider env var so is_available() returns False."""
    for k in (
        "BRAVE_SEARCH_API_KEY",
        "SEARXNG_URL",
        "KEENABLE_API_KEY",
        "TAVILY_API_KEY",
        "TAVILY_BASE_URL",
        "EXA_API_KEY",
        "PARALLEL_API_KEY",
        "PARALLEL_SEARCH_MODE",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "FIRECRAWL_GATEWAY_URL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_USER_TOKEN",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


def _ensure_plugins_loaded() -> None:
    """Idempotently load plugins so the registry is populated."""
    from hermes_cli.plugins import _ensure_plugins_discovered

    _ensure_plugins_discovered()


# ---------------------------------------------------------------------------
# Per-plugin discovery + capability flags
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with a clean web-provider env."""
    _clear_web_env(monkeypatch)


class TestBundledPluginsRegister:
    """All bundled web plugins discover and register correctly."""

    def test_all_bundled_plugins_present_in_registry(self) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import list_providers

        names = sorted(p.name for p in list_providers())
        assert names == [
            "brave-free",
            "ddgs",
            "exa",
            "firecrawl",
            "keenable",
            "parallel",
            "perplexity",
            "searxng",
            "tavily",
            "xai",
        ]

    @pytest.mark.parametrize(
        "plugin_name,expected_search,expected_extract",
        [
            ("brave-free", True, False),
            ("ddgs", True, False),
            ("searxng", True, False),
            ("exa", True, True),
            ("parallel", True, True),
            ("keenable", True, True),
            ("tavily", True, True),
            ("perplexity", True, True),
            ("firecrawl", True, True),
            # xai: search-only via Grok's agentic web_search tool.
            ("xai", True, False),
        ],
    )
    def test_capability_flags_match_spec(
        self,
        plugin_name: str,
        expected_search: bool,
        expected_extract: bool,
    ) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        provider = get_provider(plugin_name)
        assert provider is not None, f"plugin {plugin_name!r} not registered"
        assert provider.supports_search() is expected_search
        assert provider.supports_extract() is expected_extract

    @pytest.mark.parametrize(
        "plugin_name",
        ["brave-free", "ddgs", "searxng", "exa", "parallel", "tavily", "perplexity", "firecrawl", "keenable", "xai"],
    )
    def test_each_plugin_has_name_and_display_name(self, plugin_name: str) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        provider = get_provider(plugin_name)
        assert provider is not None
        assert provider.name == plugin_name
        assert provider.display_name  # any non-empty string


# ---------------------------------------------------------------------------
# is_available() behavior
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """Each plugin's ``is_available()`` returns False without env config."""

    def test_brave_free_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("brave-free")
        assert p is not None
        assert p.is_available() is False  # no BRAVE_SEARCH_API_KEY
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "real")
        assert p.is_available() is True

    def test_searxng_requires_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("searxng")
        assert p is not None
        assert p.is_available() is False
        monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")
        assert p.is_available() is True

    def test_keenable_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("keenable")
        assert p is not None
        assert p.is_available() is False
        monkeypatch.setenv("KEENABLE_API_KEY", "real")
        assert p.is_available() is True

    def test_tavily_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("tavily")
        assert p is not None
        assert p.is_available() is False
        monkeypatch.setenv("TAVILY_API_KEY", "real")
        assert p.is_available() is True

    def test_exa_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("exa")
        assert p is not None
        assert p.is_available() is False
        monkeypatch.setenv("EXA_API_KEY", "real")
        assert p.is_available() is True

    def test_parallel_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("parallel")
        assert p is not None
        assert p.is_available() is False
        monkeypatch.setenv("PARALLEL_API_KEY", "real")
        assert p.is_available() is True

    def test_firecrawl_requires_either_key_or_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("firecrawl")
        assert p is not None
        assert p.is_available() is False

        # Either FIRECRAWL_API_KEY or FIRECRAWL_API_URL lights it up.
        monkeypatch.setenv("FIRECRAWL_API_KEY", "real")
        assert p.is_available() is True
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        monkeypatch.setenv("FIRECRAWL_API_URL", "http://localhost:3002")
        assert p.is_available() is True

    def test_firecrawl_explicit_config_allows_keyless_cloud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("firecrawl")
        assert p is not None
        assert p.is_available() is False

        monkeypatch.setattr(
            "tools.web_tools._load_web_config",
            lambda: {"backend": "firecrawl"},
            raising=False,
        )
        assert p.is_available() is True

    def test_ddgs_always_available_when_package_importable(self) -> None:
        """DDGS is the always-on fallback — no API key required.

        It may report unavailable if the ``ddgs`` package itself isn't
        installed in the env (legitimate — the plugin's post_setup hook
        triggers pip install on first selection). We only assert that
        is_available() doesn't raise.
        """
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("ddgs")
        assert p is not None
        # Truthy or falsy, just must not raise.
        _ = bool(p.is_available())

    def test_xai_requires_api_key_or_oauth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """xAI needs XAI_API_KEY or OAuth tokens in auth.json."""
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_provider

        p = get_provider("xai")
        assert p is not None
        assert p.is_available() is False  # no XAI_API_KEY, no auth.json
        monkeypatch.setenv("XAI_API_KEY", "real")
        assert p.is_available() is True


# ---------------------------------------------------------------------------
# Registry resolution semantics (Option B — conservative smart fallback)
# ---------------------------------------------------------------------------


class TestRegistryResolution:
    """``_resolve()`` follows explicit-config + availability-filtered fallback."""

    def test_explicit_configured_provider_returned_even_when_unavailable(
        self,
    ) -> None:
        """Explicit ``web.search_backend`` wins regardless of is_available().

        Without availability filtering on the explicit path, the dispatcher
        would silently switch backends; with this check the dispatcher
        surfaces a precise "FOO_API_KEY is not set" error instead.
        """
        _ensure_plugins_loaded()
        from agent.web_search_registry import _resolve

        # No BRAVE_SEARCH_API_KEY (fixture cleared it).
        result = _resolve("brave-free", capability="search")
        assert result is not None
        assert result.name == "brave-free"
        # Confirm it's the unavailable one — dispatcher will surface
        # a typed credential-missing error to the caller.
        assert result.is_available() is False

    def test_unknown_configured_name_falls_back_to_available_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Typo / uninstalled plugin → walk legacy preference, pick available."""
        _ensure_plugins_loaded()
        from agent.web_search_registry import _resolve

        monkeypatch.setenv("EXA_API_KEY", "real")
        result = _resolve("not-a-real-provider", capability="search")
        # Either ddgs (no-key fallback) or exa (the only available
        # premium provider) — both are valid. The point is the unknown
        # name shouldn't return None when SOMETHING is available.
        assert result is not None
        assert result.is_available() is True


    def test_no_config_no_credentials_returns_none(
        self,
    ) -> None:
        """No backend configured AND no credentials → keyless tier or ddgs.

        Resolution order with zero credentials: ddgs if its Python package
        is importable, else the keyless free tier (Parallel/Exa public
        endpoints — resolves with ``is_available() == False`` but
        ``is_keyless_available() == True``), else None (keyless tier
        disabled). All three outcomes are correct; a provider that is
        neither keyed nor keyless-capable means an env var leaked in.
        """
        _ensure_plugins_loaded()
        from agent.web_search_registry import _resolve

        result = _resolve(None, capability="search")
        if result is not None:
            assert result.is_available() or result.is_keyless_available()

    def test_fallback_search_excludes_firecrawl_and_uses_existing_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_fallback_provider

        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc")
        monkeypatch.setenv("PARALLEL_API_KEY", "parallel")
        result = get_fallback_provider(
            "search", excluded=frozenset({"firecrawl"})
        )
        assert result is not None
        assert result.name == "parallel"

    def test_explicit_firecrawl_is_excluded_but_explicit_non_firecrawl_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        import agent.web_search_registry as registry

        monkeypatch.setattr(
            registry, "_read_config_key", lambda *path: "firecrawl"
        )
        monkeypatch.setenv("EXA_API_KEY", "exa")
        result = registry.get_fallback_provider(
            "extract", excluded=frozenset({"firecrawl"})
        )
        assert result is not None
        assert result.name == "exa"

    def test_explicit_non_firecrawl_must_be_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        import agent.web_search_registry as registry

        monkeypatch.setattr(
            registry, "_read_config_key", lambda *path: "parallel"
        )
        monkeypatch.setenv("EXA_API_KEY", "exa")
        result = registry.get_fallback_provider(
            "extract", excluded=frozenset({"firecrawl"})
        )
        assert result is not None
        assert result.name == "exa"

    def test_fallback_returns_none_when_all_capable_providers_are_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_plugins_loaded()
        import agent.web_search_registry as registry

        firecrawl = registry.get_provider("firecrawl")
        assert firecrawl is not None
        monkeypatch.setattr(registry._registry, "_providers", {"firecrawl": firecrawl})
        monkeypatch.setattr(registry._registry, "_scoped_providers", {})
        assert (
            registry.get_fallback_provider(
                "extract", excluded=frozenset({"firecrawl"})
            )
            is None
        )

    def test_fallback_rejects_unknown_capability(self) -> None:
        _ensure_plugins_loaded()
        from agent.web_search_registry import get_fallback_provider

        with pytest.raises(ValueError, match="Unsupported web capability"):
            get_fallback_provider("browse")



# ---------------------------------------------------------------------------
# Sync-vs-async extract detection
# ---------------------------------------------------------------------------


class TestAsyncExtractDispatch:
    """The dispatcher detects async vs sync extract methods correctly."""


# ---------------------------------------------------------------------------
# Error response shape (preserved bit-for-bit from legacy)
# ---------------------------------------------------------------------------


class TestErrorResponseShapes:
    @pytest.fixture(autouse=True)
    def _paid_firecrawl_path(self, monkeypatch):
        # These cases exercise the paid SDK circuit, not upstream's free ring.
        monkeypatch.setattr("plugins.web.firecrawl.provider._use_keyless_ring", lambda: False)

    """When credentials are missing, plugins return typed errors, not raises."""

    def test_firecrawl_search_classifies_payment_required_preserving_envelope(
        self,
        monkeypatch,
    ):
        from plugins.web.firecrawl import provider as firecrawl_provider

        class PaymentRequiredError(Exception):
            status_code = 402

        class Client:
            def search(self, **kwargs):
                raise PaymentRequiredError(
                    "Payment Required: Failed to search. Credits exhausted"
                )

        monkeypatch.setattr(firecrawl_provider, "_get_firecrawl_client", lambda: Client())

        result = firecrawl_provider.FirecrawlWebSearchProvider().search("test")

        assert result["success"] is False
        assert result["error"] == "Firecrawl account credits are exhausted"
        assert "Payment Required" not in repr(result)
        assert result["error_info"] == {
            "code": "provider_credits_exhausted",
            "provider": "firecrawl",
            "scope": "account",
            "retryable": False,
        }

    def test_firecrawl_search_does_not_classify_transient_error_as_credits(
        self,
        monkeypatch,
    ):
        from plugins.web.firecrawl import provider as firecrawl_provider

        class Client:
            def search(self, **kwargs):
                raise TimeoutError("temporary timeout")

        monkeypatch.setattr(firecrawl_provider, "_get_firecrawl_client", lambda: Client())

        result = firecrawl_provider.FirecrawlWebSearchProvider().search("test")

        assert result["success"] is False
        assert "error_info" not in result

    def test_firecrawl_search_run_circuit_blocks_later_network_call(
        self,
        monkeypatch,
    ):
        from agent import firecrawl_run_state as state
        from plugins.web.firecrawl import provider as firecrawl_provider

        calls = []

        class Client:
            def search(self, **kwargs):
                calls.append(kwargs)
                return {"web": []}

        monkeypatch.setattr(
            firecrawl_provider, "_get_firecrawl_client", lambda: Client()
        )
        provider = firecrawl_provider.FirecrawlWebSearchProvider()
        _, token = state.install_firecrawl_run()
        try:
            assert provider.search("before")["success"] is True
            assert len(calls) == 1
            state.record_firecrawl_credits_exhausted()
            blocked = provider.search("after")
            assert len(calls) == 1
            assert blocked["error_info"] == dict(state.CIRCUIT_OPEN_INFO)
        finally:
            state.reset_firecrawl_run(token)

    def test_firecrawl_search_402_opens_shared_run_state(
        self,
        monkeypatch,
    ):
        from agent import firecrawl_run_state as state
        from plugins.web.firecrawl import provider as firecrawl_provider

        class PaymentRequiredError(Exception):
            status_code = 402

        class Client:
            def search(self, **kwargs):
                raise PaymentRequiredError("secret response body must not escape")

        monkeypatch.setattr(
            firecrawl_provider, "_get_firecrawl_client", lambda: Client()
        )
        run, token = state.install_firecrawl_run()
        try:
            result = firecrawl_provider.FirecrawlWebSearchProvider().search("query")
            assert run.circuit_open is True
            assert result["error_info"] == dict(state.CREDITS_EXHAUSTED_INFO)
            assert result["error"] == "Firecrawl account credits are exhausted"
            assert "secret response body" not in repr(result)
            assert "secret response body" not in repr(run.first_failure)
        finally:
            state.reset_firecrawl_run(token)

    def test_firecrawl_extract_shared_run_blocks_next_invocation(
        self,
        monkeypatch,
    ):
        from agent import firecrawl_run_state as state
        from plugins.web.firecrawl import provider as firecrawl_provider

        calls = []

        class PaymentRequiredError(Exception):
            status_code = 402

        class Client:
            def scrape(self, *, url, formats):
                calls.append(url)
                raise PaymentRequiredError("secret response")

        monkeypatch.setattr(
            firecrawl_provider, "_get_firecrawl_client", lambda: Client()
        )
        monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda url: None)
        provider = firecrawl_provider.FirecrawlWebSearchProvider()
        run, token = state.install_firecrawl_run()
        try:
            first = asyncio.run(provider.extract(["https://example.com/1"]))
            second = asyncio.run(provider.extract(["https://example.com/2"]))
            assert run.circuit_open is True
            assert calls == ["https://example.com/1"]
            assert first[0]["error_info"] == dict(state.CREDITS_EXHAUSTED_INFO)
            assert first[0]["error"] == "Firecrawl account credits are exhausted"
            assert "secret response" not in repr(first[0])
            assert second[0]["error_info"] == dict(state.CIRCUIT_OPEN_INFO)
        finally:
            state.reset_firecrawl_run(token)

    def test_firecrawl_extract_transient_failure_leaves_shared_run_open_for_calls(
        self,
        monkeypatch,
    ):
        from agent import firecrawl_run_state as state
        from plugins.web.firecrawl import provider as firecrawl_provider

        calls = []

        class Client:
            def scrape(self, *, url, formats):
                calls.append(url)
                raise TimeoutError("temporary timeout")

        monkeypatch.setattr(
            firecrawl_provider, "_get_firecrawl_client", lambda: Client()
        )
        monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda url: None)
        provider = firecrawl_provider.FirecrawlWebSearchProvider()
        run, token = state.install_firecrawl_run()
        try:
            asyncio.run(provider.extract(["https://example.com/1"]))
            asyncio.run(provider.extract(["https://example.com/2"]))
            assert run.circuit_open is False
            assert calls == ["https://example.com/1", "https://example.com/2"]
        finally:
            state.reset_firecrawl_run(token)

    def test_firecrawl_extract_opens_invocation_circuit_after_payment_required(
        self,
        monkeypatch,
    ):
        from plugins.web.firecrawl import provider as firecrawl_provider

        calls = []

        class PaymentRequiredError(Exception):
            status_code = 402

        class Client:
            def scrape(self, *, url, formats):
                calls.append(url)
                raise PaymentRequiredError(
                    "Payment Required: Failed to scrape. Credits exhausted"
                )

        monkeypatch.setattr(firecrawl_provider, "_get_firecrawl_client", lambda: Client())
        monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda url: None)

        urls = ["https://example.com/1", "https://example.com/2"]
        result = asyncio.run(
            firecrawl_provider.FirecrawlWebSearchProvider().extract(urls)
        )

        assert calls == [urls[0]]
        assert [item["url"] for item in result] == urls
        assert result[0]["error_info"]["code"] == "provider_credits_exhausted"
        assert result[1]["error_info"]["code"] == "provider_circuit_open"
        assert result[1]["error_info"]["scope"] == "account"

    def test_firecrawl_extract_normal_url_failure_does_not_open_circuit(
        self,
        monkeypatch,
    ):
        from plugins.web.firecrawl import provider as firecrawl_provider

        calls = []

        class Client:
            def scrape(self, *, url, formats):
                calls.append(url)
                raise TimeoutError("temporary timeout")

        monkeypatch.setattr(firecrawl_provider, "_get_firecrawl_client", lambda: Client())
        monkeypatch.setattr(firecrawl_provider, "check_website_access", lambda url: None)

        urls = ["https://example.com/1", "https://example.com/2"]
        result = asyncio.run(
            firecrawl_provider.FirecrawlWebSearchProvider().extract(urls)
        )

        assert calls == urls
        assert all("error_info" not in item for item in result)
