"""Transport registry for provider response normalization.
    transport = get_transport("anthropic_messages")
    result = transport.normalize_response(raw_response)"""

import contextlib
import importlib

from agent.transports.types import (
    NormalizedResponse,
    ToolCall,
    Usage,
    build_tool_call,
    map_finish_reason,
)

# Deliberate re-export: these live in .types but are part of this package's
# public surface, so `from agent.transports import NormalizedResponse` works.
# Declared in __all__ rather than suppressed with a `noqa: F401` directive — a
# trailing suppression on the closing paren above was INERT, because ruff
# attributes F401 to the individual name lines, not to the line the statement
# ends on. It read as a live suppression for as long as the F group was off.
# Names listed here are "used" as far as F401 is concerned, and the intent is
# stated rather than silenced.
#
# The directive above is spelled without its leading "#" on purpose: ruff scans
# comment text for that marker anywhere in the line, so quoting it in prose
# creates a real directive. Spelled in full it made this very comment both an
# invalid-code warning and, on the next line, a bare blanket suppression —
# the exact inert-noqa trap the paragraph is describing.
__all__ = [
    "NormalizedResponse",
    "ToolCall",
    "Usage",
    "build_tool_call",
    "map_finish_reason",
    "get_transport",
    "register_transport",
]

_REGISTRY: dict = {}
_discovered: bool = False
_TRANSPORT_MODULES = ("anthropic", "codex", "chat_completions", "bedrock")


def register_transport(api_mode: str, transport_cls: type) -> None:
    """Register a transport class for an api_mode string."""
    _REGISTRY[api_mode] = transport_cls


def get_transport(api_mode: str):
    """Return a transport instance for ``api_mode``, or None so callers can fall back to the legacy path."""
    # A directly-imported transport leaves the registry partial; (re)discover on first use and on misses.
    if not _discovered or api_mode not in _REGISTRY:
        _discover_transports()
    cls = _REGISTRY.get(api_mode)
    return None if cls is None else cls()


def _discover_transports() -> None:
    """Import all transport modules to trigger auto-registration."""
    global _discovered
    _discovered = True
    for name in _TRANSPORT_MODULES:
        with contextlib.suppress(ImportError):
            importlib.import_module(f"agent.transports.{name}")
