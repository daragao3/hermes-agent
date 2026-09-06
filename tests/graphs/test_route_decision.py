"""Routing: which decision a score earns, and what can veto it.

The weighted total is a poor discriminator at the bottom of the range, and
baseline #1 (2026-09-04) measured how poor. Of 28 golden-set jobs whose posting
states a compensation ceiling below the candidate's bail line, 20 scored between
5.0 and 8.75 and were routed to `review` alongside 22 jobs a person had actually
approved — 75% of the set in one band that cannot route its halves apart. Comp
Alignment is 10% of a seven-dimension rubric, so a sub-floor ceiling moves the
weighted total by well under a point.

The dimension itself separates cleanly where the total does not: across those 56
items the human-approved half never scored below 4.0 on `comp_alignment` and 26
of the 28 sub-floor items scored at or below 2.0. So the veto reads the
dimension directly.
"""

from __future__ import annotations

import pytest

from graphs import jobflow
from graphs.jobflow import route_decision_node


def _state(score, comp=8.0, **extra):
    state = {"score": score, "breakdown": {"comp_alignment": comp}}
    state.update(extra)
    return state


@pytest.fixture(autouse=True)
def _default_thresholds(monkeypatch):
    """Pin the deployed values so a host .env cannot move the test."""
    monkeypatch.delenv("HERMES_JOBFLOW_PROCEED_THRESHOLD", raising=False)
    monkeypatch.delenv("HERMES_JOBFLOW_REVIEW_THRESHOLD", raising=False)
    monkeypatch.delenv("HERMES_JOBFLOW_COMP_FLOOR", raising=False)


class TestTheCompFloorVeto:
    def test_a_sub_floor_comp_archives_a_review_band_score(self):
        """The case the veto exists for: 20 of 28 measured items looked like this."""
        assert route_decision_node(_state(7.4, comp=2.0))["decision"] == "archive"

    def test_a_review_band_score_above_the_floor_still_reviews(self):
        assert route_decision_node(_state(7.4, comp=2.5))["decision"] == "review"

    def test_the_floor_is_inclusive(self):
        """26 of the 28 measured sub-floor items sat exactly at 1.0, 1.5 or 2.0."""
        assert route_decision_node(_state(7.4, comp=2.0))["decision"] == "archive"
        assert route_decision_node(_state(7.4, comp=2.01))["decision"] == "review"

    def test_the_lowest_human_approved_comp_in_the_set_is_untouched(self):
        """Measured floor of the human-approved half was 4.0; it must route normally."""
        assert route_decision_node(_state(7.4, comp=4.0))["decision"] == "review"

    def test_the_veto_also_applies_in_the_proceed_band(self):
        """Deliberate and unobservable in the baseline: no measured item was both.

        `hard_filter` excludes on a stated sub-floor ceiling with no carve-out
        for an otherwise-excellent job, and a model-read veto that were weaker
        than the deterministic one would be the odd rule, not the safe one.
        """
        assert route_decision_node(_state(9.0, comp=1.0))["decision"] == "archive"

    def test_a_low_total_still_archives_on_the_total_alone(self):
        assert route_decision_node(_state(3.0, comp=9.0))["decision"] == "archive"

    def test_ordinary_routing_is_unchanged(self):
        assert route_decision_node(_state(9.0))["decision"] == "tailor"
        assert route_decision_node(_state(7.0))["decision"] == "review"
        assert route_decision_node(_state(2.0))["decision"] == "archive"


class TestTheVetoFailsTowardEligible:
    """Absent or unreadable comp data must never archive.

    A job wrongly kept costs one model call. A job wrongly archived destroys a
    real opportunity with no artifact to notice it happened, so every ambiguity
    here resolves toward review.
    """

    def test_a_missing_breakdown_does_not_archive(self):
        assert route_decision_node({"score": 7.4})["decision"] == "review"

    def test_an_empty_breakdown_does_not_archive(self):
        assert route_decision_node({"score": 7.4, "breakdown": {}})["decision"] == "review"

    def test_a_null_comp_does_not_archive(self):
        assert route_decision_node(_state(7.4, comp=None))["decision"] == "review"

    def test_a_non_numeric_comp_does_not_archive(self):
        assert route_decision_node(_state(7.4, comp="low"))["decision"] == "review"

    def test_a_boolean_comp_does_not_archive(self):
        """True == 1 in Python and would veto silently."""
        assert route_decision_node(_state(7.4, comp=True))["decision"] == "review"

    def test_a_non_mapping_breakdown_does_not_archive(self):
        assert route_decision_node({"score": 7.4, "breakdown": [2.0]})["decision"] == "review"

    def test_an_llm_error_still_reaches_the_operator(self):
        """The error fail-safe outranks the veto: never archive what nobody scored."""
        state = _state(0.0, comp=1.0, error="match_score LLM failed")
        assert route_decision_node(state)["decision"] == "review"


class TestTheFloorIsTunable:
    def test_the_floor_can_be_raised(self, monkeypatch):
        monkeypatch.setenv("HERMES_JOBFLOW_COMP_FLOOR", "5.0")
        assert route_decision_node(_state(7.4, comp=4.0))["decision"] == "archive"

    def test_a_negative_floor_disables_the_veto(self, monkeypatch):
        """The documented off switch — dimension scores are bounded at 0."""
        monkeypatch.setenv("HERMES_JOBFLOW_COMP_FLOOR", "-1")
        assert route_decision_node(_state(7.4, comp=0.0))["decision"] == "review"

    def test_an_unparseable_floor_falls_back_to_the_default(self, monkeypatch):
        """A typo in .env must not silently disable the veto or archive everything."""
        monkeypatch.setenv("HERMES_JOBFLOW_COMP_FLOOR", "two")
        assert route_decision_node(_state(7.4, comp=2.0))["decision"] == "archive"
        assert route_decision_node(_state(7.4, comp=4.0))["decision"] == "review"


class TestTheScoreBandsAreTunable:
    """Band EDGES and env overrides, read from the constants the router shares.

    Two gaps, both measured 2026-09-06. Nothing above touches a boundary --
    every case sits well inside a band -- and neither threshold's env override
    was ever exercised, while the comp floor's three were.

    These follow the constants rather than pinning their values: moving
    `_DEFAULT_PROCEED_THRESHOLD` to 9.0 leaves this class green, because the
    edge it asserts moves with it. That is deliberate -- what must not drift
    is the constant against the three places that restate it in prose, and
    that is pinned in tests/graphs/test_critic_prompt_config.py, where the
    same mutation fails three tests. Here the claim is narrower: whatever the
    bands are, the edges are inclusive and an override actually moves them.
    """

    def test_the_proceed_boundary_is_inclusive(self):
        proceed = jobflow._DEFAULT_PROCEED_THRESHOLD
        assert route_decision_node(_state(proceed))["decision"] == "tailor"
        assert route_decision_node(_state(proceed - 0.01))["decision"] == "review"

    def test_the_review_boundary_is_inclusive(self):
        review = jobflow._DEFAULT_REVIEW_THRESHOLD
        assert route_decision_node(_state(review))["decision"] == "review"
        assert route_decision_node(_state(review - 0.01))["decision"] == "archive"

    def test_the_proceed_threshold_can_be_moved_by_env(self, monkeypatch):
        monkeypatch.setenv("HERMES_JOBFLOW_PROCEED_THRESHOLD", "7.0")
        assert route_decision_node(_state(7.4))["decision"] == "tailor"

    def test_the_review_threshold_can_be_moved_by_env(self, monkeypatch):
        monkeypatch.setenv("HERMES_JOBFLOW_REVIEW_THRESHOLD", "8.0")
        assert route_decision_node(_state(7.4))["decision"] == "archive"

    def test_a_malformed_threshold_raises_rather_than_routing_on_a_guess(self, monkeypatch):
        """Deliberately unlike the comp floor, which falls back -- see `_comp_floor`.

        A threshold that silently reverted to its default would route a
        calibration run against a band nobody asked for and report nothing.
        """
        monkeypatch.setenv("HERMES_JOBFLOW_PROCEED_THRESHOLD", "eight")
        with pytest.raises(ValueError):
            route_decision_node(_state(7.4))
