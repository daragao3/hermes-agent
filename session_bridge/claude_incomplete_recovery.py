"""Operator-only, one-call recovery of an exact prompt-only Claude registration."""

import hashlib
import time

from .claude_visibility import ClaudeVisibilityCandidate, ClaudeVisibilityIdentity
from .models import Provider


class IncompleteRecoveryFailed(ValueError):
    """Carry only the registrar's bounded, sanitized outcome to the CLI."""

    def __init__(self, outcome):
        super().__init__(
            "incomplete recovery not completed: " + str(outcome.error_code)
        )
        self.error_code = outcome.error_code
        self.error_detail = outcome.detail


def recover_incomplete_registration(
    *, store, registrar, job_id, reserved_uuid, policy, apply=False, now=time.time
):
    # The existing terminal inspection enforces sole-open-job and exact identity.
    store.inspect_failed_claude_visibility_reconciliation(
        expected_job_id=job_id,
        expected_reserved_claude_uuid=reserved_uuid,
        expected_error_code="bridge_conflict",
    )
    with store.db._lock:
        conn = store.db._conn
        row = conn.execute(
            "SELECT * FROM session_claude_visibility_jobs WHERE id = ? AND reserved_claude_uuid = ?",
            (job_id, reserved_uuid),
        ).fetchone()
        recovery = conn.execute(
            "SELECT * FROM session_claude_auth_recoveries WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        job = dict(row)
        recovery = dict(recovery) if recovery else None
    # One condition per raise. These were a single compound test until
    # 2026-09-13; cli.py collapses every ValueError here into one gate name, so
    # five unrelated refusals reached the operator as one sentence and the
    # cheapest question -- "which of these is it?" -- could not be answered.
    if job["state"] != "claude_failed":
        raise ValueError("incomplete recovery requires a failed job state")
    if job["operator_cleared_at"] is not None:
        raise ValueError("incomplete recovery job already dismissed")
    if job["lease_digest"] is not None:
        raise ValueError("incomplete recovery job is leased")
    if job["error_code"] != "bridge_conflict":
        raise ValueError("incomplete recovery requires bridge_conflict")
    if job["error_detail"] != "exact transcript conflict":
        raise ValueError("incomplete recovery requires an exact transcript conflict")
    candidate = ClaudeVisibilityCandidate(
        source_session_id=job["source_session_id"],
        source_provider=Provider(job["source_provider"]),
        native_name=job["native_name"],
        source_cwd=job["source_cwd"],
        git_root=job["git_root"],
        git_branch=job["git_branch"],
        git_head=job["git_head"],
        worktree_id=job["worktree_id"],
        eligible_at=job["eligible_at"],
    )
    identity = ClaudeVisibilityIdentity(
        job_id=job_id,
        bridge_id=job["bridge_id"],
        idempotency_key=job["idempotency_key"],
        claude_uuid=reserved_uuid,
        signed_marker=job["signed_marker"],
    )
    evidence = registrar.inspect_incomplete_registration(candidate, identity)
    prompt = evidence["prompt"]
    prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()
    operation_id = "incomplete-registration:" + job_id
    if recovery and any(
        recovery[key] != expected
        for key, expected in (
            ("operation_id", operation_id),
            ("evidence_digest", evidence["evidence_digest"]),
            ("prompt_digest", prompt_digest),
            ("reserved_claude_uuid", reserved_uuid),
        )
    ):
        raise ValueError("incomplete recovery authority conflict")
    complete = evidence["kind"] == "incomplete_recovered"
    # A SECOND paid call, authorized by Diego 2026-09-13, and deliberately
    # keyed to NATIVE TRANSCRIPT EVIDENCE rather than to an operator flag: the
    # transcript must show that every recovery turn so far ended in a provider
    # limit banner. An operator cannot assert their way to another attempt, and
    # the ordinary "one apply grants one call" rule is untouched for every other
    # outcome -- an ambiguous or crashed call still demands exact reconciliation,
    # because there the transcript does NOT prove the turn was refused.
    #
    # The spend stays bounded by the store, not by this flag:
    # claim_claude_auth_recovery still enforces max_attempts, the daily
    # registration limit and the reserved cost ceiling, and it is the thing that
    # books the new attempt.
    provider_limited = evidence["kind"] == "incomplete_provider_limited"
    if complete and (not recovery or recovery["call_started_at"] is None):
        raise ValueError("incomplete recovery call authority absent")
    if (
        not complete
        and not provider_limited
        and recovery
        and recovery["call_started_at"] is not None
    ):
        raise ValueError(
            "incomplete recovery already started; exact reconciliation required"
        )
    public = {
        "job_id": job_id,
        "reserved_claude_uuid": reserved_uuid,
        "status": "reconcilable" if complete else "resumable",
    }
    if provider_limited:
        # Say so in the preview: --apply here SPENDS another attempt.
        public["provider_limit_retry"] = True
    if not apply:
        return public
    if complete:
        store.reconcile_claude_auth_recovery(
            job_id=job_id,
            reserved_claude_uuid=reserved_uuid,
            operation_id=operation_id,
            evidence_digest=evidence["evidence_digest"],
            prompt_digest=prompt_digest,
            transcript_digest=evidence["transcript_digest"],
            visible_at=now(),
        )
        return {**public, "status": "visible"}
    claimed = store.claim_claude_auth_recovery(
        job_id=job_id,
        reserved_claude_uuid=reserved_uuid,
        operation_id=operation_id,
        evidence_digest=evidence["evidence_digest"],
        prompt_digest=prompt_digest,
        now=now(),
        lease_seconds=policy.lease_seconds,
        daily_limit=policy.daily_registration_limit,
        cost_limit=policy.emergency_daily_cost_usd,
        reserved_cost=policy.reserved_cost_per_attempt_usd,
        max_attempts=policy.max_attempts,
        allow_repeated_call=provider_limited,
    )
    if claimed.get("status") != "claimed":
        raise ValueError(
            "incomplete recovery unavailable: " + str(claimed.get("status"))
        )
    # Re-read after acquiring the paid lease. Never resume changed native evidence.
    fresh = registrar.inspect_incomplete_registration(candidate, identity)
    if fresh != evidence:
        raise ValueError("incomplete registration changed before resume")
    outcome = registrar.resume_auth_recovery(claimed, prompt)
    if outcome.status != "recovered":
        raise IncompleteRecoveryFailed(outcome)
    final = registrar.inspect_incomplete_registration(candidate, identity)
    if (
        final["kind"] != "incomplete_recovered"
        or final["evidence_digest"] != evidence["evidence_digest"]
    ):
        raise ValueError("incomplete recovery not completed in native transcript")
    store.commit_claude_auth_recovery(
        job_id=job_id,
        lease_digest=claimed["lease_digest"],
        reserved_claude_uuid=reserved_uuid,
        transcript_digest=final["transcript_digest"],
        visible_at=now(),
    )
    return {**public, "status": "visible"}
