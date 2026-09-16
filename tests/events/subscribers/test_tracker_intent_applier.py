"""Tests for the tracker-intent-applier subscriber's re-drive feature flag.

The flag (TRACKER_APPLIER_REDRIVE_ENABLED, default OFF) is the HARD GATE: auto-
re-drive must stay disabled until jobflow-api :4100 runs commit 8d7b5f5's dist
(idempotent no-op guard live). IntentApplier.redrive_partials() is pure/always-
acts; the subscriber wrapper is where the flag lives.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from events.bus import EventBus
from events.subscribers.tracker_intent_applier import (
    TrackerIntentApplierSubscriber,
    _hermes_root,
    _reap_enabled_from_env,
    _redrive_enabled_from_env,
    tracker_partial_dir,
)
from hermes_constants import get_default_hermes_root
from intent_applier.canonical_pipeline_reader import _default_canonical_path


@pytest.fixture
def subscriber(tmp_path):
    bus = EventBus(db_path=tmp_path / "events" / "event_bus.db")
    return TrackerIntentApplierSubscriber(bus)


class TestRedriveFlagParsing:
    def test_default_is_disabled(self, monkeypatch):
        monkeypatch.delenv("TRACKER_APPLIER_REDRIVE_ENABLED", raising=False)
        assert _redrive_enabled_from_env() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("TRACKER_APPLIER_REDRIVE_ENABLED", val)
        assert _redrive_enabled_from_env() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "", "off", "garbage"])
    def test_other_values_stay_disabled(self, monkeypatch, val):
        monkeypatch.setenv("TRACKER_APPLIER_REDRIVE_ENABLED", val)
        assert _redrive_enabled_from_env() is False


class TestRedriveDelegation:
    def test_flag_off_is_noop(self, subscriber):
        subscriber._redrive_enabled = False
        subscriber._applier = MagicMock()
        assert subscriber.redrive_partials() == 0
        subscriber._applier.redrive_partials.assert_not_called()

    def test_flag_on_calls_applier(self, subscriber):
        subscriber._redrive_enabled = True
        subscriber._applier = MagicMock()
        subscriber._applier.redrive_partials.return_value = {
            "a_INTENT_main.json": "redriven",
            "b_INTENT_main.json": "waiting",
        }
        assert subscriber.redrive_partials() == 1
        subscriber._applier.redrive_partials.assert_called_once()

    def test_flag_on_but_applier_not_built_is_noop(self, subscriber):
        subscriber._redrive_enabled = True
        subscriber._applier = None
        assert subscriber.redrive_partials() == 0


class TestReapEnabledFromEnv:
    def test_default_is_disabled(self, monkeypatch):
        monkeypatch.delenv("TRACKER_APPLIER_REAP_CONVERGED_ENABLED", raising=False)
        assert _reap_enabled_from_env() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("TRACKER_APPLIER_REAP_CONVERGED_ENABLED", val)
        assert _reap_enabled_from_env() is True

    @pytest.mark.parametrize("val", ["0", "off", "no", ""])
    def test_other_values_stay_disabled(self, monkeypatch, val):
        monkeypatch.setenv("TRACKER_APPLIER_REAP_CONVERGED_ENABLED", val)
        assert _reap_enabled_from_env() is False


class TestSubscriberReap:
    def test_flag_off_is_noop(self, subscriber):
        subscriber._reap_enabled = False
        subscriber._applier = MagicMock()
        assert subscriber.reap_converged_partials() == 0
        subscriber._applier.reap_converged_partials.assert_not_called()

    def test_flag_on_calls_applier_and_counts_reaped(self, subscriber):
        subscriber._reap_enabled = True
        subscriber._applier = MagicMock()
        subscriber._applier.reap_converged_partials.return_value = {
            "a.rd5.json": "reaped",
            "b.rd5.json": "not_converged",
            "c.rd5.json": "reaped",
        }
        assert subscriber.reap_converged_partials() == 2
        subscriber._applier.reap_converged_partials.assert_called_once()

    def test_flag_on_but_applier_not_built_is_noop(self, subscriber):
        subscriber._reap_enabled = True
        subscriber._applier = None
        assert subscriber.reap_converged_partials() == 0


class TestTrackerPartialDir:
    def test_ends_in_partial(self):
        assert tracker_partial_dir().name == "partial"
        assert tracker_partial_dir().parent.name == "tracker"


class TestHermesRootIsHermetic:
    """The mailbox root must follow the canonical resolver, not ``Path.home()``.

    Regression guard for the 2026-08-10 broad-suite hang: ``_hermes_root()``
    fell back to ``Path.home() / ".hermes"``, which the hermetic conftest
    (HERMES_HOME -> tmp_path) cannot redirect. Every test that called
    ``events.gateway_integration.startup()`` therefore rehydrated the
    idempotency DB from the REAL ``~/.hermes/mailbox/tracker/processed``
    (2,308 files, ~14s cold), wrote to the REAL
    ``~/.hermes/events/applier_state.db``, and started a live applier
    thread against the production inbox. The wall-clock cost pushed those
    tests past the 30s ``addopts`` cap, and ``--timeout-method=thread``
    hard-exits the process, so ``pytest tests/events tests/cron`` never
    printed a summary line.
    """

    def test_root_follows_canonical_resolver(self):
        # get_default_hermes_root() maps a profile-scoped HERMES_HOME back to
        # the ~/.hermes root (production is unchanged) but returns an
        # out-of-tree HERMES_HOME as-is — which is what makes tests hermetic.
        assert _hermes_root() == get_default_hermes_root()

    def test_root_is_not_the_real_hermes_home_under_test(self):
        assert _hermes_root() != Path.home() / ".hermes"

    def test_explicit_hermes_root_env_still_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_ROOT", str(tmp_path / "pinned"))
        assert _hermes_root() == tmp_path / "pinned"


class TestCanonicalPipelinePathIsHermetic:
    """Same bug, same fix, in the reaper's canonical-state reader."""

    def test_default_canonical_path_follows_canonical_resolver(self):
        assert _default_canonical_path() == (
            get_default_hermes_root()
            / "profiles" / "tracker" / "workspace" / "pipeline.json"
        )

    def test_default_canonical_path_is_not_the_real_hermes_home(self):
        assert not str(_default_canonical_path()).startswith(
            str(Path.home() / ".hermes")
        )


class TestRehydrateIsDeferredOffStartup:
    """startup() runs on the gateway EVENT LOOP thread (run_startup ->
    eventbus_startup -> startup_all). On 2026-09-15 21:08 the synchronous
    rehydrate of ~1k processed/ files blocked that loop for ~2 min: the
    30s telegram-init deadline could not fire, telegram's 45s connect timed
    out, env_probe starved. The applier has its OWN single-writer poll
    thread, so the replay belongs there -- before the first scan, never on
    the loop."""

    @pytest.fixture
    def rehydrate_calls(self, monkeypatch):
        from intent_applier.idempotency import IdempotencyTracker
        calls = []
        monkeypatch.setattr(
            IdempotencyTracker, "rehydrate_from_processed",
            lambda self, d: calls.append(d) or 0,
        )
        return calls

    def test_startup_does_not_rehydrate(self, subscriber, rehydrate_calls):
        subscriber.startup()
        assert rehydrate_calls == []
        assert subscriber._applier is not None

    def test_first_poll_rehydrates_once_before_scanning(self, subscriber, rehydrate_calls):
        subscriber.startup()
        order = []
        subscriber._applier.scan_inbox = lambda: order.append("scan") or {}
        # Interpose on the recorded rehydrate so we can see ordering.
        real = subscriber._ensure_rehydrated

        def spy():
            ok = real()
            if rehydrate_calls and "rehydrate" not in order:
                order.append("rehydrate")
            return ok
        subscriber._ensure_rehydrated = spy

        subscriber.poll()
        subscriber.poll()
        assert len(rehydrate_calls) == 1
        assert order == ["rehydrate", "scan", "scan"]

    def test_redrive_and_reap_also_rehydrate_first(self, subscriber, rehydrate_calls, monkeypatch):
        monkeypatch.setenv("TRACKER_APPLIER_REDRIVE_ENABLED", "1")
        monkeypatch.setenv("TRACKER_APPLIER_REAP_ENABLED", "1")
        sub = type(subscriber)(subscriber.bus)
        sub.startup()
        sub._applier.redrive_partials = lambda: {}
        sub._applier.reap_converged_partials = lambda: {}
        sub.redrive_partials()
        sub.reap_converged_partials()
        assert len(rehydrate_calls) == 1

    def test_rehydrate_failure_fails_closed(self, subscriber, monkeypatch):
        """Same contract as before the change: a rehydrate that raises used
        to abort startup() (startup_all logs it, _applier stays None, nothing
        is ever applied). Deferred, it must still never scan the inbox."""
        from intent_applier.idempotency import IdempotencyTracker

        def boom(self, d):
            raise RuntimeError("disk gone")
        monkeypatch.setattr(IdempotencyTracker, "rehydrate_from_processed", boom)
        subscriber.startup()
        scanned = []
        subscriber._applier.scan_inbox = lambda: scanned.append(1) or {}

        assert subscriber.poll() == 0
        assert subscriber.poll() == 0
        assert scanned == []
        assert subscriber._applier is None
