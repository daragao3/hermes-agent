"""Read-only SQL projections; full facade read-pool/queued-writer behavior is separate."""
import json
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_messages import SessionMessagesMixin
from hermes_state_portability import SessionPortabilityMixin
from hermes_state_sessions import SessionSessionsMixin


class ReadRows(SessionSessionsMixin, SessionMessagesMixin, SessionPortabilityMixin):
    _CONTENT_JSON_PREFIX = '\x00json:'

    def __init__(self, conn):
        self.conn = conn

    def _read_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def _read_all(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()


@pytest.fixture
def rows():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    for name, source, started, parent, config, archived, count in [
        ('root', 'cli', 10, None, {}, 0, 3),
        ('archive', 'cli', 20, None, {}, 1, 1),
        ('branch', 'cli', 21, 'root', {'_branched_from': 'root'}, 0, 1),
        ('delegate', 'cli', 25, 'root', {'_delegate_from': 'root'}, 0, 0),
        ('cron', 'cron', 30, None, {}, 0, 0),
    ]:
        conn.execute('INSERT INTO sessions(id,source,started_at,parent_session_id,model_config,archived,message_count) '
                     'VALUES (?,?,?,?,?,?,?)', (name, source, started, parent, json.dumps(config), archived, count))
    for session, text, timestamp, active in [
        ('root', 'first', 100, 1), ('root', 'rewound', 90, 0), ('root', 'third', 80, 1),
        ('branch', 'branch message', 150, 1), ('archive', 'archive message', 50, 1),
    ]:
        conn.execute('INSERT INTO messages(session_id,role,content,timestamp,active) VALUES (?,"user",?,?,?)',
                     (session, text, timestamp, active))
    conn.execute("INSERT INTO system_prompts VALUES ('fixture-hash','resolved prompt')")
    conn.execute("UPDATE sessions SET system_prompt_hash='fixture-hash' WHERE id='root'")
    conn.commit()
    conn.execute('PRAGMA query_only=ON')
    try:
        yield ReadRows(conn)
    finally:
        conn.close()


def test_search_keeps_archives_source_filter_and_stable_recency(rows):
    results = rows.search_sessions(source='cli')
    assert [r['id'] for r in results] == ['branch', 'root', 'archive', 'delegate']
    assert [r['id'] for r in rows.search_sessions(source='cli', limit=2, offset=1)] == ['root', 'archive']
    assert rows.search_sessions(source="cli' OR 1=1 --") == []
    root = next(r for r in results if r['id'] == 'root')
    assert root['system_prompt'] == 'resolved prompt'
    assert '_system_prompt_resolved' not in root


def test_session_count_retains_visibility_and_source_contracts(rows):
    assert rows.session_count() == 4
    assert rows.session_count(include_archived=True) == 5
    assert rows.session_count(archived_only=True) == 1
    assert rows.session_count(source='cli', exclude_children=True) == 2
    assert rows.session_count(exclude_sources=['cron'], min_message_count=1) == 2
    assert rows.session_count(source="cli' OR 1=1 --") == 0


def test_message_count_includes_inactive_rows_and_scopes_session(rows):
    assert rows.message_count() == 5
    assert rows.message_count('root') == 3
    assert rows.message_count('missing') == 0


def test_export_retains_archived_sessions_and_active_message_order(rows):
    exported = {r['id']: r for r in rows.export_all()}
    assert set(exported) == {'root', 'archive', 'branch', 'delegate', 'cron'}
    assert [m['content'] for m in exported['root']['messages']] == ['first', 'third']
    assert exported['root']['system_prompt'] == 'resolved prompt'
    assert [m['content'] for m in exported['archive']['messages']] == ['archive message']
    assert {r['id'] for r in rows.export_all(source='cron')} == {'cron'}
