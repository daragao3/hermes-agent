"""NOTIFICATION interview/offer detection reads the field producers populate, and only on employer mail.

2026-09-23 (loops interview-detection-field-fix-20260923): the translator matched on inner body +
summary, which were empty on every real NOTIFICATION envelope (203 on disk; the text lives in
formatted_message), so INTERVIEW_SIGNAL / OFFER_SIGNAL -- ACT class, pages WhatsApp -- could never
fire. The channel is internal by protocol (Notifier -> Jaum), so reading its text is also exactly
how a digest restating pipeline state would page Diego. Detection therefore reads every populated
text field but runs only on envelopes that declare employer mail.
"""

from __future__ import annotations

import pytest

from events.bus import EventBus
from events.schema import EventType
from events.subscribers import mailbox_translator as mt


@pytest.fixture
def translator(tmp_path):
    bus = EventBus(db_path=tmp_path / "event_bus.db")
    yield mt.MailboxTranslator(bus)
    bus.close()


def _signals(translator, inner, from_agent="mail-intake"):
    return [(et, p) for et, p, _ in translator._translate("NOTIFICATION", inner, from_agent)
            if et in (EventType.INTERVIEW_SIGNAL, EventType.OFFER_SIGNAL)]


def _employer(formatted_message, **extra):
    """Real envelope shape: text only in formatted_message; body/summary present but empty."""
    return {"type": "inbound_email", "origin": "employer_email", "priority": "normal",
            "body": "", "summary": "", "formatted_message": formatted_message, **extra}


# ---- the field bug ------------------------------------------------------------------------

def test_interview_invitation_only_in_formatted_message_fires(translator):
    out = _signals(translator, _employer(
        "From: talent@acme.com\nSubject: Next steps\n\nHi Diego, we'd like to schedule an interview "
        "for the Treasury Director role next week.", company="Acme", title="Treasury Director"))
    assert [et for et, _ in out] == [EventType.INTERVIEW_SIGNAL]
    payload = out[0][1]
    assert payload["company"] == "Acme"
    assert "schedule an interview" in payload["detail"], "the page text must carry the evidence"


def test_offer_only_in_formatted_message_fires(translator):
    out = _signals(translator, _employer(
        "Dear Diego, we are delighted to offer you the position of VP Liquidity.", company="BigCo"))
    assert [et for et, _ in out] == [EventType.OFFER_SIGNAL]


def test_text_only_in_subject_or_message_is_read_too(translator):
    assert _signals(translator, {"origin": "employer_email", "subject": "Phone screen: Acme"})
    assert _signals(translator, {"origin": "employer_email", "message": "Your offer letter is attached"})


def test_rejection_mail_fires_nothing(translator):
    assert _signals(translator, _employer(
        "Thank you for taking the time to interview with us. After careful consideration we will not "
        "be moving forward with your candidacy.", company="Acme")) == []


# ---- the false-positive guard -------------------------------------------------------------

# Verbatim internal lines from real envelopes (notifier morning_digest, sentinel vip_scan_summary)
# plus the realistic future digest that restates an interview the pipeline already knows about.
INTERNAL = [
    ("notifier", {"type": "morning_digest", "formatted_message":
        "• Submitted 0 | Responses / interviews / offers: 0 — still flat, still the number that matters"}),
    ("notifier", {"type": "morning_digest", "formatted_message":
        "Pipeline: Acme moved to interview. Phone screen with Acme on Thursday; interview scheduled with "
        "BigCo; BigCo extended an offer letter draft for review."}),
    ("sentinel", {"type": "vip_scan_summary", "status": "ok", "formatted_message":
        "Sentinel LinkedIn VIP scan complete\nStatus: ok\nPages visited: 2\nSaved jobs captured: 11"}),
    ("devflow", {"type": "devflow_report", "formatted_message":
        "DevFlow: fixed interview scheduled parsing in tracker; offer letter template updated"}),
]


@pytest.mark.parametrize("sender,inner", INTERNAL)
def test_internal_notifications_never_signal_even_with_matching_phrases(translator, sender, inner):
    assert _signals(translator, dict(inner, body="", summary=""), from_agent=sender) == []


def test_undeclared_envelope_with_interview_text_does_not_page(translator):
    """No origin declared = not employer mail, whatever the text says."""
    assert _signals(translator, {"formatted_message": "Interview invitation from Acme"}) == []


@pytest.mark.parametrize("inner", [{}, {"origin": "employer_email"},
                                   {"origin": "employer_email", "formatted_message": None, "body": 42},
                                   {"origin": 7, "type": None}])
def test_empty_or_malformed_envelopes_emit_nothing_and_do_not_crash(translator, inner):
    assert _signals(translator, inner) == []


# ---- text assembly ------------------------------------------------------------------------

def test_notification_text_orders_dedupes_and_caps():
    text = mt._notification_text({"summary": "same", "body": "same", "formatted_message": "first",
                                  "subject": "  ", "title": 3, "message": "x" * 20000})
    assert text.startswith("first\nsame\n")
    assert text.count("same") == 1
    assert len(text) == mt._NOTIFICATION_TEXT_CAP


def test_end_to_end_through_the_bus_uses_the_real_envelope_shape(tmp_path):
    bus = EventBus(db_path=tmp_path / "e2e.db")
    try:
        bus.emit(event_type=EventType.MAILBOX_MESSAGE, source="test", payload={
            "message_type": "NOTIFICATION", "from": "mail-intake", "to": "main", "summary": "",
            "inner_payload": _employer("We would like to set up an interview with you.", company="Acme")})
        t = mt.MailboxTranslator(bus)
        for ev in bus.query():
            if ev.event_type == EventType.MAILBOX_MESSAGE:
                t.handle(ev)
        kinds = [e.event_type for e in bus.query() if e.event_type != EventType.MAILBOX_MESSAGE]
        assert EventType.INTERVIEW_SIGNAL in kinds
    finally:
        bus.close()
