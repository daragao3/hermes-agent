"""Real SQL peer-routing contracts; no gateway or external messages are used."""
import json
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_gateway import SessionGatewayMixin


class PeerRows(SessionGatewayMixin):
    def __init__(self, conn):
        self.conn = conn

    def _execute_write(self, fn):
        with self.conn:
            return fn(self.conn)

    def _own_profile_name(self):
        return 'fixture-profile'


@pytest.fixture
def peers():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    try:
        yield PeerRows(conn)
    finally:
        conn.close()


def seed(peers, name, parent=None, source='telegram', config=None, end_reason=None):
    peers.conn.execute(
        'INSERT INTO sessions(id,source,started_at,parent_session_id,model_config,end_reason,session_key) '
        'VALUES (?,?,0,?,?,?,?)',
        (name, source, parent, json.dumps(config or {}), end_reason, 'original'))
    peers.conn.commit()


def test_missing_row_recovers_full_peer_identity(peers):
    peers.record_gateway_session_peer('s', source='telegram', user_id='u', session_key='route',
                                      chat_id='c', chat_type='group', thread_id='t',
                                      display_name='display', origin_json='{"origin":"retained"}')
    row = peers.conn.execute('SELECT * FROM sessions').fetchone()
    assert tuple(row[k] for k in ('id', 'source', 'user_id', 'session_key', 'chat_id', 'chat_type',
                                 'thread_id', 'display_name', 'origin_json', 'profile_name')) == (
        's', 'telegram', 'u', 'route', 'c', 'group', 't', 'display', '{"origin":"retained"}', 'fixture-profile')


def test_refresh_preserves_unsupplied_presentation_and_origin(peers):
    peers.record_gateway_session_peer('s', source='telegram', session_key='old',
                                      display_name='display', origin_json='{"origin":"retained"}')
    peers.record_gateway_session_peer('s', source='discord', session_key='new', chat_id='other')
    row = peers.conn.execute('SELECT * FROM sessions').fetchone()
    assert tuple(row[k] for k in ('source', 'session_key', 'chat_id', 'display_name', 'origin_json')) == (
        'discord', 'new', 'other', 'display', '{"origin":"retained"}')
    peers.record_gateway_session_peer('s', source='discord', session_key='new', display_name='', origin_json='')
    assert tuple(peers.conn.execute('SELECT display_name,origin_json FROM sessions').fetchone()) == ('', '')


@pytest.mark.parametrize(('include_ancestors', 'source', 'config', 'parent_reason', 'expected_parent'), [
    (False, 'telegram', {}, 'compression', 'original'),
    (True, 'telegram', {}, 'compression', 'new'),
    (True, 'telegram', {'_branched_from': 'parent'}, 'compression', 'original'),
    (True, 'telegram', {'_delegate_from': 'parent'}, 'compression', 'original'),
    (True, 'tool', {}, 'compression', 'original'),
    (True, 'telegram', {}, 'reset', 'original'),
])
def test_resume_routing_stops_at_non_compression_lineage(peers, include_ancestors, source, config, parent_reason, expected_parent):
    seed(peers, 'parent', end_reason=parent_reason)
    seed(peers, 'child', parent='parent', source=source, config=config)
    seed(peers, 'unrelated')
    peers.record_gateway_session_peer('child', source='discord', session_key='new',
                                      include_compression_ancestors=include_ancestors)
    keys = dict(peers.conn.execute('SELECT id,session_key FROM sessions').fetchall())
    assert keys == {'parent': expected_parent, 'child': 'new', 'unrelated': 'original'}
