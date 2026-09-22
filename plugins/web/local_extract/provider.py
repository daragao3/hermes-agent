"""Local page extraction: fetch the page ourselves and reduce it to readable text.

No key, no vendor, no quota. Extract-only (``supports_search`` is False); pair it with
any search backend via ``web.extract_backend: local-extract``.

Where a page's content comes from, in order:

1. JSON-LD ``JobPosting``. Nearly every ATS (Workday, Greenhouse, Lever, Ashby, iCIMS,
   Oracle) embeds one for Google for Jobs, and it is the cleanest copy of the posting on
   the page: title, company, location and the full description.
2. ``trafilatura``, when it is installed. It is optional and deliberately NOT a declared
   dependency; nothing here requires it.
3. A standard-library reader that drops script/style/nav/header/footer/aside/form/svg
   and keeps headings, paragraphs and list items.

A page that reduces to fewer than ``MIN_CHARS`` characters is returned as an error, not
as a near-empty success. That is almost always a JavaScript-rendered page, and when a
whole batch fails ``tools.web_tools_extract._dispatch_extract`` hands it to the keyless
rescue ring, whose vendors render JavaScript. A thin "success" would stop that.

Safety: ``web_extract_tool`` refuses private/internal URLs before any provider runs, but
a redirect can still land on one. Redirects are therefore followed by hand and every hop,
the first included, is checked with ``tools.url_safety.is_safe_url``. Bodies are capped
at ``MAX_BYTES``. ``httpx`` is imported lazily: plugins must stay cheap to load
(tests/hermes_cli/test_plugin_discovery_import_cost.py).
"""

from __future__ import annotations

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin

from plugins.web._common import (
    BaseWebSearchProvider, document, page_error, run_extract, search_fail, setup_schema,
)

logger = logging.getLogger(__name__)

MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 20.0
MIN_CHARS = 200

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset({"application/json", "application/ld+json"})

_LD_JSON = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


class _FetchError(Exception):
    """A fetch failure whose message is written for the model to read."""


def _fetch(url: str) -> Tuple[str, str, str]:
    """``(final_url, content_type, text)``. Raises :class:`_FetchError` on refusal or HTTP error."""
    import httpx
    from tools.url_safety import is_safe_url

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }
    current = url
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_safe_url(current):
                raise _FetchError(f"Blocked: {current} targets a private or internal network address")
            with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise _FetchError(f"HTTP {resp.status_code} redirect with no Location header")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise _FetchError(f"HTTP {resp.status_code} fetching {current}")
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise _FetchError(f"Page is larger than {MAX_BYTES:,} bytes")
                encoding = resp.charset_encoding or "utf-8"
                try:
                    text = bytes(body).decode(encoding, errors="replace")
                except LookupError:
                    text = bytes(body).decode("utf-8", errors="replace")
                return current, content_type, text
    raise _FetchError(f"More than {MAX_REDIRECTS} redirects")


# ---- HTML to text ---------------------------------------------------------------------

_SKIP = frozenset({
    "script", "style", "noscript", "template", "svg", "nav", "header", "footer",
    "aside", "form", "iframe", "button", "select",
})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCKS = frozenset({
    "p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol", "pre",
    "blockquote", "dd", "dt", "hr", "li",
})


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
        elif tag in _HEADINGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
        elif tag in _HEADINGS or tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in "".join(self.parts).split("\n")]
        lines = [line for line in lines if line and not re.fullmatch(r"[#\-\s]*", line)]
        return "\n".join(lines).strip()


def _read_html(markup: str) -> _Reader:
    reader = _Reader()
    try:
        reader.feed(markup)
        reader.close()
    except Exception as exc:  # noqa: BLE001 — html.parser is lenient; keep whatever it read
        logger.debug("local-extract: html.parser stopped early: %s", exc)
    return reader


def _html_to_text(markup: str) -> str:
    return _read_html(markup).text()


# ---- JSON-LD JobPosting ------------------------------------------------------------------

def _ld_nodes(obj: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(obj, list):
        for item in obj:
            yield from _ld_nodes(item)
    elif isinstance(obj, dict):
        yield obj
        if "@graph" in obj:
            yield from _ld_nodes(obj["@graph"])


def _is_posting(node: Dict[str, Any]) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "JobPosting" in kinds and bool(node.get("description"))


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


def _locations(value: Any) -> str:
    places = []
    for loc in value if isinstance(value, list) else [value]:
        address = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(address, dict):
            parts = [address.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
            parts = [_name(p) for p in parts if p]
            if parts:
                places.append(", ".join(parts))
        elif isinstance(address, str) and address.strip():
            places.append(address.strip())
    return "; ".join(dict.fromkeys(places))


def _job_posting(markup: str) -> Optional[Tuple[str, str]]:
    """``(title, content)`` from the first JSON-LD JobPosting with a description, else None."""
    for match in _LD_JSON.finditer(markup):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        for node in _ld_nodes(data):
            if not _is_posting(node):
                continue
            title = _name(node.get("title"))
            company = _name(node.get("hiringOrganization"))
            fields = [
                ("Company", company),
                ("Location", _locations(node.get("jobLocation"))),
                ("Remote", "yes" if str(node.get("jobLocationType", "")).upper() == "TELECOMMUTE" else ""),
                ("Employment type", ", ".join(node["employmentType"]) if isinstance(node.get("employmentType"), list)
                 else _name(node.get("employmentType"))),
                ("Posted", _name(node.get("datePosted"))),
                ("Apply by", _name(node.get("validThrough"))),
            ]
            header = [f"# {title}"] if title else []
            header += [f"{label}: {value}" for label, value in fields if value]
            body = _html_to_text(str(node["description"]))
            page_title = f"{title} at {company}" if title and company else title or company
            return page_title, "\n".join(header) + "\n\n" + body
    return None


def _trafilatura(markup: str, url: str) -> Optional[str]:
    try:
        import trafilatura  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return trafilatura.extract(markup, url=url, output_format="markdown", favor_recall=True) or None
    except Exception as exc:  # noqa: BLE001 — optional path; fall back to the stdlib reader
        logger.debug("local-extract: trafilatura failed on %s: %s", url, exc)
        return None


def _html_content(markup: str, url: str) -> Tuple[str, str]:
    posting = _job_posting(markup)
    if posting is not None:
        return posting
    reader = _read_html(markup)
    return reader.title.strip(), _trafilatura(markup, url) or reader.text()


# ---- Provider ---------------------------------------------------------------------------

class LocalExtractWebProvider(BaseWebSearchProvider):
    """Extract-only provider that needs no key and no vendor."""

    NAME = "local-extract"
    DISPLAY_NAME = "Local extract"
    KEY_ENV = ""
    EXTRACT = True

    def is_available(self) -> bool:
        return True  # nothing to configure

    def supports_search(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return search_fail(
            "local-extract only extracts pages; set web.search_backend to a search "
            "provider (e.g. brave-free or ddgs)"
        )

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        return run_extract("Local extract", logger, urls, lambda: [self._extract_one(u) for u in urls])

    def _extract_one(self, url: str) -> Dict[str, Any]:
        try:
            final_url, content_type, text = _fetch(url)
        except _FetchError as exc:
            return page_error(url, str(exc))
        except Exception as exc:  # noqa: BLE001 — network errors are per-page, never raised
            return page_error(url, f"Could not fetch {url}: {type(exc).__name__}: {exc}")

        is_html = content_type in _HTML_TYPES or (not content_type and "<html" in text[:2000].lower())
        if is_html:
            title, content = _html_content(text, final_url)
            if len(content) < MIN_CHARS:
                return page_error(
                    url,
                    f"Page reduced to {len(content)} characters of text, which usually means it is "
                    "rendered by JavaScript; nothing usable to return",
                )
        elif content_type.startswith("text/") or content_type in _TEXT_TYPES:
            title, content = "", text.strip()
        else:
            return page_error(url, f"Unsupported content type {content_type!r}: local-extract reads HTML and text")
        return document(url, title, content, source_url=final_url)

    def get_setup_schema(self) -> Dict[str, Any]:
        return setup_schema(
            "Local extract", "free · no key", "Extract only. Fetches pages directly; JSON-LD job postings first.",
        )
