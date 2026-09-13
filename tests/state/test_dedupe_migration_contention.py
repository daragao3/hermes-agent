"""The v25 dedupe migration must degrade gracefully on a contended DB.

Enterprise field report (2026-08-14): with state.db locked by another process,
``_dedupe_legacy_system_prompts`` raised ``sqlite3.OperationalError``
mid-loop (only the initial SELECT was guarded), which aborted schema init,
left the schema version below 25, and made EVERY subsequent
``SessionDB.__init__`` re-enter the same blocking migration — the fuel of
the gateway's watchdog crash loop.

Contract:
- A write failure mid-migration returns gracefully (no raise). Partial
  migration is safe by design: the legacy ``system_prompt`` column is kept
  as a read fallback for unmigrated rows.
- Rows migrated before the failure stay migrated; unmigrated rows remain
  readable and are picked up by a later successful run.

SEEDING ORDER IS LOAD-BEARING. Merge ``8586e305a2`` widened the migration
gate from ``current_version < 25`` to "below v25 **or** any inline prompt
still remains", so ``SessionDB.__init__`` now resumes the dedupe on an
already-current schema. Legacy rows written before the store is opened are
therefore migrated by ``__init__`` itself, leaving the proxy below nothing to
fail on. Seed through the raw connection *after* the store is open; the last
test pins the init-resume behaviour that forces this ordering.
"""

import sqlite3


from hermes_state import SessionDB

_N_ROWS = 5


def _make_db(tmp_path):
    """Create a real SessionDB file at the current schema, then close it."""
    db_path = tmp_path / "state.db"
    SessionDB(db_path=db_path).close()
    return db_path


def _seed_legacy_rows(cursor, n_rows=_N_ROWS):
    """Regress *n_rows* to the pre-v25 shape: inline prompt, no hash."""
    for i in range(n_rows):
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (id, source, started_at) "
            "VALUES (?, 'test', 1.0)",
            (f"sess-{i}",),
        )
        cursor.execute(
            "UPDATE sessions SET system_prompt = ?, system_prompt_hash = NULL "
            "WHERE id = ?",
            (f"legacy prompt {i}", f"sess-{i}"),
        )
    seeded = cursor.execute(
        "SELECT COUNT(*) FROM sessions WHERE system_prompt IS NOT NULL"
    ).fetchone()[0]
    assert seeded == n_rows, f"fixture only seeded {seeded}/{n_rows} legacy rows"


class _FailAfterN:
    """Cursor proxy: UPDATE statements start failing after N successes."""

    def __init__(self, cursor, fail_after):
        self._cursor = cursor
        self._updates = 0
        self._fail_after = fail_after

    def execute(self, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith("UPDATE"):
            if self._updates >= self._fail_after:
                raise sqlite3.OperationalError("database is locked")
            self._updates += 1
        return self._cursor.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def test_mid_loop_lock_error_returns_instead_of_raising(tmp_path):
    db_path = _make_db(tmp_path)
    db = SessionDB(db_path=db_path)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        raw = conn.cursor()
        _seed_legacy_rows(raw)  # after the open: see the module docstring
        conn.commit()
        proxy = _FailAfterN(raw, fail_after=2)
        # Must NOT raise even though the third UPDATE hits "database is locked".
        db._dedupe_legacy_system_prompts(proxy)
        conn.commit()

        rows = raw.execute(
            "SELECT id, system_prompt, system_prompt_hash FROM sessions "
            "WHERE id LIKE 'sess-%' ORDER BY id"
        ).fetchall()
        migrated = [r for r in rows if r["system_prompt"] is None]
        legacy = [r for r in rows if r["system_prompt"] is not None]
        assert migrated, "no rows migrated before the simulated lock"
        assert legacy, "expected unmigrated remainder after the failure"
        # Migrated rows carry a hash; legacy rows keep their readable prompt.
        assert all(r["system_prompt_hash"] for r in migrated)
        assert all(r["system_prompt"].startswith("legacy prompt") for r in legacy)
        conn.close()
    finally:
        db.close()


def test_later_run_completes_the_remainder(tmp_path):
    db_path = _make_db(tmp_path)
    db = SessionDB(db_path=db_path)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        raw = conn.cursor()
        _seed_legacy_rows(raw)  # after the open: see the module docstring
        conn.commit()
        db._dedupe_legacy_system_prompts(_FailAfterN(raw, fail_after=2))
        conn.commit()
        # The pause must be real, or the second run below proves nothing.
        paused = raw.execute(
            "SELECT COUNT(*) FROM sessions "
            "WHERE id LIKE 'sess-%' AND system_prompt IS NOT NULL"
        ).fetchone()[0]
        assert 0 < paused < _N_ROWS, f"expected a partial migration, got {paused}"
        # Second run with no failures finishes the job.
        db._dedupe_legacy_system_prompts(raw)
        conn.commit()
        remaining = raw.execute(
            "SELECT COUNT(*) FROM sessions "
            "WHERE id LIKE 'sess-%' AND system_prompt IS NOT NULL"
        ).fetchone()[0]
        assert remaining == 0
        conn.close()
    finally:
        db.close()


def test_schema_init_resumes_the_migration_at_the_current_version(tmp_path):
    """Pin the init-resume behaviour the two tests above are ordered around.

    Merge ``8586e305a2`` widened the gate in ``hermes_state_schema`` so a
    paused v25 dedupe resumes from the data that actually remains rather than
    from the stored schema version. Nothing else asserts that, and reverting it
    would silently restore the crash-loop shape the field report describes:
    inline prompts stranded forever on an already-current DB.
    """
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    _seed_legacy_rows(conn.cursor())
    conn.commit()
    conn.close()

    SessionDB(db_path=db_path).close()  # schema init alone must pick them up

    conn = sqlite3.connect(db_path)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE system_prompt IS NOT NULL"
    ).fetchone()[0]
    hashed = conn.execute(
        "SELECT COUNT(*) FROM sessions "
        "WHERE id LIKE 'sess-%' AND system_prompt_hash IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert remaining == 0, "schema init left inline prompts on a current-version DB"
    assert hashed == _N_ROWS
