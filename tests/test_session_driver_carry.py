import json
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_sessions import SessionSessionsMixin, detect_session_driver


class DriverDB(SessionSessionsMixin):
    _TRANSCRIPT_WRITE_PATIENCE_S = 1

    def __init__(self, conn):
        self.conn = conn

    def _own_profile_name(self):
        return None

    def _store_system_prompt(self, conn, prompt):
        assert prompt is None
        return None

    def _execute_write(self, fn, **kwargs):
        with self.conn:
            return fn(self.conn)

    def flush_token_counts(self):
        pass  # These fixtures have no queued accounting work.

    def _read_all(self, sql, params):
        return self.conn.execute(sql, params).fetchall()

    @staticmethod
    def _session_row_dict(row):
        return dict(row)


@pytest.mark.parametrize('source,origin,expected', [
    ('cli', None, 'codex'), ('tui', None, 'codex'),
    ('telegram', None, None), ('cli', '{"chat_id":"keep"}', None),
])
def test_driver_stamp_and_listing_preserve_routing(monkeypatch, source, origin, expected):
    monkeypatch.setenv('HERMES_SESSION_DRIVER', 'codex')
    conn = sqlite3.connect(':memory:')
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        db = DriverDB(conn)
        db.create_session('s', source, origin_json=origin)
        rows = db.list_sessions_rich(include_children=True)
        assert len(rows) == 1
        assert rows[0]['driver'] == expected
        if origin:
            assert rows[0]['origin_json'] == origin
        elif expected:
            assert json.loads(rows[0]['origin_json']) == {'driver': expected}
    finally:
        conn.close()


@pytest.mark.parametrize('env,expected', [
    ({}, None), ({'HERMES_SESSION_DRIVER': ' Codex '}, 'codex'),
    ({'CLAUDECODE': '1'}, 'claude-code'),
    ({'CLAUDE_CODE_ENTRYPOINT': 'cli'}, 'claude-code'),
    ({'HERMES_SESSION_DRIVER': 'invalid slug', 'CLAUDECODE': '1'}, None),
])
def test_driver_detection_preserves_local_precedence(env, expected):
    assert detect_session_driver(env) == expected
