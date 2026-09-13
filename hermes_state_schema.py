"""Schema creation, column reconciliation, and FTS DDL management for SessionDB.

Plain mixin for ``hermes_state.SessionDB`` (no ``__init__``/state of its own).
Must never import hermes_state (cycle); shared constants live in hermes_state_common.
"""

NEWLINE = chr(10)  # BRIDGE_SCHEMA_SQL is spliced between statements
from decimal import Decimal, InvalidOperation
import contextlib
import datetime
import hashlib
import logging
import json
import os
import sqlite3
import tempfile
import time
import uuid
from typing import Dict, List, Optional, Sequence


from hermes_constants import get_hermes_home
from hermes_startup_watchdog import report_startup_progress
from utils import safe_json_loads
from hermes_state_common import (
    DEFERRED_INDEX_SQL, FTS_CJK_STALE_KEY, FTS_REBUILD_DEFERRAL_KEY, FTS_STALE_KEY, FTS_SQL,
    FTS_STORAGE_VERSION, FTS_TOOL_FULL_CONTENT_HIGH_WATER_KEY, FTS_TRIGRAM_SQL, LEGACY_FTS_SQL,
    LEGACY_FTS_TRIGRAM_SQL, SCHEMA_SQL,
    SCHEMA_VERSION, _FTS_CJK_TRIGGERS, _FTS_TRIGGERS, _ephemeral_child_sql, fts_rebuild_admission,
    _message_trigram_disabled,
)
from hermes_state_holders import _read_proc_argv

# Pre-split logger identity so log filtering/capture is unchanged.
logger = logging.getLogger("hermes_state")

_FTS_HOLDER_ESCALATE_ATTEMPTS = 3
_FTS_HOLDER_ESCALATE_SECONDS = 60.0
# The same holder PID set blocking this many deferrals over this long is a structurally resident
# peer (a supervised service on the same HERMES_HOME), not a transient one worth waiting out (#106393).
_FTS_HOLDER_FUTILE_ATTEMPTS = 10
_FTS_HOLDER_FUTILE_SECONDS = 1800.0
# retry_deferred_fts_recovery cadence: startup paid the full admission wait once; later
# retries are non-blocking probes whose spacing doubles up to the cap.
_FTS_STALE_RETRY_SECONDS = 60.0
_FTS_STALE_RETRY_MAX_SECONDS = 3600.0


def _holder_cmdline(pid: int) -> str:
    argv = _read_proc_argv(pid)
    return " ".join(argv)[:120] if argv else "<cmdline unavailable>"

# schema_read_probe_statements() cache (parses SCHEMA_SQL in an in-memory DB; once per process).
_READ_PROBE_STATEMENTS: Optional[tuple] = None

# Trigram triggers need the trigram tokenizer (SQLite >= 3.34); without it _ensure_fts_schema
# soft-fails that DDL and "all six present" is unsatisfiable, so a trigger's absence is
# measured only against the DDL that can create it.
_FTS_TRIGRAM_TRIGGERS = tuple(n for n in _FTS_TRIGGERS if "_trigram_" in n)
_FTS_BASE_TRIGGERS = tuple(n for n in _FTS_TRIGGERS if n not in _FTS_TRIGRAM_TRIGGERS)

# (base DDL, trigram DDL) keyed by "legacy inline layout?" — v23 external-content vs pre-v23 inline.
_FTS_DDL = {False: (FTS_SQL, FTS_TRIGRAM_SQL), True: (LEGACY_FTS_SQL, LEGACY_FTS_TRIGRAM_SQL)}
_LEGACY_INLINE_CONCAT_SQL = (
    "COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '') "
)
_SESSION_MODEL_USAGE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_session_model_usage_session ON session_model_usage(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_session_model_usage_model ON session_model_usage(model)",
)
_SESSION_MODEL_USAGE_HEAL_DDL = """CREATE TABLE session_model_usage (
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
)"""
# v22-migration rendering of the same table (column lines at 35 spaces, paren at 31; pinned SQL).
_SESSION_MODEL_USAGE_V22_DDL = "\n".join(
    [_SESSION_MODEL_USAGE_HEAL_DDL.splitlines()[0]]
    + [" " * 35 + ln.strip() for ln in _SESSION_MODEL_USAGE_HEAL_DDL.splitlines()[1:-1]]
    + [" " * 31 + ")"]
)
# Statement text pinned by the SQL trace harness (whitespace included).
_SESSION_MODEL_USAGE_V20_SEED_SQL = """INSERT OR IGNORE INTO session_model_usage (
                               session_id, model, billing_provider,
                               billing_base_url, billing_mode,
                               api_call_count, input_tokens,
                               output_tokens, cache_read_tokens,
                               cache_write_tokens, reasoning_tokens,
                               estimated_cost_usd, actual_cost_usd,
                               cost_status, cost_source, first_seen, last_seen
                           )
                           SELECT id, COALESCE(model, 'unknown'),
                                  COALESCE(billing_provider, ''),
                                  COALESCE(billing_base_url, ''),
                                  COALESCE(billing_mode, ''),
                                  COALESCE(api_call_count, 0),
                                  COALESCE(input_tokens, 0),
                                  COALESCE(output_tokens, 0),
                                  COALESCE(cache_read_tokens, 0),
                                  COALESCE(cache_write_tokens, 0),
                                  COALESCE(reasoning_tokens, 0),
                                  COALESCE(estimated_cost_usd, 0),
                                  COALESCE(actual_cost_usd, 0),
                                  cost_status, cost_source,
                                  started_at, COALESCE(ended_at, started_at)
                           FROM sessions
                           WHERE COALESCE(input_tokens, 0)
                                 + COALESCE(output_tokens, 0)
                                 + COALESCE(cache_read_tokens, 0)
                                 + COALESCE(cache_write_tokens, 0)
                                 + COALESCE(reasoning_tokens, 0) > 0"""
_TITLE_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique ON sessions(title) WHERE title IS NOT NULL"
)
_STALE_KEY_UPSERT_SQL = (
    "INSERT INTO state_meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)
_STATE_META_UPSERT_SQL = (
    "INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)
_CLEAR_REBUILD_MARKERS_SQL = "DELETE FROM state_meta WHERE key IN ('fts_rebuild_high_water', 'fts_rebuild_progress')"


def _legacy_inline_reinsert_sql(table: str, indent: int, *, delete_first: bool = False) -> str:
    """Legacy inline (pre-v23) FTS re-population script fragment (whitespace pinned)."""
    pad = " " * indent
    body = f"{pad}DELETE FROM {table};\n" if delete_first else ""
    return (
        f"\n{body}{pad}INSERT INTO {table}(rowid, content)\n"
        f"{pad}SELECT id,\n"
        f"{pad}       COALESCE(content, '') || ' ' ||\n"
        f"{pad}       COALESCE(tool_name, '') || ' ' ||\n"
        f"{pad}       COALESCE(tool_calls, '')\n"
        f"{pad}FROM messages;\n{pad[:-4]}"
    )


def _q(ident: str) -> str:
    """Double-quote an SQL identifier."""
    return '"' + ident.replace('"', '""') + '"'


def schema_read_probe_statements() -> tuple:
    """SELECT statements that fail iff a live store is behind SCHEMA_SQL. Read-only opens skip
    ``_reconcile_columns()`` (no DDL against another profile's live DB), so healing callers
    run these afterwards: a missing table/column raises at prepare time. Derived from
    SCHEMA_SQL (a hand-maintained list went stale within days). Columns are
    table-qualified: an unqualified double-quoted identifier that fails to resolve silently
    degrades to a string literal (SQLite misfeature) and would pass on the stale store."""
    global _READ_PROBE_STATEMENTS
    if _READ_PROBE_STATEMENTS is None:
        tables = SessionSchemaMixin._parse_schema_columns(SCHEMA_SQL)
        _READ_PROBE_STATEMENTS = tuple(
            "SELECT {} FROM {} LIMIT 0".format(", ".join(f"{_q(table)}.{_q(col)}" for col in cols), _q(table))
            for table, cols in sorted(tables.items())
        )
    return _READ_PROBE_STATEMENTS


BRIDGE_SCHEMA_SQL = """
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

_CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_NAMES = (
    "trg_claude_characterization_event_identity",
    "trg_claude_characterization_cleanup_order",
    "trg_claude_characterization_abort_order",
    "trg_claude_characterization_event_no_update",
    "trg_claude_characterization_event_no_delete",
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

_SIDEBAR_RESOLUTION_TABLES = (
    "session_sidebar_terminal_resolutions",
    "session_sidebar_precreate_resolutions",
    "session_sidebar_unbound_resolutions",
    "session_sidebar_v2_attempt_zero_resolutions",
)

class SessionSchemaMixin:
    """See module docstring — mixin for SessionDB (Schema cluster)."""

    def _dedupe_legacy_system_prompts(self, cursor: sqlite3.Cursor) -> None:
        """Move inline prompt snapshots into the shared content-addressed table. Any
        ``OperationalError`` mid-loop returns instead of raising: partial migration is safe
        (the legacy column stays a read fallback; next init resumes), whereas propagating
        left the version below 25 and re-ran this on every open (gateway crash loop)."""
        try:
            rows = cursor.execute("SELECT id, system_prompt FROM sessions WHERE system_prompt IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            return
        for session_id, prompt in rows:
            try:
                prompt_hash = self._store_system_prompt(cursor, prompt)
                cursor.execute(
                    "UPDATE sessions SET system_prompt_hash = ?, system_prompt = NULL WHERE id = ?",
                    (prompt_hash, session_id),
                )
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "v25 prompt dedupe paused after contention (%s); "
                    "unmigrated rows keep the legacy inline prompt and the next schema init resumes the migration.",
                    exc,
                )
                return

    def _sqlite_supports_fts5(self, cursor: sqlite3.Cursor) -> bool:
        try:
            cursor.execute("CREATE VIRTUAL TABLE temp._hermes_fts5_probe USING fts5(x)")
            cursor.execute("DROP TABLE temp._hermes_fts5_probe")
            return True
        except sqlite3.OperationalError as exc:
            if not self._is_fts5_unavailable_error(exc):
                raise
            self._warn_fts5_unavailable(exc)
            return False

    def _drop_all_fts_triggers(self, cursor: sqlite3.Cursor) -> None:
        self._drop_fts_triggers(cursor)
        for trigger in _FTS_CJK_TRIGGERS:
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    @staticmethod
    def _fts_triggers_missing(cursor: sqlite3.Cursor, names: Sequence[str]) -> bool:
        """True unless every trigger in *names* (one DDL half) exists."""
        if not names:
            return False  # "name IN ()" is a SQLite syntax error
        placeholders = ",".join("?" for _ in names)
        sql = f"SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})"
        return int(cursor.execute(sql, tuple(names)).fetchone()[0]) < len(names)

    @staticmethod
    def _fts_update_trigger_needs_narrowing(sql: Optional[str]) -> bool:
        """True when trigger SQL is a broad AFTER UPDATE (missing ``OF``)."""
        if not sql:
            return False
        compact = " ".join(sql.split()).upper()  # multi-line DDL still matches
        return "AFTER UPDATE OF " not in compact and "AFTER UPDATE ON " in compact

    def _migrate_broad_fts_update_triggers(self, cursor: sqlite3.Cursor) -> int:
        """Replace broad AFTER UPDATE FTS triggers with AFTER UPDATE OF variants (``IF NOT EXISTS``
        never replaces an existing broad trigger). No FTS rebuild: correctness was already
        gated by WHEN clauses; OF only skips trigger evaluation. Returns the number dropped."""
        # CJK is v23-only. Decide the layout before selecting destructive candidates so the
        # legacy branch never drops a trigger it won't recreate.
        legacy_layout = self._db_has_legacy_inline_fts(cursor)
        update_names = ("messages_fts_update", "messages_fts_trigram_update") + (
            () if legacy_layout else ("messages_fts_cjk_update",)
        )
        placeholders = ", ".join("?" for _ in update_names)
        sql = f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN ({placeholders})"
        rows = cursor.execute(sql, update_names).fetchall()
        to_drop = [name for name, sql in rows if self._fts_update_trigger_needs_narrowing(sql)]
        if not to_drop:
            return 0
        for name in to_drop:
            cursor.execute(f"DROP TRIGGER IF EXISTS {name}")  # names from the literal allowlist above

        # Re-apply current DDL (legacy vs v23 as _init_schema does) so CREATE TRIGGER installs OF variants.
        base_sql, trigram_sql = _FTS_DDL[legacy_layout]
        self._ensure_fts_schema(cursor, "messages_fts", base_sql)
        self._ensure_fts_schema(cursor, "messages_fts_trigram", trigram_sql)
        # Only recreate the CJK trigger this migration dropped. ``_ensure_fts_cjk_schema`` soft-fails
        # (never raises), so afterwards require a narrowed trigger or durable quarantine.
        if "messages_fts_cjk_update" in to_drop:
            try:
                self._ensure_fts_cjk_schema(cursor)
            except Exception:
                self._quarantine_cjk_after_update_of_migration(cursor)
                logger.exception("CJK FTS re-ensure after UPDATE OF migration failed")
                raise
            row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", ("messages_fts_cjk_update",),
            ).fetchone()
            if not row or self._fts_update_trigger_needs_narrowing(row[0]):
                self._quarantine_cjk_after_update_of_migration(cursor)
                logger.warning(
                    "CJK FTS UPDATE trigger missing or still broad after "
                    "UPDATE OF migration; marked stale and unavailable"
                )
        logger.info("Migrated %d broad FTS UPDATE trigger(s) to AFTER UPDATE OF (no rebuild required)", len(to_drop))
        return len(to_drop)

    @staticmethod
    def _stamp_fts_tool_high_water(cursor: sqlite3.Cursor) -> None:
        """Record MAX(messages.id) as the bounded-tool-content high-water mark: rows at or below it keep
        their exact stored token stream; newer tool rows index only the prefix (see ``_fts_indexed_content_sql``)."""
        high_water = cursor.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]
        cursor.execute(_STATE_META_UPSERT_SQL, (FTS_TOOL_FULL_CONTENT_HIGH_WATER_KEY, str(high_water)))

    @staticmethod
    def _execute_ddl_script_transactional(cursor: sqlite3.Cursor, ddl: str) -> None:
        """Execute a DDL script without ``executescript``'s implicit commit."""
        statement = ""
        for line in ddl.splitlines():
            statement += line + "\n"
            if sqlite3.complete_statement(statement):
                cursor.execute(statement)
                statement = ""
        if statement.strip():
            raise sqlite3.OperationalError("incomplete FTS DDL statement")

    def _migrate_bounded_tool_fts_triggers(self, cursor: sqlite3.Cursor, *, legacy: bool) -> None:
        """Replace FTS triggers without rebuilding historical indexes. Existing rows keep their
        full-content token stream; the durable high-water id makes new tool rows use the bounded
        prefix in INSERT and the matching external-content delete/update. One savepoint, so no
        concurrent writer lands in a trigger gap. A fresh store has no historical index to migrate;
        its FTS family is created later under rebuild admission."""
        if not self._sqlite_table_exists(cursor, "messages_fts"):
            return
        marker = cursor.execute(
            "SELECT 1 FROM state_meta WHERE key = ? LIMIT 1", (FTS_TOOL_FULL_CONTENT_HIGH_WATER_KEY,),
        ).fetchone()
        if marker is not None:
            return
        trigram_present = self._sqlite_table_exists(cursor, "messages_fts_trigram")
        names = _FTS_BASE_TRIGGERS + (_FTS_TRIGRAM_TRIGGERS if legacy and trigram_present else ())
        has_messages = cursor.execute("SELECT 1 FROM messages LIMIT 1").fetchone() is not None
        self._fts_tool_prefix_migration_requires_rebuild = bool(
            has_messages and self._fts_triggers_missing(cursor, names)
        )
        cursor.execute("SAVEPOINT bounded_tool_fts")
        try:
            self._stamp_fts_tool_high_water(cursor)
            for name in names:
                cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
            if legacy:
                self._execute_ddl_script_transactional(cursor, LEGACY_FTS_SQL)
                if trigram_present:
                    self._execute_ddl_script_transactional(cursor, LEGACY_FTS_TRIGRAM_SQL)
            else:
                self._execute_ddl_script_transactional(cursor, FTS_SQL)
            cursor.execute("RELEASE SAVEPOINT bounded_tool_fts")
        except BaseException:
            cursor.execute("ROLLBACK TO SAVEPOINT bounded_tool_fts")
            cursor.execute("RELEASE SAVEPOINT bounded_tool_fts")
            raise

    @staticmethod
    def _sqlite_table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
        return cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,),
        ).fetchone() is not None

    def _migrate_trigram_cron_exclusion(self, cursor: sqlite3.Cursor) -> bool:
        """Install the source-filtered trigram view and purge historical rows (v29 cron exclusion,
        v30 subagent exclusion: both only change the view/trigger predicate and rebuild from it).
        Legacy inline indexes stay opt-in (their content is private to the vtable). A v1 external
        layout whose vtable still declares ``tool_calls`` is left to ``optimize-storage``: swapping
        the view underneath would make 'rebuild' read a column the view no longer has. Otherwise
        the inverted index still holds excluded rows until FTS5 rebuilds from the new view, which
        runs under the shared cross-process admission gate. Returns False to hold schema_version back."""
        if self._db_has_legacy_inline_fts(cursor) or self._db_has_trigram_tool_calls_projection(cursor):
            return True
        trigram_exists = self._fts_table_probe(cursor, "messages_fts_trigram")
        if trigram_exists is not True:
            # Absent: the normal ensure path creates/backfills it. None: this runtime cannot
            # safely inspect an existing one, so leave the version behind for retry.
            return trigram_exists is False
        for name in _FTS_TRIGRAM_TRIGGERS:
            cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        cursor.execute("DROP VIEW IF EXISTS messages_fts_trigram_src")
        if not self._ensure_fts_schema(cursor, "messages_fts_trigram", FTS_TRIGRAM_SQL):
            return False
        # Always rebuild while schema_version is behind, even if the view already has the new
        # predicate: a process can die between replacing the view and rebuilding/stamping.
        self._run_admitted_startup_rebuild(
            cursor,
            lambda: cursor.execute("INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('rebuild')"),
        )
        return True

    def _quarantine_cjk_after_update_of_migration(self, cursor: sqlite3.Cursor) -> None:
        """Fail closed after dropping the CJK UPDATE trigger mid-migration: clear availability,
        persist ``fts_cjk_stale``, drop any residual trigger so a later open cannot
        IF-NOT-EXISTS over a gap."""
        self._fts_cjk_available = False
        try:
            self.set_meta(FTS_CJK_STALE_KEY, "1", cursor=cursor)
        except Exception:
            logger.debug("Could not persist CJK FTS stale breadcrumb", exc_info=True)
        try:
            cursor.execute("DROP TRIGGER IF EXISTS messages_fts_cjk_update")
        except Exception:
            logger.debug("Could not drop residual CJK UPDATE trigger after quarantine", exc_info=True)

    @staticmethod
    def _rebuild_fts_indexes(cursor: sqlite3.Cursor, *, legacy: bool = False, include_trigram: bool = True) -> None:
        """v23+ external-content 'rebuild'. It indexes EVERY row, so the deferred-backfill
        markers are cleared or the worker would re-insert covered rows (duplicates).
        ``legacy`` (pre-v23 inline layout) has no external-content 'rebuild' source, so it
        DELETEs + reinserts the concatenated content the legacy triggers produced."""
        SessionSchemaMixin._stamp_fts_tool_high_water(cursor)
        tables = ("messages_fts", "messages_fts_trigram") if include_trigram else ("messages_fts",)
        for tbl in tables:
            if legacy:
                cursor.execute(f"DELETE FROM {tbl}")
                cursor.execute(f"INSERT INTO {tbl}(rowid, content) SELECT id, {_LEGACY_INLINE_CONCAT_SQL}FROM messages")
            else:
                cursor.execute(f"INSERT INTO {tbl}({tbl}) VALUES('rebuild')")
        if not legacy:
            cursor.execute(_CLEAR_REBUILD_MARKERS_SQL)

    def _fts_table_probe(self, cursor: sqlite3.Cursor, table_name: str) -> Optional[bool]:
        """True = queryable, False = absent, None = FTS module/tokenizer missing or content
        undecodable (index degraded, store accessible). Invalid UTF-8 surfaces as a bare
        UnicodeDecodeError on some builds and OperationalError("Could not decode to UTF-8")
        on others; both are caught so the probe never raises into init/recovery flows.
        Anything else (malformed schema, corrupt vtable) re-raises."""
        try:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
            return True
        except UnicodeDecodeError as exc:
            decode_exc = exc
        except sqlite3.OperationalError as exc:
            if self._is_fts5_unavailable_error(exc):
                # A missing trigram tokenizer only affects trigram search; only a missing
                # FTS5 module disables FTS entirely.
                if self._is_trigram_unavailable_error(exc):
                    self._warn_trigram_unavailable(exc)
                else:
                    self._warn_fts5_unavailable(exc)
                return None
            if "no such table" in str(exc).lower():
                return False
            if "decode to utf-8" not in str(exc).lower():
                raise
            decode_exc = exc
        logger.warning(
            "%s probe encountered invalid UTF-8 in FTS content; "
            "search may return incomplete results until FTS is rebuilt: %s", table_name, decode_exc,
        )
        return None

    # ── Stale-FTS recovery ─────────────────────────────────────────────────

    def _defer_stale_fts_for_holders(self, cursor: sqlite3.Cursor, foreign_holders) -> bool:
        """Record a deferral diagnostic for the foreign processes holding the DB; True = defer
        (holders remain). After ``_FTS_HOLDER_ESCALATE_ATTEMPTS`` deferrals spanning
        ``_FTS_HOLDER_ESCALATE_SECONDS``, provably inactive orphan Desktop backends are
        reaped and the holders re-checked. The orphan reap is the only exit, so a supervised
        peer (never an orphan) blocks forever: once the SAME PID set has blocked
        ``_FTS_HOLDER_FUTILE_ATTEMPTS`` deferrals over ``_FTS_HOLDER_FUTILE_SECONDS`` the
        record is marked ``futile`` and the escalation names the holders and the remedy that
        works from inside a gateway session (stop only the other holder; this process's own
        retry tick admits the rebuild). A changed holder set restarts that window."""
        now = time.time()
        try:
            row = cursor.execute(
                "SELECT value FROM state_meta WHERE key = ? LIMIT 1", (FTS_REBUILD_DEFERRAL_KEY,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        parsed = safe_json_loads(row[0]) if row else None
        record = parsed if isinstance(parsed, dict) else {}
        try:
            first_seen = float(record.get("first_seen", now))
            attempts = int(record.get("attempts", 0)) + 1
            holders_since = float(record.get("holders_since", now))
            holders_attempts = int(record.get("holders_attempts", 0)) + 1
        except (TypeError, ValueError):
            first_seen, attempts, holders_since, holders_attempts = now, 1, now, 1
        if first_seen > now or first_seen < 0:
            first_seen = now
        holder_pids = sorted({pid for pid, _path in foreign_holders if pid > 0})
        if holder_pids != record.get("holder_pids"):
            holders_since, holders_attempts = now, 1
        if attempts >= _FTS_HOLDER_ESCALATE_ATTEMPTS and now - first_seen >= _FTS_HOLDER_ESCALATE_SECONDS:
            reaped = self._reap_inactive_orphan_desktop_holders(
                foreign_holders, min_age_seconds=_FTS_HOLDER_ESCALATE_SECONDS,
            )
            if reaped:
                logger.error(
                    "Reaped inactive orphan Desktop backend(s) %s after %d "
                    "state.db FTS rebuild deferrals; checking holders again.", reaped, attempts,
                )
                foreign_holders = self._foreign_state_db_holders()
                holder_pids = sorted({pid for pid, _path in foreign_holders if pid > 0})
        futile = bool(holder_pids) and (
            holders_attempts >= _FTS_HOLDER_FUTILE_ATTEMPTS and now - holders_since >= _FTS_HOLDER_FUTILE_SECONDS
        )
        diagnostic = {
            "first_seen": first_seen, "last_seen": now, "attempts": attempts, "holder_pids": holder_pids,
            "holders_since": holders_since, "holders_attempts": holders_attempts, "futile": futile,
        }
        cursor.execute(
            "INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (FTS_REBUILD_DEFERRAL_KEY, json.dumps(diagnostic, sort_keys=True)),
        )
        if not foreign_holders:
            self._fts_deferred_holder_pids = None
            return False
        self._fts_deferred_holder_pids = holder_pids
        if futile:
            logger.error(
                "state.db FTS repair has been blocked by the same holder(s) for %d deferrals over %.0f min "
                "(%s); waiting is futile. Stop ONLY the other holder(s) — this process keeps running and its "
                "own retry admits the rebuild within %.0fs of the holder leaving. `hermes doctor` shows this.",
                holders_attempts, (now - holders_since) / 60.0,
                ", ".join(f"pid {pid}: {_holder_cmdline(pid)}" for pid in holder_pids), _FTS_STALE_RETRY_SECONDS,
            )
        elif attempts >= _FTS_HOLDER_ESCALATE_ATTEMPTS and now - first_seen >= _FTS_HOLDER_ESCALATE_SECONDS:
            logger.error(
                "state.db FTS repair remains blocked after %d deferrals by holder(s) %s. Stop the listed "
                "processes (this process's own retry then rebuilds), or run `hermes sessions optimize-storage` "
                "with every holder stopped. `hermes doctor` reports this degraded state.", attempts, foreign_holders,
            )
        logger.warning(
            "Deferred stale state.db FTS rebuild while foreign processes "
            "hold the database or WAL sidecars (%s); canonical writes and LIKE search remain available (deferral %d).",
            foreign_holders, attempts,
        )
        return True

    def _recover_stale_fts(self, cursor: sqlite3.Cursor, *, legacy: bool, timeout_seconds=None) -> bool:
        """Atomically rebuild stale base/trigram indexes and resume syncing. *timeout_seconds*
        bounds the admission wait (None = full startup budget, ``0`` = non-blocking retry).
        Fails closed: holders or a lost admission race leave the breadcrumb set."""
        foreign_holders = self._foreign_state_db_holders()
        if foreign_holders and self._defer_stale_fts_for_holders(cursor, foreign_holders):
            return False
        with fts_rebuild_admission(self.db_path, timeout_seconds=timeout_seconds) as admitted:
            if not admitted:
                logger.warning(
                    "Deferred stale state.db FTS rebuild: another process holds the rebuild authority; "
                    "canonical writes and LIKE search remain available."
                )
                return False
            return self._recover_stale_fts_locked(cursor, legacy=legacy)

    def retry_deferred_fts_recovery(self) -> bool:
        """Retry a deferred stale-FTS rebuild (gateway housekeeping tick). ``_recover_stale_fts``
        fails closed at open, leaving search on LIKE; live write/search paths must never
        start a full rebuild, and a gateway opens state.db once for days, so "next open"
        never comes. Bounded doubling backoff, non-blocking admission, no new thread. True
        only when the index was rebuilt and sync triggers restored. Never raises.

        This is the in-process retry: bounded backoff from ``_FTS_STALE_RETRY_SECONDS`` doubling to
        ``_FTS_STALE_RETRY_MAX_SECONDS``, non-blocking admission (``timeout=0``) so a live holder is skipped
        and tried again later, no new thread — the caller is an existing periodic tick (gateway
        housekeeping). See #100108, #97940.
        """
        if not self._fts_stale:
            return False
        if self._quarantine_reason() is not None:
            # Quarantined: never run FTS DDL/DML against a damaged image or a stale/replaced generation
            # (mirrors _try_wal_checkpoint / close). Reset the backoff so a future un-quarantine starts
            # from the default interval.
            self._fts_stale_retry_after = 0.0
            self._fts_stale_retry_interval = 0.0
            return False
        if self.read_only or self._conn is None:
            return False
        now = time.monotonic()
        deferred_pids = getattr(self, "_fts_deferred_holder_pids", None)
        if now < getattr(self, "_fts_stale_retry_after", 0.0):
            # The backoff was earned by a specific holder set; once that set changes (the other
            # service stopped) a capped backoff would idle up to an hour with nothing blocking (#106393).
            if deferred_pids is None or sorted(
                {pid for pid, _path in self._foreign_state_db_holders() if pid > 0}
            ) == deferred_pids:
                return False
            self._fts_stale_retry_interval = 0.0
        interval = float(getattr(self, "_fts_stale_retry_interval", 0.0))
        if interval <= 0.0:
            interval = _FTS_STALE_RETRY_SECONDS
        self._fts_stale_retry_after = now + interval
        self._fts_stale_retry_interval = min(
            max(interval, _FTS_STALE_RETRY_SECONDS, 1.0) * 2.0, _FTS_STALE_RETRY_MAX_SECONDS,
        )
        try:
            with self._lock:
                if self._conn is None or not self._fts_stale:
                    return False
                cursor = self._conn.cursor()
                legacy = self._db_has_legacy_inline_fts(cursor)
                recovered = self._recover_stale_fts(cursor, legacy=legacy, timeout_seconds=0.0)
                if recovered:
                    # CJK was detached alongside the base indexes; its own ensure path
                    # decides when it comes back online.
                    self._ensure_fts_cjk_schema(cursor)
                    self._fts_stale_retry_interval = 0.0
                with contextlib.suppress(sqlite3.Error):
                    self._conn.commit()
                return recovered
        except Exception:  # noqa: BLE001 - background retry must never raise
            logger.warning(
                "In-process retry of the deferred stale state.db FTS rebuild failed; will retry later.", exc_info=True,
            )
            return False

    def _recover_stale_fts_locked(self, cursor: sqlite3.Cursor, *, legacy: bool) -> bool:
        """Body of :meth:`_recover_stale_fts`; caller holds rebuild authority. One write
        transaction, so no canonical writer slips between rebuild and trigger restoration."""
        try:
            trigram_present = self._fts_table_probe(cursor, "messages_fts_trigram") is True
        except (sqlite3.DatabaseError, UnicodeDecodeError):
            # A corrupt vtable may fail even a LIMIT 0 probe; still include it in the drop-and-recreate.
            include_trigram = True
        else:
            include_trigram = trigram_present or (not legacy and self._trigram_tokenizer_available(cursor))

        drop_sql = "".join(f"DROP TRIGGER IF EXISTS {trigger};" for trigger in _FTS_TRIGGERS)
        if include_trigram:
            drop_sql += "DROP TABLE IF EXISTS messages_fts_trigram;"
        drop_sql += "DROP VIEW IF EXISTS messages_fts_trigram_src;DROP TABLE IF EXISTS messages_fts;"
        if legacy:
            rebuild_sql = LEGACY_FTS_SQL + (LEGACY_FTS_TRIGRAM_SQL if include_trigram else "")
            rebuild_sql += _legacy_inline_reinsert_sql("messages_fts", 16)
            if include_trigram:
                rebuild_sql += _legacy_inline_reinsert_sql("messages_fts_trigram", 20, delete_first=True)
        else:
            rebuild_sql = FTS_SQL + (FTS_TRIGRAM_SQL if include_trigram else "")
            rebuild_sql += "INSERT INTO messages_fts(messages_fts) VALUES('rebuild');"
            if include_trigram:
                rebuild_sql += "INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('rebuild');"
            rebuild_sql += _CLEAR_REBUILD_MARKERS_SQL + ";"
        recovery_sql = (
            "BEGIN IMMEDIATE;" + drop_sql + rebuild_sql
            + f"DELETE FROM state_meta WHERE key IN ('{FTS_STALE_KEY}', '{FTS_REBUILD_DEFERRAL_KEY}');COMMIT;"
        )
        try:
            cursor.executescript(recovery_sql)
        except sqlite3.DatabaseError as exc:
            with contextlib.suppress(sqlite3.Error):
                self._conn.rollback()
            # Stale indexes must stay detached even on builds whose DDL transaction behavior differs.
            self._drop_all_fts_triggers(cursor)
            self._conn.commit()
            logger.error(
                "Automatic rebuild of stale FTS indexes failed (%s); "
                "canonical writes remain enabled with FTS detached.", exc,
            )
            return False
        self._fts_stale = False
        self._fts_enabled = True
        self._trigram_available = include_trigram
        logger.warning("Rebuilt stale state.db FTS indexes from canonical messages and restored sync triggers.")
        return True

    def _trigram_tokenizer_available(self, cursor: sqlite3.Cursor) -> bool:
        """Probe trigram support without publishing a persistent FTS object."""
        probe = "temp.hermes_fts5_trigram_probe"
        cursor.execute(f"DROP TABLE IF EXISTS {probe}")
        try:
            cursor.execute(f"CREATE VIRTUAL TABLE {probe} USING fts5(content, tokenize='trigram')")
        except sqlite3.OperationalError as exc:
            if not self._is_trigram_unavailable_error(exc):
                raise
            self._warn_trigram_unavailable(exc)
            return False
        finally:
            cursor.execute(f"DROP TABLE IF EXISTS {probe}")
        return True

    # ── Declarative column reconciliation ──────────────────────────────────

    @staticmethod
    def _parse_schema_columns(schema_sql: str) -> Dict[str, Dict[str, str]]:
        """Expected columns per table: execute SCHEMA_SQL in an in-memory database and read
        PRAGMA table_info (no regex). Memoized on disk keyed by a DDL hash (~85ms per
        startup otherwise); only the reference-side parse is cached — diffing the LIVE
        database still runs every startup. A corrupt/stale cache degrades to recomputation."""
        cache_path = None
        schema_hash = hashlib.sha256(schema_sql.encode("utf-8")).hexdigest()
        with contextlib.suppress(Exception):  # missing/corrupt cache → recompute below
            # Late import: resolves a test-patched hermes_constants.get_hermes_home.
            from hermes_constants import get_hermes_home as _home
            cache_path = _home() / "cache" / "schema_columns.json"
            blob = json.loads(cache_path.read_text(encoding="utf-8"))
            tables = blob.get("tables") if isinstance(blob, dict) and blob.get("schema_hash") == schema_hash else None
            if isinstance(tables, dict) and all(
                isinstance(cols, dict) and all(isinstance(v, str) for v in cols.values()) for cols in tables.values()
            ):
                return tables

        ref = sqlite3.connect(":memory:")
        try:
            ref.executescript(schema_sql)
            table_columns: Dict[str, Dict[str, str]] = {}
            for (tbl,) in ref.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall():
                cols: Dict[str, str] = {}
                info = ref.execute(f'PRAGMA table_info("{tbl}")').fetchall()
                for _cid, col_name, col_type, notnull, default, pk in info:
                    # Reconstruct the type expression for ALTER TABLE ADD COLUMN
                    parts = [col_type] if col_type else []
                    if notnull and not pk:
                        parts.append("NOT NULL")
                    if default is not None:
                        parts.append(f"DEFAULT {default}")
                    cols[col_name] = " ".join(parts)
                table_columns[tbl] = cols
        finally:
            ref.close()

        if cache_path is not None:
            with contextlib.suppress(Exception):  # cache write is best-effort
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(cache_path.parent), prefix=".schema_columns.")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"schema_hash": schema_hash, "tables": table_columns}, fh)
                os.replace(tmp, cache_path)
        return table_columns

    def _reconcile_columns(self, cursor: sqlite3.Cursor) -> None:
        """ADD every declared column missing from the live CORE and BRIDGE tables.

        Two schemas, one loop. BRIDGE_SCHEMA_SQL is reconciled on the same terms as SCHEMA_SQL:
        without it, adding a column to a bridge table is silently a no-op on every existing
        database, which is the failure the declarative reconciler exists to prevent.

        The fork extracted this same split, but around the OLDER loop body — the one that
        swallowed lock contention and left the store half-reconciled ("no such column" on every
        read). Generalising upstream's body instead keeps its error taxonomy for both schemas.
        """
        self._reconcile_columns_from_sql(cursor, SCHEMA_SQL)
        self._reconcile_columns_from_sql(cursor, BRIDGE_SCHEMA_SQL)

    def _reconcile_columns_from_sql(self, cursor: sqlite3.Cursor, schema_sql: str) -> None:
        """ADD every column *schema_sql* declares that the live tables lack."""
        expected = self._parse_schema_columns(schema_sql)
        for table_name, declared_cols in expected.items():
            try:
                rows = cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            except sqlite3.OperationalError:
                continue  # Table doesn't exist yet (shouldn't happen after executescript)
            # PRAGMA table_info rows: (cid, name, type, notnull, dflt_value, pk)
            live_cols = {row[1] for row in rows}
            for col_name, col_type in declared_cols.items():
                if col_name in live_cols:
                    continue
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(col_name)} {col_type}')
                except sqlite3.OperationalError as exc:
                    message = str(exc).lower()
                    if "duplicate column" in message:
                        # A sibling process won the ADD race; store is correct.
                        logger.debug("reconcile %s.%s: %s", table_name, col_name, exc)
                        continue
                    if "locked" in message or "busy" in message:
                        # Swallowing lock contention left the store half-reconciled ("no such
                        # column" on every read). Re-raise so the lock-patience wrapper retries init.
                        raise
                    # Anything else permanently strands the store behind SCHEMA_SQL — be loud.
                    logger.warning(
                        "reconcile %s.%s failed; store remains behind SCHEMA_SQL: %s", table_name, col_name, exc,
                    )

    @staticmethod
    def _live_pk_columns(cursor: sqlite3.Cursor, table: str) -> Optional[List[str]]:
        """PRIMARY KEY column names of *table* in key order; None when the table is
        missing or has no columns (SCHEMA_SQL creates it correctly)."""
        try:
            rows = cursor.execute(f'PRAGMA table_info("{table}")').fetchall()
        except sqlite3.OperationalError:
            rows = None
        if not rows:
            return None
        # row: (cid, name, type, notnull, dflt_value, pk)
        return [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: r[5])]

    @staticmethod
    def _rebuild_table(cursor: sqlite3.Cursor, table: str, legacy_name: str, ddl: str, copy_sql: str, indexes=()) -> None:
        """RENAME *table* to *legacy_name*, CREATE it fresh from *ddl*, copy rows back with
        *copy_sql*, DROP the legacy copy, recreate *indexes*."""
        cursor.execute(f"ALTER TABLE {table} RENAME TO {legacy_name}")
        cursor.execute(ddl)
        cursor.execute(copy_sql)
        cursor.execute(f"DROP TABLE {legacy_name}")
        for sql in indexes:
            cursor.execute(sql)

    def _heal_gateway_routing_pk(self, cursor: sqlite3.Cursor) -> None:
        """Rebuild ``gateway_routing`` when its PRIMARY KEY predates scoping (``session_key TEXT
        PRIMARY KEY``): the reconciler ADDs ``scope`` but SQLite cannot ALTER a PK, so every
        routing write fails (ON CONFLICT mismatch / cross-scope UNIQUE violation). Newest
        row wins a cross-scope session_key collision (INSERT OR REPLACE in updated_at order).

        Early builds of the routing-index migration (#59203) created the table with ``session_key TEXT
        PRIMARY KEY`` and no ``scope`` column. ``_reconcile_columns()`` ADDs the missing ``scope`` column on
        those databases, but SQLite cannot ALTER a primary key, so the shipped composite ``PRIMARY KEY
        (scope, session_key)`` never lands. On such tables every write path is broken:
        """
        pk_cols = self._live_pk_columns(cursor, "gateway_routing")
        if pk_cols is None or pk_cols == ["scope", "session_key"]:
            return
        logger.info(
            "gateway_routing has legacy primary key %r; rebuilding with composite (scope, session_key) key", pk_cols,
        )
        self._rebuild_table(
            cursor, "gateway_routing", "gateway_routing_legacy_pk",
            """CREATE TABLE gateway_routing (
    scope TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (scope, session_key)
)""",
            "INSERT OR REPLACE INTO gateway_routing (scope, session_key, entry_json, updated_at) "
            "SELECT COALESCE(scope, ''), session_key, entry_json, updated_at "
            "FROM gateway_routing_legacy_pk ORDER BY updated_at ASC",
        )

    def _heal_session_model_usage_pk(self, cursor: sqlite3.Cursor) -> None:
        """Rebuild ``session_model_usage`` when its PRIMARY KEY lacks ``task``: installs already at
        v22+ when ``task`` landed carry the 5-column PK, the reconciler ADDs ``task`` but
        SQLite cannot ALTER a PK, and the v22 rebuild is unreachable — every upsert then
        fails (ON CONFLICT mismatch), silently zeroing accounting. Idempotent. FK-off
        window: INSERT OR IGNORE does NOT suppress FK violations, so an orphaned usage row
        would abort the rebuild (PRAGMA foreign_keys is a no-op inside a transaction; none
        is open here). OR IGNORE: COALESCE(task, '') on legacy NULL rows can collide with a
        genuine ''-task row — keep the first.

        Installs whose ``state.db`` reached ``schema_version >= 22`` before the ``task`` dimension was added
        carry a 5-column PRIMARY KEY ``(session_id, model, billing_provider, billing_base_url,
        billing_mode)``. See #73823.
        """
        pk_cols = self._live_pk_columns(cursor, "session_model_usage")
        if pk_cols is None or "task" in pk_cols:
            return
        logger.info(
            "session_model_usage has legacy primary key %r (missing task); rebuilding with composite 6-column key",
            sorted(pk_cols),
        )
        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            self._rebuild_table(
                cursor, "session_model_usage", "session_model_usage_legacy_pk", _SESSION_MODEL_USAGE_HEAL_DDL,
                # v20: per-model usage attribution (issue #51607). Going forward update_token_counts()
                # records each API call into session_model_usage keyed by the live model, but existing
                # sessions only have their aggregate totals on the sessions row. Seed one usage row per
                # historical session from those aggregates so insights reads uniformly from the new table.
                # INSERT OR IGNORE keeps it idempotent: if newer code already wrote a (session_id, model,
                # provider) row for a session, the PK conflict skips the stale aggregate rather than
                # doubling it.
                """INSERT OR IGNORE INTO session_model_usage (
                       session_id, model, billing_provider, billing_base_url,
                       billing_mode, task, api_call_count, input_tokens,
                       output_tokens, cache_read_tokens, cache_write_tokens,
                       reasoning_tokens, estimated_cost_usd, actual_cost_usd,
                       cost_status, cost_source, first_seen, last_seen
                   )
                   SELECT session_id, model,
                          COALESCE(billing_provider, ''),
                          COALESCE(billing_base_url, ''),
                          COALESCE(billing_mode, ''),
                          COALESCE(task, ''),
                          api_call_count, input_tokens,
                          output_tokens, cache_read_tokens, cache_write_tokens,
                          reasoning_tokens, estimated_cost_usd, actual_cost_usd,
                          cost_status, cost_source, first_seen, last_seen
                   FROM session_model_usage_legacy_pk""",
                _SESSION_MODEL_USAGE_INDEX_SQL,
            )
        except sqlite3.OperationalError as exc:
            logger.debug("session_model_usage PK heal skipped: %s", exc)
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")

    # ── _init_schema ───────────────────────────────────────────────────────

    def _init_schema(self):
        """Create tables and FTS if missing, reconcile columns, run data migrations. Column
        additions are declarative via _reconcile_columns(), so reordered migrations can
        never skip a column; schema_version remains for data migrations only."""
        # Startup-watchdog lease: on multi-GB files this is I/O-bound (near-zero CPU), which
        # the watchdog's CPU fallback would misread as a parked deadlock.
        # Declare a startup-watchdog progress lease before potentially long synchronous work: on multi-GB
        # state.db files the reconciliation + version-gated data migrations below are legitimately slow and
        # can be I/O-bound (near-zero CPU), which the watchdog's CPU fallback would misread as a parked
        # deadlock (OOF-298 / PR #89750). Single lease is deliberate: this is the one pre-loop phase that
        # can legitimately exceed the 300s default deadline (multi-GB DBs), and the lease is clamped to
        # _MAX_LEASE_S=900. Honest worst case: a genuinely wedged DB init delays supervisor respawn by up to
        # the lease duration. Per-chunk renewal would shrink that, but adds complexity to the migration
        # loops for a rare failure mode.
        report_startup_progress(600.0, phase="state_db_init_schema")
        cursor = self._conn.cursor()
        cursor.executescript(SCHEMA_SQL)

        # Bridge DDL as ONE transaction. ``executescript`` commits before running its SQL, so
        # without an explicit BEGIN a partial failure would leave a database carrying some of
        # the additive bridge objects and not others; this keeps it all-or-nothing.
        #
        # This is also the one write lock every open still takes on a fully-initialised
        # database (the migrations below short-circuit lock-free once applied). The DDL is
        # idempotent (CREATE ... IF NOT EXISTS), so on transient session-bridge write
        # contention we roll back and retry rather than let a momentary `database is locked`
        # propagate and blank a read caller's session list (2026-08-07 incident).
        #
        # Retry uses upstream's deadline model, not the fork's fixed _WRITE_MAX_RETRIES count,
        # which no longer exists.
        _bridge_patience = self._WRITE_PATIENCE_S
        _bridge_deadline = time.monotonic() + _bridge_patience
        while True:
            try:
                cursor.executescript("BEGIN IMMEDIATE;" + NEWLINE + BRIDGE_SCHEMA_SQL + NEWLINE + "COMMIT;")
                break
            except sqlite3.OperationalError as exc:
                if self._conn.in_transaction:
                    self._conn.rollback()
                _m = str(exc).lower()
                if ("locked" in _m or "busy" in _m) and self._sleep_before_write_retry(
                    _bridge_deadline, _bridge_patience
                ):
                    continue
                raise
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

        # c214 created this table before its durable call-start checkpoint. Upgrade that exact
        # shape BEFORE generic reconciliation so the migration stays explicit and auditable
        # rather than being silently absorbed by the column reconciler.
        self._apply_claude_auth_recovery_call_started_migration(cursor)
        # Column reconciliation, then the two table-shape repairs ADD COLUMN cannot express.
        self._reconcile_columns(cursor)
        self._heal_gateway_routing_pk(cursor)
        # Rebuild session_model_usage if its PRIMARY KEY lacks the ``task`` column (5-column PK on installs
        # already at v22+ when the column landed — the version-gated rebuild is unreachable there, #73823).
        # Same PK-rebuild constraint as gateway_routing above.
        self._heal_session_model_usage_pk(cursor)

        # Bridge security migrations carry their own durable ledger. They run after
        # bridge-column reconciliation and the PK heals above, and must not wait for FTS.
        self._apply_bridge_migrations(cursor)
        self._apply_claude_characterization_abort_trigger_migration(cursor)
        self._apply_claude_characterization_events_v28_migration(cursor)
        self._apply_claude_characterization_event_orphan_quarantine_migration(cursor)
        self._apply_sidebar_resolution_orphan_quarantine_migration(cursor)
        self._apply_sidebar_reconciliation_proof_orphan_quarantine_migration(cursor)

        # Indexes referencing reconciler-added columns must be created AFTER _reconcile_columns
        # (in SCHEMA_SQL the executescript would fail on legacy DBs).
        # Heal NULL ``active`` rows unconditionally on every startup. On real-world DBs the reconciler-added
        # ``active`` column can lack its NOT NULL DEFAULT 1 (older reconciler builds reconstructed the type
        # without the default — see #51646: PRAGMA shows (17,'active','INTEGER',0,None,0) in the wild), so
        # INSERTs that omitted the column wrote NULL and the ``WHERE active = 1`` transcript loaders hid the
        # whole history. The INSERTs now set active=1 explicitly; this idempotent repair un-hides rows
        # written before the fix. It was previously gated at ``current_version < 12`` which never re-ran for
        # already-v12+ databases.
        try:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_platform_msg_id "
                "ON messages(session_id, platform_message_id) WHERE platform_message_id IS NOT NULL"
            )
        except sqlite3.OperationalError as exc:
            logger.debug("idx_messages_platform_msg_id create skipped: %s", exc)

        # Makes a re-ingest structurally unable to append a second copy of an event this
        # session already stores. PARTIAL, so the ~5% of rows with no external identity (and
        # every non-ingested row) are exempt rather than colliding on NULL. IntegrityError is
        # caught alongside OperationalError deliberately: a database still carrying duplicates
        # must keep opening rather than fail startup — the index simply stays absent until
        # they are cleared.
        try:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_native_event_key "
                "ON messages(session_id, native_event_key) "
                "WHERE native_event_key IS NOT NULL"
            )
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            logger.warning(
                "idx_messages_native_event_key not created (%s) — duplicate "
                "external events may exist in this database.", exc
            )
        cursor.executescript(DEFERRED_INDEX_SQL)  # same ordering constraint (``active``)

        # Heal NULL ``active`` rows on every startup: older reconciler builds added ``active``
        # without NOT NULL DEFAULT 1, so ``WHERE active = 1`` loaders hid whole histories. A
        # ``current_version < 12`` gate never re-ran for already-v12+ databases.
        with contextlib.suppress(sqlite3.OperationalError):
            cursor.execute("UPDATE messages SET active = 1 WHERE active IS NULL")

        fts5_available = self._sqlite_supports_fts5(cursor)
        stale_row = cursor.execute("SELECT 1 FROM state_meta WHERE key = ? LIMIT 1", (FTS_STALE_KEY,)).fetchone()
        self._fts_stale = stale_row is not None
        if self._fts_stale:
            # A prior process detached FTS after corruption; stay detached until a full rebuild.
            self._drop_all_fts_triggers(cursor)
        if not fts5_available:
            # Existing FTS triggers would still fire though this runtime cannot read their
            # targets. Drop only the triggers; a future FTS5 runtime recreates them.
            self._drop_fts_triggers(cursor)

        row = cursor.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            # Store provenance so fresh vs wiped stores are distinguishable.
            # See #97568.
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cursor.executemany(
                "INSERT OR IGNORE INTO state_meta (key, value) VALUES (?, ?)",
                [("store_instance_id", str(uuid.uuid4())), ("store_created_at_utc", now_iso)],
            )
        else:
            self._run_data_migrations(cursor, row[0], fts5_available)

        self._ensure_unique_title_index(cursor)
        if fts5_available:
            self._init_fts(cursor)
        self._conn.commit()

    def _run_data_migrations(self, cursor: sqlite3.Cursor, current_version: int, fts5_available: bool) -> None:
        """Version-gated chain for DATA migrations only (row backfills); column additions never
        belong here. Advances schema_version at the end unless FTS5 is unavailable."""
        # Renew the lease: the chain can rewrite whole tables on large DBs.
        report_startup_progress(600.0, phase="state_db_data_migrations")
        # (v10 trigram backfill and v11 inline FTS re-index were superseded by v23 and removed.)
        # v11 (SUPERSEDED by v23): re-index FTS5 tables to cover tool_name + tool_calls in inline mode
        # (#16751). v23 drops and rebuilds both FTS tables in external-content form, so running the v11
        # inline backfill first would only burn startup time and WAL space before v23 throws the work away —
        # and its inline INSERT shape no longer matches the current external-content FTS_SQL anyway. Kept
        # only for source archaeology; unreachable while SCHEMA_VERSION >= 23.
        if current_version < 16:
            # v16: tag delegate subagent rows so pickers stay clean after parent deletes orphan them.
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(
                    "UPDATE sessions SET model_config = json_set("
                    "COALESCE(model_config, '{}'), '$._delegate_from', parent_session_id) "
                    f"WHERE parent_session_id IS NOT NULL "
                    "AND json_extract(COALESCE(model_config, '{}'), '$._delegate_from') IS NULL "
                    f"AND {_ephemeral_child_sql('sessions')}"
                )
                cursor.execute(
                    "UPDATE sessions SET model_config = json_set("
                    "COALESCE(model_config, '{}'), '$._delegate_from', '__orphaned__') WHERE parent_session_id IS NULL "
                    "AND json_extract(COALESCE(model_config, '{}'), '$._delegate_from') IS NULL "
                    "AND json_extract(COALESCE(model_config, '{}'), '$._branched_from') IS NULL "
                    "AND title IS NULL AND message_count <= 25 AND EXISTS (SELECT 1 FROM messages m "
                    "            WHERE m.session_id = sessions.id AND m.role = 'tool') "
                    "AND NOT EXISTS (SELECT 1 FROM sessions ch "
                    "                WHERE ch.parent_session_id = sessions.id)"
                )
        if current_version < 18:
            # v18: best-effort gateway metadata backfill from sessions.json.
            try:
                # Backfill display_name / origin_json / expiry_finalized from sessions.json so pre-migration
                # gateway sessions are discoverable from state.db without the JSON index. See #9006.
                self._backfill_gateway_metadata_from_sessions_json(cursor)
            except Exception as exc:
                logger.debug("v18 gateway metadata backfill skipped: %s", exc)
        if current_version < 20:
            # v20: seed session_model_usage from sessions aggregates (OR IGNORE: newer rows win).
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(_SESSION_MODEL_USAGE_V20_SEED_SQL)
        if current_version < 22:
            self._migrate_v22_session_model_usage(cursor)
        # v23: FTS storage redesign (external-content tables). OPT-IN, NOT AUTOMATIC: the
        # transition is disk-heavy (~2x transient) and long (hours on 25 GB), so an existing
        # install only gets a flag; `hermes sessions optimize-storage` performs it. The FTS
        # layout is tracked by the independent `fts_storage_version` marker, so
        # schema_version still advances for legacy-FTS users.
        if current_version < 23 and fts5_available and self._db_needs_fts_storage_upgrade(cursor):
            self.set_meta("fts_optimize_available", "1", cursor=cursor)
        if current_version < 25:
            # v25: de-duplicate system prompt snapshots (old column stays a read fallback).
            self._dedupe_legacy_system_prompts(cursor)
        fts_migrations_complete = True
        if current_version < 30 and fts5_available:
            # v29: cron sessions leave the trigram substring index (they stay in the word index);
            # v30: delegate-child transcripts too (FTS_TRIGRAM_EXCLUDED_SOURCES + _delegate_from).
            # Rebuild once so rows indexed by older view/trigger definitions do not linger.
            fts_migrations_complete = self._migrate_trigram_cron_exclusion(cursor)

        # Compensating gate for the two schema-version lineages (0.21.1 merge).
        #
        # This fork's numbering ran AHEAD of upstream's: its gates were renumbered to 29 at
        # the 0.19.0 merge and it then added 32 and 33, so an existing fork database is
        # stamped 33 (verified on the live state.db) while upstream's newest gate above is
        # 30. Every ``current_version < 23|25|30`` test is therefore False forever on such a
        # database and the three migrations above simply never run — silently, since a gate
        # that is never true raises nothing. Concretely they would lose: the
        # ``fts_optimize_available`` advertisement (v23), the legacy system-prompt dedupe
        # (v25), and — the big one — the trigram rebuild that drops cron and delegate-child
        # transcripts from the substring index (v29/v30).
        #
        # Same shape as the bug upstream fixed just above, where the ``active IS NULL``
        # repair 'was previously gated at current_version < 12 which never re-ran for
        # already-v12+ databases'; the answer there was to stop gating on the version.
        #
        # Lower bound 23, NOT 30. Fork databases exist at 29 as well as 32/33 (29 is where the
        # 0.19.0 merge parked the renumbered gates), and 29 is already >= 23 and >= 25 — so a
        # v29 database misses the v23 and v25 work exactly like a v33 one does. Only the trigram
        # rebuild is bounded at 30, because upstream's own ``< 30`` gate above still fires for a
        # v29 database and running that rebuild twice in one pass is real wasted I/O.
        #
        # An upstream-lineage database sitting in 23..29 will redo the v23/v25 actions here. That
        # is deliberate slack rather than free: both are cheap and guarded (the v23 one re-checks
        # _db_needs_fts_storage_upgrade, the v25 one is a dedupe), and there is no marker that
        # distinguishes the two lineages to test instead.
        #
        # _migrate_trigram_cron_exclusion probes for the trigram table first (a fork DB with
        # _message_trigram_disabled() bails there) and returns False to hold the version back —
        # so its result must feed fts_migrations_complete, or a partial rebuild gets stamped
        # complete and never runs again.
        if 23 <= current_version < 34:
            # The v20 seeding above is gated ``< 20`` and so is also unreachable from the fork
            # line. Most fork databases already ran it under the fork's own renumbered ``< 29``
            # gate, but one that has not been opened since the 0.19.0 merge can still be sitting
            # at 23-28 with an unseeded session_model_usage. The seed SQL is INSERT OR IGNORE, so
            # repeating it for the already-seeded majority costs one no-op statement.
            with contextlib.suppress(sqlite3.OperationalError):
                cursor.execute(_SESSION_MODEL_USAGE_V20_SEED_SQL)
            if fts5_available and self._db_needs_fts_storage_upgrade(cursor):
                self.set_meta("fts_optimize_available", "1", cursor=cursor)
            self._dedupe_legacy_system_prompts(cursor)
            if fts5_available and current_version >= 30:
                fts_migrations_complete = (
                    self._migrate_trigram_cron_exclusion(cursor) and fts_migrations_complete)

        # Stamp the FTS layout version (fresh/optimized DBs); a legacy DB keeps its absent/0
        # marker until optimize-storage runs. An INTERRUPTED optimize (markers, trash, or an
        # empty external index against non-empty messages) is NOT stamped: the marker is the
        # source of truth for "fully optimized" and keeps the resume offer alive.
        # v23: FTS storage redesign (issues #22478, #43690, #55233). The v11 inline-mode FTS tables each
        # store a full private copy of every message (content || tool_name || tool_calls), and the trigram
        # index additionally covers role='tool' rows (~90% of message bytes: base64 payloads, file dumps) at
        # ~2.6x amplification — together ~75% of state.db on heavy installs (observed: 18.9 GB of a 25 GB
        # DB). OPT-IN, NOT AUTOMATIC. The transition (demote old vtables → new external-content schema →
        # backfill → teardown → VACUUM) is disk-heavy (transient ~2x file size to fully reclaim via VACUUM)
        # and long (~1-2h background on a 25 GB DB). Doing it silently on every big user's next open — with
        # a completeness guarantee that depends on the process staying alive long enough — is the wrong
        # default. So on an EXISTING install we touch nothing here: the v22 inline FTS keeps working exactly
        # as before, and we only record a flag advertising that the optimization is available. `hermes
        # sessions optimize-storage` performs the whole transition as one deliberate, disk-checked,
        # progress-reported foreground operation. DECOUPLED VERSIONING. Crucially, this does NOT hold back
        # the main schema_version. The FTS storage LAYOUT is tracked by an independent `fts_storage_version`
        # marker (see _fts_storage_version / SETTLE below), so schema_version advances to SCHEMA_VERSION
        # here like every other migration — future v24+ migrations land automatically for legacy-FTS users
        # too. Only the FTS *layout* waits for opt-in.
        if (
            fts5_available
            and not self._db_needs_fts_storage_upgrade(cursor)
            and cursor.execute(
                "SELECT 1 FROM state_meta WHERE key = 'fts_rebuild_high_water' LIMIT 1"
            ).fetchone() is None
            and not self._has_fts_trash(cursor)
            and not self._fts_external_index_empty_with_messages(cursor)
        ):
            self.set_meta("fts_storage_version", str(FTS_STORAGE_VERSION), cursor=cursor)

        # Advance schema_version — deliberately NOT gated on the FTS opt-in (that would block
        # every future migration for a user who never optimizes). FTS5 unavailable is the
        # one skip: claiming current would lie.
        # v33 sidebar-resolution ledger. Schema DDL here is normally declarative and
        # idempotent; this one is not, because once a prior runtime has created the pre-v33
        # tables, CREATE ... IF NOT EXISTS cannot add the new cross-ledger exclusion triggers.
        # Repair and validate the complete authority in ONE transaction so a failed open
        # cannot leave a partial terminal-resolution authority looking valid.
        #
        # Unlike the fork's original this block does NOT write schema_version: upstream owns
        # the single stamp below. Raising here propagates out of _init_schema before that
        # stamp runs, which preserves the same invariant without a second writer of the
        # version. Gate stays < 33 (not the 23..34 compensating range): a fork DB at 33 has
        # already run it, and anything below — including an upstream-lineage DB that never
        # had these tables — needs it, since the repair creates as well as repairs.
        if current_version < 33:
            try:
                cursor.execute("BEGIN IMMEDIATE")
                self._repair_v33_sidebar_resolution_table(cursor)
                self._repair_v33_sidebar_resolution_triggers(cursor)
                self._validate_v33_sidebar_resolution_schema(cursor)
                self._conn.commit()
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

        if current_version < SCHEMA_VERSION and fts_migrations_complete and fts5_available:
            cursor.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    def _migrate_v22_session_model_usage(self, cursor: sqlite3.Cursor) -> None:
        """v22: ``task`` joins the session_model_usage PRIMARY KEY ('' = main loop; aux calls
        named). SQLite cannot ALTER a PK, so rebuild; existing rows → task=''."""
        try:
            # v22: task-dimension usage attribution (issue #23270). session_model_usage gains a ``task``
            # column ('' = main agent loop; 'vision'/'compression'/'title_generation'/... = auxiliary calls)
            # so aux model spend is visible in analytics. The reconciler will have already ADDed the plain
            # column on legacy DBs (harmless); the rebuild bakes it into the PK properly.
            legacy_pk = cursor.execute(
                "SELECT COUNT(*) FROM pragma_table_info('session_model_usage') WHERE name = 'task' AND pk > 0"
            ).fetchone()[0]
            if legacy_pk:
                return
            self._rebuild_table(
                cursor, "session_model_usage", "session_model_usage_v21", _SESSION_MODEL_USAGE_V22_DDL,
                """INSERT INTO session_model_usage (
                                   session_id, model, billing_provider, billing_base_url,
                                   billing_mode, task, api_call_count, input_tokens,
                                   output_tokens, cache_read_tokens, cache_write_tokens,
                                   reasoning_tokens, estimated_cost_usd, actual_cost_usd,
                                   cost_status, cost_source, first_seen, last_seen
                               )
                               SELECT session_id, model, billing_provider, billing_base_url,
                                      billing_mode, '', api_call_count, input_tokens,
                                      output_tokens, cache_read_tokens, cache_write_tokens,
                                      reasoning_tokens, estimated_cost_usd, actual_cost_usd,
                                      cost_status, cost_source, first_seen, last_seen
                               FROM session_model_usage_v21""",
                _SESSION_MODEL_USAGE_INDEX_SQL,
            )
        except sqlite3.OperationalError as exc:
            logger.debug("v22 session_model_usage rebuild skipped: %s", exc)

    def _ensure_unique_title_index(self, cursor: sqlite3.Cursor) -> None:
        """Unique title index. Older DBs may hold duplicate aliases from before the constraint;
        the newest keeps the alias. Must never abort opening the DB, so the repair is guarded."""
        try:
            cursor.execute(_TITLE_UNIQUE_INDEX_SQL)
        except sqlite3.IntegrityError:
            try:
                cursor.execute("""UPDATE sessions AS older
                       SET title = NULL
                       WHERE title IS NOT NULL
                         AND EXISTS (
                             SELECT 1 FROM sessions AS newer
                             WHERE newer.title = older.title
                               AND newer.rowid > older.rowid
                         )""")
                logger.warning(
                    "Cleared %d duplicate session title(s) while restoring the unique index", cursor.rowcount,
                )
                cursor.execute(_TITLE_UNIQUE_INDEX_SQL)
            except sqlite3.Error:
                logger.exception("Could not repair duplicate session titles; unique title index not created")
        except sqlite3.OperationalError:
            pass  # Index already exists

    def _init_fts(self, cursor: sqlite3.Cursor) -> None:
        """Create/repair the FTS objects on an FTS5-capable runtime. The DDL runs even when the
        vtable exists so CREATE TRIGGER IF NOT EXISTS repairs trigger-only degradation.
        OPT-IN v23 boundary: a legacy v22 inline install keeps its inline schema + triggers
        (the v23 DDL would create the trigram source VIEW and leave a mixed state)."""
        legacy_fts = self._db_has_legacy_inline_fts(cursor)
        if not self._fts_stale:
            self._migrate_bounded_tool_fts_triggers(cursor, legacy=legacy_fts)
        if self._fts_stale:
            if self._recover_stale_fts(cursor, legacy=legacy_fts):
                # CJK was detached alongside the base indexes; its ensure path decides when it returns.
                self._ensure_fts_cjk_schema(cursor)
            else:
                self._fts_enabled = self._trigram_available = self._fts_cjk_available = False
        else:
            base_sql, trigram_sql = _FTS_DDL[legacy_fts]
            # Measure before any DDL. Publishing missing base triggers before rebuild admission lets
            # another process write through an index whose bootstrap/repair has no owner (#105790).
            base_triggers_missing = self._fts_triggers_missing(cursor, _FTS_BASE_TRIGGERS) or getattr(
                self, "_fts_tool_prefix_migration_requires_rebuild", False)
            trigram_triggers_missing = self._fts_triggers_missing(cursor, _FTS_TRIGRAM_TRIGGERS)

            def ensure_and_rebuild() -> None:
                self._fts_enabled = self._ensure_fts_schema(cursor, "messages_fts", base_sql)
                if not self._fts_enabled:
                    return
                if _message_trigram_disabled():
                    # HERMES_DISABLE_MESSAGE_TRIGRAM: drop it if present so the pages are freed.
                    self._drop_trigram_fts(cursor)
                    self._trigram_available = False
                else:
                    self._trigram_available = self._ensure_fts_schema(
                        cursor, "messages_fts_trigram", trigram_sql)
                self._rebuild_fts_indexes(
                    cursor, legacy=legacy_fts, include_trigram=self._trigram_available,
                )
                if not legacy_fts:
                    self._ensure_fts_cjk_schema(cursor)

            if base_triggers_missing:
                # The authority covers the whole first-publication sequence, not merely the final rebuild.
                # ``executescript`` commits DDL statement-by-statement, so acquiring after ensure exposed a
                # partially initialized FTS family while another opener held the rebuild lock.
                self._run_admitted_startup_rebuild(cursor, ensure_and_rebuild)
            else:
                self._fts_enabled = self._ensure_fts_schema(cursor, "messages_fts", base_sql)
                if self._fts_enabled:
                    # Trigram is optional; without it CJK search falls back to LIKE. It can also
                    # be opted out of via HERMES_DISABLE_MESSAGE_TRIGRAM (large on-disk cost,
                    # CJK-only) — in which case drop it if present so the pages are freed.
                    if _message_trigram_disabled():
                        self._drop_trigram_fts(cursor)
                        trigram_enabled = False
                    else:
                        trigram_enabled = self._ensure_fts_schema(
                            cursor, "messages_fts_trigram", trigram_sql)
                    self._trigram_available = trigram_enabled
                    if trigram_enabled and trigram_triggers_missing:
                        self._run_admitted_startup_rebuild(
                            cursor,
                            lambda: self._rebuild_fts_indexes(
                                cursor, legacy=legacy_fts, include_trigram=trigram_enabled,
                            ),
                        )
            if self._fts_enabled and not legacy_fts and not base_triggers_missing:
                # CJK-bigram index: strictly additive, gated on the loadable tokenizer.
                self._ensure_fts_cjk_schema(cursor)
        # IF NOT EXISTS cannot rewrite pre-existing broad AFTER UPDATE triggers.
        if self._fts_enabled:
            self._migrate_broad_fts_update_triggers(cursor)

    def _run_admitted_startup_rebuild(self, cursor, rebuild_fn) -> None:
        """Run FTS bootstrap or trigger-repair rebuild under cross-process admission.

        The fresh/base-missing path includes DDL in ``rebuild_fn`` so no process can publish
        triggers before it owns the rebuild. Other repair paths may already have recreated an
        optional trigger; deferral therefore still drops every trigger and persists the stale
        breadcrumb. A later recovery path restores the complete family.

        See #93200.
        See #105790.
        """
        with fts_rebuild_admission(self.db_path) as admitted:
            if admitted:
                rebuild_fn()
                return
        logger.warning(
            "Deferred startup FTS rebuild: another process holds the "
            "rebuild authority for this state.db; detaching FTS sync until the stale-index recovery path rebuilds it."
        )
        cursor.execute(_STALE_KEY_UPSERT_SQL, (FTS_STALE_KEY,))
        self._drop_all_fts_triggers(cursor)
        self._fts_stale = True
        self._fts_enabled = self._trigram_available = self._fts_cjk_available = False

    def _backfill_gateway_metadata_from_sessions_json(self, cursor: sqlite3.Cursor) -> None:
        """One-time v18 backfill of gateway metadata from sessions.json. Only fills NULL
        columns — never overwrites data written by newer code."""
        sessions_file = get_hermes_home() / "sessions" / "sessions.json"
        if not sessions_file.exists():
            return
        with open(sessions_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for key, entry in data.items():
            if str(key).startswith("_") or not isinstance(entry, dict):
                continue
            session_id = entry.get("session_id")
            if not session_id:
                continue
            origin = entry.get("origin")
            origin_dict = origin if isinstance(origin, dict) else None
            cursor.execute(
                """UPDATE sessions
                   SET session_key = COALESCE(session_key, ?),
                       chat_id = COALESCE(chat_id, ?),
                       chat_type = COALESCE(chat_type, ?),
                       thread_id = COALESCE(thread_id, ?),
                       display_name = COALESCE(display_name, ?),
                       origin_json = COALESCE(origin_json, ?),
                       expiry_finalized = CASE
                           WHEN COALESCE(expiry_finalized, 0) = 0 AND ? = 1 THEN 1
                           ELSE expiry_finalized
                       END
                   WHERE id = ?""",
                (
                    entry.get("session_key") or key, origin_dict.get("chat_id") if origin_dict is not None else None,
                    entry.get("chat_type"), origin_dict.get("thread_id") if origin_dict is not None else None,
                    entry.get("display_name"), json.dumps(origin) if origin_dict is not None else None,
                    1 if entry.get("expiry_finalized") or entry.get("memory_flushed") else 0, str(session_id),
                ),
            )

    def has_session_schema(self) -> bool:
        """True when this file is actually a session store.

        ``state.db`` is a filename shared by two INDEPENDENT schema owners.
        ``SessionDB`` creates the full session schema (which happens to include
        ``async_delegations``), but ``tools/async_delegation.py::_connect``
        opens the SAME path and creates ONLY its own ``async_delegations``
        table. Whichever runs first in a given profile decides what the file
        contains, so a profile that has run an async delegation but never
        recorded a session holds a valid, non-empty SQLite database with no
        ``sessions`` table -- and a bare ``db_path.exists()`` guard passes it
        straight through to a query that raises ``no such table: sessions``.

        Measured on this box 2026-09-08: ``profiles/matcher/state.db`` is
        12,288 bytes and holds exactly one table, ``async_delegations``, with
        zero rows. It is the only such profile today; 17 of the 20 have no
        ``state.db`` at all.

        DELIBERATELY NOT a byte-length or SQLite-header test. The same file is
        0 bytes between ``sqlite3.connect()`` and its first checkpoint -- under
        WAL the schema lives in the ``-wal`` until then -- so length measures
        WHEN you looked, not what the file is. At 0 bytes, 4,096 bytes and
        12,288 bytes the failing query is byte-identical, which is why an
        earlier report of this same file as "zero-byte" and today's 12KB
        reading describe one defect, not two.

        Distinguishes "never initialised as a session store" from "cannot be
        read": a corrupt, locked or I/O-failing database raises out of here
        rather than returning False, so callers keep reporting it and the
        cross-profile error channel added in 8ca1e62d64 stays intact.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='sessions' LIMIT 1"
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()

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
    def _create_claude_characterization_event_triggers(
        cursor: sqlite3.Cursor,
    ) -> None:
        for trigger_sql in _CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_SQL:
            cursor.execute(trigger_sql)

    @staticmethod
    def _drop_claude_characterization_event_triggers(
        cursor: sqlite3.Cursor,
    ) -> None:
        for trigger_name in _CLAUDE_CHARACTERIZATION_EVENT_TRIGGER_NAMES:
            cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')

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
