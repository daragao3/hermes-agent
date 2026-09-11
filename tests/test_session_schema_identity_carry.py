"""Read-only schema identity contract; does not initialize the SessionDB facade."""
import contextlib
import sqlite3

import pytest

from hermes_state_schema import SessionSchemaMixin


class SchemaReader(SessionSchemaMixin):
    def __init__(self, conn):
        self.conn = conn

    def _read_one(self, sql, params=()):
        with contextlib.closing(self.conn.execute(sql, params)) as cursor:
            return cursor.fetchone()


@pytest.mark.parametrize(('ddl', 'expected'), [
    ('', False),
    ('CREATE TABLE async_delegations(id TEXT)', False),
    ('CREATE TABLE sessions(id TEXT)', True),
    ('CREATE VIEW sessions AS SELECT 1 AS id', False),
])
def test_identity_uses_session_table_without_creating_schema(ddl, expected):
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript(ddl)
        before = conn.execute('SELECT * FROM sqlite_master').fetchall()
        conn.execute('PRAGMA query_only=ON')
        assert SchemaReader(conn).has_session_schema() is expected
        assert conn.execute('SELECT * FROM sqlite_master').fetchall() == before


def test_corrupt_database_is_reported_not_treated_as_missing_schema(tmp_path):
    path = tmp_path / 'corrupt.db'
    payload = b'not a SQLite database' * 100
    path.write_bytes(payload)
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match='not a database'):
            SchemaReader(conn).has_session_schema()
    assert path.read_bytes() == payload
