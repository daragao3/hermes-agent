"""Exercise upstream conversion primitives on the exact local FTS declaration."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_fts import SessionFtsSetupMixin
from hermes_state_schema import SessionSchemaMixin
from hermes_state_search import SessionSearchMixin


class ConversionDB(SessionSearchMixin, SessionSchemaMixin, SessionFtsSetupMixin):
    """Real SQLite transaction plumbing; full SessionDB initialization is not exercised."""
    def __init__(self, conn, path):
        self._conn = conn
        self.db_path = path
        self._lock = threading.RLock()
        self._fts_enabled = True
        self._trigram_available = False
        self._fts_cjk_loaded = False

    def _execute_write(self, fn):
        with self._lock:
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                value = fn(self._conn)
                self._conn.commit()
                return value
            except BaseException:
                self._conn.rollback()
                raise

    def set_meta(self, key, value, *, cursor):
        cursor.execute('INSERT INTO state_meta(key,value) VALUES (?,?) '
                       'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def get_meta(self, key):
        row = self._conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def _read_all(self, sql, params):
        return self._conn.execute(sql, params).fetchall()

    @contextmanager
    def _read_ctx(self):
        yield self._conn


@pytest.mark.parametrize('interrupted', [False, True])
def test_upstream_primitives_convert_local_external_index(tmp_path, interrupted):
    path = tmp_path / 'conversion.db'
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.executescript((Path(__file__).parent / 'fixtures/local_v33_fts.sql').read_text(encoding='utf-8'))
        conn.execute('INSERT INTO schema_version VALUES (33)')
        conn.execute("INSERT INTO sessions(id,source,started_at) VALUES ('s','cli',0)")
        conn.executemany('INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,0)',
                         [('s', 'user', 'durableword'), ('s', 'tool', 'toolword')])
        conn.commit()
        if interrupted:
            class Interrupted(ConversionDB):
                def _ensure_v23_fts_tables(self, failure_message):
                    raise RuntimeError('injected interruption after demote commit')

            with pytest.raises(RuntimeError, match='injected interruption'):
                Interrupted(conn, path)._demote_legacy_fts_to_trash()
            assert not conn.in_transaction
            conn.close()
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            db = ConversionDB(conn, path)
            assert db.get_meta('fts_rebuild_high_water') == '2'
            db._ensure_v23_fts_tables('resume failed')
        else:
            db = ConversionDB(conn, path)
            assert db._demote_legacy_fts_to_trash() == 2
        assert db.get_meta('fts_rebuild_high_water') == '2'
        assert db._has_fts_trash(conn)
        for _ in range(20):
            if not db.fts_rebuild_step():
                break
        else:
            raise AssertionError('backfill did not finish within bounded fixture iterations')
        for _ in range(20):
            if not db._fts_teardown_trash_step():
                break
        else:
            raise AssertionError('teardown did not finish within bounded fixture iterations')
        assert db._execute_write(db._optimize_settle) is None
        assert not db._has_fts_trash(conn)
        assert db.get_meta('fts_rebuild_high_water') is None
        assert db.get_meta('fts_storage_version') == '2'
        assert conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'durableword OR toolword'").fetchone()[0] == 2
        conn.execute("INSERT INTO messages_fts(messages_fts,rank) VALUES ('integrity-check',1)")
        conn.execute("UPDATE messages SET content='changedword' WHERE role='user'")
        conn.execute("DELETE FROM messages WHERE role='tool'")
        conn.execute("INSERT INTO messages_fts(messages_fts,rank) VALUES ('integrity-check',1)")
        assert conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'changedword'").fetchone()[0] == 1
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0] == 33
    finally:
        conn.close()


class LocalRecoveryDB(ConversionDB):
    """Known fresh fixture only; file-generation/quarantine admission is not tested."""
    def __init__(self, conn, path):
        super().__init__(conn, path)
        self._fts_stale = False
        self._fts_cjk_available = False
        self.admission_calls = []

    def _raise_if_db_corrupt(self):
        self.admission_calls.append('quarantine')

    def _halt_if_db_generation_changed(self):
        self.admission_calls.append('generation')


@pytest.fixture
def local_recovery_db(tmp_path):
    path = tmp_path / 'local-recovery.db'
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript((Path(__file__).parent / 'fixtures/local_v33_fts.sql').read_text(encoding='utf-8'))
        conn.execute("INSERT INTO sessions(id,source,started_at) VALUES ('s','cli',0)")
        conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES ('s','user','preservedword',0)")
        conn.commit()
        yield LocalRecoveryDB(conn, path)
    finally:
        conn.close()


def test_local_corrupt_index_detaches_and_canonical_writes_continue(local_recovery_db):
    db = local_recovery_db
    conn = db._conn
    before = conn.execute('SELECT * FROM messages').fetchall()
    conn.execute("UPDATE messages_fts_data SET block=X'DEADBEEFDEADBEEFDEADBEEFDEADBEEF'")
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError) as failed_write:
        conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES ('s','user','retryword',0)")
        conn.commit()
    conn.rollback()
    assert conn.execute('SELECT * FROM messages').fetchall() == before
    assert db._enter_fts_fail_open(failed_write.value) is True
    assert db.admission_calls == ['quarantine', 'generation']
    assert db._fts_stale is True
    assert db._fts_enabled is False
    assert db.get_meta('fts_stale') == '1'
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'messages_fts_%'").fetchall() == []
    assert conn.execute('SELECT * FROM messages').fetchall() == before
    conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES ('s','user','retryword',0)")
    conn.commit()
    assert conn.execute('SELECT content FROM messages ORDER BY id').fetchall() == [('preservedword',), ('retryword',)]
    with sqlite3.connect(db.db_path) as peer:
        assert peer.execute("SELECT value FROM state_meta WHERE key='fts_stale'").fetchone() == ('1',)
        assert peer.execute('SELECT content FROM messages ORDER BY id').fetchall() == [('preservedword',), ('retryword',)]


def test_detach_failure_rolls_back_breadcrumb_and_trigger_changes(local_recovery_db):
    db = local_recovery_db
    conn = db._conn
    before = conn.execute('SELECT * FROM sqlite_master ORDER BY type,name').fetchall()
    # Permit one real trigger drop, then deny the second to verify rollback of
    # partially executed DDL and the already-inserted stale breadcrumb.
    drops = []

    def authorize(action, arg1, arg2, database, source):
        if action == sqlite3.SQLITE_DROP_TRIGGER:
            drops.append(arg1)
            if len(drops) == 2:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    try:
        assert db._enter_fts_fail_open(sqlite3.DatabaseError('fts5: corrupt structure record for table "messages_fts"')) is False
    finally:
        conn.set_authorizer(None)
    assert len(drops) == 2
    assert conn.in_transaction is False
    assert conn.execute('SELECT * FROM sqlite_master ORDER BY type,name').fetchall() == before
    assert db.get_meta('fts_stale') is None
    assert db._fts_enabled is True
    assert db._fts_stale is False


def test_generic_structural_error_does_not_detach_fts(local_recovery_db):
    db = local_recovery_db
    before = db._conn.execute('SELECT * FROM sqlite_master ORDER BY type,name').fetchall()
    assert db._enter_fts_fail_open(sqlite3.DatabaseError('database disk image is malformed')) is False
    assert db.admission_calls == []
    assert db.get_meta('fts_stale') is None
    assert db._conn.execute('SELECT * FROM sqlite_master ORDER BY type,name').fetchall() == before
