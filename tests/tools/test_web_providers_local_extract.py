"""Tests for the local-extract web provider (plugins/web/local_extract).

It fetches pages itself, so these tests put an ``httpx.MockTransport`` under the
client the provider builds and stub ``tools.url_safety.is_safe_url`` where a test is
about the redirect guard.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import httpx
import pytest

from plugins.web.local_extract import provider as local
from plugins.web.local_extract.provider import LocalExtractWebProvider


def _serve(monkeypatch, handler, *, safe=lambda url: True):
    """Route the provider's httpx.Client through ``handler`` and stub the SSRF check."""
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client)
    monkeypatch.setattr("tools.url_safety.is_safe_url", safe)


def _html(body: str, head: str = "") -> str:
    return f"<html><head><title>Page title</title>{head}</head><body>{body}</body></html>"


_LONG = "Owns forecasting, planning and board reporting for the AI business. " * 6


def _extract_one(url="https://jobs.example.com/p/1"):
    [result] = LocalExtractWebProvider().extract([url])
    return result


class TestJobPosting:
    def test_json_ld_job_posting_wins_over_the_page_body(self, monkeypatch):
        posting = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Director, FP&A",
            "hiringOrganization": {"@type": "Organization", "name": "Capital One"},
            "jobLocation": [{"@type": "Place", "address": {
                "addressLocality": "McLean", "addressRegion": "VA", "addressCountry": "US"}}],
            "employmentType": ["FULL_TIME"],
            "datePosted": "2026-09-20",
            "description": f"<p>{_LONG}</p><ul><li>Lead a team of 6</li><li>SQL</li></ul>",
        }
        head = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        page = _html("<nav>Menu</nav><div>Cookie banner noise</div>", head)
        _serve(monkeypatch, lambda req: httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"}))

        result = _extract_one()

        assert "error" not in result
        assert result["title"] == "Director, FP&A at Capital One"
        content = result["content"]
        assert content.startswith("# Director, FP&A\nCompany: Capital One\nLocation: McLean, VA, US")
        assert "Employment type: FULL_TIME" in content
        assert "- Lead a team of 6" in content
        assert "Cookie banner noise" not in content, "the page body must not be mixed into a posting"

    def test_posting_inside_an_at_graph_is_found(self, monkeypatch):
        graph = {"@graph": [{"@type": "WebPage"}, {"@type": ["JobPosting"], "title": "VP Finance",
                                                    "description": _LONG}]}
        page = _html("", f'<script type="application/ld+json">{json.dumps(graph)}</script>')
        _serve(monkeypatch, lambda req: httpx.Response(200, text=page, headers={"content-type": "text/html"}))
        assert _extract_one()["title"] == "VP Finance"


class TestReader:
    def test_reader_keeps_content_and_drops_chrome(self, monkeypatch):
        page = _html(
            "<header>Site header</header><nav>Nav</nav><script>var x = 1;</script>"
            f"<main><h2>About the role</h2><p>{_LONG}</p><ul><li>One</li><li>Two</li></ul></main>"
            "<footer>Footer links</footer>"
        )
        _serve(monkeypatch, lambda req: httpx.Response(200, text=page, headers={"content-type": "text/html"}))

        result = _extract_one()

        assert result["title"] == "Page title"
        content = result["content"]
        assert "## About the role" in content
        assert "- One\n- Two" in content
        for noise in ("Site header", "Nav", "var x", "Footer links"):
            assert noise not in content

    def test_a_javascript_shell_is_an_error_not_a_thin_success(self, monkeypatch):
        """An error lets _dispatch_extract hand the batch to the keyless rescue ring."""
        page = _html('<div id="root"></div><script src="/app.js"></script>')
        _serve(monkeypatch, lambda req: httpx.Response(200, text=page, headers={"content-type": "text/html"}))

        result = _extract_one()

        assert "JavaScript" in result["error"]
        assert result["content"] == ""

    def test_plain_text_is_returned_as_is(self, monkeypatch):
        _serve(monkeypatch, lambda req: httpx.Response(200, text="short note", headers={"content-type": "text/plain"}))
        assert _extract_one()["content"] == "short note"


class TestFetchGuards:
    def test_redirect_into_a_private_address_is_blocked(self, monkeypatch):
        def handler(req):
            if req.url.host == "jobs.example.com":
                return httpx.Response(302, headers={"location": "http://127.0.0.1:8642/health"})
            return httpx.Response(200, text=_html(_LONG), headers={"content-type": "text/html"})

        _serve(monkeypatch, handler, safe=lambda url: "127.0.0.1" not in url)

        result = _extract_one()

        assert result["error"].startswith("Blocked:")
        assert "127.0.0.1" in result["error"]

    def test_safe_redirects_are_followed_and_the_final_url_recorded(self, monkeypatch):
        def handler(req):
            if req.url.path == "/p/1":
                return httpx.Response(301, headers={"location": "/p/1/canonical"})
            return httpx.Response(200, text=_html(f"<p>{_LONG}</p>"), headers={"content-type": "text/html"})

        _serve(monkeypatch, handler)

        result = _extract_one()

        assert "error" not in result
        assert result["url"] == "https://jobs.example.com/p/1"
        assert result["metadata"]["sourceURL"] == "https://jobs.example.com/p/1/canonical"

    def test_http_errors_are_per_page(self, monkeypatch):
        _serve(monkeypatch, lambda req: httpx.Response(404, text="nope"))
        assert _extract_one()["error"] == "HTTP 404 fetching https://jobs.example.com/p/1"

    def test_binary_content_is_refused(self, monkeypatch):
        _serve(monkeypatch, lambda req: httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}))
        assert "Unsupported content type 'application/pdf'" in _extract_one()["error"]

    def test_oversized_bodies_are_cut_off(self, monkeypatch):
        monkeypatch.setattr(local, "MAX_BYTES", 1000)
        _serve(monkeypatch, lambda req: httpx.Response(200, text="x" * 5000, headers={"content-type": "text/html"}))
        assert "larger than" in _extract_one()["error"]

    def test_one_bad_url_does_not_sink_the_batch(self, monkeypatch):
        def handler(req):
            if req.url.path == "/bad":
                return httpx.Response(500)
            return httpx.Response(200, text=_html(f"<p>{_LONG}</p>"), headers={"content-type": "text/html"})

        _serve(monkeypatch, handler)

        good, bad = LocalExtractWebProvider().extract(["https://a.example.com/ok", "https://a.example.com/bad"])

        assert "error" not in good
        assert bad["error"] == "HTTP 500 fetching https://a.example.com/bad"


class TestRegistration:
    def test_extract_only_and_always_available(self):
        p = LocalExtractWebProvider()
        assert p.name == "local-extract"
        assert p.is_available() is True
        assert p.supports_extract() is True
        assert p.supports_search() is False
        assert p.search("anything")["success"] is False

    def test_an_extract_only_provider_never_wins_the_shared_backend(self):
        """_get_backend() serves web_search too. local-extract is always available, so without
        the supports_search check a keyless fresh install would resolve web_search to it."""
        from tools.web_tools import _get_backend

        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {}, clear=False), \
             patch("tools.web_tools._has_env", return_value=False), \
             patch("tools.web_tools._is_tool_gateway_ready", return_value=False), \
             patch("tools.web_tools._ddgs_package_importable", return_value=False), \
             patch("tools.web_tools._list_registered_web_providers", return_value=[LocalExtractWebProvider()]), \
             patch("agent.web_search_registry._keyless_tier_enabled", return_value=False):
            assert _get_backend() == "firecrawl"


@pytest.mark.parametrize("module", ["plugins.web.local_extract.provider"])
def test_plugin_import_does_not_pull_an_http_client(module):
    """Mirrors tests/hermes_cli/test_plugin_discovery_import_cost.py: plugins load cheaply."""
    import subprocess
    import sys

    code = f"import sys, {module}; print('httpx' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=os.getcwd(),
                         env={**os.environ, "PYTHONPATH": os.getcwd()})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


class TestToolGates:
    """web_search and web_extract have separate check_fns: local-extract makes extraction always
    possible, but it must not advertise web_search on an install with no search backend."""

    def _no_search_backend(self, monkeypatch):
        from agent import web_search_registry
        from plugins.web.ddgs.provider import DDGSWebSearchProvider
        from tools import web_tools

        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {})
        for key in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "PARALLEL_API_KEY", "EXA_API_KEY",
                    "SEARXNG_URL", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "KEENABLE_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: False)
        monkeypatch.setattr(web_tools, "check_firecrawl_api_key", lambda: False)
        monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: False)
        monkeypatch.setattr(DDGSWebSearchProvider, "is_available", lambda self: False)
        monkeypatch.setattr(web_search_registry, "_keyless_tier_enabled", lambda: False)
        return web_tools

    def test_extract_is_available_with_no_credentials(self, monkeypatch):
        web_tools = self._no_search_backend(monkeypatch)
        assert web_tools.check_web_extract_available() is True

    def test_search_stays_dark_with_no_search_backend(self, monkeypatch):
        web_tools = self._no_search_backend(monkeypatch)
        assert web_tools.check_web_api_key() is False

    def test_the_tools_are_registered_on_their_own_gates(self):
        from tools import web_tools
        from tools.registry import registry

        assert registry.get_entry("web_search").check_fn is web_tools.check_web_api_key
        assert registry.get_entry("web_extract").check_fn is web_tools.check_web_extract_available
