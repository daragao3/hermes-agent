"""Bounded synthetic-volume migration using historical DDL and real SQLite."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from hermes_state import SessionDB
from hermes_state_conversion import convert_local_snapshot


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@pytest.mark.timeout(180)
def test_ten_thousand_message_conversion():
    output = Path('C:/Users/diego/architecture-map/wave-execution/2026-09-08') / ('schema-scale-' + uuid.uuid4().hex[:8])
    output.mkdir()
    source, target = output / 'source.db', output / 'converted.db'
    with closing(sqlite3.connect(source)) as conn:
        conn.executescript((Path(__file__).parent / 'fixtures/local33-schema.sql').read_text())
        conn.execute('INSERT INTO schema_version VALUES (33)')
        for i in range(40):
            kind = 'cron' if i % 10 == 0 else 'subagent' if i % 10 == 1 else 'cli'
            config = '{"_delegate_from":"parent"}' if i == 2 else '{}'
            conn.execute('INSERT INTO sessions(id,source,started_at,system_prompt,model_config) VALUES (?,?,0,?,?)',
                         (str(i), kind, 'shared synthetic system prompt', config))
        conn.executemany('INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,?,?,?)',
                         ((str(i % 40), 'tool' if i % 5 == 0 else 'user',
                           f'scale{i:05d} ' + 'alpha beta gamma delta ' * 96, i)
                          for i in range(10000)))
        conn.commit()
    original_digest = digest(source)
    started = time.monotonic()
    report = convert_local_snapshot(source, target, timeout_seconds=120)
    duration = time.monotonic() - started
    assert digest(source) == original_digest
    with SessionDB(target) as db:
        assert db.search_messages('scale09999')
        assert db.get_session('39')['system_prompt'] == 'shared synthetic system prompt'
        word_count = db._conn.execute('SELECT COUNT(*) FROM messages_fts_docsize').fetchone()[0]
        trigram_count = db._conn.execute('SELECT COUNT(*) FROM messages_fts_trigram_docsize').fetchone()[0]
        assert word_count == 10000
        expected_trigram = sum(i % 5 != 0 and i % 40 != 2 and i % 10 not in (0, 1) for i in range(10000))
        assert trigram_count == expected_trigram
        assert db._conn.execute('SELECT COUNT(*) FROM system_prompts').fetchone()[0] == 1
    report.update(duration_seconds=duration, source_bytes=source.stat().st_size,
                  target_bytes=target.stat().st_size, source_sha256=original_digest,
                  target_sha256=digest(target), word_rows=word_count, trigram_rows=trigram_count,
                  scope='Synthetic scale acceptance, not production snapshot cutover')
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    print('Scale conversion evidence:', output, flush=True)
