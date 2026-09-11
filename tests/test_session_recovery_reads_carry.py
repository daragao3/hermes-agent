import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_sessions import SessionSessionsMixin


class RecoveryReads(SessionSessionsMixin):
    def __init__(self, conn):
        self.conn = conn

    def _read_all(self, sql, params):
        return self.conn.execute(sql, params).fetchall()

    def _read_one(self, sql, params):
        return self.conn.execute(sql, params).fetchone()


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    yield db
    db.close()


def test_open_sessions_are_source_scoped_and_ordered_without_writes(conn):
    conn.executemany('INSERT INTO sessions(id,source,started_at,ended_at) VALUES (?,?,?,?)', [
        ('b', 'cron', 2, None), ('a', 'cron', 2, None), ('old', 'cron', 1, None),
        ('closed', 'cron', 0, 1), ('other', 'cli', 0, None),
    ])
    conn.commit()
    conn.execute('PRAGMA query_only=ON')
    assert RecoveryReads(conn).list_open_session_ids('cron') == ['old', 'a', 'b']
    assert RecoveryReads(conn).list_open_session_ids("cron' OR 1=1 --") == []


@pytest.mark.parametrize('parent_source,child_source,relative,expected', [
    ('cli', 'cli', False, True), ('tui', 'tui', False, True),
    ('cli', 'tui', False, False), ('telegram', 'cli', False, False),
    ('cli', 'cli', True, False),
])
def test_cwd_lookup_preserves_shared_validation(conn, tmp_path, parent_source, child_source, relative, expected):
    cwd = 'relative' if relative else str(tmp_path)
    conn.execute('INSERT INTO sessions(id,source,started_at,cwd) VALUES (?,?,0,?)', ('p', parent_source, cwd))
    conn.commit()
    conn.execute('PRAGMA query_only=ON')
    assert RecoveryReads(conn).get_inheritable_local_child_cwd('p', child_source) == (cwd if expected else None)
    assert RecoveryReads(conn).get_inheritable_local_child_cwd('missing', child_source) is None


def test_invalid_lookup_arguments_do_not_read():
    class NoReads(RecoveryReads):
        def _read_one(self, *args):
            raise AssertionError('invalid input reached the database')

    db = NoReads(None)
    assert db.get_inheritable_local_child_cwd('', 'cli') is None
    assert db.get_inheritable_local_child_cwd('p', 'telegram') is None
    assert db.get_inheritable_local_child_cwd(None, 'cli') is None
