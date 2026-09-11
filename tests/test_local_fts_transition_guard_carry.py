"""Never rewrite local external-content FTS with upstream inline trigger semantics."""
from pathlib import Path
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL, FTS_SQL, LEGACY_FTS_SQL, FTS_TOOL_FULL_CONTENT_HIGH_WATER_KEY
from hermes_state_schema import SessionSchemaMixin


def test_local_external_index_refuses_inline_trigger_migration():
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript((Path(__file__).parent / 'fixtures/local_v33_fts.sql').read_text(encoding='utf-8'))
        before = conn.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        with pytest.raises(RuntimeError, match='explicit storage conversion'):
            SessionSchemaMixin()._migrate_bounded_tool_fts_triggers(conn.cursor(), legacy=True)
        assert conn.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall() == before
        assert conn.execute('SELECT COUNT(*) FROM state_meta').fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize('legacy,ddl', [(True, LEGACY_FTS_SQL), (False, FTS_SQL)])
def test_upstream_layouts_keep_bounded_trigger_migration(legacy, ddl):
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(SCHEMA_SQL + ddl)
        SessionSchemaMixin()._migrate_bounded_tool_fts_triggers(conn.cursor(), legacy=legacy)
        assert conn.execute('SELECT value FROM state_meta WHERE key=?',
                            (FTS_TOOL_FULL_CONTENT_HIGH_WATER_KEY,)).fetchone() == ('0',)
    finally:
        conn.close()
