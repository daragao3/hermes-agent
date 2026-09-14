"""Tests for events.noise_guards (v3 P4/P6)."""

from events.noise_guards import FlapGuard, RepeatGuard, is_noop_cron_output


# ----------------------------------------------------------------- noop guard

def test_empty_output_is_noop():
    assert is_noop_cron_output("")
    assert is_noop_cron_output(None)
    assert is_noop_cron_output("   \n  ")


def test_silent_marker_only_is_noop():
    assert is_noop_cron_output("[SILENT]")
    assert is_noop_cron_output("[SILENT] ")
    assert is_noop_cron_output("[silent]")


def test_noop_phrases():
    assert is_noop_cron_output("no work")
    assert is_noop_cron_output("Nothing to do.")
    assert is_noop_cron_output("OK")


def test_content_after_silent_marker_survives():
    assert not is_noop_cron_output(
        "[SILENT] errors=1 — first error: GET https://api.github.com/...")


def test_substantive_output_is_not_noop():
    assert not is_noop_cron_output("synced 42 rows in 3.1s")


# --------------------------------------------------------------- repeat guard

def test_repeat_suppressed_within_window():
    g = RepeatGuard(window_seconds=1800)
    assert not g.is_repeat("t1", "devflow-bridge: tick", now=0)
    assert g.is_repeat("t1", "devflow-bridge: tick", now=300)
    assert g.suppressed_count == 1


def test_repeat_allowed_after_window():
    g = RepeatGuard(window_seconds=1800)
    assert not g.is_repeat("t1", "msg", now=0)
    assert not g.is_repeat("t1", "msg", now=1801)


def test_sliding_window_keeps_suppressing_steady_stream():
    """A message repeating every 5 min never re-delivers (the window slides)."""
    g = RepeatGuard(window_seconds=1800)
    assert not g.is_repeat("t1", "m", now=0)
    for i in range(1, 20):
        assert g.is_repeat("t1", "m", now=i * 300)


def test_different_topics_independent():
    g = RepeatGuard()
    assert not g.is_repeat("t1", "m", now=0)
    assert not g.is_repeat("t2", "m", now=1)


def test_lru_bounded():
    g = RepeatGuard(max_entries=10)
    for i in range(50):
        g.is_repeat("t", f"m{i}", now=i)
    assert len(g._seen) <= 10


# ----------------------------------------------------------------- flap guard

def test_same_state_reannounce_suppressed():
    g = FlapGuard()
    assert g.observe("wa", "down", now=0).deliver
    assert not g.observe("wa", "down", now=60).deliver
    assert not g.observe("wa", "down", now=120).deliver


def test_state_change_delivers():
    g = FlapGuard()
    assert g.observe("wa", "down", now=0).deliver
    d = g.observe("wa", "up", now=60)
    assert d.deliver and d.note is None


def test_flapping_collapses_then_mutes():
    g = FlapGuard(window_seconds=900, flap_threshold=4, mute_seconds=1800)
    assert g.observe("wa", "down", now=0).deliver
    assert g.observe("wa", "up", now=100).deliver
    assert g.observe("wa", "down", now=200).deliver
    d = g.observe("wa", "up", now=300)  # 4th transition in window
    assert d.deliver and "flapping" in d.note
    # muted now
    assert not g.observe("wa", "down", now=400).deliver
    assert not g.observe("wa", "up", now=500).deliver


def test_post_mute_stabilization_note():
    g = FlapGuard(window_seconds=900, flap_threshold=4, mute_seconds=1800)
    for i, s in enumerate(["down", "up", "down", "up"]):
        g.observe("wa", s, now=i * 100)
    assert not g.observe("wa", "down", now=500).deliver  # muted
    d = g.observe("wa", "up", now=500 + 1801)
    assert d.deliver
    assert "stabilized" in d.note
    assert "up" in d.note


def test_keys_independent():
    g = FlapGuard()
    g.observe("wa", "down", now=0)
    d = g.observe("telegram", "down", now=1)
    assert d.deliver


# ---------------------------------------------------------- known-debt guard

def test_known_debt_signature_applies_only_to_partials_naming_a_debt():
    from events.noise_guards import known_debt_signature
    assert known_debt_signature({"reason": "success",
                                 "counters": {"stage_count_delta": 17}}) is None
    assert known_debt_signature({"reason": "partial", "counters": {"jobs_seen": 3}}) is None
    assert known_debt_signature({"reason": "partial"}) is None
    assert known_debt_signature(None) is None
    assert known_debt_signature(
        {"reason": "partial",
         "counters": {"stage_count_delta": 17, "shadow_rows": 4, "jobs_seen": 0}}
    ) == "stage_delta=17;shadows=4"


def test_known_debt_signature_normalizes_renamed_counters():
    """The tracker LLM renames its counters between cycles (2026-09-13
    stage_count_delta/shadow_rows, 2026-09-14 stage_mismatch_count/
    shadow_inserts_refused) for the identical debt."""
    from events.noise_guards import known_debt_signature
    a = known_debt_signature({"reason": "partial",
                              "counters": {"stage_count_delta": 17, "shadow_rows": 4}})
    b = known_debt_signature({"reason": "partial",
                              "counters": {"stage_mismatch_count": 17,
                                           "shadow_inserts_refused": 4}})
    assert a == b == "stage_delta=17;shadows=4"


def test_known_debt_guard_unchanged_debt_is_one_message_per_window():
    from events.noise_guards import KnownDebtGuard
    g = KnownDebtGuard(window_seconds=6 * 3600)
    first = g.observe("tracker:partial", "stage_delta=17;shadows=4", now=0)
    assert first.deliver and not first.changed
    # Hourly cycles inside the window: all suppressed.
    for hour in range(1, 6):
        assert not g.observe("tracker:partial", "stage_delta=17;shadows=4",
                             now=hour * 3600).deliver
    assert g.suppressed_count == 5
    # Non-sliding: the window is measured from the DELIVERY, so the
    # persisting debt re-delivers at +6h even though it never stopped.
    again = g.observe("tracker:partial", "stage_delta=17;shadows=4", now=6 * 3600)
    assert again.deliver and not again.changed


def test_known_debt_guard_changed_numbers_deliver_immediately():
    from events.noise_guards import KnownDebtGuard
    g = KnownDebtGuard(window_seconds=6 * 3600)
    assert g.observe("tracker:partial", "stage_delta=17;shadows=4", now=0).deliver
    moved = g.observe("tracker:partial", "stage_delta=18;shadows=4", now=3600)
    assert moved.deliver and moved.changed
    # ...and the new value then starts its own window.
    assert not g.observe("tracker:partial", "stage_delta=18;shadows=4", now=7200).deliver


def test_known_debt_guard_keys_are_independent():
    from events.noise_guards import KnownDebtGuard
    g = KnownDebtGuard(window_seconds=6 * 3600)
    assert g.observe("tracker:partial", "stage_delta=17;shadows=4", now=0).deliver
    assert g.observe("matcher:partial", "remaining=15", now=0).deliver
    assert not g.observe("tracker:partial", "stage_delta=17;shadows=4", now=60).deliver
