"""``cron.scheduler._deliver_result`` RETURNS its error; it does not raise.

The four event-bus subscribers that deliver through it all wrapped the call
in ``try/except`` and threw the return value away. ``except`` therefore never
fired on an abandoned send, and each caller went on to do whatever it does on
success. In ``TelegramNotifier._deliver`` that meant emitting
NOTIFICATION_DELIVERED and returning ``True`` for a message the chat never
received -- a FALSE SUCCESS on the very ledger an operator would consult to
answer "did that alert arrive". 158 abandoned deliveries sat in
``errors-gateway.log{,.1,.2}`` on 2026-09-20 (68 WhatsApp connect refusals,
51 Telegram ``Timed out``, 39 Telegram ``ConnectError``), so the bus has been
carrying one false success per drop for at least nine days.

The contract is documented on ``_deliver_result`` itself: "Returns None on
success, else an error." ``WhatsAppEscalator._deliver`` (whatsapp_escalator.py
~803) already read it and is the model these tests generalize from.

NO RETRY IS TESTED, AND NONE MAY BE ADDED. An ambiguous ``TimedOut`` may
already have reached the platform; ``plugins/platforms/telegram/adapter.py``
retries only the provably-pre-send classes and fails closed on the rest, and
``tools/send_message_tool.py`` takes the same stance ("a retry would duplicate
it"). ``test_error_return_does_not_resend`` pins exactly one send attempt in
each caller so a future "helpful" retry lands as a test failure rather than a
duplicate 3am alert.

NO NEW COUNTER, EITHER. ``events/delivery_loss.py`` already emits the
AGENT_ERROR that makes the LOSS countable, from inside the scheduler's
standalone lane -- i.e. it fires for these same drops. These callers must
therefore record the outcome they own (the notifier's per-event reverse
signal; a log line everywhere else) and must NOT emit a second
loss event, or every drop would be counted twice.
"""

import json
import logging
from unittest.mock import patch

import pytest

from events.bus import EventBus
from events.schema import Event, EventType, Priority
from events.subscribers.digest_composer import DigestComposer
from events.subscribers.telegram_mirror import TelegramMirror
from events.subscribers.telegram_notifier import TelegramNotifier
from events.subscribers.whatsapp_escalator import WhatsAppEscalator

# A verbatim abandonment string as _deliver_result composes it: the target
# suffix is appended by _deliver_standalone, and the whole is joined from
# ``delivery_errors``. Tests assert on the substring an operator would grep.
TIMED_OUT = (
    "delivery error: Telegram send failed: Timed out "
    "(target telegram:-1001234567890:101)"
)
WA_REFUSED = (
    "delivery error: WhatsApp send failed: "
    "[Errno 111] Connection refused (target whatsapp)"
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
            "jobflow_firehose": {"thread_id": 101, "name": "JobFlow Firehose"},
            "scribe_daily": {"thread_id": 105, "name": "Scribe Daily"},
            "action_required": {"thread_id": 110, "name": "Action Required"},
        },
    }
    path = tmp_path / "telegram" / "topics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def verbosity_config(tmp_path):
    path = tmp_path / "telegram" / "verbosity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"jobflow_firehose": {"mode": "all"},
                    "watchdog_alerts": {"mode": "all"}}),
        encoding="utf-8",
    )
    return path


def _notifier(bus, topics_config, verbosity_config):
    return TelegramNotifier(
        bus, topics_path=topics_config, verbosity_path=verbosity_config,
    )


def _emit_deliverable(bus):
    """Emit an INFO-class event that routes to immediate (non-batched)
    delivery, and hand back the Event object as handle() receives it."""
    bus.emit(
        event_type=EventType.APPLICATION_SUBMITTED, source="applier",
        payload={"title": "Engineer", "company": "Beta"},
        priority=Priority.NORMAL,
    )
    return bus.query(event_type=EventType.APPLICATION_SUBMITTED)[0]


class TestNotifierDoesNotRecordAFalseSuccess:
    """The headline defect. Each test has a paired success control so a
    guard that simply stopped emitting anything could not pass."""

    def test_error_return_emits_no_notification_delivered(
        self, bus, topics_config, verbosity_config,
    ):
        notifier = _notifier(bus, topics_config, verbosity_config)
        event = _emit_deliverable(bus)

        with patch("cron.scheduler._deliver_result", return_value=TIMED_OUT):
            notifier.handle(event)

        assert bus.query(event_type=EventType.NOTIFICATION_DELIVERED) == [], (
            "_deliver_result returned an error string -- the message was "
            "abandoned -- yet the bus recorded NOTIFICATION_DELIVERED. An "
            "operator auditing 'did that alert arrive' would read a success "
            "for a message the chat never saw."
        )

    def test_error_return_emits_notification_failed_carrying_the_error(
        self, bus, topics_config, verbosity_config,
    ):
        notifier = _notifier(bus, topics_config, verbosity_config)
        event = _emit_deliverable(bus)

        with patch("cron.scheduler._deliver_result", return_value=TIMED_OUT):
            notifier.handle(event)

        failed = bus.query(event_type=EventType.NOTIFICATION_FAILED)
        assert len(failed) == 1, (
            f"expected exactly one NOTIFICATION_FAILED, got {len(failed)}"
        )
        assert "Timed out" in failed[0].payload["error"]["message"], (
            "the reverse signal must carry _deliver_result's own error text; "
            "without it the ledger says 'failed' but not why"
        )

    def test_success_control_still_emits_notification_delivered(
        self, bus, topics_config, verbosity_config,
    ):
        """Vacuity control for the two tests above: on the documented
        success return (None) the delivered signal must be unchanged."""
        notifier = _notifier(bus, topics_config, verbosity_config)
        event = _emit_deliverable(bus)

        with patch("cron.scheduler._deliver_result", return_value=None):
            notifier.handle(event)

        assert len(bus.query(event_type=EventType.NOTIFICATION_DELIVERED)) == 1
        assert bus.query(event_type=EventType.NOTIFICATION_FAILED) == []

    def test_deliver_returns_false_on_error_return(
        self, bus, topics_config, verbosity_config,
    ):
        """_deliver's bool is the batch flush's requeue signal. Returning
        True for an abandoned send drops the batch buffer on the floor."""
        notifier = _notifier(bus, topics_config, verbosity_config)

        with patch("cron.scheduler._deliver_result", return_value=TIMED_OUT):
            assert notifier._deliver("-1001234567890", "101", "body") is False
        with patch("cron.scheduler._deliver_result", return_value=None):
            assert notifier._deliver("-1001234567890", "101", "body") is True

    def test_batch_flush_error_return_emits_batch_failed_not_delivered(
        self, bus, topics_config, verbosity_config,
    ):
        """The batched lane has its own synthetic pair. An error return
        must land on the batch_flush FAILED twin, never the DELIVERED one."""
        notifier = _notifier(bus, topics_config, verbosity_config)

        with patch("cron.scheduler._deliver_result", return_value=TIMED_OUT):
            ok = notifier._deliver(
                "-1001234567890", "101", "Batched (3 events)",
                batch_count=3, topic_key="jobflow_firehose",
            )

        assert ok is False
        assert bus.query(event_type=EventType.NOTIFICATION_DELIVERED) == []
        failed = bus.query(event_type=EventType.NOTIFICATION_FAILED)
        assert len(failed) == 1
        assert failed[0].payload["original_event_type"] == "batch_flush"

    def test_batch_flush_success_control(
        self, bus, topics_config, verbosity_config,
    ):
        notifier = _notifier(bus, topics_config, verbosity_config)

        with patch("cron.scheduler._deliver_result", return_value=None):
            ok = notifier._deliver(
                "-1001234567890", "101", "Batched (3 events)",
                batch_count=3, topic_key="jobflow_firehose",
            )

        assert ok is True
        assert len(bus.query(event_type=EventType.NOTIFICATION_DELIVERED)) == 1
        assert bus.query(event_type=EventType.NOTIFICATION_FAILED) == []

    def test_empty_string_return_is_success(
        self, bus, topics_config, verbosity_config,
    ):
        """``"; ".join(delivery_errors) if delivery_errors else None`` cannot
        produce "", but the bot-chat lane has its own ``return ""`` paths.
        An empty string is not an error; truthiness is the right test and
        ``is not None`` would be wrong."""
        notifier = _notifier(bus, topics_config, verbosity_config)

        with patch("cron.scheduler._deliver_result", return_value=""):
            assert notifier._deliver("-1001234567890", "101", "body") is True


class TestNoRetryOnAnAbandonedSend:
    """CRITICAL CONSTRAINT. A generic TimedOut may ALREADY have reached the
    platform. The Telegram adapter retries only the provably-pre-send classes
    and fails closed on the rest, precisely so an ambiguous timeout cannot
    produce a duplicate alert. These callers sit above that decision and
    cannot tell the cases apart, so they must never re-send."""

    def test_error_return_does_not_resend(
        self, bus, topics_config, verbosity_config,
    ):
        notifier = _notifier(bus, topics_config, verbosity_config)
        event = _emit_deliverable(bus)

        with patch("cron.scheduler._deliver_result",
                   return_value=TIMED_OUT) as deliver:
            notifier.handle(event)

        assert deliver.call_count == 1, (
            f"exactly one send attempt is allowed per abandoned delivery; "
            f"saw {deliver.call_count}. Re-sending an ambiguous TimedOut "
            f"risks a DUPLICATE alert and overrides the adapter's "
            f"deliberate fail-closed decision."
        )

    def test_error_return_emits_no_second_loss_counter(
        self, bus, topics_config, verbosity_config,
    ):
        """events/delivery_loss.py already emits AGENT_ERROR for this same
        drop from inside the scheduler's standalone lane. The notifier owns
        the per-event reverse signal and nothing else -- an AGENT_ERROR from
        here would double-count every drop in the digest's SYSTEM HEALTH
        rollup."""
        notifier = _notifier(bus, topics_config, verbosity_config)
        event = _emit_deliverable(bus)

        with patch("cron.scheduler._deliver_result", return_value=TIMED_OUT):
            notifier.handle(event)

        assert bus.query(event_type=EventType.AGENT_ERROR) == [], (
            "the notifier must not emit its own loss counter; "
            "events/delivery_loss.py already counts this drop"
        )


class TestNotificationFailedCannotFeedTheFailingLane:
    """Structural containment, re-pinned here because this change RAISES the
    volume of NOTIFICATION_FAILED on exactly the transport that is already
    broken. If either subscriber ever consumed the type, a dropped Telegram
    send would try to deliver a Telegram message about it."""

    def test_notifier_never_consumes_notification_failed(
        self, bus, topics_config, verbosity_config,
    ):
        notifier = _notifier(bus, topics_config, verbosity_config)
        signal = Event.create(
            EventType.NOTIFICATION_FAILED, "telegram-notifier",
            {"original_event_id": "x", "platform": "telegram",
             "error": {"kind": "RuntimeError", "message": TIMED_OUT}},
            priority=Priority.NORMAL,
        )

        with patch("cron.scheduler._deliver_result",
                   return_value=None) as deliver:
            notifier.handle(signal)

        assert deliver.call_count == 0
        assert bus.query(event_type=EventType.NOTIFICATION_DELIVERED) == []

    def test_escalator_never_consumes_notification_failed(self, bus):
        escalator = WhatsAppEscalator(bus, send_fn=lambda _m: None)
        signal = Event.create(
            EventType.NOTIFICATION_FAILED, "telegram-notifier",
            {"original_event_id": "x", "platform": "telegram",
             "error": {"kind": "RuntimeError", "message": TIMED_OUT}},
            priority=Priority.NORMAL,
        )

        escalator.handle(signal)

        assert bus.query(event_type=EventType.NOTIFICATION_FAILED) == []


class TestDigestComposerSurfacesTheError:
    """The digest has no per-event reverse signal to correct, so the whole
    consequence of the discarded return is SILENCE: a digest that never
    arrived left no log line at all. It must not emit a bus event either --
    DigestComposer ships the digest through this same path, so an event here
    would be a delivery -> event -> delivery cycle, and delivery_loss.py
    already counts the drop."""

    def _topics(self, tmp_path):
        topics = tmp_path / "telegram" / "topics.json"
        topics.parent.mkdir(parents=True, exist_ok=True)
        topics.write_text(json.dumps({
            "group_chat_id": "-1001234567890",
            "topics": {"scribe_daily": {"thread_id": 105}},
        }), encoding="utf-8")
        return topics

    def test_telegram_error_return_is_logged(self, bus, tmp_path, caplog):
        topics = self._topics(tmp_path)
        composer = DigestComposer(bus)

        with patch("events.paths.telegram_topics_path", return_value=topics), \
                patch("cron.scheduler._deliver_result", return_value=TIMED_OUT), \
                caplog.at_level(logging.ERROR):
            composer._deliver_telegram("HERMES DIGEST\nbody")

        assert any("Timed out" in r.getMessage() for r in caplog.records), (
            "an abandoned digest send left no trace anywhere: the error "
            "string was discarded and no exception was ever raised"
        )

    def test_telegram_success_control_logs_no_error(self, bus, tmp_path, caplog):
        topics = self._topics(tmp_path)
        composer = DigestComposer(bus)

        with patch("events.paths.telegram_topics_path", return_value=topics), \
                patch("cron.scheduler._deliver_result", return_value=None), \
                caplog.at_level(logging.ERROR):
            composer._deliver_telegram("HERMES DIGEST\nbody")

        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []

    def test_whatsapp_error_return_is_logged(self, bus, caplog):
        composer = DigestComposer(bus)

        with patch("cron.scheduler._deliver_result",
                   return_value=WA_REFUSED) as deliver, \
                caplog.at_level(logging.ERROR):
            composer._deliver_whatsapp("body", [])

        assert deliver.call_count == 1, "no retry on the digest lane either"
        assert any("Connection refused" in r.getMessage()
                   for r in caplog.records)

    def test_whatsapp_success_control_logs_no_error(self, bus, caplog):
        composer = DigestComposer(bus)

        with patch("cron.scheduler._deliver_result", return_value=None), \
                caplog.at_level(logging.ERROR):
            composer._deliver_whatsapp("body", [])

        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []

    def test_digest_emits_no_loss_event(self, bus, caplog):
        composer = DigestComposer(bus)

        with patch("cron.scheduler._deliver_result", return_value=WA_REFUSED), \
                caplog.at_level(logging.ERROR):
            composer._deliver_whatsapp("body", [])

        assert bus.query(event_type=EventType.AGENT_ERROR) == [], (
            "DigestComposer delivers THROUGH _deliver_result, so emitting a "
            "loss event here arms a delivery -> event -> delivery cycle "
            "exactly when the transport is already failing"
        )


class TestEscalatorTelegramFallbackTellsTheTruth:
    """_telegram_fallback is the escalation lane's last resort: WhatsApp is
    already down and this is the backstop. It discarded the return and then
    logged 'message delivered to Telegram action_required as fallback'
    unconditionally -- so the one log line an operator has for a
    both-transports-down event asserted success for a send that failed."""

    def _topics(self, tmp_path):
        topics = tmp_path / "telegram" / "topics.json"
        topics.parent.mkdir(parents=True, exist_ok=True)
        topics.write_text(json.dumps({
            "group_chat_id": "-1001234567890",
            "topics": {"action_required": {"thread_id": 110}},
        }), encoding="utf-8")
        return topics

    def test_fallback_error_return_is_not_logged_as_delivered(
        self, bus, tmp_path, caplog,
    ):
        topics = self._topics(tmp_path)
        escalator = WhatsAppEscalator(bus)

        with patch("events.paths.telegram_topics_path", return_value=topics), \
                patch("cron.scheduler._deliver_result",
                      return_value=TIMED_OUT) as deliver, \
                caplog.at_level(logging.WARNING):
            escalator._telegram_fallback("escalation body")

        assert deliver.call_count == 1, "no retry on the last-resort lane"
        messages = [r.getMessage() for r in caplog.records]
        # The exact success line, so a mutant that drops the early return
        # (logging BOTH the failure and the success) is still killed.
        assert not any(
            "message delivered to Telegram action_required as fallback" in m
            for m in messages
        ), f"the fallback claimed success after an abandoned send: {messages}"
        assert any("Timed out" in m for m in messages), (
            "both transports failed and nothing said so"
        )

    def test_fallback_success_control_still_reports_delivery(
        self, bus, tmp_path, caplog,
    ):
        topics = self._topics(tmp_path)
        escalator = WhatsAppEscalator(bus)

        with patch("events.paths.telegram_topics_path", return_value=topics), \
                patch("cron.scheduler._deliver_result", return_value=None), \
                caplog.at_level(logging.WARNING):
            escalator._telegram_fallback("escalation body")

        assert any("fallback" in r.getMessage() for r in caplog.records)


class TestTelegramMirrorSurfacesTheError:
    """TelegramMirror is RETIRED (events/subscriber_roster.json, since
    2026-04-28), so this changes no live behaviour. It is fixed anyway
    because the file is a template someone copies, and a retired subscriber
    that still demonstrates the defect is how the defect returns."""

    def _mirror(self, bus, tmp_path):
        topics = tmp_path / "topics.json"
        topics.write_text(json.dumps({
            "group_chat_id": "-1001234567890",
            "topics": {"scribe_daily": {"thread_id": 105}},
        }), encoding="utf-8")
        return TelegramMirror(bus, topics_path=topics)

    def test_error_return_is_logged(self, bus, tmp_path, caplog):
        mirror = self._mirror(bus, tmp_path)

        with patch("cron.scheduler._deliver_result",
                   return_value=TIMED_OUT) as deliver, \
                caplog.at_level(logging.ERROR):
            mirror._deliver_to_agent_comms("mirror body")

        assert deliver.call_count == 1
        assert any("Timed out" in r.getMessage() for r in caplog.records)

    def test_success_control_logs_no_error(self, bus, tmp_path, caplog):
        mirror = self._mirror(bus, tmp_path)

        with patch("cron.scheduler._deliver_result", return_value=None), \
                caplog.at_level(logging.ERROR):
            mirror._deliver_to_agent_comms("mirror body")

        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
