"""Countability boundary for an ABANDONED cron/notification delivery.

``cron.scheduler_delivery._deliver_standalone`` is the end of the line for a
message that was generated, rendered and attempted: when the standalone sender
comes back with an error the function logs ``ERROR cron.scheduler: Job '<id>':
delivery error: ...`` and gives up. Nothing else happened -- no event, no
counter -- so a lost alert reached neither the operator nor the daily triage.
158 such drops sat in the rotated gateway error logs on 2026-09-20 (68 WhatsApp
connect refusals, 51 Telegram ``Timed out``, 39 Telegram ``ConnectError``), a
9+ day standing condition that nothing on the bus could see. This module is the
missing half: it makes the LOSS countable.

It deliberately does NOT retry, and nothing here should grow into one. An
ambiguous ``TimedOut`` may already have reached the platform -- the Telegram
adapter retries only the provably-pre-send classes (pool/connect timeouts) and
fails closed on the rest to avoid a DUPLICATE alert, and
``tools/send_message_tool`` takes the same stance. Re-sending here would
override that decision from the one place that cannot tell the cases apart.

Design constraints (this code runs when something is ALREADY broken):

* **Never raises, never blocks.** Every failure mode degrades to a debug log
  and ``False``. A failure path that can fail loudly is worse than no failure
  path at all.
* **Cannot feed the loop it reports.** The notification subscribers
  (TelegramNotifier, DigestComposer, WhatsAppEscalator) deliver THROUGH
  ``_deliver_result``, so a dropped alert emitting an event that is itself
  delivered to chat would be a delivery -> event -> delivery cycle, and it
  would arm exactly when the transport is already failing. Containment is
  structural rather than rate-based, and lives at the two consumers:
  ``TelegramNotifier.handle`` drops this source before delivery (the same
  bus-only treatment the ``event-bus`` lag alerts get), and
  ``events.failure_eligibility`` keeps it out of failure clustering so the
  WhatsApp escalator cannot page on it. What remains is the digest, where
  ``DigestComposer`` rolls AGENT_ERROR into SYSTEM HEALTH: one line per
  (platform, error class), counted.
* **AGENT_ERROR, not a new type.** A dedicated type would need a routing-policy
  spec, an icon, a digest rollup branch and coverage-test entries, and would
  land at ``WARN``/``watchdog_alerts``/``wa=urgent`` anyway -- a per-event
  Telegram send plus a WhatsApp page per cluster. AGENT_ERROR is already
  rolled into the digest and costs nothing extra.
* **Scope is the STANDALONE abandonment only.** Two neighbouring losses are
  deliberately NOT covered here, so that absence reads as a boundary rather
  than an oversight: a relay-fronted target (relay owns the credential, there
  is no standalone fallback, and the loss belongs to the live lane), and the
  live-adapter lane's own failures, which fall back to standalone and are
  counted here only when that fallback also fails. Neither appears in the
  measured population -- all 158 logged drops came through the standalone
  sender's result dict. Widening to them means auditing
  ``_deliver_via_live_adapter``, which is a separate piece of work.
* **The digest's own delivery can feed one row back.** DigestComposer ships
  the digest through the same ``_deliver_result``, so a digest that fails to
  send emits one loss event which lands in the NEXT digest. That is bounded --
  one row per digest period, not per event, and the period is a schedule
  rather than a per-event trigger -- so it settles instead of amplifying.
* **Stable ``error`` key.** ``DigestComposer`` groups SYSTEM HEALTH rows on
  ``f"{source}: {payload['error'][:100]}"``. The job id and chat id therefore
  stay out of ``error`` (they ride in their own payload fields for
  ``audit.jsonl``), or 51 identical timeouts render as 51 one-off rows instead
  of one ``(x51)`` -- losing the countability this exists to provide.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Bus ``source`` for every event emitted here. Both containment points key on
#: this exact string, so it is API: see ``TelegramNotifier.handle`` and
#: ``events.failure_eligibility.failure_cluster_eligible``.
DELIVERY_LOSS_SOURCE = "cron-delivery"

_DETAIL_LIMIT = 500

# Coarse classes for the SYSTEM HEALTH grouping key. Ordered: the first match
# wins, so the more specific patterns come first. Every pattern below is drawn
# from a message shape actually measured in
# profiles/main/logs/errors-gateway.log* -- resist adding speculative ones,
# "other" is a perfectly good answer and keeps the raw text in `detail`.
_ERROR_CLASS_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("rate_limited", re.compile(r"flood control|rate.?limit|too many requests|retry in \d", re.I)),
    ("auth", re.compile(r"unauthoriz|forbidden|invalid token|authentication|401|403", re.I)),
    ("timeout", re.compile(r"timed out|timeout", re.I)),
    ("connection", re.compile(
        r"connecterror|cannot connect|connection (refused|reset|aborted|error)"
        r"|getaddrinfo|refused the network|unreachable|ssl", re.I)),
)


def classify_delivery_error(error: Optional[str]) -> str:
    """Coarse class for a delivery error message: the digest's grouping axis.

    Never raises; an unrecognised (or empty) message is ``"other"``, which is a
    real answer rather than a failure -- the verbatim text still rides in the
    event's ``detail``.
    """
    text = str(error or "")
    for label, pattern in _ERROR_CLASS_PATTERNS:
        if pattern.search(text):
            return label
    return "other"


def _redact(value: Any, limit: int) -> str:
    """Force-redact a value for the bus, bounded. Falls back to truncation only
    if the redactor itself is unavailable -- an unredacted secret must never be
    the fallback, so a redactor failure yields the empty string instead."""
    text = str(value or "")
    try:
        from agent.redact import redact_sensitive_text

        return redact_sensitive_text(text, force=True, redact_url_credentials=True)[:limit]
    except Exception:
        logger.debug("delivery-loss redaction unavailable; dropping detail")
        return ""


def emit_delivery_abandoned(
    *,
    job_id: Optional[str],
    platform: Optional[str],
    target: Optional[str],
    error: Optional[str],
    bus: Any = None,
) -> bool:
    """Record that one standalone delivery was attempted and lost. Returns True
    if an event reached the bus.

    Never raises. ``bus`` is injectable for tests; production passes None and an
    ``EventBus()`` is built lazily (``cron`` carries no events import).
    """
    try:
        from events.schema import EventType, Priority

        error_class = classify_delivery_error(error)
        safe_platform = _redact(platform, 64) or "unknown"
        # The grouping key the digest counts on: platform + class only.
        summary = f"cron delivery abandoned ({safe_platform}, {error_class})"[:100]
        payload = {
            "error": summary,
            "abandoned": True,
            "job_id": _redact(job_id, 200) or "unknown",
            "platform": safe_platform,
            "target": _redact(target, 200) or "unknown",
            "error_class": error_class,
            "detail": _redact(error, _DETAIL_LIMIT),
            # Says out loud, in audit.jsonl, that no retry was attempted --
            # so a later reader does not mistake the gap for a retry that
            # also failed. See the module docstring.
            "retried": False,
        }

        if bus is None:
            from events.bus import EventBus

            bus = EventBus()

        bus.emit(
            event_type=EventType.AGENT_ERROR,
            source=DELIVERY_LOSS_SOURCE,
            payload=payload,
            priority=Priority.HIGH,
            job_id=payload["job_id"],
        )
        return True
    except Exception:  # pragma: no cover - the failure path must never fail loudly
        logger.debug("emit_delivery_abandoned failed (swallowed)", exc_info=True)
        return False
