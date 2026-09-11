"""Loud-failure boundary for the agent loop (SR-471 / ADR-0024 §3).

R57 ran silently for hours because the agent loop classified a *library*
``TypeError`` (the openai parse_response crash on ``output=None``) as a
non-retryable "programming bug", returned an empty-response result, and emitted
NO alert. The traceback half was closed by ``exc_info=True`` at
``run_agent.py:10783``; this module is the **alert half**: it emits an
``AGENT_LOOP_FAULT`` bus event for ANY unhandled stream-accumulation exception,
**ignoring the upstream non-retryable classification** — silence is the bug.

Design constraints:
* Best-effort: it must NEVER raise and NEVER block the agent loop (it is called
  from ``run_agent.py``'s abort path). Every failure mode degrades to a debug log.
* Lazy bus access: ``run_agent`` has no events imports; the bus is constructed
  here (``EventBus()`` defaults to the canonical ``~/.hermes/events/event_bus.db``).
* One event per caught exception: downstream subscribers own debounce/coalescing;
  the boundary must not silently discard later failures from the same process.
* Sanitized payload: exception text and traceback are force-redacted before they
  cross the event-bus boundary.
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Any, Optional

logger = logging.getLogger(__name__)

def _resolve_source(source_hint: Optional[str]) -> str:
    """Best-effort canonical agent identity for the fault.

    Prefers explicit env hints, then the caller's hint (e.g. log_prefix), then
    'agent-loop'. Normalised through canonical_agent_source so it lines up with
    the FailureClusterDetector / watchdog_alerts taxonomy.
    """
    raw = (
        os.environ.get("HERMES_CRON_JOB_NAME")
        or os.environ.get("HERMES_AGENT_SOURCE")
        or (source_hint or "")
    )
    raw = raw.strip().strip("[]").strip()
    if not raw:
        raw = "agent-loop"
    try:
        from events.producers.agent_source_mapping import canonical_agent_source
        return canonical_agent_source(raw)
    except Exception:
        return raw


def emit_agent_loop_fault(
    exc: BaseException,
    *,
    source_hint: Optional[str] = None,
    phase: str = "stream_accumulation",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status_code: Optional[int] = None,
    correlation_id: Optional[str] = None,
    bus: Any = None,
) -> bool:
    """Emit an AGENT_LOOP_FAULT event for ``exc``. Returns True if emitted.

    Never raises. ``bus`` is injectable for tests; production passes None and
    an EventBus() is built lazily.
    """
    try:
        from events.schema import EventType, Priority

        from agent.redact import redact_sensitive_text

        source = _resolve_source(source_hint)
        redact = lambda value, limit: redact_sensitive_text(
            str(value or ""),
            force=True,
            redact_url_credentials=True,
        )[:limit]
        safe_source = redact(source, 200) or "agent-loop"
        exc_type = redact(type(exc).__name__, 200) or "Exception"
        redacted_traceback = redact_sensitive_text(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            force=True,
            redact_url_credentials=True,
        )
        tb_tail = redacted_traceback[-2000:]
        safe_provider = redact(provider, 200)
        safe_model = redact(model, 200)
        safe_correlation_id = redact(correlation_id, 200)
        safe_status_code = (
            status_code
            if isinstance(status_code, int) and not isinstance(status_code, bool)
            else None
        )
        payload = {
            "exception_type": exc_type,
            "error_class": exc_type,
            "message": redact(exc, 500),
            "phase": redact(phase, 200),
            "provider": safe_provider,
            "model": safe_model,
            "status_code": safe_status_code,
            "backend": {
                "provider": safe_provider,
                "model": safe_model,
                "status_code": safe_status_code,
            },
            "correlation_id": safe_correlation_id,
            "traceback_tail": tb_tail,
        }

        if bus is None:
            from events.bus import EventBus
            bus = EventBus()

        bus.emit(
            event_type=EventType.AGENT_LOOP_FAULT,
            source=safe_source,
            payload=payload,
            priority=Priority.HIGH,
            correlation_id=safe_correlation_id or None,
        )
        logger.info("Emitted AGENT_LOOP_FAULT (%s) from %s", exc_type, safe_source)
        return True
    except Exception:  # pragma: no cover - alerting must never break the loop
        logger.debug("emit_agent_loop_fault failed (swallowed)")
        return False
