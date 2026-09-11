import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_schema import SessionSchemaMixin


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.executescript(SCHEMA_SQL)
    yield db
    db.close()


def add(conn, session, key):
    conn.execute('INSERT INTO messages(session_id,role,timestamp,native_event_key) VALUES (?,"user",0,?)',
                 (session, key))


def test_partial_unique_index_is_scoped_to_session(conn):
    SessionSchemaMixin()._ensure_native_event_key_index(conn.cursor())
    add(conn, 'a', 'event')
    with pytest.raises(sqlite3.IntegrityError):
        add(conn, 'a', 'event')
    add(conn, 'b', 'event')
    add(conn, 'a', None)
    add(conn, 'a', None)
    assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 4


def test_legacy_duplicates_are_retained_with_warning(conn, caplog):
    add(conn, 'a', 'event')
    add(conn, 'a', 'event')
    before = conn.execute('SELECT * FROM messages').fetchall()
    SessionSchemaMixin()._ensure_native_event_key_index(conn.cursor())
    assert conn.execute('SELECT * FROM messages').fetchall() == before
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='idx_messages_native_event_key'").fetchone() is None
    assert 'duplicate external events may exist' in caplog.text
