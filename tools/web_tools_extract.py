"""web_extract helpers: URL validation, provider resolution, cache-aware dispatch.

Order of controls (each is a gate, never skipped by a cache hit): secret-URL
refusal -> SSRF filter (in web_tools.web_extract_tool) -> provider resolution
(strict selection) -> per-URL website policy -> disk cache -> vendor call with
one-shot keyless rescue. Logs under the origin (tools.web_tools) logger.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from tools.tool_backend_helpers import selection_error, selection_exists
from tools.url_safety import normalize_url_for_request, sensitive_query_param_name
from tools.web_tools_rescue import _rescue_eligible, _rescue_extract

logger = logging.getLogger("tools.web_tools")

_NO_RESULT_ERROR = "Extract backend returned no result for this URL"
_EXTRACT_BACKENDS_HINT = "firecrawl, tavily, keenable, exa, or parallel."
_INVALID_ITEM_ERROR = (
    "Invalid URL item at index {}: expected a URL string or an object with a string 'url' or 'href' field"
)


def _web_extract_url(value: Any) -> Optional[str]:
    """URL from a model-supplied extract item (str, or dict with ``url``/``href``); None if unusable.

    Models sometimes forward a whole search result instead of its URL, hence the dict form. Never
    stringify arbitrary objects into misleading fetch targets.
    """
    if isinstance(value, dict):
        value = value.get("url") or value.get("href")
    return (value.strip() or None) if isinstance(value, str) else None


def _disabled_plugin_error(capability: str, disabled_key: str) -> str:
    """Error text when the configured backend's bundled plugin is disabled in config."""
    vendor = disabled_key.split("/", 1)[-1]
    return (
        f"web.{capability}_backend is set to '{vendor}', but its plugin ('{disabled_key}') is disabled "
        f"in config. Re-enable it with `hermes plugins enable {disabled_key}` "
        "(or remove it from plugins.disabled)."
    )


def _no_provider_error(capability: str, fallback: str) -> str:
    """Error when no provider resolved: point at a disabled bundled plugin if that is the real cause."""
    from agent.web_search_registry import _disabled_web_plugin_for
    disabled_key = _disabled_web_plugin_for(capability=capability)
    return _disabled_plugin_error(capability, disabled_key) if disabled_key else fallback


def _strict_selection_error(capability: str, backend: str) -> str:
    """Error for a stored-but-unregistered backend: name the disabled plugin, else the bad selection.
    Strict selection never silently switches to whatever the availability walk finds."""
    failure = f"no registered web {capability} provider has that name"
    return _no_provider_error(capability, selection_error("web", f"'{backend}'", failure))


def _result_entry(url: str, error: Optional[str]) -> Dict[str, Any]:
    return {"url": url, "title": "", "content": "", "error": error}


def _extract_error_json(error: str) -> str:
    return json.dumps({"success": False, "error": error}, ensure_ascii=False)


def _refuse_all(error: str):
    """Whole-call refusal tuple for ``_validate_extract_urls`` (exfiltration prevention)."""
    return None, None, None, json.dumps({"success": False, "error": error})


def _merge_in_order(
    total: int, fixed: Dict[int, dict], fetch_positions: List[int], fetch_urls: List[str], results: List[dict]
) -> List[dict]:
    """Rebuild a ``total``-long result list: *fixed* entries by position, fetched *results* at
    *fetch_positions* (a short provider list yields ``_NO_RESULT_ERROR`` entries for the rest)."""
    merged = dict(fixed)
    for pos, position in enumerate(fetch_positions):
        missing = _result_entry(fetch_urls[pos], _NO_RESULT_ERROR)
        merged[position] = results[pos] if pos < len(results) else missing
    return [merged[i] for i in range(total)]


def _validate_extract_urls(urls: List[Any]):
    """Normalize model-supplied items and block URLs carrying secrets (percent-encoded forms are unquoted
    and checked too). Returns ``(normalized_urls, normalized_indices, invalid_urls, blocked_json)``;
    ``blocked_json`` is a whole-call refusal (exfiltration prevention) or None."""
    from agent.redact import _PREFIX_RE
    from urllib.parse import unquote

    normalized_urls, normalized_indices, invalid_urls = [], [], {}
    for index, item in enumerate(urls):
        _url = _web_extract_url(item)
        if _url is None:
            invalid_urls[index] = _result_entry("", _INVALID_ITEM_ERROR.format(index))
            continue
        normalized_url = normalize_url_for_request(_url)
        if any(_PREFIX_RE.search(c) for c in (_url, unquote(_url), normalized_url, unquote(normalized_url))):
            return _refuse_all(
                "Blocked: URL contains what appears to be an API key or token. "
                "Secrets must not be sent in URLs."
            )
        if sensitive_query_key := sensitive_query_param_name(normalized_url):
            return _refuse_all(
                "Blocked: URL contains a credential-like query parameter "
                f"({sensitive_query_key}). Web extract backends are third-party "
                "readers; remove the sensitive query parameter or use a local "
                "browser session when this access is explicitly required."
            )
        normalized_urls.append(normalized_url)
        normalized_indices.append(index)
    return normalized_urls, normalized_indices, invalid_urls, None


def _resolve_extract_provider(backend: str):
    """Resolve the extract provider for *backend*; returns ``(provider, error_json)``.

    A registered search-only backend is a typed error (never a silent switch). An unregistered name with
    a stored web selection is a strict-selection error; with no selection, fall through to the walk.
    """
    from agent.web_search_registry import get_active_extract_provider, get_provider as _wsp_get_provider
    provider = _wsp_get_provider(backend) if backend else None
    if provider is not None and provider.supports_extract():
        return provider, None
    if provider is not None:
        return None, _extract_error_json(
            f"{provider.display_name} is a search-only backend and cannot extract URL content. "
            "Set web.extract_backend to " + _EXTRACT_BACKENDS_HINT
        )
    if backend and selection_exists("web"):
        return None, _extract_error_json(_strict_selection_error("extract", backend))
    provider = get_active_extract_provider()
    if provider is None:
        fallback = "No web extract provider configured. Set web.extract_backend to " + _EXTRACT_BACKENDS_HINT
        return None, _extract_error_json(_no_provider_error("extract", fallback))
    return provider, None


async def _dispatch_extract(provider, fetch_urls: List[str], format: Optional[str]) -> List[dict]:
    """Call ``provider.extract`` (async or sync-in-thread), with one-shot keyless rescue.

    Rescue fires on a raised exception or when the WHOLE batch failed (backend outage, not per-page
    problems). Rescued batches are never cached.
    """
    import inspect
    from tools.web_result_cache import extract_cache_put
    try:
        if inspect.iscoroutinefunction(provider.extract):
            results = await provider.extract(fetch_urls, format=format)
        else:  # sync extract() runs in a thread so network I/O never blocks the loop
            results = await asyncio.to_thread(provider.extract, fetch_urls, format=format)
    except Exception as exc:  # noqa: BLE001 — candidate for rescue
        if not _rescue_eligible(provider):
            raise
        failed = [_result_entry(u, str(exc)) for u in fetch_urls]
        return await asyncio.to_thread(_rescue_extract, provider.name, fetch_urls, failed)
    if results and all(r.get("error") for r in results) and _rescue_eligible(provider):
        return await asyncio.to_thread(_rescue_extract, provider.name, fetch_urls, results)

    # Cache each successful fetch's full clean text (best-effort; oversized skipped).
    for url, fetched in zip(fetch_urls, results):
        _content = fetched.get("raw_content", "") or fetched.get("content", "")
        if _content and not fetched.get("error"):
            extract_cache_put(url, _content, fetched.get("title", ""), format=format, provider=provider.name)
    # AFTER the cache loop, on purpose: that loop keys on provider.name, so running the
    # fallback first would store the FALLBACK's content under the PRIMARY's key and serve it
    # for the whole TTL as if Firecrawl had produced it. Here, fallback results are simply
    # never cached — the same rule upstream already applies to rescued batches — and nothing
    # is lost, because credit-blocked entries carry an `error` and the loop skipped them.
    return await _serve_credit_blocked_from_fallback(results, fetch_urls, format)


async def _invoke_extract_provider(provider, urls: List[str], *, format: Optional[str]) -> List[dict]:
    """``provider.extract`` whether it is async or sync (sync runs in a thread)."""
    import inspect

    if inspect.iscoroutinefunction(provider.extract):
        return await provider.extract(urls, format=format)
    return await asyncio.to_thread(provider.extract, urls, format=format)


async def _serve_credit_blocked_from_fallback(
    results: List[dict], fetch_urls: List[str], format: Optional[str],
) -> List[dict]:
    """Re-extract the entries Firecrawl refused for lack of credits, via another provider."""
    blocked = [(i, fetch_urls[i]) for i, r in enumerate(results)
               if _is_firecrawl_credit_result(r)]
    if not blocked:
        return results
    fallback = _resolve_run_fallback("extract")
    if fallback is None:
        return results

    from tools.website_policy import check_website_access as _check_site

    retry: List[tuple] = []
    for index, url in blocked:
        # Re-checked deliberately: the primary's policy check happened inside a provider that
        # then refused to fetch. A different provider is a different fetch, and a blocked URL
        # must not slip through because the first attempt failed for an unrelated reason.
        try:
            policy = _check_site(url)
        except Exception:  # noqa: BLE001 — policy errors fail open, as in dispatch
            policy = None
        if policy:
            results[index] = {"url": url, "title": "", "content": "",
                              "error": policy["message"],
                              "blocked_by_policy": {k: policy[k]
                                                    for k in ("host", "rule", "source")}}
        else:
            retry.append((index, url))
    if not retry:
        return results
    try:
        fetched = await _invoke_extract_provider(
            fallback, [url for _i, url in retry], format=format)
        if not isinstance(fetched, list):
            fetched = []
    except Exception:  # noqa: BLE001 — a failed fallback degrades per URL, never the batch
        fetched = [
            _result_entry(url, "Fallback extract failed for this URL")
            for _index, url in retry
        ]
    return _merge_credit_fallback_results(results, fetched, retry)


# --- Firecrawl credit exhaustion: serve from another provider ---------------------------------

_FIRECRAWL_CREDIT_CODES = frozenset(
    {"provider_credits_exhausted", "provider_circuit_open"}
)


def _is_firecrawl_credit_result(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    error_info = value.get("error_info")
    return bool(
        isinstance(error_info, dict)
        and error_info.get("provider") == "firecrawl"
        and error_info.get("code") in _FIRECRAWL_CREDIT_CODES
    )


def _resolve_run_fallback(capability: str):
    from agent.firecrawl_run_state import get_or_select_fallback_provider
    from agent.web_search_registry import get_fallback_provider

    return get_or_select_fallback_provider(
        capability,
        lambda: get_fallback_provider(
            capability,
            excluded=frozenset({"firecrawl"}),
        ),
    )


def _incomplete_extract_result(url: str) -> Dict[str, Any]:
    return {
        "url": url,
        "title": "",
        "content": "",
        "error": "Extract backend returned no usable result for this URL",
    }


def _merge_credit_fallback_results(primary, fallback, urls):
    """Replace credit-blocked entries with the fallback's answer for the SAME url.

    Matched by URL, never by position: a fallback that raises, returns a short list, or reorders
    would otherwise attribute one page's content to another URL. Anything left unmatched becomes
    an explicit no-result entry rather than silently keeping the billing error."""
    by_url = {}
    for entry in fallback or ():
        if isinstance(entry, dict) and entry.get("url"):
            by_url.setdefault(str(entry["url"]), []).append(entry)
    merged = list(primary)
    for index, url in urls:
        candidates = by_url.get(url, [])
        candidate = candidates.pop(0) if candidates else None
        merged[index] = dict(candidate) if candidate else _incomplete_extract_result(url)
    return merged


async def _extract_safe_urls(provider, safe_urls: List[str], format: Optional[str]) -> List[dict]:
    """Serve cache hits, fetch the rest, and merge back in ``safe_urls`` order.

    The disk cache (tools/web_result_cache.py) sits AFTER the secret-URL gate, SSRF gate, and provider
    resolution, and is gated per-URL on the website policy — a hit skips only the vendor call, never a
    control; policy-blocked URLs are cache misses. Keys include provider and format, so switching either
    within the TTL never serves the other's content."""
    from tools.web_result_cache import extract_cache_get
    from tools.website_policy import check_website_access as _check_site
    cached_results, fetch_urls, fetch_positions = {}, [], []
    for position, url in enumerate(safe_urls):
        try:
            _policy_block = _check_site(url)
        except Exception:  # noqa: BLE001 — policy errors fail open like dispatch
            _policy_block = None
        hit = extract_cache_get(url, format=format, provider=provider.name) if _policy_block is None else None
        if hit is not None:
            cached_results[position] = hit
        else:
            fetch_urls.append(url)
            fetch_positions.append(position)

    if not fetch_urls:
        return [cached_results[i] for i in range(len(safe_urls))]
    logger.info("Web extract via %s: %d URL(s)", provider.name, len(fetch_urls))
    results = await _dispatch_extract(provider, fetch_urls, format)
    if not cached_results:
        return results
    return _merge_in_order(len(safe_urls), cached_results, fetch_positions, fetch_urls, results)
