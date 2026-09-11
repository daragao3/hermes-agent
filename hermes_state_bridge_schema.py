"""Local Session Bridge ledger schema and preservation checks.

Bridge migrations have their own ledger and run independently of core/FTS versions.
"""
import sqlite3
import hashlib
import json
import time
import random
from decimal import Decimal, InvalidOperation

def desktop_registry_value_hash(value_json: str) -> str:
    """Content address of one desktop-registry baseline group value.

    SHA-256 of the canonical JSON text's UTF-8 bytes, as lowercase hex. The
    text is canonical by construction (``session_bridge.desktop_registry``
    emits it with sorted keys and fixed separators), so equal group values
    always hash equal and the side table stores each distinct blob once.
    """
    if not isinstance(value_json, str):
        raise TypeError("desktop registry value must be JSON text")
    return hashlib.sha256(value_json.encode("utf-8")).hexdigest()

BRIDGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_sidebar_exclusions (
    source_session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    provider TEXT NOT NULL CHECK (provider IN ('claude', 'hermes')),
    reason_code TEXT NOT NULL CHECK (reason_code IN ('source_cwd_missing')),
    source_identity_digest TEXT NOT NULL,
    excluded_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_sidebar_exclusions_reason
    ON session_sidebar_exclusions(reason_code, excluded_at DESC);

CREATE TABLE IF NOT EXISTS external_sessions (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('claude', 'codex')),
    native_id TEXT NOT NULL,
    native_path TEXT,
    native_status TEXT NOT NULL DEFAULT 'unknown',
    last_native_cursor TEXT,
    last_native_hash TEXT,
    first_indexed_at REAL NOT NULL,
    last_indexed_at REAL NOT NULL,
    parser_version INTEGER NOT NULL,
    origin_kind TEXT NOT NULL CHECK (
        origin_kind IN ('native', 'bridge_placeholder', 'bridge_continuation')
    ),
    origin_bridge_id TEXT,
    sync_error TEXT,
    UNIQUE(provider, native_id)
);

CREATE TABLE IF NOT EXISTS external_message_map (
    session_id TEXT NOT NULL REFERENCES external_sessions(session_id) ON DELETE CASCADE,
    native_event_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    PRIMARY KEY(session_id, native_event_id, ordinal),
    UNIQUE(message_id)
);

CREATE TABLE IF NOT EXISTS session_links (
    id TEXT PRIMARY KEY,
    from_session_id TEXT NOT NULL REFERENCES sessions(id),
    to_session_id TEXT NOT NULL REFERENCES sessions(id),
    relation TEXT NOT NULL CHECK (relation IN ('mirrors', 'continues', 'forks')),
    bridge_id TEXT NOT NULL,
    source_cursor TEXT,
    source_hash TEXT,
    created_at REAL NOT NULL,
    hydrated_at REAL,
    diverged_at REAL,
    UNIQUE(bridge_id, from_session_id, to_session_id, relation)
);

CREATE TABLE IF NOT EXISTS session_mirror_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL REFERENCES sessions(id),
    target_provider TEXT NOT NULL CHECK (target_provider IN ('claude', 'codex')),
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'retry', 'succeeded', 'manual_failure')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    target_native_id TEXT,
    error_code TEXT,
    error_detail TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS session_sidebar_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL REFERENCES sessions(id),
    bridge_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN (
            'sidebar_pending', 'sidebar_leased', 'sidebar_visible',
            'sidebar_retry', 'sidebar_failed'
        )
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at REAL NOT NULL,
    lease_digest TEXT,
    lease_expires_at REAL,
    completion_digest TEXT,
    codex_thread_id TEXT UNIQUE,
    error_code TEXT,
    eligible_at REAL NOT NULL,
    indexed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    visible_at REAL,
    placement_generation INTEGER,
    placement_verified_at REAL,
    reconciliation_proof_digest TEXT,
    CHECK (
        (state = 'sidebar_leased' AND lease_digest IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (state != 'sidebar_leased' AND lease_digest IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK (
        state != 'sidebar_visible'
        OR (
            codex_thread_id IS NOT NULL
            AND visible_at IS NOT NULL
            AND completion_digest IS NOT NULL
        )
    )
);

-- Parent delete guard. Its four children (terminal/precreate/unbound
-- resolutions, reconciliation_proofs) are already ON DELETE RESTRICT and
-- individually delete-guarded; the parent was not, which is how a bulk
-- DELETE run with foreign_keys=OFF orphaned 97 proofs on 2026-08-09.
-- Triggers fire regardless of the FK pragma and regardless of whether the
-- deleting script was ever committed. Legitimate repairs drop, delete and
-- recreate this trigger inside one transaction -- see
-- session-bridge/repair_fabricated_sidebar_jobs.py.
CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_jobs_no_delete
BEFORE DELETE ON session_sidebar_jobs
BEGIN
    SELECT RAISE(ABORT, 'session_sidebar_jobs rows are delete-guarded');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_reconciliation_proofs (
    proof_digest TEXT PRIMARY KEY CHECK (
        length(proof_digest) = 64
        AND proof_digest NOT GLOB '*[^0-9a-f]*'
    ),
    job_id TEXT NOT NULL
        REFERENCES session_sidebar_jobs(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    source_session_id TEXT NOT NULL,
    bridge_id TEXT NOT NULL,
    marker_digest TEXT NOT NULL CHECK (
        length(marker_digest) = 64
        AND marker_digest NOT GLOB '*[^0-9a-f]*'
    ),
    placement_generation INTEGER NOT NULL CHECK (placement_generation > 0),
    delivery_generation INTEGER NOT NULL CHECK (delivery_generation > 0),
    reconciliation_generation TEXT NOT NULL,
    completed_at REAL NOT NULL,
    expires_at REAL NOT NULL CHECK (expires_at >= completed_at),
    inventory_digest TEXT NOT NULL CHECK (
        length(inventory_digest) = 64
        AND inventory_digest NOT GLOB '*[^0-9a-f]*'
    ),
    state TEXT NOT NULL CHECK (
        state IN ('recovered', 'absence_proven', 'blocked')
    ),
    match_count INTEGER NOT NULL CHECK (match_count >= 0),
    recovered_thread_id TEXT,
    fixed_reason TEXT,
    created_at REAL NOT NULL,
    CHECK (
        (state = 'recovered'
            AND match_count = 1
            AND recovered_thread_id IS NOT NULL
            AND fixed_reason IS NULL)
        OR (state = 'absence_proven'
            AND match_count = 0
            AND recovered_thread_id IS NULL
            AND fixed_reason IS NULL)
        OR (state = 'blocked'
            AND recovered_thread_id IS NULL
            AND fixed_reason IS NOT NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS trg_sidebar_reconciliation_proofs_no_update
BEFORE UPDATE ON session_sidebar_reconciliation_proofs
BEGIN
    SELECT RAISE(ABORT, 'sidebar reconciliation proof is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_sidebar_reconciliation_proofs_no_delete
BEFORE DELETE ON session_sidebar_reconciliation_proofs
BEGIN
    SELECT RAISE(ABORT, 'sidebar reconciliation proof is immutable');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_hydration_jobs (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
    bridge_id TEXT NOT NULL UNIQUE,
    codex_thread_id TEXT NOT NULL UNIQUE,
    source_cursor TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    preview_version INTEGER NOT NULL CHECK (preview_version = 1),
    preview_digest TEXT NOT NULL UNIQUE CHECK (
        length(preview_digest) = 64
        AND preview_digest NOT GLOB '*[^0-9a-f]*'
    ),
    hydration_marker TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN (
            'hydration_pending', 'hydration_leased', 'hydration_retry',
            'hydration_visible', 'hydration_failed'
        )
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at REAL NOT NULL,
    lease_digest TEXT UNIQUE,
    lease_expires_at REAL,
    send_reserved_at REAL,
    sent_at REAL,
    verified_at REAL,
    completion_digest TEXT UNIQUE,
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    CHECK (
        (state = 'hydration_leased'
            AND lease_digest IS NOT NULL
            AND lease_expires_at IS NOT NULL)
        OR (state != 'hydration_leased'
            AND lease_digest IS NULL
            AND lease_expires_at IS NULL)
    ),
    CHECK (
        state != 'hydration_visible'
        OR (
            send_reserved_at IS NOT NULL
            AND sent_at IS NOT NULL
            AND verified_at IS NOT NULL
            AND completion_digest IS NOT NULL
        )
    ),
    CHECK (
        state = 'hydration_visible'
        OR completion_digest IS NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_session_sidebar_hydration_due
    ON session_sidebar_hydration_jobs(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_session_sidebar_hydration_lease
    ON session_sidebar_hydration_jobs(lease_digest)
    WHERE lease_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_sidebar_hydration_completion
    ON session_sidebar_hydration_jobs(completion_digest)
    WHERE completion_digest IS NOT NULL;

-- Parent delete guard. This table has NO children, so PRAGMA
-- foreign_keys=ON alone would not refuse a bulk delete of it -- the
-- trigger is the only control that covers this table.
CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_hydration_jobs_no_delete
BEFORE DELETE ON session_sidebar_hydration_jobs
BEGIN
    SELECT RAISE(ABORT, 'session_sidebar_hydration_jobs rows are delete-guarded');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_terminal_resolutions (
    job_id TEXT PRIMARY KEY
        REFERENCES session_sidebar_jobs(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL UNIQUE,
    bridge_id TEXT NOT NULL UNIQUE,
    codex_thread_id TEXT NOT NULL UNIQUE,
    failure_state TEXT NOT NULL CHECK (failure_state = 'sidebar_failed'),
    failure_code TEXT NOT NULL CHECK (failure_code = 'native_create_ambiguous'),
    failure_attempts INTEGER NOT NULL CHECK (failure_attempts >= 0),
    failure_next_attempt_at REAL NOT NULL,
    failure_updated_at REAL NOT NULL,
    resolution_code TEXT NOT NULL CHECK (
        resolution_code = 'native_thread_unrecoverable'
    ),
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind = 'codex_app_server_read_not_loaded_resume_no_rollout'
    ),
    evidence_version INTEGER NOT NULL CHECK (evidence_version = 1),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_at REAL NOT NULL,
    CHECK (resolved_at >= failure_updated_at)
);

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_replacement
BEFORE INSERT ON session_sidebar_terminal_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_terminal_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
        OR existing.codex_thread_id = NEW.codex_thread_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_update
BEFORE UPDATE ON session_sidebar_terminal_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_delete
BEFORE DELETE ON session_sidebar_terminal_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions are immutable');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_precreate_resolutions (
    job_id TEXT PRIMARY KEY
        REFERENCES session_sidebar_jobs(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL UNIQUE,
    bridge_id TEXT NOT NULL UNIQUE,
    failure_state TEXT NOT NULL CHECK (failure_state = 'sidebar_failed'),
    failure_code TEXT NOT NULL CHECK (failure_code = 'native_create_ambiguous'),
    failure_attempts INTEGER NOT NULL CHECK (failure_attempts = 0),
    failure_next_attempt_at REAL NOT NULL,
    failure_updated_at REAL NOT NULL,
    cutover_applied_at REAL NOT NULL,
    reservation_reserved_at REAL NOT NULL,
    resolution_code TEXT NOT NULL CHECK (
        resolution_code = 'precutover_create_unrecoverable'
    ),
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind = 'codex_inventory_marker_and_recovery_zero_no_rollout'
    ),
    evidence_version INTEGER NOT NULL CHECK (evidence_version = 1),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_at REAL NOT NULL,
    CHECK (reservation_reserved_at = cutover_applied_at),
    CHECK (resolved_at >= failure_updated_at)
);

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_precreate_resolutions_no_replacement
BEFORE INSERT ON session_sidebar_precreate_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_precreate_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_terminal_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar precreate resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_precreate_resolutions_no_update
BEFORE UPDATE ON session_sidebar_precreate_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar precreate resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_precreate_resolutions_no_delete
BEFORE DELETE ON session_sidebar_precreate_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar precreate resolutions are immutable');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_unbound_resolutions (
    job_id TEXT PRIMARY KEY
        REFERENCES session_sidebar_jobs(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL UNIQUE,
    bridge_id TEXT NOT NULL UNIQUE,
    failure_state TEXT NOT NULL CHECK (failure_state = 'sidebar_failed'),
    failure_code TEXT NOT NULL CHECK (failure_code = 'native_create_ambiguous'),
    failure_attempts INTEGER NOT NULL CHECK (failure_attempts > 0),
    failure_next_attempt_at REAL NOT NULL,
    failure_updated_at REAL NOT NULL,
    reservation_reserved_at REAL NOT NULL,
    resolution_code TEXT NOT NULL CHECK (
        resolution_code = 'native_create_unrecoverable'
    ),
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind = 'codex_inventory_marker_and_recovery_zero_no_rollout'
    ),
    evidence_version INTEGER NOT NULL CHECK (evidence_version = 1),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_at REAL NOT NULL,
    CHECK (resolved_at >= failure_updated_at)
);

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_unbound_resolutions_no_replacement
BEFORE INSERT ON session_sidebar_unbound_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_unbound_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_terminal_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_precreate_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar unbound resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_unbound_resolutions_no_update
BEFORE UPDATE ON session_sidebar_unbound_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar unbound resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_unbound_resolutions_no_delete
BEFORE DELETE ON session_sidebar_unbound_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar unbound resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_precreate_overlap
BEFORE INSERT ON session_sidebar_terminal_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_precreate_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions overlap precreate evidence');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_unbound_overlap
BEFORE INSERT ON session_sidebar_terminal_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_unbound_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions overlap unbound evidence');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_precreate_resolutions_no_unbound_overlap
BEFORE INSERT ON session_sidebar_precreate_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_unbound_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar precreate resolutions overlap unbound evidence');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_v2_attempt_zero_resolutions (
    job_id TEXT PRIMARY KEY
        REFERENCES session_sidebar_jobs(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_session_id TEXT NOT NULL UNIQUE,
    bridge_id TEXT NOT NULL UNIQUE,
    failure_state TEXT NOT NULL CHECK (failure_state = 'sidebar_failed'),
    failure_code TEXT NOT NULL CHECK (failure_code = 'native_create_ambiguous'),
    failure_attempts INTEGER NOT NULL CHECK (failure_attempts = 0),
    failure_next_attempt_at REAL NOT NULL,
    failure_updated_at REAL NOT NULL,
    reservation_reserved_at REAL NOT NULL,
    reservation_reconciliation_proof_digest TEXT NOT NULL UNIQUE
        REFERENCES session_sidebar_reconciliation_proofs(proof_digest)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    reservation_reconciliation_generation TEXT NOT NULL,
    proof_completed_at REAL NOT NULL,
    proof_expires_at REAL NOT NULL,
    proof_inventory_digest TEXT NOT NULL CHECK (
        length(proof_inventory_digest) = 64
        AND proof_inventory_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resolution_code TEXT NOT NULL CHECK (
        resolution_code = 'v2_attempt_zero_create_unrecoverable'
    ),
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind =
            'codex_inventory_marker_and_recovery_zero_with_bound_absence_proof'
    ),
    evidence_version INTEGER NOT NULL CHECK (evidence_version = 1),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_at REAL NOT NULL,
    CHECK (proof_expires_at > proof_completed_at),
    CHECK (resolved_at >= failure_updated_at),
    CHECK (resolved_at >= proof_completed_at),
    CHECK (resolved_at <= proof_expires_at)
);

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_v2_attempt_zero_resolutions_no_replacement
BEFORE INSERT ON session_sidebar_v2_attempt_zero_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_v2_attempt_zero_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_terminal_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_precreate_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
OR EXISTS (
    SELECT 1 FROM session_sidebar_unbound_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar v2 attempt-zero resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_v2_attempt_zero_resolutions_no_update
BEFORE UPDATE ON session_sidebar_v2_attempt_zero_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar v2 attempt-zero resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_v2_attempt_zero_resolutions_no_delete
BEFORE DELETE ON session_sidebar_v2_attempt_zero_resolutions
BEGIN
    SELECT RAISE(ABORT, 'sidebar v2 attempt-zero resolutions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_terminal_resolutions_no_v2_attempt_zero_overlap
BEFORE INSERT ON session_sidebar_terminal_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_v2_attempt_zero_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar terminal resolutions overlap v2 attempt-zero evidence');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_precreate_resolutions_no_v2_attempt_zero_overlap
BEFORE INSERT ON session_sidebar_precreate_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_v2_attempt_zero_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar precreate resolutions overlap v2 attempt-zero evidence');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_sidebar_unbound_resolutions_no_v2_attempt_zero_overlap
BEFORE INSERT ON session_sidebar_unbound_resolutions
WHEN EXISTS (
    SELECT 1 FROM session_sidebar_v2_attempt_zero_resolutions AS existing
     WHERE existing.job_id = NEW.job_id
        OR existing.idempotency_key = NEW.idempotency_key
        OR existing.source_session_id = NEW.source_session_id
        OR existing.bridge_id = NEW.bridge_id
)
BEGIN
    SELECT RAISE(ABORT, 'sidebar unbound resolutions overlap v2 attempt-zero evidence');
END;

CREATE TABLE IF NOT EXISTS session_sidebar_orphan_resolution_quarantine (
    resolution_table TEXT NOT NULL CHECK (
        resolution_table IN (
            'session_sidebar_terminal_resolutions',
            'session_sidebar_precreate_resolutions',
            'session_sidebar_unbound_resolutions',
            'session_sidebar_v2_attempt_zero_resolutions'
        )
    ),
    original_resolution_rowid INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason = 'missing_parent_job'),
    quarantined_at REAL NOT NULL,
    PRIMARY KEY (resolution_table, original_resolution_rowid)
);

-- Orphaned reconciliation proofs, quarantined by the v31 migration. The proofs
-- ledger is immutable by trigger and ON DELETE RESTRICT, so a parent job that
-- vanishes (the 2026-08-09 foreign_keys=OFF bulk DELETE) strands its children
-- permanently: they cannot be reached by any consumer -- every read is keyed on
-- session_sidebar_jobs.reconciliation_proof_digest -- and cannot be removed.
-- This FK-free table keeps the exact evidence while restoring integrity.
CREATE TABLE IF NOT EXISTS session_sidebar_reconciliation_proof_quarantine (
    proof_digest TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    bridge_id TEXT NOT NULL,
    marker_digest TEXT NOT NULL,
    placement_generation INTEGER NOT NULL,
    delivery_generation INTEGER NOT NULL,
    reconciliation_generation TEXT NOT NULL,
    completed_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    inventory_digest TEXT NOT NULL,
    state TEXT NOT NULL,
    match_count INTEGER NOT NULL,
    recovered_thread_id TEXT,
    fixed_reason TEXT,
    created_at REAL NOT NULL,
    reason TEXT NOT NULL CHECK (reason = 'missing_parent_job'),
    quarantined_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS session_claude_visibility_jobs (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL UNIQUE,
    bridge_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    reserved_claude_uuid TEXT NOT NULL UNIQUE,
    native_name TEXT NOT NULL,
    source_provider TEXT NOT NULL CHECK (source_provider IN ('codex', 'hermes')),
    source_cwd TEXT NOT NULL,
    git_root TEXT,
    git_branch TEXT,
    git_head TEXT,
    worktree_id TEXT,
    signed_marker TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'claude_pending', 'claude_leased', 'claude_retry',
            'claude_visible', 'claude_failed'
        )
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at REAL NOT NULL,
    lease_digest TEXT,
    lease_expires_at REAL,
    lease_kind TEXT CHECK (lease_kind IN ('launch', 'reconciliation')),
    error_code TEXT,
    error_detail TEXT,
    completion_digest TEXT,
    -- Operator acknowledgement of a TERMINAL job. Set only on a claude_failed
    -- row, only by dismiss_claude_visibility_job, and never cleared. A job
    -- carrying this stamp stops counting as open work everywhere the gates
    -- look (status counts/codes, the idle-enqueue check, the five
    -- sole-open-job guards) without lying about how it ended: state,
    -- attempts, error_code and the session_claude_registration_usage ledger
    -- all stay exactly as written. It exists because job rows are
    -- delete-guarded and the only other terminal state is 'claude_visible',
    -- which would assert a registration that never happened. Deliberately NOT
    -- a CHECK: _reconcile_columns_from_sql only ADDs the column to databases
    -- that predate it, so a CHECK here would bind new databases and not
    -- existing ones. The single writer enforces the rule instead, in its
    -- guarded UPDATE.
    operator_cleared_at REAL,
    eligible_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    visible_at REAL,
    CHECK (
        (state = 'claude_leased' AND lease_digest IS NOT NULL
         AND lease_expires_at IS NOT NULL AND lease_kind IS NOT NULL)
        OR (state != 'claude_leased' AND lease_digest IS NULL
            AND lease_expires_at IS NULL AND lease_kind IS NULL)
    ),
    CHECK (
        state != 'claude_visible'
        OR (completion_digest IS NOT NULL AND visible_at IS NOT NULL)
    )
);

-- Parent delete guard. Children: characterization_events RESTRICT,
-- visibility_reconciliations/auth_recoveries CASCADE, registration_usage
-- NO ACTION. No production DELETE site targets this table; jobs are
-- retired by state transition. The strict trigger-set validator at
-- _validate_claude_characterization_events_v28 checks the CHILD event
-- table, not this one, so this trigger does not trip it.
CREATE TRIGGER IF NOT EXISTS trg_session_claude_visibility_jobs_no_delete
BEFORE DELETE ON session_claude_visibility_jobs
BEGIN
    SELECT RAISE(ABORT, 'session_claude_visibility_jobs rows are delete-guarded');
END;

CREATE TABLE IF NOT EXISTS session_claude_registration_usage (
    local_day TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES session_claude_visibility_jobs(id),
    attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal >= 1),
    reserved_estimated_cost_usd TEXT NOT NULL,
    reserved_at REAL NOT NULL,
    UNIQUE(job_id, attempt_ordinal)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_claude_job_id_reserved_uuid
    ON session_claude_visibility_jobs(id, reserved_claude_uuid);

CREATE TABLE IF NOT EXISTS session_claude_visibility_reconciliations (
    job_id TEXT NOT NULL,
    reserved_claude_uuid TEXT NOT NULL,
    attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal >= 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('absent', 'exact_match', 'conflict')),
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    checked_at REAL NOT NULL,
    consumed_at REAL,
    PRIMARY KEY (job_id, attempt_ordinal, outcome, checked_at),
    FOREIGN KEY (job_id, reserved_claude_uuid)
        REFERENCES session_claude_visibility_jobs(id, reserved_claude_uuid)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_claude_visibility_characterization_events (
    job_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('registered', 'cleanup_completed', 'launch_aborted')
    ),
    operation_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    bridge_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    reserved_claude_uuid TEXT NOT NULL,
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, event_kind),
    UNIQUE (operation_id, event_kind),
    UNIQUE (source_session_id, event_kind),
    UNIQUE (bridge_id, event_kind),
    UNIQUE (idempotency_key, event_kind),
    UNIQUE (reserved_claude_uuid, event_kind),
    FOREIGN KEY (job_id, reserved_claude_uuid)
        REFERENCES session_claude_visibility_jobs(id, reserved_claude_uuid)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS session_claude_visibility_characterization_event_quarantine (
    original_event_rowid INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    bridge_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    reserved_claude_uuid TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    created_at REAL NOT NULL,
    reason TEXT NOT NULL CHECK (reason = 'missing_parent_job'),
    quarantined_at REAL NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_claude_characterization_event_identity
BEFORE INSERT ON session_claude_visibility_characterization_events
WHEN NOT EXISTS (
    SELECT 1 FROM session_claude_visibility_jobs AS job
    WHERE job.id = NEW.job_id
      AND job.source_session_id = NEW.source_session_id
      AND job.bridge_id = NEW.bridge_id
      AND job.idempotency_key = NEW.idempotency_key
      AND job.reserved_claude_uuid = NEW.reserved_claude_uuid
)
BEGIN
    SELECT RAISE(ABORT, 'Claude characterization identity mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_claude_characterization_cleanup_order
BEFORE INSERT ON session_claude_visibility_characterization_events
WHEN NEW.event_kind = 'cleanup_completed' AND (
    NOT EXISTS (
        SELECT 1 FROM session_claude_visibility_characterization_events
        WHERE job_id = NEW.job_id AND event_kind = 'registered'
    )
    OR NOT EXISTS (
        SELECT 1 FROM session_claude_visibility_jobs
        WHERE id = NEW.job_id AND state = 'claude_visible'
          AND completion_digest IS NOT NULL AND visible_at IS NOT NULL
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Claude characterization cleanup is not anchored');
END;

CREATE TRIGGER IF NOT EXISTS trg_claude_characterization_abort_order
BEFORE INSERT ON session_claude_visibility_characterization_events
WHEN NEW.event_kind = 'launch_aborted' AND (
    NOT EXISTS (
        SELECT 1 FROM session_claude_visibility_characterization_events
        WHERE job_id = NEW.job_id AND event_kind = 'registered'
    )
    OR NOT EXISTS (
        SELECT 1
        FROM session_claude_visibility_jobs AS job
        JOIN session_claude_visibility_reconciliations AS reconciliation
          ON reconciliation.job_id = job.id
         AND reconciliation.reserved_claude_uuid = job.reserved_claude_uuid
         AND reconciliation.attempt_ordinal = job.attempts
        WHERE job.id = NEW.job_id
          AND (
              job.state = 'claude_retry'
              OR (
                  job.state = 'claude_failed'
                  AND job.error_code = 'max_attempts_exhausted'
              )
          )
          AND reconciliation.outcome = 'absent'
          AND reconciliation.consumed_at IS NULL
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Claude characterization abort is not anchored');
END;

CREATE TRIGGER IF NOT EXISTS trg_claude_characterization_event_no_update
BEFORE UPDATE ON session_claude_visibility_characterization_events
BEGIN
    SELECT RAISE(ABORT, 'Claude characterization events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_claude_characterization_event_no_delete
BEFORE DELETE ON session_claude_visibility_characterization_events
BEGIN
    SELECT RAISE(ABORT, 'Claude characterization events are append-only');
END;

CREATE TABLE IF NOT EXISTS session_claude_auth_recoveries (
    job_id TEXT PRIMARY KEY,
    reserved_claude_uuid TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    prompt_digest TEXT NOT NULL CHECK (
        length(prompt_digest) = 64
        AND prompt_digest NOT GLOB '*[^0-9a-f]*'
    ),
    state TEXT NOT NULL CHECK (state IN ('leased', 'retry', 'completed')),
    attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal >= 1),
    next_attempt_at REAL NOT NULL,
    lease_digest TEXT UNIQUE,
    lease_expires_at REAL,
    call_started_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    CHECK (
        (state = 'leased' AND lease_digest IS NOT NULL
         AND lease_expires_at IS NOT NULL)
        OR (state != 'leased' AND lease_digest IS NULL
            AND lease_expires_at IS NULL)
    ),
    CHECK ((state = 'completed') = (completed_at IS NOT NULL)),
    FOREIGN KEY (job_id, reserved_claude_uuid)
        REFERENCES session_claude_visibility_jobs(id, reserved_claude_uuid)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_context_packs (
    id TEXT PRIMARY KEY,
    bridge_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL REFERENCES sessions(id),
    target_session_id TEXT REFERENCES sessions(id),
    source_cursor TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    budget_chars INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    immutable_at REAL,
    UNIQUE(bridge_id, source_cursor, source_hash, budget_chars)
);

CREATE TABLE IF NOT EXISTS session_bridge_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- ``list_sidebar_candidates`` orders Claude candidates by a ``last_active``
-- that only exists inside this table's JSON, so without an index SQLite had to
-- compute it for every candidate and sort the whole set before LIMIT could cut
-- it.  Indexing the extracted value DESC, key lets the Claude arm read its page
-- straight off the index in final order and stop at LIMIT: the key is
-- ``<constant prefix> || session_id``, so ordering by key is ordering by
-- session_id and the index satisfies ``last_active DESC, session_id`` outright.
--
-- The ``json_valid`` guard keeps the expression total.  Without it, indexing
-- json_extract would make ANY non-JSON write to session_bridge_state fail with
-- "malformed JSON", coupling ten unrelated writers to this index.  The query
-- must repeat this expression verbatim for SQLite to substitute the indexed
-- value.
CREATE INDEX IF NOT EXISTS idx_session_bridge_state_activity_ordered
    ON session_bridge_state(
        CASE
            WHEN json_valid(value_json) THEN CAST(json_extract(
                value_json, '$.last_active'
            ) AS REAL)
        END DESC,
        key
    );

-- Superseded by the ordered index above.  The first cut of this optimisation
-- indexed (key, <expr>) to make the per-candidate key lookup covering; the
-- query no longer looks activity rows up by key at all, so keeping it would
-- cost every session_bridge_state write a second expression index for nothing.
DROP INDEX IF EXISTS idx_session_bridge_state_activity;

CREATE TABLE IF NOT EXISTS session_bridge_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at REAL NOT NULL
);

-- Desktop registry reconciliation ledger (cross-account session record
-- convergence). Baselines are the last verified per-replica group values;
-- they advance only after an all-root disk verification, which is what makes
-- an interrupted cycle recoverable by replanning rather than byte replay.
CREATE TABLE IF NOT EXISTS desktop_registry_values (
    value_hash TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS desktop_registry_baselines (
    filename TEXT NOT NULL,
    root_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL,
    PRIMARY KEY (filename, root_id, group_name),
    FOREIGN KEY (value_hash) REFERENCES desktop_registry_values(value_hash)
);

CREATE TABLE IF NOT EXISTS desktop_registry_runs (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (
        state IN ('prepared', 'committed', 'conflicted', 'abandoned')
    ),
    grouping_version INTEGER NOT NULL CHECK (grouping_version >= 1),
    payload_json TEXT NOT NULL,
    resolution TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_desktop_registry_runs_state
    ON desktop_registry_runs(state, created_at);

CREATE TABLE IF NOT EXISTS desktop_registry_conflicts (
    filename TEXT NOT NULL,
    group_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    PRIMARY KEY (filename, group_name)
);

CREATE INDEX IF NOT EXISTS idx_external_sessions_last_indexed_at
    ON external_sessions(last_indexed_at);
CREATE INDEX IF NOT EXISTS idx_external_sessions_origin_bridge_id
    ON external_sessions(origin_bridge_id);
CREATE INDEX IF NOT EXISTS idx_session_links_bridge_id
    ON session_links(bridge_id);
CREATE INDEX IF NOT EXISTS idx_session_links_from_session_id
    ON session_links(from_session_id);
CREATE INDEX IF NOT EXISTS idx_session_links_to_session_id
    ON session_links(to_session_id);
CREATE INDEX IF NOT EXISTS idx_session_mirror_jobs_state_next_attempt_at
    ON session_mirror_jobs(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_session_sidebar_jobs_state_next_attempt_at
    ON session_sidebar_jobs(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_session_sidebar_jobs_source_session_id
    ON session_sidebar_jobs(source_session_id);
CREATE INDEX IF NOT EXISTS idx_session_sidebar_jobs_lease_digest
    ON session_sidebar_jobs(lease_digest) WHERE lease_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_sidebar_jobs_completion_digest
    ON session_sidebar_jobs(completion_digest)
    WHERE completion_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_sidebar_jobs_visible_at
    ON session_sidebar_jobs(state, visible_at DESC, id DESC)
    WHERE visible_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sidebar_reconciliation_job_created
    ON session_sidebar_reconciliation_proofs(job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_claude_visibility_jobs_state_next_attempt_at
    ON session_claude_visibility_jobs(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_session_claude_visibility_jobs_lease_digest
    ON session_claude_visibility_jobs(lease_digest)
    WHERE lease_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_session_claude_registration_usage_local_day
    ON session_claude_registration_usage(local_day, reserved_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_claude_reconciliation_unconsumed_absent
    ON session_claude_visibility_reconciliations(job_id, attempt_ordinal)
    WHERE outcome = 'absent' AND consumed_at IS NULL;
"""



_CLAUDE_CHARACTERIZATION_EVENTS_TABLE_V28_SQL = """
CREATE TABLE _session_claude_visibility_characterization_events_v28 (
    job_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('registered', 'cleanup_completed', 'launch_aborted')
    ),
    operation_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    bridge_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    reserved_claude_uuid TEXT NOT NULL,
    evidence_digest TEXT NOT NULL CHECK (
        length(evidence_digest) = 64
        AND evidence_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, event_kind),
    UNIQUE (operation_id, event_kind),
    UNIQUE (source_session_id, event_kind),
    UNIQUE (bridge_id, event_kind),
    UNIQUE (idempotency_key, event_kind),
    UNIQUE (reserved_claude_uuid, event_kind),
    FOREIGN KEY (job_id, reserved_claude_uuid)
        REFERENCES session_claude_visibility_jobs(id, reserved_claude_uuid)
        ON DELETE RESTRICT
)
"""


_CLAUDE_CHARACTERIZATION_EVENT_COLUMNS = (
    "job_id",
    "event_kind",
    "operation_id",
    "source_session_id",
    "bridge_id",
    "idempotency_key",
    "reserved_claude_uuid",
    "evidence_digest",
    "created_at",
)


_CLAUDE_CHARACTERIZATION_EVENT_QUARANTINE_COLUMNS = (
    "original_event_rowid",
    *_CLAUDE_CHARACTERIZATION_EVENT_COLUMNS,
    "reason",
    "quarantined_at",
)


_SIDEBAR_RESOLUTION_TABLES = (
    "session_sidebar_terminal_resolutions",
    "session_sidebar_precreate_resolutions",
    "session_sidebar_unbound_resolutions",
    "session_sidebar_v2_attempt_zero_resolutions",
)


_SIDEBAR_ORPHAN_RESOLUTION_QUARANTINE_COLUMNS = (
    "resolution_table",
    "original_resolution_rowid",
    "job_id",
    "source_session_id",
    "payload_json",
    "reason",
    "quarantined_at",
)


_SIDEBAR_RECONCILIATION_PROOF_COLUMNS = (
    "proof_digest",
    "job_id",
    "source_session_id",
    "bridge_id",
    "marker_digest",
    "placement_generation",
    "delivery_generation",
    "reconciliation_generation",
    "completed_at",
    "expires_at",
    "inventory_digest",
    "state",
    "match_count",
    "recovered_thread_id",
    "fixed_reason",
    "created_at",
)


_SIDEBAR_RECONCILIATION_PROOF_QUARANTINE_COLUMNS = (
    *_SIDEBAR_RECONCILIATION_PROOF_COLUMNS,
    "reason",
    "quarantined_at",
)


_CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_SQL = (
    """CREATE TRIGGER trg_claude_characterization_event_identity
       BEFORE INSERT ON session_claude_visibility_characterization_events
       WHEN NOT EXISTS (
           SELECT 1 FROM session_claude_visibility_jobs AS job
           WHERE job.id = NEW.job_id
             AND job.source_session_id = NEW.source_session_id
             AND job.bridge_id = NEW.bridge_id
             AND job.idempotency_key = NEW.idempotency_key
             AND job.reserved_claude_uuid = NEW.reserved_claude_uuid
       )
       BEGIN
           SELECT RAISE(ABORT, 'Claude characterization identity mismatch');
       END""",
    """CREATE TRIGGER trg_claude_characterization_cleanup_order
       BEFORE INSERT ON session_claude_visibility_characterization_events
       WHEN NEW.event_kind = 'cleanup_completed' AND (
           NOT EXISTS (
               SELECT 1 FROM session_claude_visibility_characterization_events
               WHERE job_id = NEW.job_id AND event_kind = 'registered'
           )
           OR NOT EXISTS (
               SELECT 1 FROM session_claude_visibility_jobs
               WHERE id = NEW.job_id AND state = 'claude_visible'
                 AND completion_digest IS NOT NULL AND visible_at IS NOT NULL
           )
       )
       BEGIN
           SELECT RAISE(
               ABORT,
               'Claude characterization cleanup is not anchored'
           );
       END""",
    """CREATE TRIGGER trg_claude_characterization_abort_order
       BEFORE INSERT ON session_claude_visibility_characterization_events
       WHEN NEW.event_kind = 'launch_aborted' AND (
           NOT EXISTS (
               SELECT 1 FROM session_claude_visibility_characterization_events
               WHERE job_id = NEW.job_id AND event_kind = 'registered'
           )
           OR NOT EXISTS (
               SELECT 1
               FROM session_claude_visibility_jobs AS job
               JOIN session_claude_visibility_reconciliations AS reconciliation
                 ON reconciliation.job_id = job.id
                AND reconciliation.reserved_claude_uuid = job.reserved_claude_uuid
                AND reconciliation.attempt_ordinal = job.attempts
               WHERE job.id = NEW.job_id
                 AND (
                     job.state = 'claude_retry'
                     OR (
                         job.state = 'claude_failed'
                         AND job.error_code = 'max_attempts_exhausted'
                     )
                 )
                 AND reconciliation.outcome = 'absent'
                 AND reconciliation.consumed_at IS NULL
           )
       )
       BEGIN
           SELECT RAISE(
               ABORT,
               'Claude characterization abort is not anchored'
           );
       END""",
    """CREATE TRIGGER trg_claude_characterization_event_no_update
       BEFORE UPDATE ON session_claude_visibility_characterization_events
       BEGIN
           SELECT RAISE(
               ABORT,
               'Claude characterization events are append-only'
           );
       END""",
    """CREATE TRIGGER trg_claude_characterization_event_no_delete
       BEFORE DELETE ON session_claude_visibility_characterization_events
       BEGIN
           SELECT RAISE(
               ABORT,
               'Claude characterization events are append-only'
           );
       END""",
)


_CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_NAMES = (
    "trg_claude_characterization_event_identity",
    "trg_claude_characterization_cleanup_order",
    "trg_claude_characterization_abort_order",
    "trg_claude_characterization_event_no_update",
    "trg_claude_characterization_event_no_delete",
)



class SessionBridgeSchemaMixin:
    _DESKTOP_REGISTRY_VALUES_MIGRATION = "desktop_registry_values_v34"
    _DESKTOP_REGISTRY_VALUES_MIGRATION_BATCH = 1_000

    def _apply_desktop_registry_values_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Move desktop_registry_baselines.value_json into the values table.

        Pre-v34 the baseline table carried the full canonical JSON of every
        group on every row: 564,174 rows / 600 MB for 34,265 distinct values
        (7.7 MB) on the production ledger, i.e. ~700 MB of state.db for 8 MB
        of information. This rewrites a legacy-shaped table into the v34
        shape (``value_hash`` referencing ``desktop_registry_values``).

        ONE transaction, deliberately. The copy is batched only to bound
        memory; it commits once, so any other process sees either the whole
        legacy table or the whole v34 table, never a mixture. A session-bridge
        worker still running pre-v34 code after the commit fails LOUDLY on its
        next load (``no such column: value_json``) and writes nothing -- the
        safe direction. The alternative, keeping a nullable value_json beside
        the hash, would have let that stale worker read an empty string as a
        real baseline and plan mutations from it.

        Runs BEFORE ``_reconcile_columns`` so the reconciler never tries (and
        fails, at DEBUG) to ADD the NOT NULL ``value_hash`` column onto the
        legacy table. Name-gated like the other bridge data migrations; the
        pre-check is lock-free so an already-migrated database never takes
        the write lock here (2026-08-07 incident class).
        """
        migration_name = self._DESKTOP_REGISTRY_VALUES_MIGRATION
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                connection.commit()
                return
            columns = {
                row[1]
                for row in cursor.execute(
                    'PRAGMA table_info("desktop_registry_baselines")'
                ).fetchall()
            }
            if "value_json" in columns:
                self._rebuild_desktop_registry_baselines_content_addressed(cursor)
            elif "value_hash" not in columns:
                raise RuntimeError(
                    "desktop_registry_baselines has neither value_json nor "
                    "value_hash; refusing to guess its shape"
                )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise

    @classmethod
    def _rebuild_desktop_registry_baselines_content_addressed(
        cls, cursor: sqlite3.Cursor
    ) -> None:
        """Rename the legacy table aside, create the canonical v34 table, copy.

        Must run inside the caller's open transaction. The v34 DDL is taken
        from BRIDGE_SCHEMA_SQL through a reference database rather than
        restated here, so the rebuilt table cannot drift from what a fresh
        database gets.
        """
        legacy = "desktop_registry_baselines__legacy_v33"
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(BRIDGE_SCHEMA_SQL)
            canonical = {
                name: sql
                for name, sql in reference.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                    "AND name IN ('desktop_registry_values', "
                    "'desktop_registry_baselines')"
                ).fetchall()
            }
        finally:
            reference.close()
        if set(canonical) != {"desktop_registry_values", "desktop_registry_baselines"}:
            raise RuntimeError("v34 desktop registry schema incomplete")

        # A previous attempt cannot have left this behind (it rolled back with
        # everything else), so an existing table here is foreign: refuse.
        if cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (legacy,),
        ).fetchone() is not None:
            raise RuntimeError(f"{legacy} already exists; refusing to overwrite it")
        cursor.execute(f'ALTER TABLE desktop_registry_baselines RENAME TO "{legacy}"')
        # sqlite_master drops IF NOT EXISTS; the values table normally already
        # exists because BRIDGE_SCHEMA_SQL ran first, so re-add the guard.
        cursor.execute(
            canonical["desktop_registry_values"].replace(
                "CREATE TABLE desktop_registry_values",
                "CREATE TABLE IF NOT EXISTS desktop_registry_values",
                1,
            )
        )
        cursor.execute(canonical["desktop_registry_baselines"])

        expected = cursor.execute(f'SELECT COUNT(*) FROM "{legacy}"').fetchone()[0]
        copied = 0
        last_rowid = 0
        batch_size = cls._DESKTOP_REGISTRY_VALUES_MIGRATION_BATCH
        while True:
            rows = cursor.execute(
                f"""SELECT rowid, filename, root_id, group_name, value_json,
                           revision, updated_at
                    FROM "{legacy}"
                    WHERE rowid > ?
                    ORDER BY rowid
                    LIMIT ?""",
                (last_rowid, batch_size),
            ).fetchall()
            if not rows:
                break
            values: dict[str, str] = {}
            baselines: list[tuple[str, str, str, str, int, float]] = []
            for row in rows:
                last_rowid = int(row[0])
                value_json = row[4]
                if not isinstance(value_json, str) or not value_json:
                    raise RuntimeError(
                        "legacy desktop registry baseline rowid "
                        f"{row[0]} carries no JSON text"
                    )
                value_hash = desktop_registry_value_hash(value_json)
                values.setdefault(value_hash, value_json)
                baselines.append(
                    (row[1], row[2], row[3], value_hash, row[5], row[6])
                )
            cursor.executemany(
                "INSERT OR IGNORE INTO desktop_registry_values "
                "(value_hash, value_json) VALUES (?, ?)",
                list(values.items()),
            )
            cursor.executemany(
                """INSERT INTO desktop_registry_baselines
                       (filename, root_id, group_name, value_hash,
                        revision, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                baselines,
            )
            copied += len(rows)
        if copied != expected:
            raise RuntimeError(
                f"desktop registry rebuild copied {copied} of {expected} rows"
            )
        rebuilt = cursor.execute(
            "SELECT COUNT(*) FROM desktop_registry_baselines"
        ).fetchone()[0]
        if rebuilt != expected:
            raise RuntimeError(
                f"desktop registry rebuild holds {rebuilt} of {expected} rows"
            )
        cursor.execute(f'DROP TABLE "{legacy}"')

    def _initialize_bridge_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create additive bridge objects atomically with the local bounded lock retry."""
        for attempt in range(15):
            try:
                cursor.executescript('BEGIN IMMEDIATE;\n' + BRIDGE_SCHEMA_SQL + '\nCOMMIT;')
                return
            except BaseException as exc:
                if self._conn.in_transaction:
                    self._conn.rollback()
                if (isinstance(exc, sqlite3.OperationalError)
                        and any(word in str(exc).lower() for word in ('locked', 'busy'))
                        and attempt < 14):
                    time.sleep(random.uniform(0.020, 0.150))
                    continue
                raise

    def _initialize_bridge_migrations(self, cursor: sqlite3.Cursor) -> None:
        """Preserve local ledger order; no FTS/core scalar-version inference."""
        self._conn.commit()
        self._apply_bridge_migrations(cursor)
        self._apply_claude_characterization_abort_trigger_migration(cursor)
        self._apply_claude_characterization_events_v28_migration(cursor)
        self._apply_claude_characterization_event_orphan_quarantine_migration(cursor)
        self._apply_sidebar_resolution_orphan_quarantine_migration(cursor)
        self._apply_sidebar_reconciliation_proof_orphan_quarantine_migration(cursor)
        try:
            self._validate_v33_sidebar_resolution_schema(cursor)
        except RuntimeError:
            cursor.execute('BEGIN IMMEDIATE')
            try:
                self._repair_v33_sidebar_resolution_table(cursor)
                self._repair_v33_sidebar_resolution_triggers(cursor)
                self._validate_v33_sidebar_resolution_schema(cursor)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    """Exact local v33 ledger repair and validation contracts."""

    @staticmethod
    def _v33_sidebar_resolution_schema() -> tuple[str, dict[str, str]]:
        """Return the canonical v33 ledger table and trigger definitions."""
        table_name = "session_sidebar_v2_attempt_zero_resolutions"
        trigger_names = (
            "trg_session_sidebar_terminal_resolutions_no_v2_attempt_zero_overlap",
            "trg_session_sidebar_precreate_resolutions_no_v2_attempt_zero_overlap",
            "trg_session_sidebar_unbound_resolutions_no_v2_attempt_zero_overlap",
            "trg_session_sidebar_v2_attempt_zero_resolutions_no_replacement",
            "trg_session_sidebar_v2_attempt_zero_resolutions_no_update",
            "trg_session_sidebar_v2_attempt_zero_resolutions_no_delete",
        )
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(BRIDGE_SCHEMA_SQL)
            table_row = reference.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            expected_triggers = {
                name: sql
                for name, sql in reference.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'trigger' AND name IN ("
                    + ", ".join("?" for _ in trigger_names)
                    + ")",
                    trigger_names,
                ).fetchall()
            }
        finally:
            reference.close()
        if (
            table_row is None
            or not isinstance(table_row[0], str)
            or set(expected_triggers) != set(trigger_names)
        ):
            raise RuntimeError("v33 sidebar terminal resolution schema incomplete")
        return table_row[0], expected_triggers


    @classmethod
    def _repair_v33_sidebar_resolution_table(cls, cursor: sqlite3.Cursor) -> None:
        """Restore an empty malformed v33 ledger without discarding evidence."""
        table_name = "session_sidebar_v2_attempt_zero_resolutions"
        expected_table_sql, _ = cls._v33_sidebar_resolution_schema()
        current = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        current_sql = None if current is None else current[0]
        if isinstance(current_sql, str) and " ".join(current_sql.split()) == " ".join(
            expected_table_sql.split()
        ):
            return
        if current is not None:
            row_count = cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if int(row_count):
                raise RuntimeError(
                    "malformed v33 sidebar terminal resolution ledger contains evidence"
                )
            trigger_rows = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
                (table_name,),
            ).fetchall()
            for trigger_row in trigger_rows:
                quoted_name = str(trigger_row[0]).replace('"', '""')
                cursor.execute(f'DROP TRIGGER "{quoted_name}"')
            cursor.execute(f'DROP TABLE "{table_name}"')
        cursor.execute(expected_table_sql)


    @classmethod
    def _repair_v33_sidebar_resolution_triggers(cls, cursor: sqlite3.Cursor) -> None:
        """Restore the exact v33 trigger definitions before granting v33."""
        _, expected = cls._v33_sidebar_resolution_schema()
        for name, expected_sql in expected.items():
            current = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                (name,),
            ).fetchone()
            current_sql = None if current is None else current[0]
            if isinstance(current_sql, str) and " ".join(current_sql.split()) == " ".join(
                expected_sql.split()
            ):
                continue
            quoted_name = name.replace('"', '""')
            cursor.execute(f'DROP TRIGGER IF EXISTS "{quoted_name}"')
            cursor.execute(expected_sql)


    @classmethod
    def _validate_v33_sidebar_resolution_schema(cls, cursor: sqlite3.Cursor) -> None:
        """Require byte-equivalent canonical v33 table and trigger authority."""
        table_name = "session_sidebar_v2_attempt_zero_resolutions"
        expected_table_sql, expected_triggers = cls._v33_sidebar_resolution_schema()
        table_row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if (
            table_row is None
            or not isinstance(table_row[0], str)
            or " ".join(table_row[0].split()) != " ".join(expected_table_sql.split())
        ):
            raise RuntimeError("v33 sidebar terminal resolution schema incomplete")
        for name, expected_sql in expected_triggers.items():
            trigger_row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                (name,),
            ).fetchone()
            if (
                trigger_row is None
                or not isinstance(trigger_row[0], str)
                or " ".join(trigger_row[0].split())
                != " ".join(expected_sql.split())
            ):
                raise RuntimeError("v33 sidebar terminal resolution schema incomplete")



    @staticmethod
    def _canonicalize_legacy_claude_cost(raw: object, rowid: int) -> str:
        """Return exact six-decimal legacy cost text or fail closed."""
        try:
            value = Decimal(str(raw))
            quantum = Decimal("0.000001")
            canonical = value.quantize(quantum)
        except (InvalidOperation, ValueError):
            canonical = None
        if (
            canonical is None
            or not value.is_finite()
            or value < 0
            or value > Decimal("1000000")
            or value != canonical
        ):
            raise RuntimeError(
                "unsafe session_claude_registration_usage row "
                f"{rowid} reserved_estimated_cost_usd={raw!r}"
            )
        return format(canonical, ".6f")


    def _bridge_migration_applied(
        self, cursor: sqlite3.Cursor, migration_name: str
    ) -> bool:
        """Lock-free check whether *migration_name* is already recorded.

        Runs as a plain autocommit read (no ``BEGIN IMMEDIATE``) so an
        already-migrated database — the overwhelmingly common case on every
        ``SessionDB()`` open, including the desktop's per-request read
        endpoints — never has to acquire the WAL write lock.  Taking that lock
        unconditionally is what let transient session-bridge write contention
        raise ``database is locked`` and blank the desktop session list
        (2026-08-07 incident).  Returns False (fall through to the locked
        migration path) when the ledger table does not exist yet on a
        brand-new database.
        """
        try:
            row = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return False
            raise
        return row is not None


    def _apply_bridge_migrations(self, cursor: sqlite3.Cursor) -> None:
        """Apply bridge-only data migrations independently of core/FTS."""
        migration_name = "claude_visibility_security_v24"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                connection.commit()
                return

            for row in cursor.execute(
                """SELECT rowid, reserved_estimated_cost_usd
                   FROM session_claude_registration_usage"""
            ).fetchall():
                rowid = row["rowid"] if isinstance(row, sqlite3.Row) else row[0]
                raw = (
                    row["reserved_estimated_cost_usd"]
                    if isinstance(row, sqlite3.Row)
                    else row[1]
                )
                canonical = self._canonicalize_legacy_claude_cost(raw, rowid)
                if raw != canonical:
                    cursor.execute(
                        """UPDATE session_claude_registration_usage
                           SET reserved_estimated_cost_usd = ? WHERE rowid = ?""",
                        (canonical, rowid),
                    )

            # v23 lease/error sentinels were not authenticated authorization.
            cursor.execute(
                """UPDATE session_claude_visibility_jobs
                   SET state = 'claude_retry', next_attempt_at = updated_at,
                       lease_digest = NULL, lease_expires_at = NULL,
                       lease_kind = NULL, error_code = 'lease_expired',
                       error_detail = substr(
                           'v23 active lease invalidated during v24 migration; '
                           || COALESCE(error_code, 'no prior diagnostic') || '; '
                           || COALESCE(error_detail, ''), 1, 512
                       )
                   WHERE state = 'claude_leased'"""
            )
            cursor.execute(
                """UPDATE session_claude_visibility_jobs
                   SET error_code = 'creation_ambiguous',
                       error_detail = substr(
                           'v23 authorization sentinel invalidated during v24 migration; '
                           || error_code || '; ' || COALESCE(error_detail, ''), 1, 512
                       )
                   WHERE state = 'claude_retry'
                     AND error_code IN (
                         'exact_id_absent_reconciled',
                         'exact_id_reconciliation_in_progress'
                     )"""
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    def _apply_claude_characterization_abort_trigger_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Allow exact max-attempt absence to anchor operator-confirmed abort."""

        migration_name = "claude_characterization_abort_max_attempts_v27"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                connection.commit()
                return
            cursor.execute(
                "DROP TRIGGER IF EXISTS trg_claude_characterization_abort_order"
            )
            cursor.execute(
                """CREATE TRIGGER trg_claude_characterization_abort_order
                   BEFORE INSERT ON session_claude_visibility_characterization_events
                   WHEN NEW.event_kind = 'launch_aborted' AND (
                       NOT EXISTS (
                           SELECT 1
                           FROM session_claude_visibility_characterization_events
                           WHERE job_id = NEW.job_id AND event_kind = 'registered'
                       )
                       OR NOT EXISTS (
                           SELECT 1
                           FROM session_claude_visibility_jobs AS job
                           JOIN session_claude_visibility_reconciliations AS reconciliation
                             ON reconciliation.job_id = job.id
                            AND reconciliation.reserved_claude_uuid = job.reserved_claude_uuid
                            AND reconciliation.attempt_ordinal = job.attempts
                           WHERE job.id = NEW.job_id
                             AND (
                                 job.state = 'claude_retry'
                                 OR (
                                     job.state = 'claude_failed'
                                     AND job.error_code = 'max_attempts_exhausted'
                                 )
                             )
                             AND reconciliation.outcome = 'absent'
                             AND reconciliation.consumed_at IS NULL
                       )
                   )
                   BEGIN
                       SELECT RAISE(
                           ABORT,
                           'Claude characterization abort is not anchored'
                       );
                   END"""
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    @staticmethod
    def _drop_claude_characterization_event_triggers(
        cursor: sqlite3.Cursor,
    ) -> None:
        for trigger_name in _CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_NAMES:
            cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')


    @staticmethod
    def _create_claude_characterization_event_triggers(
        cursor: sqlite3.Cursor,
    ) -> None:
        for trigger_sql in _CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_SQL:
            cursor.execute(trigger_sql)


    @staticmethod
    def _validate_claude_characterization_events_v28(
        cursor: sqlite3.Cursor,
        *,
        expected_rows: int | None = None,
        check_foreign_keys: bool = True,
    ) -> None:
        table_name = "session_claude_visibility_characterization_events"
        schema_row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if schema_row is None or schema_row[0] is None:
            raise RuntimeError("Claude characterization event table is missing")
        normalized_schema = " ".join(str(schema_row[0]).split())
        if "'launch_aborted'" not in normalized_schema:
            raise RuntimeError("Claude characterization event CHECK is stale")

        columns = tuple(
            row[1]
            for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        )
        if columns != _CLAUDE_CHARACTERIZATION_EVENT_COLUMNS:
            raise RuntimeError("Claude characterization event columns changed")

        unique_column_sets: set[tuple[str, ...]] = set()
        for index_row in cursor.execute(
            f'PRAGMA index_list("{table_name}")'
        ).fetchall():
            if int(index_row[2]) != 1:
                continue
            index_name = str(index_row[1]).replace('"', '""')
            unique_column_sets.add(
                tuple(
                    row[2]
                    for row in cursor.execute(
                        f'PRAGMA index_info("{index_name}")'
                    ).fetchall()
                )
            )
        expected_unique = {
            ("job_id", "event_kind"),
            ("operation_id", "event_kind"),
            ("source_session_id", "event_kind"),
            ("bridge_id", "event_kind"),
            ("idempotency_key", "event_kind"),
            ("reserved_claude_uuid", "event_kind"),
        }
        if unique_column_sets != expected_unique:
            raise RuntimeError("Claude characterization event uniqueness changed")

        foreign_keys = tuple(
            (row[3], row[4], row[2], row[6])
            for row in cursor.execute(
                f'PRAGMA foreign_key_list("{table_name}")'
            ).fetchall()
        )
        if foreign_keys != (
            (
                "job_id",
                "id",
                "session_claude_visibility_jobs",
                "RESTRICT",
            ),
            (
                "reserved_claude_uuid",
                "reserved_claude_uuid",
                "session_claude_visibility_jobs",
                "RESTRICT",
            ),
        ):
            raise RuntimeError("Claude characterization event foreign key changed")
        if check_foreign_keys and (
            cursor.execute(f'PRAGMA foreign_key_check("{table_name}")').fetchone()
            is not None
        ):
            raise RuntimeError("Claude characterization event foreign key violation")

        triggers = {
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = ?",
                (table_name,),
            ).fetchall()
        }
        if triggers != set(_CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_NAMES):
            raise RuntimeError("Claude characterization event triggers changed")
        if expected_rows is not None:
            actual_rows = cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if int(actual_rows) != expected_rows:
                raise RuntimeError("Claude characterization event row count changed")


    def _apply_claude_characterization_events_v28_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Rebuild the v26/v27 event table so launch-abort is persistable."""

        migration_name = "claude_characterization_events_v28"
        table_name = "session_claude_visibility_characterization_events"
        temporary_name = "_session_claude_visibility_characterization_events_v28"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            # v29 can preserve and quarantine historical rows whose parent jobs
            # were deleted by a pre-foreign-key writer.  Validate v28's shape
            # first, then let v29 perform the final referential validation.
            self._validate_claude_characterization_events_v28(
                cursor, check_foreign_keys=False
            )
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                self._validate_claude_characterization_events_v28(
                    cursor, check_foreign_keys=False
                )
                connection.commit()
                return

            table_row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if table_row is None or table_row[0] is None:
                raise RuntimeError("Claude characterization event table is missing")
            source_rows = int(
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            )
            if "'launch_aborted'" not in " ".join(str(table_row[0]).split()):
                if (
                    cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (temporary_name,),
                    ).fetchone()
                    is not None
                ):
                    raise RuntimeError(
                        "Claude characterization event migration temp table exists"
                    )
                self._drop_claude_characterization_event_triggers(cursor)
                cursor.execute(_CLAUDE_CHARACTERIZATION_EVENTS_TABLE_V28_SQL)
                column_list = ", ".join(
                    f'"{column}"' for column in _CLAUDE_CHARACTERIZATION_EVENT_COLUMNS
                )
                cursor.execute(
                    f'INSERT INTO "{temporary_name}" ({column_list}) '
                    f'SELECT {column_list} FROM "{table_name}"'
                )
                copied_rows = int(
                    cursor.execute(
                        f'SELECT COUNT(*) FROM "{temporary_name}"'
                    ).fetchone()[0]
                )
                if copied_rows != source_rows:
                    raise RuntimeError(
                        "Claude characterization event row count changed"
                    )
                missing = cursor.execute(
                    f'SELECT 1 FROM (SELECT {column_list} FROM "{table_name}" '
                    f'EXCEPT SELECT {column_list} FROM "{temporary_name}") LIMIT 1'
                ).fetchone()
                extra = cursor.execute(
                    f'SELECT 1 FROM (SELECT {column_list} FROM "{temporary_name}" '
                    f'EXCEPT SELECT {column_list} FROM "{table_name}") LIMIT 1'
                ).fetchone()
                if missing is not None or extra is not None:
                    raise RuntimeError("Claude characterization event rows changed")
                cursor.execute(f'DROP TABLE "{table_name}"')
                cursor.execute(
                    f'ALTER TABLE "{temporary_name}" RENAME TO "{table_name}"'
                )
            else:
                self._drop_claude_characterization_event_triggers(cursor)

            self._create_claude_characterization_event_triggers(cursor)
            self._validate_claude_characterization_events_v28(
                cursor, expected_rows=source_rows
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    @staticmethod
    def _validate_claude_characterization_event_quarantine(
        cursor: sqlite3.Cursor,
        *,
        expected_rows: int | None = None,
    ) -> None:
        table_name = "session_claude_visibility_characterization_event_quarantine"
        columns = tuple(
            row[1]
            for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        )
        if columns != _CLAUDE_CHARACTERIZATION_EVENT_QUARANTINE_COLUMNS:
            raise RuntimeError("Claude characterization event quarantine changed")
        if expected_rows is not None:
            actual_rows = cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if int(actual_rows) != expected_rows:
                raise RuntimeError("Claude characterization event quarantine changed")


    def _apply_claude_characterization_event_orphan_quarantine_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Preserve and quarantine audit rows whose parent job is absent.

        These rows cannot participate in any delivery or recovery operation.
        Keeping them in an FK-free audit table repairs startup without losing
        the exact historical evidence needed for operator review.
        """

        migration_name = "claude_characterization_event_orphan_quarantine_v29"
        event_table = "session_claude_visibility_characterization_events"
        quarantine_table = "session_claude_visibility_characterization_event_quarantine"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            self._validate_claude_characterization_events_v28(cursor)
            self._validate_claude_characterization_event_quarantine(cursor)
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                self._validate_claude_characterization_events_v28(cursor)
                self._validate_claude_characterization_event_quarantine(cursor)
                connection.commit()
                return

            self._validate_claude_characterization_events_v28(
                cursor, check_foreign_keys=False
            )
            self._validate_claude_characterization_event_quarantine(cursor)
            event_columns = ", ".join(
                f'event."{column}"'
                for column in _CLAUDE_CHARACTERIZATION_EVENT_COLUMNS
            )
            orphan_rows = cursor.execute(
                f"""SELECT event.rowid, {event_columns}
                    FROM \"{event_table}\" AS event
                    WHERE NOT EXISTS (
                        SELECT 1 FROM session_claude_visibility_jobs AS job
                        WHERE job.id = event.job_id
                          AND job.reserved_claude_uuid = event.reserved_claude_uuid
                    )
                    ORDER BY event.rowid"""
            ).fetchall()
            source_rows = int(
                cursor.execute(f'SELECT COUNT(*) FROM "{event_table}"').fetchone()[0]
            )

            if orphan_rows:
                self._drop_claude_characterization_event_triggers(cursor)
                insert_columns = ", ".join(
                    f'"{column}"'
                    for column in _CLAUDE_CHARACTERIZATION_EVENT_QUARANTINE_COLUMNS
                )
                placeholders = ", ".join(
                    "?" for _ in _CLAUDE_CHARACTERIZATION_EVENT_QUARANTINE_COLUMNS
                )
                for orphan_row in orphan_rows:
                    cursor.execute(
                        f'INSERT INTO "{quarantine_table}" ({insert_columns}) '
                        f"VALUES ({placeholders})",
                        (
                            *tuple(orphan_row),
                            "missing_parent_job",
                            time.time(),
                        ),
                    )
                for orphan_row in orphan_rows:
                    cursor.execute(
                        f'DELETE FROM "{event_table}" WHERE rowid = ?',
                        (orphan_row[0],),
                    )
                self._create_claude_characterization_event_triggers(cursor)

            self._validate_claude_characterization_events_v28(
                cursor, expected_rows=source_rows - len(orphan_rows)
            )
            self._validate_claude_characterization_event_quarantine(
                cursor, expected_rows=len(orphan_rows)
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    @staticmethod
    def _validate_sidebar_orphan_resolution_quarantine(
        cursor: sqlite3.Cursor,
        *,
        expected_rows: int | None = None,
    ) -> None:
        table_name = "session_sidebar_orphan_resolution_quarantine"
        columns = tuple(
            row[1]
            for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        )
        if columns != _SIDEBAR_ORPHAN_RESOLUTION_QUARANTINE_COLUMNS:
            raise RuntimeError("sidebar orphan resolution quarantine changed")
        if expected_rows is not None:
            actual_rows = cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if int(actual_rows) != expected_rows:
                raise RuntimeError("sidebar orphan resolution quarantine changed")


    def _apply_sidebar_resolution_orphan_quarantine_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Preserve stale sidebar-resolution evidence without blocking delivery.

        The source rows have no parent sidebar job, so they cannot resolve or
        suppress a delivery.  A single transaction moves their exact payloads
        to a dedicated audit table and restores referential integrity.
        """

        migration_name = "sidebar_resolution_orphan_quarantine_v30"
        quarantine_table = "session_sidebar_orphan_resolution_quarantine"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            self._validate_sidebar_orphan_resolution_quarantine(cursor)
            for table_name in _SIDEBAR_RESOLUTION_TABLES:
                if cursor.execute(
                    f'PRAGMA foreign_key_check("{table_name}")'
                ).fetchone() is not None:
                    raise RuntimeError("sidebar resolution foreign key violation")
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                self._validate_sidebar_orphan_resolution_quarantine(cursor)
                for table_name in _SIDEBAR_RESOLUTION_TABLES:
                    if cursor.execute(
                        f'PRAGMA foreign_key_check("{table_name}")'
                    ).fetchone() is not None:
                        raise RuntimeError("sidebar resolution foreign key violation")
                connection.commit()
                return

            self._validate_sidebar_orphan_resolution_quarantine(cursor)
            quarantined_rows = 0
            for table_name in _SIDEBAR_RESOLUTION_TABLES:
                orphan_rows = cursor.execute(
                    f"""SELECT resolution.rowid AS original_resolution_rowid,
                               resolution.*
                        FROM \"{table_name}\" AS resolution
                        WHERE NOT EXISTS (
                            SELECT 1 FROM session_sidebar_jobs AS job
                            WHERE job.id = resolution.job_id
                        )
                        ORDER BY resolution.rowid"""
                ).fetchall()
                if not orphan_rows:
                    continue
                trigger_rows = cursor.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = ?",
                    (table_name,),
                ).fetchall()
                if any(
                    not isinstance(row["name"], str)
                    or not isinstance(row["sql"], str)
                    for row in trigger_rows
                ):
                    raise RuntimeError("sidebar resolution trigger is malformed")
                for trigger_row in trigger_rows:
                    trigger_name = trigger_row["name"].replace('"', '""')
                    cursor.execute(f'DROP TRIGGER "{trigger_name}"')
                for orphan_row in orphan_rows:
                    payload = dict(orphan_row)
                    payload.pop("original_resolution_rowid", None)
                    cursor.execute(
                        f"""INSERT INTO \"{quarantine_table}\" (
                                resolution_table, original_resolution_rowid,
                                job_id, source_session_id, payload_json,
                                reason, quarantined_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            table_name,
                            orphan_row["original_resolution_rowid"],
                            orphan_row["job_id"],
                            orphan_row["source_session_id"],
                            json.dumps(
                                payload,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            "missing_parent_job",
                            time.time(),
                        ),
                    )
                for orphan_row in orphan_rows:
                    cursor.execute(
                        f'DELETE FROM "{table_name}" WHERE rowid = ?',
                        (orphan_row["original_resolution_rowid"],),
                    )
                for trigger_row in trigger_rows:
                    cursor.execute(trigger_row["sql"])
                quarantined_rows += len(orphan_rows)

            for table_name in _SIDEBAR_RESOLUTION_TABLES:
                if cursor.execute(
                    f'PRAGMA foreign_key_check("{table_name}")'
                ).fetchone() is not None:
                    raise RuntimeError("sidebar resolution foreign key violation")
            self._validate_sidebar_orphan_resolution_quarantine(
                cursor, expected_rows=quarantined_rows
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    @staticmethod
    def _validate_sidebar_reconciliation_proof_quarantine(
        cursor: sqlite3.Cursor,
        *,
        expected_rows: int | None = None,
    ) -> None:
        table_name = "session_sidebar_reconciliation_proof_quarantine"
        columns = tuple(
            row[1]
            for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        )
        if columns != _SIDEBAR_RECONCILIATION_PROOF_QUARANTINE_COLUMNS:
            raise RuntimeError("sidebar reconciliation proof quarantine changed")
        if expected_rows is not None:
            actual_rows = cursor.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if int(actual_rows) != expected_rows:
                raise RuntimeError("sidebar reconciliation proof quarantine changed")


    def _apply_sidebar_reconciliation_proof_orphan_quarantine_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Preserve reconciliation proofs whose parent sidebar job is gone.

        ``session_sidebar_reconciliation_proofs`` is an append-only ledger: both
        UPDATE and DELETE raise, and its ``job_id`` is ON DELETE RESTRICT. When a
        parent job disappeared anyway -- the 2026-08-09 bulk DELETE ran with
        ``foreign_keys`` OFF, so RESTRICT never fired -- the children were left
        permanently stranded. They are unreachable by every consumer (each read is
        keyed on ``session_sidebar_jobs.reconciliation_proof_digest``, which no
        surviving job carries for them) yet cannot be removed, so they would
        report as foreign-key violations forever.

        Same remedy as v29/v30: one transaction moves the exact rows, every column
        preserved, into an FK-free audit table. The immutability triggers are
        dropped and restored verbatim from ``sqlite_master`` inside that
        transaction, so the ledger is guarded again the moment it commits.
        """

        migration_name = "sidebar_reconciliation_proof_orphan_quarantine_v31"
        proof_table = "session_sidebar_reconciliation_proofs"
        quarantine_table = "session_sidebar_reconciliation_proof_quarantine"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            self._validate_sidebar_reconciliation_proof_quarantine(cursor)
            if cursor.execute(
                f'PRAGMA foreign_key_check("{proof_table}")'
            ).fetchone() is not None:
                raise RuntimeError("sidebar reconciliation proof foreign key violation")
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                self._validate_sidebar_reconciliation_proof_quarantine(cursor)
                if cursor.execute(
                    f'PRAGMA foreign_key_check("{proof_table}")'
                ).fetchone() is not None:
                    raise RuntimeError(
                        "sidebar reconciliation proof foreign key violation"
                    )
                connection.commit()
                return

            self._validate_sidebar_reconciliation_proof_quarantine(cursor)
            proof_columns = ", ".join(
                f'proof."{column}"' for column in _SIDEBAR_RECONCILIATION_PROOF_COLUMNS
            )
            orphan_rows = cursor.execute(
                f"""SELECT {proof_columns}
                    FROM "{proof_table}" AS proof
                    WHERE NOT EXISTS (
                        SELECT 1 FROM session_sidebar_jobs AS job
                        WHERE job.id = proof.job_id
                    )
                    ORDER BY proof.created_at, proof.proof_digest"""
            ).fetchall()

            if orphan_rows:
                trigger_rows = cursor.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = ?",
                    (proof_table,),
                ).fetchall()
                if any(
                    not isinstance(row["name"], str) or not isinstance(row["sql"], str)
                    for row in trigger_rows
                ):
                    raise RuntimeError(
                        "sidebar reconciliation proof trigger is malformed"
                    )
                for trigger_row in trigger_rows:
                    trigger_name = trigger_row["name"].replace('"', '""')
                    cursor.execute(f'DROP TRIGGER "{trigger_name}"')
                insert_columns = ", ".join(
                    f'"{column}"'
                    for column in _SIDEBAR_RECONCILIATION_PROOF_QUARANTINE_COLUMNS
                )
                placeholders = ", ".join(
                    "?" for _ in _SIDEBAR_RECONCILIATION_PROOF_QUARANTINE_COLUMNS
                )
                quarantined_at = time.time()
                for orphan_row in orphan_rows:
                    cursor.execute(
                        f'INSERT INTO "{quarantine_table}" ({insert_columns}) '
                        f"VALUES ({placeholders})",
                        (*tuple(orphan_row), "missing_parent_job", quarantined_at),
                    )
                for orphan_row in orphan_rows:
                    cursor.execute(
                        f'DELETE FROM "{proof_table}" WHERE proof_digest = ?',
                        (orphan_row["proof_digest"],),
                    )
                for trigger_row in trigger_rows:
                    cursor.execute(trigger_row["sql"])
                restored = {
                    row["name"]
                    for row in cursor.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND tbl_name = ?",
                        (proof_table,),
                    ).fetchall()
                }
                if restored != {row["name"] for row in trigger_rows}:
                    raise RuntimeError(
                        "sidebar reconciliation proof triggers were not restored"
                    )

            if cursor.execute(
                f'PRAGMA foreign_key_check("{proof_table}")'
            ).fetchone() is not None:
                raise RuntimeError("sidebar reconciliation proof foreign key violation")
            self._validate_sidebar_reconciliation_proof_quarantine(
                cursor, expected_rows=len(orphan_rows)
            )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


    def _apply_claude_auth_recovery_call_started_migration(
        self, cursor: sqlite3.Cursor
    ) -> None:
        """Add the crash-accounting checkpoint to the c214 recovery table."""

        migration_name = "claude_auth_recovery_call_started_v25"
        connection = self._conn
        if connection is None:
            raise RuntimeError("bridge migration requires an open database")
        if self._bridge_migration_applied(cursor, migration_name):
            return
        try:
            cursor.execute("BEGIN IMMEDIATE")
            applied = cursor.execute(
                "SELECT 1 FROM session_bridge_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied is not None:
                connection.commit()
                return
            columns = {
                row["name"] if isinstance(row, sqlite3.Row) else row[1]
                for row in cursor.execute(
                    'PRAGMA table_info("session_claude_auth_recoveries")'
                ).fetchall()
            }
            if "call_started_at" not in columns:
                cursor.execute(
                    "ALTER TABLE session_claude_auth_recoveries "
                    "ADD COLUMN call_started_at REAL"
                )
            cursor.execute(
                """INSERT INTO session_bridge_migrations
                   (migration_name, applied_at) VALUES (?, ?)""",
                (migration_name, time.time()),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise



# Lease triggers require reconciled columns and completed security migrations.
BRIDGE_DEFERRED_SQL = """
CREATE INDEX IF NOT EXISTS idx_desktop_registry_baselines_value_hash ON desktop_registry_baselines(value_hash);
DROP TRIGGER IF EXISTS trg_claude_visibility_lease_kind_insert;
DROP TRIGGER IF EXISTS trg_claude_visibility_lease_kind_update;
CREATE TRIGGER IF NOT EXISTS trg_claude_visibility_lease_kind_insert
BEFORE INSERT ON session_claude_visibility_jobs
WHEN (
    NEW.state = 'claude_leased'
    AND (
        NEW.lease_digest IS NULL OR NEW.lease_expires_at IS NULL
        OR NEW.lease_kind IS NULL
        OR NEW.lease_kind NOT IN ('launch', 'reconciliation')
    )
) OR (
    NEW.state != 'claude_leased'
    AND (
        NEW.lease_digest IS NOT NULL OR NEW.lease_expires_at IS NOT NULL
        OR NEW.lease_kind IS NOT NULL
    )
)
BEGIN
    SELECT RAISE(ABORT, 'invalid Claude visibility lease fields');
END;
CREATE TRIGGER IF NOT EXISTS trg_claude_visibility_lease_kind_update
BEFORE UPDATE ON session_claude_visibility_jobs
WHEN (
    NEW.state = 'claude_leased'
    AND (
        NEW.lease_digest IS NULL OR NEW.lease_expires_at IS NULL
        OR NEW.lease_kind IS NULL
        OR NEW.lease_kind NOT IN ('launch', 'reconciliation')
    )
) OR (
    NEW.state != 'claude_leased'
    AND (
        NEW.lease_digest IS NOT NULL OR NEW.lease_expires_at IS NOT NULL
        OR NEW.lease_kind IS NOT NULL
    )
)
BEGIN
    SELECT RAISE(ABORT, 'invalid Claude visibility lease fields');
END;
"""
