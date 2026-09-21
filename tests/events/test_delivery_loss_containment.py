"""The abandoned-delivery event must never re-enter the lane that dropped it.

TelegramNotifier, DigestComposer and WhatsAppEscalator all deliver THROUGH
cron.scheduler._deliver_result, which is the function that abandons the send in
the first place. So an AGENT_ERROR reporting a dropped delivery, routed
normally, is a delivery -> event -> delivery cycle that arms exactly when the
transport is already failing. These tests pin the two structural cut points and
the one surface the event IS supposed to reach (the digest).
"""

import json

import pytest

from events.bus import EventBus
from events.failure_eligibility import failure_cluster_eligible
from events.routing_policy import classify
from events.schema import Event, EventType, Priority
from events.subscribers.telegram_notifier import TelegramNotifier

from events.delivery_loss import DELIVERY_LOSS_SOURCE


def _loss_event(**overrides):
    payload = {
        "error": "cron delivery abandoned (telegram, timeout)",
        "abandoned": True,
        "job_id": "event-bus",
        "platform": "telegram",
        "target": "telegram:-1003925553573",
        "error_class": "timeout",
        "detail": "Telegram send failed: Timed out",
        "retried": False,
    }
    payload.update(overrides.pop("payload", {}))
    return Event.create(
        EventType.AGENT_ERROR, overrides.pop("source", DELIVERY_LOSS_SOURCE),
        payload, priority=Priority.HIGH, **overrides,
    )


@pytest.fixture
def bus(tmp_path):
    return EventBus(db_path=tmp_path / "events" / "event_bus.db")


@pytest.fixture
def topics_config(tmp_path):
    config = {
        "group_chat_id": "-1001234567890",
        "topics": {
            "watchdog_alerts": {"thread_id": 100, "name": "Watchdog Alerts"},
            "scribe_daily": {"thread_id": 105, "name": "Scribe Daily"},
            "security_and_system": {"thread_id": 106, "name": "Security & System"},
        },
    }
    path = tmp_path / "telegram" / "topics.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def verbosity_config(tmp_path):
    path = tmp_path / "notifications" / "verbosity.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"watchdog_alerts": {"mode": "all"}}), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Cut 1: chat delivery
# --------------------------------------------------------------------------

def test_telegram_notifier_never_delivers_an_abandoned_delivery_to_chat(
    bus, topics_config, verbosity_config,
):
    sent = []
    notifier = TelegramNotifier(
        bus, topics_path=topics_config, verbosity_path=verbosity_config,
        send_fn=lambda chat_id, thread_id, msg: sent.append(msg),
    )

    notifier.handle(_loss_event())

    assert sent == []


def test_the_suppression_is_scoped_to_this_source_only(
    bus, topics_config, verbosity_config,
):
    """A guard that swallowed every AGENT_ERROR would silence real alerts.

    Without this the first test passes just as well with a far too wide guard,
    which is the failure mode that matters here.
    """
    sent = []
    notifier = TelegramNotifier(
        bus, topics_path=topics_config, verbosity_path=verbosity_config,
        send_fn=lambda chat_id, thread_id, msg: sent.append(msg),
    )

    notifier.handle(_loss_event(source="jobflow-applier"))

    assert sent, "an ordinary AGENT_ERROR must still reach chat"


def test_the_event_still_reaches_the_bus_for_audit_and_the_digest():
    """Suppression is chat-only. audit_logger writes every bus event to
    audit.jsonl, and that file is what the daily triage counts."""
    route = classify(_loss_event())
    assert route is not None, "the event must still classify (no silent drop on the bus)"


# --------------------------------------------------------------------------
# Cut 2: WhatsApp paging
# --------------------------------------------------------------------------

def test_an_abandoned_delivery_is_not_failure_evidence_for_clustering():
    """3 of these in 15 min would otherwise page Diego on WhatsApp -- over a
    lane that also delivers via _deliver_result, i.e. the one that is failing.
    A dropped delivery is a monitored condition observed by the scheduler, not
    a failed execution of it: the same category as MODEL_RATE_LIMITED."""
    assert failure_cluster_eligible(_loss_event()) is False


def test_ordinary_agent_errors_remain_cluster_eligible():
    assert failure_cluster_eligible(_loss_event(source="jobflow-applier")) is True


# --------------------------------------------------------------------------
# The surface it IS meant to reach
# --------------------------------------------------------------------------

def test_the_digest_counts_repeats_as_one_system_health_row(tmp_path):
    from events.subscribers.digest_composer import DigestComposer

    composer = DigestComposer(EventBus(db_path=tmp_path / "events" / "event_bus.db"))
    digest = composer._format_digest([_loss_event() for _ in range(51)])

    assert "SYSTEM HEALTH" in digest
    assert f"{DELIVERY_LOSS_SOURCE}: cron delivery abandoned (telegram, timeout)" in digest
    assert "(x51)" in digest


def test_the_digest_does_not_mistake_it_for_an_event_bus_lag_alert(tmp_path):
    """digest_composer has a `source == "event-bus" and AGENT_ERROR` branch that
    `continue`s into the subscriber-lag rollup. Landing there would read the
    absent `subscriber_id`/`lag` keys and drop the row entirely -- so the source
    string must stay OUT of that branch."""
    from events.subscribers.digest_composer import DigestComposer

    composer = DigestComposer(EventBus(db_path=tmp_path / "events" / "event_bus.db"))
    digest = composer._format_digest([_loss_event()])

    assert "subscribers fell behind" not in digest


def test_a_burst_of_abandoned_deliveries_never_pages_whatsapp(bus):
    """The predicate test above pins the mechanism; this pins the OBSERVABLE.

    WhatsAppEscalator gates AGENT_ERROR on failure_cluster_eligible AND a
    3-in-15-minutes cluster. At the measured rates (peak 37/day, 51 repeats of
    one Telegram timeout across three days of logs) that threshold is routine,
    and the page would go out over a lane that also delivers through
    _deliver_result -- i.e. the one already dropping messages.
    """
    from events.subscribers.whatsapp_escalator import WhatsAppEscalator

    escalator = WhatsAppEscalator(bus)
    events = [_loss_event() for _ in range(10)]

    assert not any(escalator.should_escalate(e) for e in events)


def test_a_burst_of_ordinary_agent_errors_still_pages_whatsapp(bus):
    """Control: without this, the test above passes just as well if the
    escalator were broken outright, or if the cluster threshold never trips in
    this harness -- neither of which would say anything about the new guard."""
    from events.subscribers.whatsapp_escalator import WhatsAppEscalator

    escalator = WhatsAppEscalator(bus)
    events = [_loss_event(source="jobflow-applier") for _ in range(10)]

    assert any(escalator.should_escalate(e) for e in events)
