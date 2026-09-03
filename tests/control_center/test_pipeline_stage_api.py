"""Tests for POST /api/v1/pipeline/jobs/{job_id}/stage.

2026-07-12: the endpoint routes through the JobOps intent lane (so the
tracker-intent-applier gives stage changes the full trio: legacy projection,
Postgres, canonical-store mirror) and falls back to the old direct
PipelineManager write only when the intent lane fails.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import intent_applier
import pipeline_state
from control_center import storage
from control_center.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_manager(monkeypatch):
    mgr = MagicMock()
    mgr.get_job.return_value = {"job_id": "job-1", "stage": "review"}
    monkeypatch.setattr(pipeline_state, "PipelineManager", MagicMock(return_value=mgr))
    return mgr


def test_stage_routes_through_intent_lane(client, fake_manager, monkeypatch):
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post(
        "/api/v1/pipeline/jobs/job-1/stage",
        json={"stage": "approved", "actor": "diego", "source": "control_center"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued"] is True
    kw = jobops.post_intent.call_args.kwargs
    assert kw["job_id"] == "job-1"
    assert kw["stage"] == "approved"
    assert kw["actor_id"] == "diego"
    assert kw["source"] == "control_center"
    # The direct write must NOT run when the intent lane accepted the change —
    # the tracker-intent-applier owns the projection write from here.
    fake_manager.update_stage.assert_not_called()


def test_stage_falls_back_to_direct_write_when_intent_lane_fails(
    client, fake_manager, monkeypatch
):
    jobops = MagicMock()
    jobops.post_intent.side_effect = RuntimeError("jobops down")
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post("/api/v1/pipeline/jobs/job-1/stage", json={"stage": "approved"})

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued"] is False
    fake_manager.update_stage.assert_called_once()


def test_stage_unknown_job_404_when_intent_lane_also_rejects(
    client, fake_manager, monkeypatch
):
    fake_manager.get_job.return_value = None
    jobops = MagicMock()
    jobops.post_intent.side_effect = RuntimeError("400 unknown job")
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post("/api/v1/pipeline/jobs/nope/stage", json={"stage": "approved"})
    assert r.status_code == 404
    fake_manager.update_stage.assert_not_called()


def test_stage_unknown_locally_but_intent_lane_accepts(client, fake_manager, monkeypatch):
    """Jobs discovered after the legacy projection's last refresh exist only
    in the control plane — JobOps arbitrates, not the stale local file."""
    fake_manager.get_job.return_value = None
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post("/api/v1/pipeline/jobs/fresh-job/stage", json={"stage": "approved"})
    assert r.status_code == 200
    assert r.json()["queued"] is True
    jobops.post_intent.assert_called_once()


def test_stage_missing_stage_400(client, fake_manager):
    r = client.post("/api/v1/pipeline/jobs/job-1/stage", json={})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Actor attribution (2026-09-03)
#
# This endpoint is an unauthenticated loopback POST -- auth is opt-in via
# HERMES_CC_TOKEN and even then the token is a bearer secret naming nobody. The
# body's `actor` is OPTIONAL, and the default used to be the literal "diego",
# so a request that established no actor produced a durable pipeline.json
# history entry claiming Diego took an action he may not have taken. That is
# wrong attribution, not missing attribution.
#
# It was not inert: jobflow_quality.golden_set._HUMAN_ACTORS = ("diego",) reads
# a `diego` actor in pipeline history as proof that a real person decided, and
# labels the job HUMAN_APPROVAL in the golden evaluation set.
# ---------------------------------------------------------------------------


def test_stage_without_an_actor_does_not_claim_diego(client, fake_manager, monkeypatch):
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post("/api/v1/pipeline/jobs/job-1/stage", json={"stage": "approved"})

    assert r.status_code == 200
    actor_id = jobops.post_intent.call_args.kwargs["actor_id"]
    assert actor_id != "diego"
    assert actor_id == storage.unattributed_actor("legacy_dashboard")


def test_stage_unattributed_actor_names_the_requested_surface(
    client, fake_manager, monkeypatch
):
    """The surface comes from the request's own `source`, so the actor string is
    self-describing wherever it is rendered alone."""
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post(
        "/api/v1/pipeline/jobs/job-1/stage",
        json={"stage": "approved", "source": "agent_script"},
    )

    assert r.status_code == 200
    assert jobops.post_intent.call_args.kwargs["actor_id"] == (
        storage.unattributed_actor("agent_script")
    )


def test_stage_blank_actor_counts_as_absent(client, fake_manager, monkeypatch):
    """Pre-fix, a whitespace actor slipped past the `or` and was written through
    as the EMPTY STRING -- a falsy actor that reads as attributed-to-nothing
    rather than as missing."""
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post(
        "/api/v1/pipeline/jobs/job-1/stage",
        json={"stage": "approved", "actor": "   "},
    )

    assert r.status_code == 200
    assert jobops.post_intent.call_args.kwargs["actor_id"] == (
        storage.unattributed_actor("legacy_dashboard")
    )


def test_stage_fallback_direct_write_carries_the_same_actor(
    client, fake_manager, monkeypatch
):
    """WIRING test for the second consumer. The endpoint has two call sites --
    the intent lane and the direct PipelineManager fallback -- and the fallback
    is the one that writes pipeline.json itself. A fix applied only to the lane
    would leave the fallback claiming Diego."""
    jobops = MagicMock()
    jobops.post_intent.side_effect = RuntimeError("jobops down")
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post("/api/v1/pipeline/jobs/job-1/stage", json={"stage": "approved"})

    assert r.status_code == 200
    assert r.json()["queued"] is False
    actor = fake_manager.update_stage.call_args.kwargs["actor"]
    assert actor != "diego"
    assert actor == storage.unattributed_actor("legacy_dashboard")


def test_stage_explicit_actor_is_still_threaded_verbatim(
    client, fake_manager, monkeypatch
):
    """REGRESSION GUARD, not a fix assertion -- passes on both sides by design.
    The change must not touch a caller that DOES establish an actor."""
    jobops = MagicMock()
    monkeypatch.setattr(intent_applier, "JobOpsClient", MagicMock(return_value=jobops))

    r = client.post(
        "/api/v1/pipeline/jobs/job-1/stage",
        json={"stage": "approved", "actor": "operator_api"},
    )

    assert r.status_code == 200
    assert jobops.post_intent.call_args.kwargs["actor_id"] == "operator_api"
