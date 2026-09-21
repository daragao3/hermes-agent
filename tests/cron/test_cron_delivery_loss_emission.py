"""_deliver_standalone must make an abandoned send countable on the event bus.

Before this, the end of the standalone lane was one ERROR log line and a
return: no event, no counter, nothing the operator or the daily triage could
see. The send itself is still deliberately NOT retried -- see
events/delivery_loss.py and plugins/platforms/telegram/adapter.py's send path.
"""

import pytest

from cron import scheduler_delivery as sched_delivery
from events import delivery_loss


def _target(**overrides):
    """A _TargetDelivery with only the fields the standalone lane reads."""
    fields = dict(
        job={"id": "event-bus", "name": "event-bus"},
        platform=object(), platform_name="telegram", chat_id="-1003925553573",
        thread_id=None, transport=None, pconfig=object(), runtime_adapter=None,
        target_adapters=None, config=object(), loop=None, notify_delivery=False,
        origin={}, origin_target=False, origin_user_id=None, is_dm_target=False,
        mirror_text="", mirror_this_target=False, in_channel_surface=False,
        inchannel_continuable=False, opened_thread_id=None,
    )
    fields.update(overrides)
    return sched_delivery._TargetDelivery(**fields)


@pytest.fixture
def emitted(monkeypatch):
    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(delivery_loss, "emit_delivery_abandoned", _spy)
    return calls


def _deliver(monkeypatch, send_result, target=None):
    """Run _deliver_standalone with _standalone_send stubbed. Returns delivery_errors."""
    monkeypatch.setattr(sched_delivery, "_standalone_send", lambda *a, **k: send_result)
    monkeypatch.setattr(sched_delivery, "_maybe_mirror_cron_delivery", lambda *a, **k: None)
    target_errors, delivery_errors = [], []
    sched_delivery._deliver_standalone(
        target or _target(), "body", [], target_errors, delivery_errors)
    return delivery_errors


def test_a_result_dict_error_emits_one_loss_event(monkeypatch, emitted):
    """The dominant shape: the sender returns success with an `error` key.

    All 158 abandoned deliveries in the rotated gateway logs on 2026-09-20
    arrived this way ("delivery error: ... (target ...)").
    """
    _deliver(monkeypatch, ({"error": "Telegram send failed: Timed out"}, None))

    assert len(emitted) == 1
    assert emitted[0] == {
        "job_id": "event-bus",
        "platform": "telegram",
        "target": "telegram:-1003925553573",
        "error": "Telegram send failed: Timed out",
    }


def _run_real_standalone_send(monkeypatch, *, send=None, shutting_down=False,
                              content="body", media_files=None):
    """Drive the REAL _standalone_send, which is where the attempted-vs-skipped
    distinction lives. Returns (result, err).

    tools.send_message_tool is stubbed into sys.modules rather than imported:
    _standalone_send imports _send_to_platform INSIDE the function, and the real
    module pulls the whole platform-plugin tree (~1600 modules, ~2 min per test
    subprocess). Nothing under test reads anything else from it.
    """
    import sys
    import types

    async def _default(*a, **k):
        raise ConnectionError("Cannot connect to host localhost:3000")

    stub = types.ModuleType("tools.send_message_tool")
    stub._send_to_platform = send or _default
    monkeypatch.setitem(sys.modules, "tools.send_message_tool", stub)
    monkeypatch.setattr(sched_delivery._sched, "_interpreter_shutting_down",
                        lambda *a, **k: shutting_down)
    return sched_delivery._standalone_send(
        _target(), content, media_files if media_files is not None else [])


def test_a_raised_send_failure_emits_one_loss_event(monkeypatch, emitted):
    """The other abandonment shape: the send was attempted and raised. Equally
    lost, equally uncounted before this -- and here the exception object is in
    hand, so the class is exact rather than parsed back out of a message."""
    _, err = _run_real_standalone_send(monkeypatch)

    assert err is not None
    assert len(emitted) == 1
    assert emitted[0]["error"] == "ConnectionError: Cannot connect to host localhost:3000"
    assert emitted[0]["platform"] == "telegram"


def test_an_interpreter_shutdown_race_is_a_skip_and_is_not_counted(monkeypatch, emitted):
    """_standalone_send returns an error string here too, but nothing was
    attempted -- SIGTERM/restart/OOM arrived first, which is why this branch
    logs WARNING rather than ERROR. Counting it would inflate the one number
    this change exists to make trustworthy."""
    _, err = _run_real_standalone_send(monkeypatch, shutting_down=True)

    assert err is not None, "the skip must still be reported to the caller"
    assert emitted == []


def test_an_empty_payload_skip_is_not_counted(monkeypatch, emitted):
    """Nothing to deliver, so nothing was lost. (The skip itself exists because
    standalone senders return success for empty content WITHOUT an API call.)"""
    _, err = _run_real_standalone_send(monkeypatch, content="   ", media_files=[])

    assert err is not None
    assert emitted == []


def test_a_successful_delivery_emits_nothing(monkeypatch, emitted):
    _deliver(monkeypatch, ({"ok": True}, None))

    assert emitted == []


def test_a_per_file_attachment_warning_is_not_an_abandoned_delivery(monkeypatch, emitted):
    """The message DID leave; only an attachment was dropped. Counting it as a
    loss would inflate the very number this change exists to make trustworthy."""
    _deliver(monkeypatch, ({"warnings": ["attachment vanished"]}, None))

    assert emitted == []


def test_a_relay_target_emits_nothing_from_this_lane(monkeypatch, emitted):
    """Relay owns the destination and there is no standalone fallback, so the
    standalone lane never attempted (or lost) anything here."""
    class _Relay:
        is_relay = True

    _deliver(monkeypatch, ({"error": "unused"}, None), target=_target(transport=_Relay()))

    assert emitted == []


def test_the_error_is_still_recorded_and_the_send_is_still_not_retried(
    monkeypatch, emitted,
):
    """Emission is additive: the caller's error accounting is unchanged, and
    exactly one send attempt is made."""
    attempts = []

    def _send(*a, **k):
        attempts.append(1)
        return ({"error": "Telegram send failed: Timed out"}, None)

    monkeypatch.setattr(sched_delivery, "_standalone_send", _send)
    monkeypatch.setattr(sched_delivery, "_maybe_mirror_cron_delivery", lambda *a, **k: None)
    target_errors, delivery_errors = [], []
    sched_delivery._deliver_standalone(_target(), "body", [], target_errors, delivery_errors)

    assert attempts == [1], "an ambiguous timeout must never be retried here"
    assert delivery_errors == [
        "delivery error: Telegram send failed: Timed out (target telegram:-1003925553573)"
    ]


def test_an_emitter_that_raises_cannot_break_the_delivery_path(monkeypatch):
    """This runs when something is already broken; the observability hook must
    never be the thing that takes the caller down."""
    monkeypatch.setattr(
        delivery_loss, "emit_delivery_abandoned",
        lambda **k: (_ for _ in ()).throw(RuntimeError("bus exploded")))
    monkeypatch.setattr(
        sched_delivery, "_standalone_send",
        lambda *a, **k: ({"error": "Telegram send failed: Timed out"}, None))

    target_errors, delivery_errors = [], []
    sched_delivery._deliver_standalone(_target(), "body", [], target_errors, delivery_errors)

    assert delivery_errors == [
        "delivery error: Telegram send failed: Timed out (target telegram:-1003925553573)"
    ]
