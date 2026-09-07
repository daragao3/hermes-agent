"""The graph's LLM nodes classify their failures for batch drivers (2026-09-07).

``match_score_node`` and ``tailor_node`` catch their own LLM exceptions and
return an ``error`` in state instead of raising -- which is why one job that
blocked 6.7 h through a provider outage came back as a "successful" state and
was written to the outbox. Now that obs/oauth_llm.py bounds each call, a
timed-out call reaches the node as ``CodexTimeoutError`` (a ``TimeoutError``),
and the node must tell the driver WHICH failure it was without the driver
parsing prose: ``error_kind`` is "timeout" for the bound and "llm" otherwise.

The LLM call is stubbed at ``graphs.jobflow.codex_structured_invoke``; nothing
here builds a client or touches the network.
"""

from __future__ import annotations

import pytest

from graphs import jobflow
from obs.oauth_llm import CodexTimeoutError

_JOB = {
    "id": "job-1",
    "title": "Treasury Director",
    "company": "Example Co",
    "location": "Remote",
    "description": "A job description long enough to be a description.",
}


def _state(**extra):
    base = {"job": dict(_JOB), "job_id": "job-1", "profile_summary": "profile text"}
    base.update(extra)
    return base


def _raise(exc):
    def _stub(*args, **kwargs):
        raise exc

    return _stub


# --- match_score ------------------------------------------------------------


def test_timed_out_call_yields_error_kind_timeout_and_no_score(monkeypatch):
    monkeypatch.setattr(
        jobflow, "codex_structured_invoke", _raise(CodexTimeoutError("Codex request exceeded 120s bound"))
    )

    out = jobflow.match_score_node(_state())

    assert out["error_kind"] == "timeout"
    assert out["error"].startswith("match_score LLM failed: CodexTimeoutError: ")
    assert "exceeded 120s bound" in out["error"]
    assert "score" not in out  # nothing that could be mistaken for a verdict


def test_builtin_timeout_error_is_classified_the_same_way(monkeypatch):
    """A stubbed client in a driver test may raise the builtin; same class."""
    monkeypatch.setattr(jobflow, "codex_structured_invoke", _raise(TimeoutError("slow")))

    out = jobflow.match_score_node(_state())

    assert out["error_kind"] == "timeout"


def test_other_llm_failures_are_kind_llm(monkeypatch):
    monkeypatch.setattr(
        jobflow, "codex_structured_invoke", _raise(RuntimeError("codex_structured_invoke failed after retries: x"))
    )

    out = jobflow.match_score_node(_state())

    assert out["error_kind"] == "llm"
    assert out["error"].startswith("match_score LLM failed: RuntimeError: ")


def test_successful_call_carries_no_error_fields(monkeypatch):
    score = jobflow.MatcherScore(
        score=7.5,
        recommendation="REVIEW",
        breakdown=jobflow.ScoreBreakdown(**{
            name: 7.5 for name in jobflow.ScoreBreakdown.model_fields
        }),
        penalties_applied=[],
        key_strengths=["a"],
        gaps=["b"],
        rationale="ok",
    )
    monkeypatch.setattr(jobflow, "codex_structured_invoke", lambda *a, **k: score)
    # The node upserts pipeline.json on success; keep that off the real disk.
    import pipeline_state

    monkeypatch.setattr(
        pipeline_state.PipelineManager, "upsert_metadata", lambda self, **kw: None, raising=True
    )

    out = jobflow.match_score_node(_state())

    assert out["score"] == 7.5
    assert "error" not in out and "error_kind" not in out


# --- the error routes to the operator either way ----------------------------


@pytest.mark.parametrize("kind", ["timeout", "llm"])
def test_route_decision_sends_any_error_to_review(kind):
    out = jobflow.route_decision_node(
        _state(score=None, error=f"match_score LLM failed: {kind}", error_kind=kind)
    )
    assert out["decision"] == "review"


# --- tailor -----------------------------------------------------------------


def test_tailor_node_classifies_a_timeout_too(monkeypatch):
    monkeypatch.setattr(jobflow, "codex_structured_invoke", _raise(CodexTimeoutError("bound")))

    out = jobflow.tailor_node(
        _state(score=9.0, recommendation="PROCEED", key_strengths=["a"], gaps=[], rationale="r")
    )

    assert out["error_kind"] == "timeout"
    assert out["error"].startswith("tailor_node LLM failed: CodexTimeoutError: ")
