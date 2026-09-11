import json
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_messages import SessionMessagesMixin
from hermes_state_errors import CompressionSessionClosedError


class MessageWriter(SessionMessagesMixin):
    _CONTENT_JSON_PREFIX = '\x00json:'
    _TRANSCRIPT_WRITE_PATIENCE_S = 60

    def __init__(self, conn):
        self.conn = conn

    def _execute_write(self, fn, *, patience_s):
        assert patience_s == self._TRANSCRIPT_WRITE_PATIENCE_S
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            result = fn(self.conn)
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    db.execute("INSERT INTO sessions(id,source,started_at) VALUES ('s','codex',0)")
    db.commit()
    yield db
    db.close()


def test_ids_metadata_and_caller_rollback(conn):
    messages = [
        {'role': 'assistant', 'content': 'answer', 'native_event_key': 'event1', 'timestamp': 0,
         'tool_calls': [{'id': 't', 'type': 'function', 'function': {'name': 'read'}}],
         'display_kind': 'note', 'display_metadata': {'title': 'keep'}},
        {'role': 'user', 'content': 'question', 'native_event_key': 'event2', 'reasoning': 'must not persist'},
    ]
    conn.execute('BEGIN')
    ids, tools = SessionMessagesMixin()._insert_message_rows_with_ids(conn, 's', messages)
    assert len(ids) == 2 and len(set(ids)) == 2 and tools == 1
    assert [m['_row_id'] for m in messages] == ids
    rows = conn.execute('SELECT * FROM messages ORDER BY id').fetchall()
    assert [r['native_event_key'] for r in rows] == ['event1', 'event2']
    assert rows[0]['timestamp'] == 0
    assert rows[0]['display_kind'] == 'note'
    assert json.loads(rows[0]['display_metadata']) == {'title': 'keep'}
    assert rows[1]['reasoning'] is None
    assert conn.execute('SELECT message_count FROM sessions').fetchone()[0] == 0
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0


def test_count_wrapper_keeps_upstream_contract(conn):
    result = SessionMessagesMixin()._insert_message_rows(conn, 's', [{'role': 'user', 'content': 'hello'}])
    assert result == (1, 0)


def test_append_preserves_replay_fields_and_updates_counters_atomically(conn):
    writer = MessageWriter(conn)
    parts = [{'type': 'text', 'text': 'ação'}, {'type': 'image_url', 'image_url': {'url': 'fixture-image'}}]
    tool_calls = [{'id': 'one'}, {'id': 'two'}]
    api_content = ' exact API content\nwith trailing spaces  '
    row_id = writer.append_message('s', 'assistant', content=parts, tool_calls=tool_calls,
        timestamp=0, api_content=api_content, platform_message_id='platform-id', observed=True,
        reasoning='r', reasoning_details=[{'text': 'detail'}], codex_reasoning_items=[{'id': 'reason'}],
        codex_message_items=[{'id': 'message'}], display_kind='note', display_metadata={'title': 'kept'})
    stored = conn.execute('SELECT * FROM messages').fetchone()
    assert stored['id'] == row_id
    assert writer._decode_content(stored['content']) == parts
    assert stored['api_content'] == api_content
    assert stored['timestamp'] == 0
    assert stored['platform_message_id'] == 'platform-id'
    assert stored['observed'] == stored['active'] == 1
    assert stored['reasoning'] == 'r'
    assert json.loads(stored['reasoning_details']) == [{'text': 'detail'}]
    assert json.loads(stored['codex_reasoning_items']) == [{'id': 'reason'}]
    assert json.loads(stored['codex_message_items']) == [{'id': 'message'}]
    assert json.loads(stored['tool_calls']) == tool_calls
    assert json.loads(stored['display_metadata']) == {'title': 'kept'}
    assert stored['display_kind'] == 'note'
    assert tuple(conn.execute('SELECT message_count,tool_call_count FROM sessions').fetchone()) == (1, 2)


def test_counter_failure_rolls_back_inserted_message(conn):
    conn.executescript("""CREATE TRIGGER reject_counter BEFORE UPDATE OF message_count ON sessions
                          BEGIN SELECT RAISE(ABORT, 'injected counter failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match='injected counter failure'):
        MessageWriter(conn).append_message('s', 'user', content='must roll back')
    assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
    assert tuple(conn.execute('SELECT message_count,tool_call_count FROM sessions').fetchone()) == (0, 0)
    assert conn.in_transaction is False


def test_closed_compression_parent_rejects_append_before_persistence(conn):
    conn.execute("UPDATE sessions SET end_reason='compression',ended_at=1 WHERE id='s'")
    conn.commit()
    with pytest.raises(CompressionSessionClosedError):
        MessageWriter(conn).append_message('s', 'user', content='must not enter old parent')
    assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
    assert conn.execute('SELECT message_count FROM sessions').fetchone()[0] == 0
