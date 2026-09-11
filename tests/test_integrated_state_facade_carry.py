"""Whole candidate SessionDB on disposable files; never a production upgrade test."""
import sqlite3

import pytest

from hermes_state import SessionDB
from hermes_state_schema import SessionSchemaMixin


def test_full_facade_initializes_bridge_and_preserves_messages_on_reopen(tmp_path):
    path = tmp_path / 'integrated.db'
    with SessionDB(db_path=path) as db:
        assert db.has_session_schema()
        db.ensure_session('s', source='cli', model='fixture-model')
        message_id = db.append_message('s', 'user', content='facade persistence needle', timestamp=0)
        assert message_id > 0
        assert db.message_count('s') == 1
        assert db.get_messages('s')[0]['timestamp'] == 0
        assert db._conn.execute('SELECT COUNT(*) FROM session_bridge_migrations').fetchone()[0] == 7
        assert db._conn.execute("SELECT name FROM sqlite_master WHERE name='external_sessions'").fetchone()
    with SessionDB(db_path=path, read_only=True) as reopened:
        assert reopened.get_messages('s')[0]['content'] == 'facade persistence needle'
        assert reopened.search_messages('needle')


def test_full_facade_uses_strict_fts_corruption_classification():
    assert SessionDB._is_fts_write_corruption_error(sqlite3.DatabaseError('database disk image is malformed')) is False
    assert SessionDB._is_fts_write_corruption_error(sqlite3.DatabaseError('fts5: corrupt structure record for table "messages_fts"')) is True
    assert {'source', 'model_config'} <= set(SessionDB._TOKEN_DELTA_ROUTE_FIELDS)


def test_newer_scalar_refusal_precedes_schema_mutation(tmp_path):
    path = tmp_path / 'local-history.db'
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE schema_version(version INTEGER)')
        conn.execute('INSERT INTO schema_version VALUES (33)')
        conn.commit()
        before = conn.execute('SELECT * FROM sqlite_master').fetchall()
        schema = SessionSchemaMixin()
        schema._conn = conn
        with pytest.raises(RuntimeError, match='explicit migration-domain conversion'):
            schema._init_schema()
        assert conn.execute('SELECT * FROM sqlite_master').fetchall() == before
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0] == 33
    finally:
        conn.close()
