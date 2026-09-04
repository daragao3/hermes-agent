"""The gate that stands between a candidate route and production.

The premium-routing plan's release gate reads: *"No premium route is changed
until workload evaluation and shadow outputs pass. Cost is a tie-breaker only
after quality floors."* This module is that gate, and it is built to fail
closed — a route that cannot be measured does not pass.

The asymmetry from the filter applies here too, sharper. A candidate that
advances a job it should have excluded costs one model call. A candidate that
excludes a job a person approved destroys a real opportunity, silently. So
precision on human-approved items is required to be perfect, and a missing
prediction is never scored as correct.
"""

from __future__ import annotations

import pytest

from jobflow_quality.evaluation import Prediction, evaluate
from jobflow_quality.golden_set import Difficulty, GoldenItem, Label, LabelSource


def _item(job_id, label=Label.ADVANCE, difficulty=Difficulty.NUANCED):
    source = (LabelSource.HUMAN_APPROVAL if label is Label.ADVANCE
              else LabelSource.DETERMINISTIC_EXCLUSION)
    return GoldenItem(
        job_id=job_id, label=label, source=source, difficulty=difficulty,
        evidence=source.value, description_sha256="0" * 64,
    )


def _balanced(n=4):
    items = tuple(_item(f"a{i}", Label.ADVANCE, Difficulty.NUANCED) for i in range(n))
    items += tuple(_item(f"e{i}", Label.EXCLUDE, Difficulty.OBVIOUS) for i in range(n))
    return items


def _perfect(items):
    return tuple(Prediction(job_id=i.job_id, label=i.label) for i in items)



def _partial(items, difficulty, n_correct):
    """Perfect everywhere except `difficulty`, where only `n_correct` are right."""
    preds = []
    seen = 0
    for item in items:
        if item.difficulty is not difficulty:
            preds.append(Prediction(job_id=item.job_id, label=item.label))
            continue
        seen += 1
        if seen <= n_correct:
            preds.append(Prediction(job_id=item.job_id, label=item.label))
        else:
            flipped = Label.EXCLUDE if item.label is Label.ADVANCE else Label.ADVANCE
            preds.append(Prediction(job_id=item.job_id, label=flipped))
    return tuple(preds)


class TestPerfectCandidate:
    def test_a_candidate_agreeing_everywhere_passes(self):
        items = _balanced()
        r = evaluate(items, _perfect(items))
        assert r.passed is True
        assert r.reasons == ()

    def test_counts_are_reported(self):
        items = _balanced()
        r = evaluate(items, _perfect(items))
        assert r.total == 8
        assert r.correct == 8


class TestTheExpensiveError:
    """Excluding something a person approved. Never acceptable, at any rate."""

    def test_one_false_exclude_on_a_human_approval_fails_the_gate(self):
        items = _balanced()
        preds = list(_perfect(items))
        preds[0] = Prediction(job_id=items[0].job_id, label=Label.EXCLUDE)
        r = evaluate(items, tuple(preds))
        assert r.passed is False
        assert items[0].job_id in r.false_excludes

    def test_the_reason_names_the_protected_positive_rule(self):
        items = _balanced()
        preds = list(_perfect(items))
        preds[0] = Prediction(job_id=items[0].job_id, label=Label.EXCLUDE)
        r = evaluate(items, tuple(preds))
        assert any("protected" in reason for reason in r.reasons)

    def test_a_false_advance_alone_does_not_fail_the_gate(self):
        """Wrongly keeping a job costs one model call. That is the cheap error."""
        items = _balanced()
        preds = list(_perfect(items))
        preds[-1] = Prediction(job_id=items[-1].job_id, label=Label.ADVANCE)
        r = evaluate(items, tuple(preds))
        assert items[-1].job_id in r.false_advances
        assert r.passed is True


class TestMissingPredictionsAreNotCorrect:
    def test_an_unpredicted_item_fails_the_gate(self):
        """Silence must never read as agreement — that is how a broken candidate passes."""
        items = _balanced()
        r = evaluate(items, _perfect(items)[:-1])
        assert r.passed is False
        assert any("coverage" in reason for reason in r.reasons)

    def test_an_unpredicted_item_is_not_counted_correct(self):
        items = _balanced()
        r = evaluate(items, _perfect(items)[:-1])
        assert r.correct == 7
        assert r.unpredicted == (items[-1].job_id,)

    def test_no_predictions_at_all_fails(self):
        r = evaluate(_balanced(), ())
        assert r.passed is False
        assert r.correct == 0

    def test_a_prediction_for_an_unknown_job_is_ignored_not_credited(self):
        items = _balanced()
        preds = _perfect(items) + (Prediction(job_id="ghost", label=Label.ADVANCE),)
        r = evaluate(items, preds)
        assert r.total == 8
        assert r.passed is True


class TestUnbalancedSetsCannotPass:
    def test_an_all_obvious_set_fails_regardless_of_accuracy(self):
        """100% on easy negatives is not evidence of quality."""
        items = tuple(_item(f"e{i}", Label.EXCLUDE, Difficulty.OBVIOUS) for i in range(10))
        r = evaluate(items, _perfect(items))
        assert r.passed is False
        assert any("balance" in reason for reason in r.reasons)

    def test_an_empty_set_fails(self):
        r = evaluate((), ())
        assert r.passed is False


class TestPerDifficultyReporting:
    def test_accuracy_is_broken_out_by_difficulty(self):
        """An aggregate hides the only number that matters — the nuanced one."""
        items = _balanced()
        preds = list(_perfect(items))
        preds[0] = Prediction(job_id=items[0].job_id, label=Label.EXCLUDE)
        r = evaluate(items, tuple(preds))
        assert r.accuracy_by_difficulty["obvious"] == 1.0
        assert r.accuracy_by_difficulty["nuanced"] < 1.0


class TestContract:
    def test_the_result_is_immutable(self):
        items = _balanced()
        r = evaluate(items, _perfect(items))
        with pytest.raises(AttributeError):
            r.passed = False

    def test_duplicate_predictions_for_one_job_are_rejected(self):
        """Two verdicts for one item means the caller cannot say what it predicted."""
        items = _balanced()
        preds = _perfect(items) + (Prediction(job_id=items[0].job_id, label=Label.EXCLUDE),)
        with pytest.raises(ValueError, match="duplicate"):
            evaluate(items, preds)

    def test_reasons_are_present_whenever_the_gate_fails(self):
        r = evaluate((), ())
        assert r.passed is False and r.reasons


class TestCircularityIsVisibleInTheReport:
    """A candidate graded against labels IT produced agrees with itself.

    The deterministic-exclusion labels come from `hard_filter`, so evaluating
    that same filter scores 100% on them by construction. Breaking accuracy out
    by label source puts that in the artifact a reader actually looks at,
    instead of only in the prose alongside it.
    """

    def test_accuracy_is_broken_out_by_label_source(self):
        items = _balanced()
        r = evaluate(items, _perfect(items))
        assert r.accuracy_by_source["human_approval"] == 1.0
        assert r.accuracy_by_source["deterministic_exclusion"] == 1.0

    def test_a_source_with_a_miss_reports_below_one(self):
        items = _balanced()
        preds = list(_perfect(items))
        preds[0] = Prediction(job_id=items[0].job_id, label=Label.EXCLUDE)
        r = evaluate(items, tuple(preds))
        assert r.accuracy_by_source["human_approval"] < 1.0
        assert r.accuracy_by_source["deterministic_exclusion"] == 1.0


class TestTheAccuracyFloor:
    """Without a floor, a candidate that answers everything the same way passes.

    Measured rather than hypothesised. Baseline #1 (2026-09-04, the first run
    ever made against the golden set) recorded a constant "always advance"
    predictor scoring 50% on the 56-item set, producing zero false excludes,
    and passing with an empty reason list. The same run scored 100% on the
    nuanced half and 28.6% on the obvious half for a 64.3% headline — which is
    why the floor is applied per difficulty and not to the aggregate the
    failing half hides inside.
    """

    def test_a_constant_advance_candidate_fails(self):
        items = _balanced()
        preds = tuple(Prediction(job_id=i.job_id, label=Label.ADVANCE) for i in items)
        r = evaluate(items, preds)
        assert r.passed is False

    def test_a_constant_candidate_is_named_as_one(self):
        items = _balanced()
        preds = tuple(Prediction(job_id=i.job_id, label=Label.ADVANCE) for i in items)
        r = evaluate(items, preds)
        assert any("constant" in reason for reason in r.reasons)

    def test_a_constant_exclude_candidate_fails_as_a_constant_too(self):
        """It already failed on protected positives; it must be named a constant as well."""
        items = _balanced()
        preds = tuple(Prediction(job_id=i.job_id, label=Label.EXCLUDE) for i in items)
        r = evaluate(items, preds)
        assert r.passed is False
        assert any("constant" in reason for reason in r.reasons)
        assert any("protected" in reason for reason in r.reasons)

    def test_a_ghost_prediction_cannot_rescue_a_constant_candidate(self):
        """Only predictions that matched an item count toward what was answered."""
        items = _balanced()
        preds = tuple(Prediction(job_id=i.job_id, label=Label.ADVANCE) for i in items)
        preds += (Prediction(job_id="ghost", label=Label.EXCLUDE),)
        r = evaluate(items, preds)
        assert any("constant" in reason for reason in r.reasons)

    def test_a_strong_headline_with_one_stratum_below_chance_fails(self):
        """The exact shape baseline #1 found, reproduced: 100% / 28.6% for a 64.3% headline."""
        items = _balanced(7)
        r = evaluate(items, _partial(items, Difficulty.OBVIOUS, 2))
        assert r.correct == 9 and r.total == 14
        assert r.accuracy_by_difficulty["nuanced"] == 1.0
        assert r.passed is False

    def test_the_reason_names_the_difficulty_that_failed(self):
        """An operator must be able to act on it without re-deriving which half broke."""
        items = _balanced(7)
        r = evaluate(items, _partial(items, Difficulty.OBVIOUS, 2))
        assert any("obvious" in reason for reason in r.reasons)
        assert not any("nuanced" in reason for reason in r.reasons)

    def test_a_stratum_exactly_at_chance_fails(self):
        """Chance is the line to beat, not the line to match."""
        items = _balanced(4)
        r = evaluate(items, _partial(items, Difficulty.OBVIOUS, 2))
        assert r.accuracy_by_difficulty["obvious"] == 0.5
        assert r.passed is False

    def test_a_stratum_just_above_chance_passes(self):
        """The floor is the weakest rule that does the job, not a quality bar."""
        items = _balanced(5)
        r = evaluate(items, _partial(items, Difficulty.OBVIOUS, 3))
        assert r.accuracy_by_difficulty["obvious"] == 0.6
        assert r.passed is True

    def test_a_perfect_candidate_still_passes(self):
        items = _balanced()
        assert evaluate(items, _perfect(items)).passed is True


class TestTheFloorDoesNotFireOnTheSetsOwnShape:
    def test_a_single_label_set_does_not_make_a_correct_candidate_degenerate(self):
        """`balanced` checks DIFFICULTY, so a set may legitimately carry one label.

        A candidate that gets such a set entirely right emits one label and must
        not be called a constant for it — that would fail the gate on the shape
        of the set rather than on anything the candidate did.
        """
        items = (
            _item("a0", Label.ADVANCE, Difficulty.NUANCED),
            _item("a1", Label.ADVANCE, Difficulty.OBVIOUS),
        )
        r = evaluate(items, _perfect(items))
        assert r.passed is True
        assert r.reasons == ()
