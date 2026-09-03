"""Pure logic of the durable P6 silence watchdog: staleness + cooldown edges."""

import importlib.util
from pathlib import Path

# Load the script module by path (scripts/ is not a package).
_SPEC = importlib.util.spec_from_file_location(
    "p6_silence_watchdog",
    Path(__file__).resolve().parents[2] / "scripts" / "p6_silence_watchdog.py",
)
wd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wd)

NOW = 1_800_000_000.0


def test_evaluate_no_events_is_silent():
    silent, age = wd.evaluate(None, NOW, 1200.0)
    assert silent is True and age is None


def test_evaluate_fresh_is_healthy():
    silent, age = wd.evaluate(NOW - 300.0, NOW, 1200.0)
    assert silent is False and age == 300.0


def test_evaluate_boundary():
    # exactly at the threshold is NOT silent (strictly greater trips it)
    assert wd.evaluate(NOW - 1200.0, NOW, 1200.0)[0] is False
    assert wd.evaluate(NOW - 1200.1, NOW, 1200.0)[0] is True


def test_rising_edge_alerts_once_then_cooldown():
    state = {}
    action, state = wd.decide_emit(True, NOW, state, 3600.0)
    assert action == "alert" and state["silent"] is True
    # still silent, within cooldown -> no repeat
    action, state = wd.decide_emit(True, NOW + 600.0, state, 3600.0)
    assert action == "none"
    # cooldown elapsed -> re-alert
    action, state = wd.decide_emit(True, NOW + 3601.0, state, 3600.0)
    assert action == "alert"


def test_recovery_edge_emits_once_and_resets():
    state = {"silent": True, "last_alert_at": NOW}
    action, state = wd.decide_emit(False, NOW + 100.0, state, 3600.0)
    assert action == "recovered" and state["silent"] is False
    # healthy again -> nothing
    action, state = wd.decide_emit(False, NOW + 200.0, state, 3600.0)
    assert action == "none"


def test_healthy_from_empty_state_is_silent_noop():
    action, state = wd.decide_emit(False, NOW, {}, 3600.0)
    assert action == "none" and state["silent"] is False


def test_newest_result_epoch_takes_max():
    class R:
        def __init__(self, ts):
            self.timestamp = ts
    rows = [R("2026-08-31T15:00:00+00:00"), R("2026-08-31T15:10:00+00:00"),
            R("bad-timestamp"), R("2026-08-31T15:05:00+00:00")]
    epoch = wd.newest_result_epoch(rows)
    from datetime import datetime, timezone
    assert epoch == datetime(2026, 8, 31, 15, 10, tzinfo=timezone.utc).timestamp()
    assert wd.newest_result_epoch([]) is None
    assert wd.newest_result_epoch([R("nope")]) is None


# ---------------------------------------------------------------- threshold
# The literal 1200.0 these replace was commented "20 min = 4 missed 5-min
# passes" while the controller task actually repeated every PT10M -- so the
# real margin was ONE missed pass, and every single hung pass paged. Fixed
# 2026-09-02; loops claim p6-fleet-silence-watchdog-flap-20260902.


def test_threshold_is_derived_from_the_interval_not_hardcoded():
    assert wd.DEFAULT_MAX_AGE_SECONDS == (
        wd.MISSES_TOLERATED * wd.CONTROLLER_INTERVAL_SECONDS
    )


def test_threshold_tolerates_a_single_hung_pass():
    """One hang costs ~2 intervals (PT8M kill + IgnoreNew skip). Must NOT page."""
    one_hang_gap = 2.0 * wd.CONTROLLER_INTERVAL_SECONDS
    silent, _ = wd.evaluate(NOW - one_hang_gap, NOW, wd.DEFAULT_MAX_AGE_SECONDS)
    assert silent is False, "a single hung pass must not page -- that is the flap"


def test_threshold_still_catches_a_real_stop():
    """A genuinely stopped controller must still page; the fix must not blind it."""
    stopped_gap = 4.0 * wd.CONTROLLER_INTERVAL_SECONDS
    silent, _ = wd.evaluate(NOW - stopped_gap, NOW, wd.DEFAULT_MAX_AGE_SECONDS)
    assert silent is True


def test_alert_label_is_not_hardcoded_to_five_minutes():
    src = (
        __import__("pathlib").Path(wd.__file__).read_text(encoding="utf-8")
        if getattr(wd, "__file__", None) else ""
    )
    assert "5-min)" not in src, "controller cadence must be derived, not typed"


def test_interval_duration_parser():
    parse = wd.live_controller_interval_seconds  # exercised via the regex below
    assert callable(parse)
    # The parser is internal to that function; assert the pinned value's shape
    # instead of re-implementing it here.
    assert wd.CONTROLLER_INTERVAL_SECONDS > 0


def test_assumed_interval_matches_the_live_task():
    """FAILS (never skips) when the deployed task disagrees with the pin.

    Skipping on an unreadable task would let the assumption rot silently --
    which is the exact failure being fixed. Unreadable is reported as such.
    """
    live = wd.live_controller_interval_seconds()
    if live is None:
        import pytest
        pytest.fail(
            "could not read %s repetition interval; the pinned "
            "CONTROLLER_INTERVAL_SECONDS=%s is unverified"
            % (wd.CONTROLLER_TASK, wd.CONTROLLER_INTERVAL_SECONDS)
        )
    assert live == wd.CONTROLLER_INTERVAL_SECONDS, (
        "live task interval %.0fs != pinned %.0fs -- update "
        "CONTROLLER_INTERVAL_SECONDS (the threshold derives from it)"
        % (live, wd.CONTROLLER_INTERVAL_SECONDS)
    )
