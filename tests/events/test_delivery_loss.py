"""An abandoned standalone delivery must become a countable bus event.

Context: cron/scheduler_delivery.py::_deliver_standalone logged an ERROR and gave up,
so a notification that was generated, attempted and lost reached neither the operator
nor the daily triage. 158 such drops sat in the rotated gateway error logs on
2026-09-20 (68 WhatsApp connect refusals, 90 Telegram timeout/connect) with nothing
on the bus. This is the OBSERVABILITY half only -- the send is deliberately NOT
retried (an ambiguous TimedOut may have reached the platform; see
plugins/platforms/telegram/adapter.py's send path).
"""

import pytest

from events.schema import EventType, Priority


class _FakeBus:
    def __init__(self):
        self.emitted = []

    def emit(self, **kwargs):
        self.emitted.append(kwargs)
        return "evt-id"


class _ExplodingBus:
    def emit(self, **kwargs):
        raise RuntimeError("bus is down")


def _emit(**kwargs):
    from events.delivery_loss import emit_delivery_abandoned

    bus = kwargs.pop("bus", None) or _FakeBus()
    ok = emit_delivery_abandoned(bus=bus, **kwargs)
    return ok, bus


# --------------------------------------------------------------------------
# The event itself
# --------------------------------------------------------------------------

def test_abandoned_delivery_emits_agent_error_from_the_cron_delivery_source():
    ok, bus = _emit(
        job_id="event-bus", platform="telegram", target="telegram:-1003925553573",
        error="Telegram send failed: Timed out",
    )

    assert ok is True
    assert len(bus.emitted) == 1
    event = bus.emitted[0]
    assert event["event_type"] is EventType.AGENT_ERROR
    assert event["source"] == "cron-delivery"
    assert event["priority"] is Priority.HIGH
    payload = event["payload"]
    assert payload["job_id"] == "event-bus"
    assert payload["platform"] == "telegram"
    assert payload["target"] == "telegram:-1003925553573"
    assert payload["error_class"] == "timeout"
    assert payload["abandoned"] is True
    assert "Timed out" in payload["detail"]


def test_error_key_is_stable_so_the_digest_can_count_repeats():
    """digest_composer groups SYSTEM HEALTH rows by f"{source}: {payload['error'][:100]}".

    The varying parts (job id, chat id, raw platform text) must therefore stay OUT of
    `error`, or 51 identical Telegram timeouts render as 51 separate one-off rows
    instead of one "(x51)" line -- which is the countability this whole change is for.
    """
    _, bus_a = _emit(job_id="event-bus", platform="telegram",
                     target="telegram:-1003925553573", error="Telegram send failed: Timed out")
    _, bus_b = _emit(job_id="scribe-daily", platform="telegram",
                     target="telegram:-100999:42", error="Telegram send failed: Timed out")

    assert bus_a.emitted[0]["payload"]["error"] == bus_b.emitted[0]["payload"]["error"]
    error = bus_a.emitted[0]["payload"]["error"]
    assert len(error) <= 100
    assert "event-bus" not in error
    assert "-1003925553573" not in error
    assert "telegram" in error and "timeout" in error


def test_a_different_platform_or_class_stays_a_distinct_digest_row():
    _, tg = _emit(job_id="j", platform="telegram", target="t", error="Telegram send failed: Timed out")
    _, wa = _emit(job_id="j", platform="whatsapp", target="t",
                  error="WhatsApp send failed: Cannot connect to host localhost:3000")

    assert tg.emitted[0]["payload"]["error"] != wa.emitted[0]["payload"]["error"]


@pytest.mark.parametrize("raw,expected", [
    # Verbatim shapes measured in profiles/main/logs/errors-gateway.log* on 2026-09-20.
    ("Telegram send failed: Timed out", "timeout"),
    ("Telegram send failed: httpx.ConnectError: [Errno 11001] getaddrinfo failed", "connection"),
    ("Telegram send failed: httpx.ConnectError: ", "connection"),
    ("WhatsApp send failed: Cannot connect to host localhost:3000 ssl:default "
     "[The remote computer refused the network connection]", "connection"),
    ("Telegram send failed: Unauthorized", "auth"),
    ("Telegram send failed: Flood control exceeded. Retry in 30 seconds", "rate_limited"),
    ("Telegram send failed: Chat not found", "other"),
    ("", "other"),
])
def test_error_class_is_derived_from_the_message(raw, expected):
    _, bus = _emit(job_id="j", platform="telegram", target="t", error=raw)
    assert bus.emitted[0]["payload"]["error_class"] == expected


def test_secrets_in_the_error_text_never_reach_the_bus():
    _, bus = _emit(job_id="j", platform="telegram", target="t",
                   error="send failed: bot8112345678:AAH1bcDefGhIjKlMnOpQrStUvWxYz012345 rejected")
    detail = bus.emitted[0]["payload"]["detail"]
    assert "AAH1bcDefGhIjKlMnOpQrStUvWxYz012345" not in detail


def test_detail_is_bounded_so_one_drop_cannot_bloat_the_audit_log():
    _, bus = _emit(job_id="j", platform="telegram", target="t", error="x" * 5000)
    assert len(bus.emitted[0]["payload"]["detail"]) <= 500


# --------------------------------------------------------------------------
# The failure path must never fail loudly: it runs when something is already broken
# --------------------------------------------------------------------------

def test_a_dead_bus_is_swallowed_and_reported_as_not_emitted():
    from events.delivery_loss import emit_delivery_abandoned

    assert emit_delivery_abandoned(
        job_id="j", platform="telegram", target="t", error="boom", bus=_ExplodingBus(),
    ) is False


def test_unusable_arguments_are_survived_rather_than_raised():
    from events.delivery_loss import emit_delivery_abandoned

    bus = _FakeBus()
    assert emit_delivery_abandoned(
        job_id=None, platform=None, target=None, error=None, bus=bus,
    ) is True
    assert bus.emitted[0]["payload"]["error_class"] == "other"
