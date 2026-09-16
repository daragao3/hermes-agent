"""Cross-session provider quota guard.

When a provider answers a request with a quota wall that names its own reset
time -- Codex ``usage_limit_reached`` (``resets_in_seconds`` / ``resets_at`` in the
body), an Anthropic weekly window, any ``Retry-After`` measured in minutes -- the
fact is about the ACCOUNT, not about the agent that saw it. Until 2026-09-15 it
was remembered per agent (``agent._rate_limited_until``), so every fresh cron
agent in the gateway re-tried the exhausted primary, took the 429, emitted an
``agent_loop_fault`` and only then walked the fallback chain: one Telegram alert
per cron fire for the whole reset window (measured: 10 alerts in 75 minutes on
2026-09-15 with a healthy DeepSeek fallback answering every turn).

This module records the exhaustion in a shared file so every session (CLI,
gateway, cron, auxiliary) can skip the provider before calling it, mirroring
``agent.nous_rate_guard`` -- the Nous-specific breaker that already exists for
the same reason -- but keyed by provider and populated from the error itself.

Evidence-based on purpose: an entry is written only when the response carried a
reset time at least ``MIN_RESET_SECONDS`` away. A bare 429 with no reset stays
with the per-agent exponential backoff, and a monthly wall with no date
(Kimi's "refreshed in the next cycle") records nothing rather than guessing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from utils import atomic_write_text

logger = logging.getLogger(__name__)

# Below this a reset is transient jitter (per-minute buckets, retry-after 2s), not a quota
# window that other sessions should route around. Same threshold as the Nous breaker.
MIN_RESET_SECONDS = 60.0

# Never trust a reset further out than this: a mis-parsed epoch or a provider bug must not
# bench a provider for a month. Weekly windows (the longest real one seen) fit comfortably.
MAX_RESET_SECONDS = 8 * 24 * 3600.0

_RESET_SECONDS_FIELDS = ("resets_in_seconds", "retry_after", "retry_after_seconds")
_RESET_EPOCH_FIELDS = ("resets_at", "reset_at")
_RESET_HEADERS = ("retry-after", "x-ratelimit-reset")

# Fallback for the common case where the SDK error carries the JSON body only as text:
# ``Error code: 429 - {'error': {'type': 'usage_limit_reached', ..., 'resets_in_seconds': 377072}}``
_SECONDS_IN_TEXT = re.compile(r"resets?_in_seconds['\"]?\s*[:=]\s*(\d+(?:\.\d+)?)")
_EPOCH_IN_TEXT = re.compile(r"resets?_at['\"]?\s*[:=]\s*(\d{9,11})(?:\.\d+)?")


def _state_path() -> str:
    try:
        from hermes_constants import get_hermes_home
        base = str(get_hermes_home())
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".hermes")
    return os.path.join(base, "rate_limits", "providers.json")


def _load_state() -> dict[str, dict[str, Any]]:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    path = _state_path()
    if not state:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return
    atomic_write_text(path, json.dumps(state, sort_keys=True))


def _key(provider: str) -> str:
    return str(provider or "").strip().lower()


def _positive_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _error_payloads(api_error: Any) -> list[dict]:
    """The dict-shaped places a reset field may live: ``error.body`` and ``error.body['error']``."""
    body = getattr(api_error, "body", None)
    payloads: list[dict] = []
    if isinstance(body, dict):
        payloads.append(body)
        inner = body.get("error")
        if isinstance(inner, dict):
            payloads.append(inner)
    return payloads


def _headers_of(api_error: Any, headers: Optional[Mapping[str, str]]) -> dict[str, str]:
    if headers is None:
        response = getattr(api_error, "response", None)
        headers = getattr(response, "headers", None)
    try:
        return {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    except Exception:
        return {}


def reset_seconds_from_error(
    api_error: Any, *, headers: Optional[Mapping[str, str]] = None, now: Optional[float] = None,
) -> Optional[float]:
    """Seconds until the provider says it will serve again, or None when the error names no
    reset. Order: body fields (relative, then absolute epoch), headers, then the body as it
    appears in the message text. A ``Retry-After`` HTTP-date is not parsed (never seen)."""
    now = time.time() if now is None else now
    for payload in _error_payloads(api_error):
        for field in _RESET_SECONDS_FIELDS:
            secs = _positive_float(payload.get(field))
            if secs is not None:
                return secs
        for field in _RESET_EPOCH_FIELDS:
            epoch = _positive_float(payload.get(field))
            if epoch is not None and epoch - now > 0:
                return epoch - now
    lowered = _headers_of(api_error, headers)
    for header in _RESET_HEADERS:
        secs = _positive_float(lowered.get(header))
        if secs is not None:
            # x-ratelimit-reset is an epoch on some providers and a delta on others.
            return secs - now if secs > now else secs
    text = str(getattr(api_error, "message", "") or api_error)
    m = _SECONDS_IN_TEXT.search(text)
    if m:
        return _positive_float(m.group(1))
    m = _EPOCH_IN_TEXT.search(text)
    if m:
        epoch = _positive_float(m.group(1))
        if epoch is not None and epoch - now > 0:
            return epoch - now
    return None


def record_provider_exhaustion(
    provider: str, model: str, *, api_error: Any, headers: Optional[Mapping[str, str]] = None,
    reason: str = "rate_limit",
) -> Optional[float]:
    """Record that ``provider`` is exhausted until the reset the error names. Returns the reset
    delay in seconds when an entry was written, None when the error carried no usable reset
    (nothing is written -- see the module docstring). Never raises."""
    key = _key(provider)
    if not key:
        return None
    try:
        secs = reset_seconds_from_error(api_error, headers=headers)
        if secs is None or secs < MIN_RESET_SECONDS:
            return None
        secs = min(secs, MAX_RESET_SECONDS)
        now = time.time()
        state = _load_state()
        existing = state.get(key) or {}
        # Keep the later of two resets: a second 429 seen mid-window must not shorten the memo.
        reset_at = max(now + secs, _positive_float(existing.get("reset_at")) or 0.0)
        state[key] = {
            "provider": key,
            "model": str(model or ""),
            "reason": reason,
            "reset_at": reset_at,
            "reset_at_iso": datetime.fromtimestamp(reset_at, tz=timezone.utc).isoformat(timespec="seconds"),
            "recorded_at": now,
            "error_type": type(api_error).__name__,
        }
        _save_state(state)
        logger.warning(
            "Provider quota guard: %s (%s) exhausted; other sessions will skip it for %.0fs (until %s)",
            key, model, reset_at - now, state[key]["reset_at_iso"],
        )
        return reset_at - now
    except Exception as exc:  # the guard must never break error handling
        logger.debug("Provider quota guard: could not record %s: %s", key, exc)
        return None


def provider_exhaustion_remaining(provider: str) -> Optional[float]:
    """Seconds until ``provider``'s recorded reset, or None when it is not (or no longer)
    recorded. Expired entries are pruned on read."""
    key = _key(provider)
    if not key:
        return None
    try:
        state = _load_state()
        now = time.time()
        live = {k: v for k, v in state.items()
                if isinstance(v, dict) and (_positive_float(v.get("reset_at")) or 0.0) > now}
        if len(live) != len(state):
            _save_state(live)
        entry = live.get(key)
        return (float(entry["reset_at"]) - now) if entry else None
    except Exception as exc:
        logger.debug("Provider quota guard: could not read state: %s", exc)
        return None


def clear_provider_exhaustion(provider: str) -> None:
    """Forget ``provider`` (a successful call proves the wall is down)."""
    key = _key(provider)
    if not key:
        return
    try:
        state = _load_state()
        if state.pop(key, None) is not None:
            _save_state(state)
    except Exception as exc:
        logger.debug("Provider quota guard: could not clear %s: %s", key, exc)


def format_remaining(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"
