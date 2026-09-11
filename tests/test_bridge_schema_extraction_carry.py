"""Local ledger preservation checks after extracting the schema from the facade."""
import sqlite3

import pytest

from hermes_state_bridge_schema import BRIDGE_SCHEMA_SQL, SessionBridgeSchemaMixin
from hermes_state_common import SCHEMA_SQL


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.executescript(BRIDGE_SCHEMA_SQL)
    yield db
    db.close()


def test_canonical_schema_is_idempotent(conn):
    before = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    conn.executescript(BRIDGE_SCHEMA_SQL)
    SessionBridgeSchemaMixin._validate_v33_sidebar_resolution_schema(conn.cursor())
    assert conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall() == before


def test_malformed_nonempty_ledger_is_preserved():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE session_sidebar_v2_attempt_zero_resolutions(evidence TEXT)")
        db.execute("INSERT INTO session_sidebar_v2_attempt_zero_resolutions VALUES ('retained')")
        with pytest.raises(RuntimeError, match="contains evidence"):
            SessionBridgeSchemaMixin._repair_v33_sidebar_resolution_table(db.cursor())
        assert db.execute("SELECT evidence FROM session_sidebar_v2_attempt_zero_resolutions").fetchall() == [('retained',)]
    finally:
        db.close()


def test_empty_malformed_ledger_can_be_repaired():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE session_sidebar_v2_attempt_zero_resolutions(wrong TEXT)")
        SessionBridgeSchemaMixin._repair_v33_sidebar_resolution_table(db.cursor())
        expected, _ = SessionBridgeSchemaMixin._v33_sidebar_resolution_schema()
        actual = db.execute("SELECT sql FROM sqlite_master WHERE name='session_sidebar_v2_attempt_zero_resolutions'").fetchone()[0]
        assert ' '.join(actual.split()) == ' '.join(expected.split())
    finally:
        db.close()


def test_trigger_repair_stays_inside_caller_transaction(conn):
    name = 'trg_session_sidebar_v2_attempt_zero_resolutions_no_delete'
    conn.execute(f'DROP TRIGGER "{name}"')
    conn.commit()
    with pytest.raises(RuntimeError, match="incomplete"):
        SessionBridgeSchemaMixin._validate_v33_sidebar_resolution_schema(conn.cursor())
    conn.execute("BEGIN")
    SessionBridgeSchemaMixin._repair_v33_sidebar_resolution_triggers(conn.cursor())
    SessionBridgeSchemaMixin._validate_v33_sidebar_resolution_schema(conn.cursor())
    assert conn.in_transaction
    conn.rollback()
    with pytest.raises(RuntimeError, match="incomplete"):
        SessionBridgeSchemaMixin._validate_v33_sidebar_resolution_schema(conn.cursor())


def test_bridge_migration_chain_replays_without_write_lock(conn):
    class Migrator(SessionBridgeSchemaMixin):
        def __init__(self, db):
            self._conn = db

    conn.executescript(SCHEMA_SQL)
    db = Migrator(conn)
    names = (
        '_apply_claude_auth_recovery_call_started_migration', '_apply_bridge_migrations',
        '_apply_claude_characterization_abort_trigger_migration',
        '_apply_claude_characterization_events_v28_migration',
        '_apply_claude_characterization_event_orphan_quarantine_migration',
        '_apply_sidebar_resolution_orphan_quarantine_migration',
        '_apply_sidebar_reconciliation_proof_orphan_quarantine_migration',
    )
    for name in names:
        getattr(db, name)(conn.cursor())
    markers = conn.execute('SELECT migration_name, applied_at FROM session_bridge_migrations ORDER BY migration_name').fetchall()
    assert len(markers) == len(names)
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        for name in names:
            getattr(db, name)(conn.cursor())
    finally:
        conn.set_trace_callback(None)
    assert all(not statement.lstrip().upper().startswith(('BEGIN', 'INSERT', 'UPDATE', 'DELETE', 'ALTER'))
               for statement in statements)
    assert conn.execute('SELECT migration_name, applied_at FROM session_bridge_migrations ORDER BY migration_name').fetchall() == markers


def test_recovery_column_and_marker_roll_back_together(conn):
    class Migrator(SessionBridgeSchemaMixin):
        def __init__(self, db):
            self._conn = db

    # Minimal pre-checkpoint table: the migration only adds call_started_at.
    conn.execute('DROP TABLE session_claude_auth_recoveries')
    conn.execute('CREATE TABLE session_claude_auth_recoveries(id TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO session_claude_auth_recoveries VALUES ('retained')")
    conn.execute("CREATE TRIGGER reject_test_marker BEFORE INSERT ON session_bridge_migrations "
                 "BEGIN SELECT RAISE(ABORT, 'injected marker failure'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match='injected marker failure'):
        Migrator(conn)._apply_claude_auth_recovery_call_started_migration(conn.cursor())
    assert not conn.in_transaction
    assert [r[1] for r in conn.execute('PRAGMA table_info(session_claude_auth_recoveries)')] == ['id']
    assert conn.execute('SELECT * FROM session_claude_auth_recoveries').fetchall() == [('retained',)]
    assert conn.execute('SELECT COUNT(*) FROM session_bridge_migrations').fetchone()[0] == 0
