"""Critic judges its own threshold proposals on the golden-set replay (loops
critic-threshold-replay-golden-20260923).

The pair-based replay needed prod-vs-shadow pairs, which the Phase-B cutover ended, so it
skipped. Now a threshold proposal is judged by re-routing the SAME golden run's stored scores
(total + comp_alignment) under current vs proposed thresholds with the production routing
function, and applying the release gate: no worse on every difficulty, no new false exclude of a
Diego-approved job, not degenerate, strictly better on something. Unavailable golden -> HELD.
"""

from __future__ import annotations

import pytest

# graphs needs langgraph, which is only in requirements-local-graph.txt, not
# the CI extras; skip rather than error at collection (same as test_critic_paths).
pytest.importorskip("langgraph.graph")

from graphs import critic, critic_golden, jobflow

CURRENT = (8.75, 5.0, 2.0)


def _row(job_id, label, difficulty, score, comp, thresholds=CURRENT):
    src = "human_approval" if label == "advance" else "deterministic_exclusion"
    return {"job_id": job_id, "label": label, "difficulty": difficulty, "source": src,
            "score": score, "comp": comp, "error": None,
            "decision": jobflow.decide_route(score, comp, *thresholds)}


def _golden(rows=None, status="ok"):
    rows = rows if rows is not None else [
        # nuanced: Diego-approved, all currently advanced
        _row("n1", "advance", "nuanced", 9.0, 8.0),
        _row("n2", "advance", "nuanced", 8.2, 7.0),
        _row("n3", "advance", "nuanced", 8.0, 6.0),
        _row("n4", "advance", "nuanced", 7.9, 4.0),
        # obvious: sub-floor comp facts; two caught by the veto, two leak to review
        _row("o1", "exclude", "obvious", 7.2, 1.5),
        _row("o2", "exclude", "obvious", 6.0, 2.0),
        _row("o3", "exclude", "obvious", 6.6, 4.0),
        _row("o4", "exclude", "obvious", 6.4, 3.0),
    ]
    return {"status": status, "dataset": "hermes-jobs-v3", "thresholds_at_replay": list(CURRENT),
            "rows": rows, "error": None if status == "ok" else "ConnectError"}


def test_a_proposal_that_fixes_false_advances_without_touching_approvals_is_accepted():
    v = critic_golden.judge_threshold_proposal(_golden(), (8.75, 7.0, 2.0))
    assert v["status"] == "golden_accepted", v["notes"]
    assert v["candidate"]["accuracy_by_difficulty"] == {"nuanced": 1.0, "obvious": 1.0}
    assert v["baseline"]["accuracy_by_difficulty"]["obvious"] == 0.5
    assert v["new_false_excludes"] == []
    assert v["notes"].startswith("ACCEPTED") and "obvious 50.0%->100.0%" in v["notes"]


def test_better_on_one_floor_but_losing_an_approval_is_rejected():
    """Raising review to 8.1 fixes the obvious half AND archives two Diego approvals."""
    v = critic_golden.judge_threshold_proposal(_golden(), (8.75, 8.1, 2.0))
    assert v["status"] == "golden_rejected"
    assert v["new_false_excludes"] == ["n3", "n4"]
    assert any(r.startswith("new false exclude") for r in v["rejections"])
    assert any(r.startswith("worse: nuanced") for r in v["rejections"])
    assert v["notes"].startswith("REJECTED")


def test_no_change_is_rejected_as_no_improvement():
    v = critic_golden.judge_threshold_proposal(_golden(), CURRENT)
    assert v["status"] == "golden_rejected"
    assert v["rejections"] == ["no improvement: identical on every floor, false excludes and false advances"]


def test_a_same_answer_router_is_rejected_as_degenerate():
    """Lowering review to 0 and disabling the veto advances every item."""
    v = critic_golden.judge_threshold_proposal(_golden(), (8.75, 0.0, -1.0))
    assert v["status"] == "golden_rejected"
    assert any(r.startswith("degenerate") for r in v["rejections"])


def test_unavailable_golden_replay_holds_the_proposal():
    for golden in (_golden(status="unavailable"), _golden(status="degraded"), None):
        v = critic_golden.judge_threshold_proposal(golden, (8.75, 7.0, 2.0))
        assert v["status"] == "held_golden_unavailable"
        assert v["notes"].startswith("HELD") and "must not be applied" in v["notes"]


def test_stored_scores_that_do_not_reproduce_the_decisions_hold_the_verdict():
    rows = _golden()["rows"]
    rows[0] = dict(rows[0], decision="archive")  # n1 at 9.0 cannot be archive under CURRENT
    v = critic_golden.judge_threshold_proposal(_golden(rows), (8.75, 7.0, 2.0))
    assert v["status"] == "held_recompute_mismatch" and "n1" in v["notes"]


def test_parse_proposed_thresholds():
    p = critic_golden.parse_proposed_thresholds
    assert p("set HERMES_JOBFLOW_REVIEW_THRESHOLD=7.0, was 5.0", CURRENT) == (8.75, 7.0, 2.0)
    assert p("HERMES_JOBFLOW_PROCEED_THRESHOLD=8.5 and HERMES_JOBFLOW_COMP_FLOOR = 3", CURRENT) == (8.5, 5.0, 3.0)
    assert p("make the matcher stricter", CURRENT) is None


def test_production_replay_stores_the_inputs_to_routing():
    items = [{"job_id": "a", "job": {"id": "a"}, "golden": critic_golden.GoldenItem(
        job_id="a", label=critic_golden.Label.ADVANCE, source=critic_golden.LabelSource.HUMAN_APPROVAL,
        difficulty=critic_golden.Difficulty.NUANCED, evidence="", description_sha256="")}]
    out = critic_golden.evaluate_production(
        "hermes-jobs-v3", loader=lambda n: items,
        scorer=lambda job: {"decision": "review", "score": 7.1, "breakdown": {"comp_alignment": 6.0}})
    assert out["rows"][0]["score"] == 7.1 and out["rows"][0]["comp"] == 6.0
    assert out["rows"][0]["label"] == "advance" and out["rows"][0]["difficulty"] == "nuanced"
    assert out["thresholds_at_replay"] == list(jobflow.routing_thresholds())


def test_route_decision_node_is_decide_route():
    """One routing function: the node's decision equals decide_route's for the same inputs."""
    for score, comp in ((9.0, 8.0), (7.0, 5.0), (7.0, 1.5), (3.0, 9.0)):
        node = jobflow.route_decision_node({"score": score, "breakdown": {"comp_alignment": comp}})
        assert node["decision"] == jobflow.decide_route(score, comp, *jobflow.routing_thresholds())
    assert jobflow.route_decision_node({"score": 1.0, "error": "x"})["decision"] == "review"


# ---- Critic graph wiring ------------------------------------------------------------------------

def _proposal(kind, change, pid="p1"):
    return {"proposal_id": pid, "kind": kind, "specific_change": change, "cluster_pattern_name": "c",
            "summary": "", "rationale": "", "expected_effect": "", "risk": "low"}


def _replay(state):
    return {p["proposal_id"]: p["replay"] for p in critic.reflexion_replay_node(state)["proposals_classified"]}


def test_reflexion_replay_judges_on_golden_without_any_pairs(monkeypatch):
    monkeypatch.setattr(jobflow, "routing_thresholds", lambda: CURRENT)
    out = _replay({"golden": _golden(), "paired_jobs": [], "proposals_classified": [
        _proposal("matcher.threshold_adjust", "set HERMES_JOBFLOW_REVIEW_THRESHOLD=7.0, was 5.0", "good"),
        _proposal("matcher.threshold_adjust", "set HERMES_JOBFLOW_REVIEW_THRESHOLD=8.1, was 5.0", "bad"),
        _proposal("matcher.dimension_weight", "comp_alignment weight 0.10 -> 0.20", "w"),
        _proposal("matcher.threshold_adjust", "be stricter", "vague"),
    ]})
    assert out["good"]["status"] == "golden_accepted" and out["good"]["supported"] is True
    assert out["bad"]["status"] == "golden_rejected" and "n3" in out["bad"]["notes"]
    assert out["w"]["status"] == "held_not_recomputable"
    assert out["vague"]["status"] == "held_unparseable"


def test_reflexion_replay_holds_everything_when_golden_is_unavailable(monkeypatch):
    monkeypatch.setattr(jobflow, "routing_thresholds", lambda: CURRENT)
    out = _replay({"golden": _golden(status="unavailable"), "paired_jobs": [], "proposals_classified": [
        _proposal("matcher.threshold_adjust", "set HERMES_JOBFLOW_REVIEW_THRESHOLD=7.0, was 5.0", "t"),
        _proposal("matcher.dimension_weight", "x", "w")]})
    assert out["t"]["status"] == "held_golden_unavailable" and out["t"]["supported"] is False
    assert out["w"]["status"] == "held_golden_unavailable"
