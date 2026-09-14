"""Task 2: wiring ai_usage.quota_signal.evaluate() into collector.collect() so
findings become MODEL_RATE_LIMITED alerts via events.rate_limit_signal.record.

Phase 3 is REPORT-ONLY: Claude Code and the Codex CLI are separate processes
Hermes cannot reroute, so no button may ever appear on these alerts. Every
test here uses a fake record()/clear() -- no real event bus, no real state
file -- so these tests never depend on or mutate ~/.hermes state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from ai_usage.collector import collect

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeWin:
    label: str
    used_percent: Optional[float]
    reset_at: Optional[datetime]


@dataclass
class FakeSnap:
    available: bool
    windows: tuple
    fetched_at: datetime = NOW
    unavailable_reason: Optional[str] = None
    balance_usd: Optional[float] = None


def _unconfigured(_provider):
    return FakeSnap(False, (), unavailable_reason="no token")


def _fetch_with(overrides):
    """Build a fetch_usage(provider) callable; unlisted providers -> unconfigured."""

    def fetch(provider):
        if provider in overrides:
            return overrides[provider]
        return _unconfigured(provider)

    return fetch


def _fake_record_batch(calls, batches=None):
    """Stand in for events.rate_limit_signal.record_batch (2026-09-13).

    Expands each hit into one dict merged with the batch kwargs, so the
    per-hit assertions written against the old per-provider record() keep
    their exact shape; ``batches`` (when given) records one entry per CALL,
    which is what the consolidation tests count.
    """

    def record_batch(hits, **kwargs):
        if batches is not None:
            batches.append({"hits": list(hits), **kwargs})
        for hit in hits:
            calls.append({**kwargs, **hit})
        return True

    return record_batch


def test_full_window_emits_once_with_chain_exhausted(tmp_path, monkeypatch):
    import events.rate_limit_signal as rate_limit_signal

    calls: list[dict] = []
    monkeypatch.setattr(rate_limit_signal, "record_batch", _fake_record_batch(calls))

    fetch = _fetch_with(
        {"anthropic": FakeSnap(True, (FakeWin("Current session", 100.0, None),))}
    )
    db = tmp_path / "state.db"
    data = collect(db_path=str(db), prev=None, fetch_usage=fetch, now=NOW)

    # The snapshot itself is unaffected by the emit path.
    assert any(p["key"] == "anthropic" for p in data["providers"])

    assert len(calls) == 1
    call = calls[0]
    assert call["provider"] == "anthropic"
    assert call["model"] == "5h-window"
    assert call["reason"] == "quota_window"
    assert call["detector"] == "usage_poller"
    assert call["outcome"] == "chain_exhausted"


def test_healthy_snapshot_emits_nothing(tmp_path, monkeypatch):
    import events.rate_limit_signal as rate_limit_signal

    calls: list[dict] = []
    monkeypatch.setattr(rate_limit_signal, "record_batch", _fake_record_batch(calls))

    fetch = _fetch_with(
        {"anthropic": FakeSnap(True, (FakeWin("Current session", 12.0, None),))}
    )
    db = tmp_path / "state.db"
    collect(db_path=str(db), prev=None, fetch_usage=fetch, now=NOW)

    assert calls == []


def test_record_raising_does_not_break_collect(tmp_path, monkeypatch):
    import events.rate_limit_signal as rate_limit_signal

    def raising_record_batch(hits, **kwargs):
        raise RuntimeError("boom: simulated record_batch() failure")

    monkeypatch.setattr(rate_limit_signal, "record_batch", raising_record_batch)

    fetch = _fetch_with(
        {"anthropic": FakeSnap(True, (FakeWin("Current session", 100.0, None),))}
    )
    db = tmp_path / "state.db"

    # Must not raise -- a detector failure can never break usage collection.
    data = collect(db_path=str(db), prev=None, fetch_usage=fetch, now=NOW)

    # The snapshot returned must still be intact and correct.
    assert data["generated_at"] == "2026-08-18T12:00:00Z"
    by = {p["key"]: p for p in data["providers"]}
    assert by["anthropic"]["state"] == "ok"
    assert by["anthropic"]["windows"][0]["used_pct"] == 100.0
    assert len(data["providers"]) == 7  # deepseek row retired 2026-09-13
    assert "diagnostics" in data


def test_buttons_for_returns_none_for_usage_poller_detector():
    """PROVE THE NO-BUTTON GUARANTEE (defining constraint of Phase 3).

    Phase 2's buttons_for() gates on detector == "runtime"; usage_poller
    inherits the block, but that inheritance must be pinned with a test
    rather than trusted on faith.
    """
    from events.override_buttons import buttons_for
    from events.schema import Event, EventType

    for outcome in ("diverted", "chain_exhausted"):
        event = Event.create(
            event_type=EventType.MODEL_RATE_LIMITED,
            source="usage_poller",
            payload={
                "provider": "anthropic",
                "model": "5h-window",
                "reason": "quota_window",
                "detector": "usage_poller",
                "outcome": outcome,
                "fallback_provider": "",
                "fallback_model": "",
                "resets_at": "",
                "diverted_calls": 1,
                "episode_opened_at": "x",
            },
        )
        assert buttons_for(event) is None


def test_absent_window_never_recovers_an_open_episode(tmp_path, monkeypatch):
    """An episode open for a window must never be read as RECOVERED just
    because the next snapshot omits that window entirely.

    Codex nulls its 5h window precisely when the weekly is capped -- if a
    disappearing window caused a "recovery", the operator would get a false
    all-clear at the worst possible moment.

    This test does not merely check that recovery doesn't happen: it patches
    clear() itself, so it would FAIL if a future change added a naive "no
    finding this round -> the open episode must have recovered" clear.
    """
    import events.rate_limit_signal as rate_limit_signal

    record_calls: list[dict] = []
    clear_calls: list[dict] = []

    monkeypatch.setattr(
        rate_limit_signal, "record_batch", _fake_record_batch(record_calls))

    def fake_clear(**kwargs):
        clear_calls.append(kwargs)
        return True

    monkeypatch.setattr(rate_limit_signal, "clear", fake_clear)

    db = tmp_path / "state.db"

    # Round 1: the 5h window is fully exhausted -- an episode opens.
    fetch_capped = _fetch_with(
        {"anthropic": FakeSnap(True, (FakeWin("Current session", 100.0, None),))}
    )
    first = collect(db_path=str(db), prev=None, fetch_usage=fetch_capped, now=NOW)
    assert len(record_calls) == 1
    assert record_calls[0]["outcome"] == "chain_exhausted"

    # Round 2: the window is gone entirely from the snapshot (Codex-style
    # nulling), not present-and-healthy. evaluate() correctly yields no
    # finding for it either way -- the property under test is that our emit
    # layer never turns "no finding" into a clear() call.
    fetch_absent = _fetch_with({"anthropic": FakeSnap(True, ())})
    collect(db_path=str(db), prev=first, fetch_usage=fetch_absent, now=NOW)

    assert clear_calls == []


class TestStaleResetsAtIsNotForwarded:
    """Regression for a defect caught IN PRODUCTION within two poll cycles.

    Phase 1's episode reaper forgets any episode whose `resets_at` has passed.
    That is right for a real rate limit. It is wrong for this detector: on
    2026-08-18 anthropic reported used_pct 100.0 with resets_at 2026-08-17 -- a
    day in the past on a still-capped window. Forwarding it got the episode
    reaped on the next read, so every 5-minute poll re-alerted (observed at
    00:20:13 and again at 00:25:14 for the same window).

    The design rule "resets_at is display-only" was already in place, but was
    enforced one layer too shallow -- in evaluate(), not at the boundary where
    the value reaches a consumer that branches on it.
    """

    def test_past_resets_at_is_dropped(self):
        from ai_usage.collector import _future_resets_at
        assert _future_resets_at("2026-08-17T08:00:00Z") == ""

    def test_future_resets_at_is_preserved(self):
        from ai_usage.collector import _future_resets_at
        from datetime import datetime, timedelta, timezone
        soon = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        assert _future_resets_at(soon) == soon

    def test_missing_or_garbage_resets_at_is_dropped_not_raised(self):
        from ai_usage.collector import _future_resets_at
        assert _future_resets_at(None) == ""
        assert _future_resets_at("") == ""
        assert _future_resets_at("not-a-timestamp") == ""

    def test_a_still_capped_window_with_a_past_reset_emits_without_resets_at(self, monkeypatch):
        """The end-to-end shape of the production defect."""
        calls = []
        import events.rate_limit_signal as rls
        monkeypatch.setattr(rls, "record_batch", _fake_record_batch(calls))
        from ai_usage.collector import _emit_quota_findings
        _emit_quota_findings({
            "providers": [{
                "key": "anthropic", "mode": "budget",
                "windows": [{"id": "wk", "label": "Weekly", "used_pct": 100.0,
                             "resets_at": "2026-08-17T08:00:00Z"}],
            }]
        })
        assert len(calls) == 1
        assert calls[0]["outcome"] == "chain_exhausted"
        assert calls[0]["resets_at"] == "", (
            "a stale reset time must not reach record() -- Phase 1's reaper "
            "branches on it and would forget the episode every poll"
        )


# A balance-mode row for the consolidated-page tests. The real grid has no
# balance provider since the direct DeepSeek row was retired on 2026-09-13
# (DeepSeek is served via OpenCode Go), so the label lookup in
# collector._provider_display_label is fed this injected row instead.
BALANCE_KEY, BALANCE_LABEL = "prepaid-sample", "Prepaid Sample"


@pytest.fixture
def balance_grid(monkeypatch):
    import ai_usage.collector as collector_module
    import ai_usage.contract as contract_module

    grid = list(contract_module.PROVIDERS) + [(BALANCE_KEY, BALANCE_LABEL, "balance")]
    monkeypatch.setattr(contract_module, "PROVIDERS", grid)
    monkeypatch.setattr(collector_module, "PROVIDERS", grid)
    return grid


class TestOneConsolidatedCallPerSnapshot:
    """2026-09-13: five providers capped in one poll produced FIVE separate
    MODEL_RATE_LIMITED pages (anthropic2, deepseek, openai-codex, kimi,
    anthropic). The collector now hands the whole snapshot to record_batch()
    ONCE; the consolidation itself is pinned in tests/events/
    test_rate_limit_signal.py::TestRecordBatch.

    The balance-mode member of that page was the direct DeepSeek key, retired
    from PROVIDERS later the same day; the fixture-injected BALANCE_KEY stands
    in so the balance detail/label formatting stays pinned without expecting
    a deepseek member."""

    def _five_capped(self):
        return {
            "providers": [
                {"key": "anthropic2", "mode": "budget",
                 "windows": [{"id": "5h", "label": "5h", "used_pct": 100.0,
                              "resets_at": "2099-01-01T02:00:00Z"}]},
                {"key": BALANCE_KEY, "mode": "balance", "balance_usd": 0.0},
                {"key": "openai-codex", "mode": "budget",
                 "windows": [{"id": "wk", "label": "Weekly", "used_pct": 100.0}]},
                {"key": "kimi", "mode": "budget",
                 "windows": [{"id": "wk", "label": "Weekly", "used_pct": 100.0}]},
                {"key": "anthropic", "mode": "budget",
                 "windows": [{"id": "wk", "label": "Weekly", "used_pct": 100.0}]},
            ]
        }

    def test_five_findings_are_one_record_batch_call(self, monkeypatch, balance_grid):
        import events.rate_limit_signal as rls
        from ai_usage.collector import _emit_quota_findings

        calls: list[dict] = []
        batches: list[dict] = []
        monkeypatch.setattr(rls, "record_batch", _fake_record_batch(calls, batches))
        _emit_quota_findings(self._five_capped())

        assert len(batches) == 1, "one poll snapshot must be one batch call"
        batch = batches[0]
        assert batch["reason"] == "quota_window"
        assert batch["detector"] == "usage_poller"
        assert batch["source_hint"] == "usage-poller"
        assert [h["provider"] for h in batch["hits"]] == [
            "anthropic2", BALANCE_KEY, "openai-codex", "kimi", "anthropic"]
        assert {h["outcome"] for h in batch["hits"]} == {"chain_exhausted"}

    def test_hits_carry_operator_facing_label_and_detail(self, monkeypatch, balance_grid):
        import events.rate_limit_signal as rls
        from ai_usage.collector import _emit_quota_findings

        calls: list[dict] = []
        monkeypatch.setattr(rls, "record_batch", _fake_record_batch(calls))
        _emit_quota_findings(self._five_capped())
        by = {c["provider"]: c for c in calls}
        assert by["anthropic2"]["label"] == "Claude 2 (second Claude Code login)"
        assert by["anthropic2"]["detail"] == "5h window 100% used"
        assert by["anthropic2"]["resets_at"] == "2099-01-01T02:00:00Z"
        assert by[BALANCE_KEY]["label"] == BALANCE_LABEL
        assert by[BALANCE_KEY]["detail"] == "prepaid balance $0.00 — top up"
        assert by[BALANCE_KEY]["model"] == "balance"
        assert by["kimi"]["detail"] == "weekly window 100% used"

    def test_no_findings_means_no_call_at_all(self, monkeypatch):
        import events.rate_limit_signal as rls
        from ai_usage.collector import _emit_quota_findings

        batches: list[dict] = []
        monkeypatch.setattr(rls, "record_batch", _fake_record_batch([], batches))
        _emit_quota_findings({"providers": [
            {"key": "anthropic", "mode": "budget",
             "windows": [{"id": "5h", "label": "5h", "used_pct": 12.0}]}]})
        assert batches == []
