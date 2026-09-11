
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    session_key TEXT,
    chat_id TEXT,
    chat_type TEXT,
    thread_id TEXT,
    display_name TEXT,
    origin_json TEXT,
    expiry_finalized INTEGER DEFAULT 0,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cwd TEXT,
    git_branch TEXT,
    git_repo_root TEXT,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count INTEGER DEFAULT 0,
    handoff_state TEXT,
    handoff_platform TEXT,
    handoff_error TEXT,
    compression_failure_cooldown_until REAL,
    compression_failure_error TEXT,
    compression_fallback_streak INTEGER NOT NULL DEFAULT 0,
    profile_name TEXT,
    rewind_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    effect_disposition TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT,
    platform_message_id TEXT,
    -- External-harness event identity: native_event_id||':'||ordinal, set by
    -- the session-bridge ingest. Backs the partial UNIQUE index that makes a
    -- re-ingest unable to append a second copy of an already-stored event.
    -- NULL for every non-ingested row, which the partial index excludes.
    native_event_key TEXT,
    observed INTEGER DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    compacted INTEGER NOT NULL DEFAULT 0,
    api_content TEXT
);

CREATE TABLE IF NOT EXISTS session_model_usage (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    billing_provider TEXT NOT NULL DEFAULT '',
    billing_base_url TEXT NOT NULL DEFAULT '',
    billing_mode TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    api_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    actual_cost_usd REAL NOT NULL DEFAULT 0,
    cost_status TEXT,
    cost_source TEXT,
    first_seen REAL,
    last_seen REAL,
    PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)
);

CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS gateway_routing (
    scope TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (scope, session_key)
);

CREATE TABLE IF NOT EXISTS compression_locks (
    session_id TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS async_delegations (
    delegation_id TEXT PRIMARY KEY,
    origin_session TEXT NOT NULL,
    origin_ui_session_id TEXT NOT NULL DEFAULT '',
    parent_session_id TEXT,
    state TEXT NOT NULL,
    dispatched_at REAL NOT NULL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    event_json TEXT,
    result_json TEXT,
    delivery_state TEXT NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at REAL,
    owner_pid INTEGER,
    owner_started_at INTEGER,
    task_json TEXT,
    delivery_claim TEXT,
    delivery_claimed_at REAL
);

CREATE TABLE IF NOT EXISTS session_sidebar_exclusions (
    source_session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    provider TEXT NOT NULL CHECK (provider IN ('claude', 'hermes')),
    reason_code TEXT NOT NULL CHECK (reason_code IN ('source_cwd_missing')),
    source_identity_digest TEXT NOT NULL,
    excluded_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_source_id ON sessions(source, id);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_compression_locks_expires ON compression_locks(expires_at);
CREATE INDEX IF NOT EXISTS idx_session_model_usage_session ON session_model_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_session_model_usage_model ON session_model_usage(model);
CREATE INDEX IF NOT EXISTS idx_async_delegations_delivery
    ON async_delegations(delivery_state, completed_at);
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
CREATE TABLE IF NOT EXISTS desktop_registry_baselines (
    filename TEXT NOT NULL,
    root_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL,
    PRIMARY KEY (filename, root_id, group_name)
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


CREATE INDEX IF NOT EXISTS idx_messages_session_active
    ON messages(session_id, active, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_active_null
    ON messages(active) WHERE active IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_session_key
    ON sessions(session_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_gateway_peer
    ON sessions(source, user_id, chat_id, chat_type, thread_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_handoff_state
    ON sessions(handoff_state, started_at);
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


CREATE VIEW IF NOT EXISTS messages_fts_source AS
SELECT
    id AS id,
    COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '') AS content
FROM messages;

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages_fts_source',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES (
        'delete',
        old.id,
        COALESCE(old.content, '') || ' ' || COALESCE(old.tool_name, '') || ' ' || COALESCE(old.tool_calls, '')
    );
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES (
        'delete',
        old.id,
        COALESCE(old.content, '') || ' ' || COALESCE(old.tool_name, '') || ' ' || COALESCE(old.tool_calls, '')
    );
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;


CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(
    content,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_trigram_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts_trigram(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_trigram_delete AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts_trigram WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_trigram_update AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts_trigram WHERE rowid = old.id;
    INSERT INTO messages_fts_trigram(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;
