"""Bounded retention on scratch SQLite only; cleanup calls are observed, never executed."""
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_maintenance import SessionMaintenanceMixin
from hermes_state_sessions import SessionSessionsMixin


class RetentionRows(SessionMaintenanceMixin, SessionSessionsMixin):
    _AUTO_PRUNE_STALE_OPEN_SOURCES = ('cron',)
    def __init__(self, conn):
        self.conn = conn
        self.transactions = []
        self.cleaned = []
        self.protected = set()

    def _read_all(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def _write_rowcount(self, sql, params):
        def write(conn):
            cursor = conn.execute(sql, params)
            return cursor.rowcount if cursor.rowcount >= 0 else conn.execute('SELECT changes()').fetchone()[0]
        return self._execute_write(write)

    def _execute_write(self, fn):
        before = {r[0] for r in self.conn.execute('SELECT id FROM sessions')}
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            result = fn(self.conn)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        after = {r[0] for r in self.conn.execute('SELECT id FROM sessions')}
        self.transactions.append(before - after)
        return result

    def _write_guards_reject(self, conn, session_id, **kwargs):
        assert conn.in_transaction
        assert kwargs == {'allow_closed_compression_parent': True}
        return session_id in self.protected

    def _delete_unreferenced_system_prompts(self, conn):
        conn.execute('DELETE FROM system_prompts WHERE hash NOT IN '
                     '(SELECT system_prompt_hash FROM sessions WHERE system_prompt_hash IS NOT NULL)')

    def _remove_session_files(self, directory, session_id):
        assert not self.conn.in_transaction
        assert self.conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone() is None
        self.cleaned.append(session_id)


@pytest.fixture
def rows():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    try:
        yield RetentionRows(conn)
    finally:
        conn.close()


def seed(rows, name, *, ended=1, pinned=0, parent=None):
    rows.conn.execute('INSERT INTO sessions(id,source,started_at,ended_at,pinned,parent_session_id) '
                      'VALUES (?,"cli",0,?,?,?)', (name, ended, pinned, parent))
    rows.conn.execute('INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,"user",?,0)', (name, name))
    rows.conn.commit()


def test_batches_bound_deleted_sessions_preserve_pins_open_rows_and_children(rows):
    for name in ['a', 'b', 'c', 'd', 'e']:
        seed(rows, name)
    seed(rows, 'pinned', pinned=1)
    seed(rows, 'open-child', ended=None, parent='a')
    assert rows.prune_sessions(older_than_days=None, max_batch=2) == 5
    assert [len(ids) for ids in rows.transactions if ids] == [2, 2, 1]
    assert set(rows.cleaned) == {'a', 'b', 'c', 'd', 'e'}
    assert {r[0] for r in rows.conn.execute('SELECT id FROM sessions')} == {'pinned', 'open-child'}
    assert rows.conn.execute('SELECT parent_session_id FROM sessions WHERE id="open-child"').fetchone()[0] is None
    assert {r[0] for r in rows.conn.execute('SELECT session_id FROM messages')} == {'pinned', 'open-child'}


def test_guarded_first_batch_does_not_starve_later_unprotected_rows(rows):
    for name in ['a', 'b', 'c', 'd']:
        seed(rows, name)
    rows.protected = {'a', 'b'}
    assert rows.prune_sessions(older_than_days=None, max_batch=2, exclude_active_write_guards=True) == 2
    assert {r[0] for r in rows.conn.execute('SELECT id FROM sessions')} == {'a', 'b'}
    assert set(rows.cleaned) == {'c', 'd'}


def test_failed_transaction_cleans_no_files_and_preserves_all_rows(rows):
    seed(rows, 'a')
    rows.conn.executescript("""CREATE TRIGGER refuse_delete BEFORE DELETE ON sessions
                              BEGIN SELECT RAISE(ABORT, 'injected refusal'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match='injected refusal'):
        rows.prune_sessions(older_than_days=None, max_batch=1)
    assert rows.cleaned == []
    assert rows.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
    assert rows.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_unbounded_default_keeps_one_transaction(rows):
    for name in ['a', 'b', 'c']:
        seed(rows, name)
    assert rows.prune_sessions(older_than_days=None) == 3
    assert len(rows.transactions) == 1


def test_retention_dry_run_uses_inactivity_and_preserves_recent_old_sessions(rows, monkeypatch):
    import hermes_state_maintenance as maintenance
    monkeypatch.setattr(maintenance.time, 'time', lambda: 1000000)
    for name in ['old', 'recent', 'pinned']:
        seed(rows, name, pinned=int(name == 'pinned'))
    seed(rows, 'open', ended=None)
    rows.conn.execute('UPDATE messages SET timestamp=999999 WHERE session_id="recent"')
    rows.conn.commit()
    rows.conn.execute('PRAGMA query_only=ON')
    assert [r['id'] for r in rows.list_prune_candidates(older_than_days=1)] == ['old']
    assert rows.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 4


def test_archive_is_idempotent_keeps_messages_and_archives_compression_chain(rows):
    seed(rows, 'parent')
    seed(rows, 'child', parent='parent')
    seed(rows, 'pinned', pinned=1)
    rows.conn.execute('UPDATE sessions SET end_reason="compression" WHERE id="parent"')
    rows.conn.commit()
    before = [tuple(r) for r in rows.conn.execute('SELECT * FROM messages ORDER BY id')]
    assert rows.archive_sessions() == 2
    assert rows.archive_sessions() == 0
    assert dict(rows.conn.execute('SELECT id,archived FROM sessions')) == {'parent': 1, 'child': 1, 'pinned': 0}
    assert [tuple(r) for r in rows.conn.execute('SELECT * FROM messages ORDER BY id')] == before
    assert rows.cleaned == []


@pytest.mark.parametrize('prune_fails', [False, True])
def test_auto_maintenance_forwards_batch_and_throttles_failed_attempt(rows, monkeypatch, tmp_path, prune_fails):
    import hermes_state_repair as repair
    rows.db_path = tmp_path / 'owner-fixture.db'
    owner = object()
    released = []
    monkeypatch.setattr(repair, '_try_acquire_auto_maintenance_lock', lambda path: owner)
    monkeypatch.setattr(repair, '_release_auto_maintenance_lock', released.append)
    rows.get_meta = lambda key: (rows.conn.execute('SELECT value FROM state_meta WHERE key=?', (key,)).fetchone() or [None])[0]

    def set_meta(key, value):
        with rows.conn:
            rows.conn.execute('INSERT INTO state_meta(key,value) VALUES (?,?) '
                              'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    rows.set_meta = set_meta
    calls = []

    def prune(**kwargs):
        calls.append(kwargs)
        if prune_fails:
            raise sqlite3.OperationalError('injected contention')
        return 0

    rows.prune_sessions = prune
    rows.sweep_orphaned_sessions = lambda **kwargs: []
    result = rows.maybe_auto_prune_and_vacuum(max_batch=2, vacuum=False)
    assert calls[0]['max_batch'] == 2
    assert calls[0]['exclude_active_write_guards'] is True
    assert rows.get_meta('last_auto_prune') is not None
    assert released == [owner]
    assert ('error' in result) is prune_fails
    second = rows.maybe_auto_prune_and_vacuum(max_batch=2, vacuum=False)
    assert second['skipped'] is True
    assert len(calls) == 1
    assert released == [owner, owner]
