"""Dashboard run-now preserves an operator's containment pause."""

import pytest
from fastapi import HTTPException
from hermes_cli.web_routers import cron


@pytest.mark.parametrize("hold", [{"enabled": False}, {"state": "paused"}])
def test_trigger_refuses_pause_before_provider_fire(monkeypatch, hold):
    job = {"id": "held", "paused_reason": "containment", "paused_at": "2026-09-10", **hold}
    monkeypatch.setattr(cron, "_call_cron_for_profile", lambda *a, **k: job)
    monkeypatch.setattr(cron, "_fire_cron_job_for_profile", lambda *a, **k: pytest.fail("held job fired"))
    with pytest.raises(HTTPException) as error:
        cron._trigger_cron_job_sync("held", "work")
    assert error.value.status_code == 409
    assert error.value.detail["paused_reason"] == "containment"
    assert error.value.detail["paused_at"] == "2026-09-10"


@pytest.mark.parametrize("operation", ["pause", "resume"])
def test_pause_resume_retain_http_audit_caller(monkeypatch, operation):
    calls = []
    def mutate(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "job"}
    monkeypatch.setattr(cron, "_mutate_cron_for_profile", mutate)
    getattr(cron, f"_{operation}_cron_job_sync")("job", "work")
    assert calls == [(("work", f"{operation}_job", "job"), {"caller": "http_api:web_server"})]


def test_active_trigger_keeps_provider_claim_and_refresh(monkeypatch):
    job = {"id": "job", "enabled": True, "state": "scheduled", "last_run_at": None}
    refreshed = {**job, "last_run_at": "2026-09-10"}
    monkeypatch.setattr(cron, "_call_cron_for_profile", lambda p, method, *a, **k: job if method == "resolve_job_ref" else refreshed)
    calls = []
    monkeypatch.setattr(cron, "_fire_cron_job_for_profile", lambda *a, **k: calls.append((a, k)) or True)
    assert cron._trigger_cron_job_sync("job", "work") == refreshed
    assert calls == [(("work", "job"), {"force": False})]


@pytest.mark.parametrize("claimed", [False, True])
def test_trigger_audits_only_own_claim_with_reason(monkeypatch, claimed):
    job = {"id": "job", "name": "Nightly", "enabled": True, "next_run_at": "before"}
    refreshed = {**job, "next_run_at": "after"}
    audits = []

    def call(profile, method, *args, **kwargs):
        if method == "emit_cron_triggered_safe":
            audits.append((profile, kwargs))
            return
        return job if method == "resolve_job_ref" else refreshed

    monkeypatch.setattr(cron, "_call_cron_for_profile", call)
    monkeypatch.setattr(cron, "_fire_cron_job_for_profile", lambda *a, **k: claimed)
    if claimed:
        assert cron._trigger_cron_job_sync("job", "work", "operator retry") == refreshed
        assert audits == [("work", {
            "job_id": "job", "job_name": "Nightly", "caller": "http_api:web_server",
            "reason": "operator retry", "previous_next_run_at": "before", "new_next_run_at": "after",
        })]
    else:
        with pytest.raises(HTTPException) as error:
            cron._trigger_cron_job_sync("job", "work", "operator retry")
        assert error.value.status_code == 409
        assert audits == []


def test_cron_aggregate_reports_partial_profile_failure(monkeypatch):
    monkeypatch.setattr(cron, "_cron_profile_dicts", lambda: [{"name": "healthy"}, {"name": "broken"}])
    def read(profile, *args):
        if profile == "broken":
            raise RuntimeError("store unreadable")
        return [{"id": "job", "profile": profile}]
    monkeypatch.setattr(cron, "_call_cron_for_profile", read)
    assert cron._list_cron_jobs_sync() == {
        "jobs": [{"id": "job", "profile": "healthy"}],
        "errors": [{"profile": "broken", "error": "store unreadable"}],
    }


def test_cron_concrete_list_has_same_response_shape(monkeypatch):
    monkeypatch.setattr(cron, "_call_cron_for_profile", lambda *a: [])
    assert cron._list_cron_jobs_sync("work") == {"jobs": [], "errors": []}
