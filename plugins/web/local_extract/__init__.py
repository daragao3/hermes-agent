"""Local page extraction plugin (no vendor) — bundled, auto-loaded."""
from __future__ import annotations
from plugins.web.local_extract.provider import LocalExtractWebProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(LocalExtractWebProvider())
