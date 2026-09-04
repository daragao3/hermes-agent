"""Assemble a labelled evaluation set from evidence that did not come from the scorer.

The premium-routing plan asks for a golden set before any route may change.
The obvious source is the pipeline's own history — but most of it is the
scorer's own output fed back as truth. 4,670 rows are archived, and they are
archived *because the scorer scored them low*. Grading the scorer against those
measures nothing: it will agree with itself perfectly and prove nothing about
quality.

So the only admissible labels are ones the scorer did not produce:

* a human acted on the job (``actor_id: diego`` through the intent applier), or
* a fact printed in the posting decides it (a stated ceiling under the bail
  line), which is true whatever any model says.

Auto-route approvals look identical to human ones at a glance — same stage,
same shape — and are the trap this module exists to avoid.
"""

from __future__ import annotations

import pytest

from jobflow_quality.golden_set import (
    Difficulty,
    Label,
    LabelSource,
    build_golden_set,
)
from jobflow_quality.matcher_filter import DEFAULT_CRITERIA


def _row(**over):
    base = {
        "title": "VP Data Engineering",
        "company": "Acme Bank",
        "description_raw": "Lead the data platform.",
        "score": 7.8,
        "stage": "approved",
        "history": [],
    }
    base.update(over)
    return base


def _human_event(**over):
    """A genuine human approval: actor, emitter and intent type together.

    All three are load-bearing since 2026-09-03. A bare ``actor_id`` used to be
    enough, which is why the Control Center caller-default could have written
    rows that read as human decisions.
    """
    meta = {"actor_id": "diego", "emitted_by": "tracker-intent-applier",
            "intent_type": "APPROVAL_INTENT"}
    meta.update(over)
    return {"from_stage": "scored", "to_stage": "approved", "metadata": meta}


def _nested_human_event(**over):
    """The shape real history actually carries: intent under metadata.metadata."""
    inner = {"actor_id": "diego", "emitted_by": "tracker-intent-applier",
             "intent_type": "APPROVAL_INTENT"}
    inner.update(over)
    return {"from_stage": "scored", "to_stage": "approved",
            "metadata": {"source_file": "20260714T011234154965Z_PIPELINE_UPDATE_operator_045b191d.json",
                         "metadata": inner}}


def _auto_event():
    return {"from_stage": "scored", "to_stage": "approved",
            "metadata": {"approved_by": "main-auto-route",
                         "reason": "Auto-approved under JobFlow score routing (score >= 8.0)"}}


class TestHumanApprovalsBecomeLabels:
    def test_a_diego_actor_event_yields_an_advance_label(self):
        items = build_golden_set({"j1": _row(history=[_human_event()])}, DEFAULT_CRITERIA)
        assert len(items) == 1
        assert items[0].label is Label.ADVANCE
        assert items[0].source is LabelSource.HUMAN_APPROVAL

    def test_human_approvals_are_marked_nuanced(self):
        """They are the hard cases — a scorer must not be graded only on easy ones."""
        items = build_golden_set({"j1": _row(history=[_human_event()])}, DEFAULT_CRITERIA)
        assert items[0].difficulty is Difficulty.NUANCED

    def test_a_later_archive_does_not_revoke_the_approval(self):
        """Diego approved it; the employer going quiet is not a scoring error.

        11 of the 20 human-approved rows are archived today. Reading that as
        "the label was wrong" would invert most of the positive evidence.
        """
        row = _row(stage="archived", history=[_human_event()])
        items = build_golden_set({"j1": row}, DEFAULT_CRITERIA)
        assert len(items) == 1
        assert items[0].label is Label.ADVANCE


class TestCircularLabelsAreRefused:
    """The whole point. An auto-approval is the scorer's own verdict."""

    def test_an_auto_route_approval_is_not_a_label(self):
        items = build_golden_set({"j1": _row(history=[_auto_event()])}, DEFAULT_CRITERIA)
        assert items == ()

    def test_stage_approved_alone_is_not_a_label(self):
        """26 of 32 approved rows are VIP auto-approvals, not scoring judgements."""
        items = build_golden_set({"j1": _row(stage="approved", vip=True, history=[])},
                                 DEFAULT_CRITERIA)
        assert items == ()

    def test_stage_archived_alone_is_not_a_label(self):
        """4,670 archived rows were archived BY the scorer. Circular."""
        items = build_golden_set({"j1": _row(stage="archived", history=[])},
                                 DEFAULT_CRITERIA)
        assert items == ()

    def test_a_human_event_alongside_an_auto_event_still_counts(self):
        row = _row(history=[_auto_event(), _human_event()])
        assert len(build_golden_set({"j1": row}, DEFAULT_CRITERIA)) == 1


class TestDeterministicExclusions:
    def test_a_posting_under_the_bail_line_yields_an_exclude_label(self):
        row = _row(salary_range={"min": 90000.0, "max": 120000.0,
                                 "currency": "USD", "period": "annual"})
        items = build_golden_set({"j1": row}, DEFAULT_CRITERIA)
        assert len(items) == 1
        assert items[0].label is Label.EXCLUDE
        assert items[0].source is LabelSource.DETERMINISTIC_EXCLUSION

    def test_deterministic_exclusions_are_marked_obvious(self):
        """Kept separate so an evaluator cannot be flattered by easy negatives."""
        row = _row(salary_range={"min": 90000.0, "max": 120000.0,
                                 "currency": "USD", "period": "annual"})
        assert build_golden_set({"j1": row}, DEFAULT_CRITERIA)[0].difficulty is Difficulty.OBVIOUS

    def test_an_ordinary_posting_yields_no_label(self):
        assert build_golden_set({"j1": _row()}, DEFAULT_CRITERIA) == ()


class TestConflicts:
    def test_a_human_approval_overrides_a_deterministic_exclusion(self):
        """A person looked at it and said yes. That outranks the rule."""
        row = _row(history=[_human_event()],
                   salary_range={"min": 90000.0, "max": 120000.0,
                                 "currency": "USD", "period": "annual"})
        items = build_golden_set({"j1": row}, DEFAULT_CRITERIA)
        assert len(items) == 1, "one job must never produce two contradictory labels"
        assert items[0].label is Label.ADVANCE
        assert items[0].conflicted is True


class TestSecretFree:
    def test_no_item_carries_raw_posting_text(self):
        """Task 6: store references and hashes, not private raw documents."""
        secret = "CONFIDENTIAL internal comp band do not distribute"
        row = _row(description_raw=secret, history=[_human_event()])
        item = build_golden_set({"j1": row}, DEFAULT_CRITERIA)[0]
        assert secret not in repr(item)
        for value in vars(item).values():
            assert secret not in str(value)

    def test_the_description_is_referenced_by_hash(self):
        row = _row(description_raw="abc", history=[_human_event()])
        item = build_golden_set({"j1": row}, DEFAULT_CRITERIA)[0]
        assert len(item.description_sha256) == 64
        assert item.description_sha256 == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_evidence_is_a_bounded_code_not_free_text(self):
        row = _row(history=[_human_event()])
        item = build_golden_set({"j1": row}, DEFAULT_CRITERIA)[0]
        assert item.evidence in {s.value for s in LabelSource} or item.evidence.islower()
        assert len(item.evidence) <= 64


class TestDeterminism:
    def test_the_same_input_yields_the_same_ordering(self):
        jobs = {f"j{i}": _row(history=[_human_event()]) for i in range(8)}
        assert build_golden_set(jobs, DEFAULT_CRITERIA) == build_golden_set(jobs, DEFAULT_CRITERIA)

    def test_ordering_does_not_depend_on_dict_insertion_order(self):
        a = {"j2": _row(history=[_human_event()]), "j1": _row(history=[_human_event()])}
        b = {"j1": _row(history=[_human_event()]), "j2": _row(history=[_human_event()])}
        assert [i.job_id for i in build_golden_set(a, DEFAULT_CRITERIA)] == \
               [i.job_id for i in build_golden_set(b, DEFAULT_CRITERIA)]

    def test_items_are_immutable(self):
        item = build_golden_set({"j1": _row(history=[_human_event()])}, DEFAULT_CRITERIA)[0]
        with pytest.raises(AttributeError):
            item.label = Label.EXCLUDE


class TestMalformedInput:
    @pytest.mark.parametrize("jobs", ({}, {"j1": None}, {"j1": "nonsense"}, {"j1": {}}))
    def test_unusable_input_yields_no_labels_and_never_raises(self, jobs):
        assert build_golden_set(jobs, DEFAULT_CRITERIA) == ()

    def test_a_malformed_history_entry_is_skipped(self):
        row = _row(history=["nonsense", None, _human_event()])
        assert len(build_golden_set({"j1": row}, DEFAULT_CRITERIA)) == 1

    def test_a_job_with_no_id_key_is_skipped(self):
        assert build_golden_set({"": _row(history=[_human_event()])}, DEFAULT_CRITERIA) == ()


class TestSetComposition:
    def test_the_set_reports_its_own_balance(self):
        from jobflow_quality.golden_set import summarize

        jobs = {
            "a": _row(history=[_human_event()]),
            "b": _row(salary_range={"min": 1.0, "max": 90000.0,
                                    "currency": "USD", "period": "annual"}),
            "c": _row(),
        }
        s = summarize(build_golden_set(jobs, DEFAULT_CRITERIA))
        assert s["total"] == 2
        assert s["by_label"] == {"advance": 1, "exclude": 1}
        assert s["by_difficulty"] == {"nuanced": 1, "obvious": 1}

    def test_an_all_obvious_set_is_flagged_as_unbalanced(self):
        """A set of only easy negatives makes any scorer look good."""
        from jobflow_quality.golden_set import summarize

        jobs = {f"j{i}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                            "currency": "USD", "period": "annual"})
                for i in range(5)}
        s = summarize(build_golden_set(jobs, DEFAULT_CRITERIA))
        assert s["balanced"] is False

    def test_a_mixed_set_is_balanced(self):
        from jobflow_quality.golden_set import summarize

        jobs = {f"h{i}": _row(history=[_human_event()]) for i in range(5)}
        jobs.update({f"e{i}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                                 "currency": "USD", "period": "annual"})
                     for i in range(5)})
        assert summarize(build_golden_set(jobs, DEFAULT_CRITERIA))["balanced"] is True


class TestBalancedSampling:
    """109 real items are 82% obvious negatives. Used whole, they hide failure.

    Downsampling the dominant difficulty is what makes the set usable at all —
    but it must be deterministic, or two evaluation runs grade against
    different data and their scores are not comparable.
    """

    def _mixed(self, nuanced: int, obvious: int):
        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(nuanced)}
        jobs.update({f"e{i:03d}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                                     "currency": "USD", "period": "annual"})
                     for i in range(obvious)})
        return build_golden_set(jobs, DEFAULT_CRITERIA)

    def test_the_dominant_difficulty_is_capped_to_the_scarcer_one(self):
        from jobflow_quality.golden_set import balanced_sample, summarize

        sampled = balanced_sample(self._mixed(20, 89))
        s = summarize(sampled)
        assert s["by_difficulty"] == {"nuanced": 20, "obvious": 20}
        assert s["balanced"] is True

    def test_sampling_is_deterministic(self):
        items = self._mixed(20, 89)
        from jobflow_quality.golden_set import balanced_sample

        assert balanced_sample(items) == balanced_sample(items)

    def test_an_already_balanced_set_is_returned_unchanged(self):
        from jobflow_quality.golden_set import balanced_sample

        items = self._mixed(10, 10)
        assert balanced_sample(items) == items

    def test_sampling_never_invents_items(self):
        from jobflow_quality.golden_set import balanced_sample

        items = self._mixed(20, 89)
        assert set(balanced_sample(items)) <= set(items)

    def test_an_empty_set_samples_to_empty(self):
        from jobflow_quality.golden_set import balanced_sample

        assert balanced_sample(()) == ()

    def test_a_single_difficulty_set_cannot_be_balanced(self):
        """Refuse to pretend: with no nuanced cases there is nothing to sample to."""
        from jobflow_quality.golden_set import balanced_sample, summarize

        items = self._mixed(0, 12)
        assert balanced_sample(items) == ()
        assert summarize(balanced_sample(items))["balanced"] is False


class TestHumanLabelRequiresPositiveEvidence:
    """A person's *name* is not evidence that a person decided.

    Until 2026-09-03 both Control Center write paths defaulted the actor to
    "diego" when the request established nobody, so an unauthenticated loopback
    POST could mint a durable history entry that read as a human approval. The
    label now requires the approval gate itself — emitter and intent type —
    alongside the name. The pre-fix rows on disk are deliberately left as they
    are; this narrows what the *label* will accept, it does not rewrite history.
    """

    def test_the_real_nested_shape_still_earns_a_label(self):
        # Real history nests the intent under metadata.metadata; the fixture
        # above is flat. Both must work, or this passes in tests and silently
        # labels nothing in production.
        items = build_golden_set({"j1": _row(history=[_nested_human_event()])},
                                 DEFAULT_CRITERIA)
        assert len(items) == 1
        assert items[0].source is LabelSource.HUMAN_APPROVAL

    def test_a_bare_actor_name_is_not_a_human_decision(self):
        # Exactly what the caller-default produced: the name, nothing else.
        bare = {"from_stage": "scored", "to_stage": "approved",
                "metadata": {"actor_id": "diego"}}
        assert build_golden_set({"j1": _row(history=[bare])}, DEFAULT_CRITERIA) == ()

    def test_a_state_transition_is_not_an_approval(self):
        # Measured on live data: job 4432638835's only diego entry is a
        # review->ready move. An operator stepping a job between stages — to
        # verify a restart, say — is not a hiring decision.
        moved = _nested_human_event(intent_type="STATE_TRANSITION_INTENT")
        assert build_golden_set({"j1": _row(history=[moved])}, DEFAULT_CRITERIA) == ()

    def test_an_actor_without_the_intent_applier_is_not_a_human_decision(self):
        elsewhere = _human_event(emitted_by="operator_api")
        assert build_golden_set({"j1": _row(history=[elsewhere])}, DEFAULT_CRITERIA) == ()

    def test_the_three_fields_must_sit_on_one_record(self):
        # The old check json.dumps'd the whole entry and substring-matched, so
        # unrelated objects could combine to satisfy it. Here the actor sits on
        # one object and the approval markers on another: not evidence.
        split = {"from_stage": "scored", "to_stage": "approved",
                 "metadata": {"actor_id": "diego"},
                 "other": {"emitted_by": "tracker-intent-applier",
                           "intent_type": "APPROVAL_INTENT"}}
        assert build_golden_set({"j1": _row(history=[split])}, DEFAULT_CRITERIA) == ()

    def test_an_unattributed_actor_is_never_a_human_decision(self):
        # What the fix writes now in place of the fabricated default.
        unattributed = _nested_human_event(actor_id="unattributed:legacy_dashboard")
        assert build_golden_set({"j1": _row(history=[unattributed])},
                                DEFAULT_CRITERIA) == ()

    def test_a_job_keeps_its_label_when_one_of_several_entries_qualifies(self):
        # Live shape: job e8d66258 carries two operator "post-restart verify"
        # state transitions AND a genuine approval. The probes must not cost it
        # the label the real approval earns.
        row = _row(history=[
            _nested_human_event(intent_type="STATE_TRANSITION_INTENT",
                                notes="post-restart verify archived"),
            _nested_human_event(),
        ])
        items = build_golden_set({"j1": row}, DEFAULT_CRITERIA)
        assert len(items) == 1
        assert items[0].source is LabelSource.HUMAN_APPROVAL

    def test_field_matching_tolerates_case_and_padding(self):
        padded = _nested_human_event(intent_type="  approval_intent  ",
                                     emitted_by="Tracker-Intent-Applier")
        assert len(build_golden_set({"j1": _row(history=[padded])},
                                    DEFAULT_CRITERIA)) == 1

    def test_a_malformed_entry_is_not_evidence_and_does_not_raise(self):
        row = _row(history=[None, 42, "nonsense", {"metadata": {"actor_id": None}},
                            _nested_human_event()])
        items = build_golden_set({"j1": row}, DEFAULT_CRITERIA)
        assert len(items) == 1
class TestSamplingRequiresAReplayablePosting:
    """An item with no posting behind it cannot measure text comprehension.

    Measured on live data 2026-09-04: 65 of the 93 exclusions were the *same*
    company matched against a one-entry blocklist, and none of them carried
    posting text — the blocklist fires on the company field, so nothing ever
    fetched one. Sampled, they were 25 of 33 obvious items, so 38% of the
    published set was one string comparison repeated. The label is sound; what
    it *measures* is not what the set is for.
    """

    def _textless(self, **over):
        """A row the hard filter excludes on company, with no posting at all."""
        return _row(company="DataAnnotation", description_raw="", **over)

    def test_an_item_with_no_posting_is_not_replayable(self):
        items = build_golden_set({"j1": self._textless()}, DEFAULT_CRITERIA)
        assert items[0].evidence == "excluded_company"
        assert items[0].replayable is False

    def test_an_item_with_a_posting_is_replayable(self):
        items = build_golden_set({"j1": _row(history=[_human_event()])},
                                 DEFAULT_CRITERIA)
        assert items[0].replayable is True

    def test_the_empty_digest_is_what_marks_an_item_unreplayable(self):
        """Not a flag set at build time — the digest itself carries it."""
        import hashlib

        items = build_golden_set({"j1": self._textless()}, DEFAULT_CRITERIA)
        assert items[0].description_sha256 == hashlib.sha256(b"").hexdigest()

    def test_sampling_drops_items_with_no_posting(self):
        from jobflow_quality.golden_set import balanced_sample

        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(5)}
        jobs.update({f"x{i:03d}": self._textless() for i in range(5)})
        sampled = balanced_sample(build_golden_set(jobs, DEFAULT_CRITERIA))
        assert sampled == ()

    def test_every_sampled_item_is_replayable(self):
        from jobflow_quality.golden_set import balanced_sample

        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(6)}
        jobs.update({f"e{i:03d}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                                     "currency": "USD",
                                                     "period": "annual"})
                     for i in range(4)})
        jobs.update({f"x{i:03d}": self._textless() for i in range(20)})
        sampled = balanced_sample(build_golden_set(jobs, DEFAULT_CRITERIA))
        assert sampled
        assert all(i.replayable for i in sampled)

    def test_the_cap_is_computed_after_dropping_unreplayable_items(self):
        """The order is load-bearing, and getting it wrong is invisible.

        Dropping *after* the cap would fill the obvious bucket with the 20
        text-less rows, cap both halves at 6, and then hand back a lopsided set
        — the exact flattery the balance exists to remove, arriving under a
        summary that still reports the set balanced.
        """
        from jobflow_quality.golden_set import balanced_sample, summarize

        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(6)}
        jobs.update({f"e{i:03d}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                                     "currency": "USD",
                                                     "period": "annual"})
                     for i in range(4)})
        jobs.update({f"x{i:03d}": self._textless() for i in range(20)})
        s = summarize(balanced_sample(build_golden_set(jobs, DEFAULT_CRITERIA)))
        assert s["by_difficulty"] == {"nuanced": 4, "obvious": 4}

    def test_a_blocklisted_company_that_does_carry_text_is_kept(self):
        """The test is the posting, not the rule that excluded the job.

        Keyed on the evidence string instead, this item would be thrown away
        for carrying the wrong rule name while being perfectly replayable — and
        a new exclusion rule would be silently excluded from the set until
        someone remembered to name it here.
        """
        from jobflow_quality.golden_set import balanced_sample

        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(3)}
        jobs.update({f"b{i:03d}": _row(company="DataAnnotation",
                                       description_raw="A real posting.")
                     for i in range(3)})
        sampled = balanced_sample(build_golden_set(jobs, DEFAULT_CRITERIA))
        kept = [i for i in sampled if i.evidence == "excluded_company"]
        assert len(kept) == 3

    def test_a_set_with_no_replayable_items_at_all_samples_to_empty(self):
        from jobflow_quality.golden_set import balanced_sample

        jobs = {f"x{i:03d}": self._textless() for i in range(9)}
        assert balanced_sample(build_golden_set(jobs, DEFAULT_CRITERIA)) == ()

    def test_dropping_postings_never_invents_or_reorders_items(self):
        from jobflow_quality.golden_set import balanced_sample

        jobs = {f"h{i:03d}": _row(history=[_human_event()]) for i in range(5)}
        jobs.update({f"e{i:03d}": _row(salary_range={"min": 1.0, "max": 90000.0,
                                                     "currency": "USD",
                                                     "period": "annual"})
                     for i in range(5)})
        jobs.update({f"x{i:03d}": self._textless() for i in range(5)})
        items = build_golden_set(jobs, DEFAULT_CRITERIA)
        sampled = balanced_sample(items)
        assert set(sampled) <= set(items)
        assert list(sampled) == sorted(sampled, key=lambda i: i.job_id)
