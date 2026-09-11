"""LLM nodes must survive a job whose title/company are PRESENT but None.

Regression for 2026-09-10: a user-submitted job (HiringCafe URL, enrichment_status=failed)
reached match_score_node with title=None and company=None. The span attribute line used a
dict default (``job.get("title", "")``) that never applies to a present-but-None key, so
``None[:120]`` raised TypeError BEFORE the node's own LLM try/except, the graph invoke
failed, and bin/matcher_shadow_run.py re-raised it every hour (8 consecutive failures).

Same stubbing as test_llm_error_kind.py: the LLM call is stubbed at
``graphs.jobflow.codex_structured_invoke``; nothing builds a client or touches the network.
"""

from __future__ import annotations

from graphs import jobflow
from obs.oauth_llm import CodexTimeoutError

_NULL_JOB = {
    "id": "173b915a984ca3f9",
    "job_id": "173b915a984ca3f9",
    "title": None,
    "company": None,
    "location": None,
    "url": "https://hiringcafe.com/job/treasury-technology",
    "source": "user-submitted",
    "metadata": {"enrichment_status": "failed", "fast_track": True},
}


def _state(**extra):
    base = {"job": dict(_NULL_JOB), "job_id": "173b915a984ca3f9", "profile_summary": "profile text"}
    base.update(extra)
    return base


def _score():
    return jobflow.MatcherScore(
        score=3.0,
        recommendation="ARCHIVE",
        breakdown=jobflow.ScoreBreakdown(**{name: 3.0 for name in jobflow.ScoreBreakdown.model_fields}),
        penalties_applied=[],
        key_strengths=[],
        gaps=["no posting text"],
        rationale="nothing to score",
    )


def test_match_score_node_reaches_the_llm_with_null_title_and_company(monkeypatch):
    calls = []
    monkeypatch.setattr(jobflow, "codex_structured_invoke", lambda *a, **k: calls.append(1) or _score())
    import pipeline_state

    monkeypatch.setattr(pipeline_state.PipelineManager, "upsert_metadata", lambda self, **kw: None, raising=True)

    out = jobflow.match_score_node(_state())  # pre-fix: TypeError: 'NoneType' object is not subscriptable

    assert calls == [1]
    assert out["score"] == 3.0
    assert "error" not in out


def test_match_score_node_still_classifies_llm_failures_for_a_null_job(monkeypatch):
    def _raise(*a, **k):
        raise CodexTimeoutError("bound")

    monkeypatch.setattr(jobflow, "codex_structured_invoke", _raise)

    out = jobflow.match_score_node(_state())

    assert out.get("error_kind") == "timeout"


def test_tailor_node_survives_a_null_company(monkeypatch):
    def _raise(*a, **k):
        raise CodexTimeoutError("bound")

    monkeypatch.setattr(jobflow, "codex_structured_invoke", _raise)

    out = jobflow.tailor_node(  # pre-fix: TypeError at the job.company span attribute
        _state(score=9.0, recommendation="PROCEED", key_strengths=["a"], gaps=[], rationale="r")
    )

    assert out.get("error_kind") == "timeout"
