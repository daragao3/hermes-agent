"""Core and local bridge reconciliation must keep upstream lock semantics."""
import sqlite3

import pytest

from hermes_state_bridge_schema import BRIDGE_SCHEMA_SQL
from hermes_state_common import SCHEMA_SQL
from hermes_state_schema import SessionSchemaMixin


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA_SQL + BRIDGE_SCHEMA_SQL)
    yield db
    db.close()


def test_reconciles_bridge_column_with_default(conn):
    conn.execute('ALTER TABLE external_sessions DROP COLUMN native_status')
    conn.execute("INSERT INTO external_sessions(session_id, provider, native_id, first_indexed_at, "
                 "last_indexed_at, parser_version, origin_kind) VALUES ('s','claude','n',1,1,1,'native')")
    SessionSchemaMixin()._reconcile_columns(conn.cursor())
    assert conn.execute('SELECT native_status FROM external_sessions').fetchone()[0] == 'unknown'
    before = conn.total_changes
    SessionSchemaMixin()._reconcile_columns(conn.cursor())
    assert conn.total_changes == before


def test_schema_specific_reconciliation_propagates_lock(conn):
    ddl = 'CREATE TABLE target(id TEXT, added TEXT DEFAULT "value")'
    conn.execute('CREATE TABLE target(id TEXT)')

    class LockedCursor:
        def execute(self, sql, *args):
            if sql.startswith('ALTER TABLE'):
                raise sqlite3.OperationalError('database is locked')
            return conn.execute(sql, *args)

    with pytest.raises(sqlite3.OperationalError, match='locked'):
        SessionSchemaMixin()._reconcile_columns_from_sql(LockedCursor(), ddl)
