"""Offline conversion contracts against actual frozen local DDL."""
import hashlib
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def local_snapshot(tmp_path):
    path = tmp_path / 'local.db'
    with sqlite3.connect(path) as conn:
        conn.executescript((Path(__file__).parent / 'fixtures/local33-schema.sql').read_text())
        conn.execute('INSERT INTO schema_version VALUES (33)')
        conn.execute("INSERT INTO sessions(id, source, started_at, system_prompt) VALUES ('s', 'cli', 0, 'preserve prompt')")
        conn.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES ('s', 'user', 'preserve transcript needle', 0)")
    return path


def test_inspection_preserves_source_and_identifies_both_domains(local_snapshot):
    from hermes_state_conversion import inspect_local_snapshot
    before = hashlib.sha256(local_snapshot.read_bytes()).digest()
    report = inspect_local_snapshot(local_snapshot)
    assert report['source_domain'] == 'hermes-local-33'
    assert report['fts_layout'] == 'single-column-external'
    assert report['sessions'] == 1 and report['messages'] == 1
    assert 'session_bridge_migrations' in report['tables']
    assert hashlib.sha256(local_snapshot.read_bytes()).digest() == before


def test_finish_owned_copy_after_interrupted_fts_reuses_source(local_snapshot, tmp_path, monkeypatch):
    import time
    import hermes_state_conversion as conversion
    from hermes_state_schema import SessionSchemaMixin
    before = hashlib.sha256(local_snapshot.read_bytes()).digest()
    destination = tmp_path / 'resumed.db'
    original = SessionSchemaMixin._rebuild_fts_indexes

    def interrupted(*args, **kwargs):
        raise sqlite3.OperationalError('interrupted')

    monkeypatch.setattr(SessionSchemaMixin, '_rebuild_fts_indexes', staticmethod(interrupted))
    with pytest.raises(sqlite3.OperationalError, match='interrupted'):
        conversion.convert_local_snapshot(local_snapshot, destination)
    stages = list(tmp_path.glob('.hermes-conversion-*/state.db'))
    assert len(stages) == 1 and not destination.exists()
    monkeypatch.setattr(SessionSchemaMixin, '_rebuild_fts_indexes', staticmethod(original))
    report = conversion.inspect_local_snapshot(local_snapshot)
    result = conversion._finish_local_snapshot_conversion(
        local_snapshot, destination, stages[0], report, time.monotonic() + 60,
    )
    assert result['messages'] == 1
    assert destination.exists() and not stages[0].exists()
    assert hashlib.sha256(local_snapshot.read_bytes()).digest() == before


def test_finish_owned_copy_preserves_files_when_space_is_insufficient(local_snapshot, tmp_path, monkeypatch):
    import shutil
    import time
    from types import SimpleNamespace
    import hermes_state_conversion as conversion
    stage = tmp_path / '.hermes-conversion-budget' / 'state.db'
    stage.parent.mkdir()
    shutil.copyfile(local_snapshot, stage)
    before = stage.read_bytes()
    report = conversion.inspect_local_snapshot(local_snapshot)
    monkeypatch.setattr(conversion.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(RuntimeError, match='Insufficient disk reserve'):
        conversion._finish_local_snapshot_conversion(
            local_snapshot, tmp_path / 'refused.db', stage, report, time.monotonic() + 60,
        )
    assert stage.read_bytes() == before == local_snapshot.read_bytes()
    assert not (tmp_path / 'refused.db').exists()


@pytest.mark.parametrize('version', [33, 34])
def test_conversion_preserves_registry_values_across_local_domains(local_snapshot, tmp_path, version):
    from contextlib import closing
    from hermes_state_conversion import convert_local_snapshot
    from hermes_state import SessionDB
    from session_bridge.store import SessionBridgeStore
    value = '{"state":"present","value":"shared baseline"}'
    digest = hashlib.sha256(value.encode()).hexdigest()
    with closing(sqlite3.connect(local_snapshot)) as conn:
        if version == 34:
            conn.execute('DROP TABLE desktop_registry_baselines')
            conn.executescript((Path(__file__).parent / 'fixtures/local34-registry-schema.sql').read_text())
            conn.execute('INSERT INTO desktop_registry_values VALUES (?,?)', (digest, value))
            conn.execute("INSERT INTO session_bridge_migrations VALUES ('desktop_registry_values_v34',0)")
        conn.execute('INSERT INTO desktop_registry_baselines VALUES (?,?,?,?,?,?)',
                     ('a.json', 'root', 'field:title', digest if version == 34 else value, 3, 0))
        conn.execute('UPDATE schema_version SET version=?', (version,))
        conn.commit()
    before = local_snapshot.read_bytes()
    destination = tmp_path / 'converted-registry.db'
    convert_local_snapshot(local_snapshot, destination)
    assert local_snapshot.read_bytes() == before
    with SessionDB(destination) as db:
        rows = SessionBridgeStore(db).load_desktop_registry_baselines()
        assert len(rows) == 1 and rows[0]['value_json'] == value and rows[0]['revision'] == 3
        assert db.get_meta('schema_conversion_source_domain') == f'hermes-local-{version}'


@pytest.mark.parametrize('damage', ['version', 'ledger', 'fts'])
def test_inspection_refuses_unknown_or_partial_authority(local_snapshot, damage):
    from hermes_state_conversion import inspect_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        if damage == 'version':
            conn.execute('UPDATE schema_version SET version=34')
        elif damage == 'ledger':
            conn.execute('DROP TABLE session_sidebar_v2_attempt_zero_resolutions')
        else:
            conn.execute('DROP TABLE messages_fts')
    before = local_snapshot.read_bytes()
    with pytest.raises((ValueError, RuntimeError), match='history|schema|FTS'):
        inspect_local_snapshot(local_snapshot)
    assert local_snapshot.read_bytes() == before


def test_inspection_does_not_create_missing_source(tmp_path):
    from hermes_state_conversion import inspect_local_snapshot
    path = tmp_path / 'absent.db'
    with pytest.raises(FileNotFoundError):
        inspect_local_snapshot(path)
    assert not path.exists()


def test_inspection_refuses_wal_snapshot_without_creating_sidecars(local_snapshot):
    from hermes_state_conversion import inspect_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    conn.close()
    before = {p.name for p in local_snapshot.parent.iterdir()}
    with pytest.raises(ValueError, match='detached and checkpointed'):
        inspect_local_snapshot(local_snapshot)
    assert {p.name for p in local_snapshot.parent.iterdir()} == before


def test_inspection_refuses_ambiguous_version_rows(local_snapshot):
    from hermes_state_conversion import inspect_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute('INSERT INTO schema_version VALUES (30)')
    with pytest.raises(ValueError, match='one local33 version row'):
        inspect_local_snapshot(local_snapshot)


def test_offline_conversion_preserves_history_and_reopens(local_snapshot):
    from hermes_state_conversion import convert_local_snapshot
    from hermes_state import SessionDB
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute("INSERT INTO session_bridge_state VALUES ('fixture-proof', '{\"keep\":true}', 0)")
    before = local_snapshot.read_bytes()
    destination = local_snapshot.with_name('converted.db')
    convert_local_snapshot(local_snapshot, destination)
    assert local_snapshot.read_bytes() == before
    with SessionDB(destination) as db:
        assert db.get_session('s')['system_prompt'] == 'preserve prompt'
        assert db.get_messages('s')[0]['content'] == 'preserve transcript needle'
        assert db.search_messages('needle')
        assert db._conn.execute("SELECT value_json FROM session_bridge_state WHERE key='fixture-proof'").fetchone()[0] == '{"keep":true}'
        db._conn.execute("UPDATE messages SET content='replacement horizon' WHERE session_id='s'")
        db._conn.commit()
        assert db.search_messages('horizon')
        assert not db.search_messages('needle')
        db._conn.execute("DELETE FROM messages WHERE session_id='s'")
        db._conn.commit()
        assert not db.search_messages('horizon')
    with SessionDB(destination) as db:
        assert db.get_session('s')['system_prompt'] == 'preserve prompt'
        assert db.get_meta('schema_conversion_source_domain') == 'hermes-local-33'


def test_conversion_never_overwrites_destination(local_snapshot):
    from hermes_state_conversion import convert_local_snapshot
    destination = local_snapshot.with_name('existing.db')
    destination.write_bytes(b'keep existing artifact')
    with pytest.raises(FileExistsError):
        convert_local_snapshot(local_snapshot, destination)
    assert destination.read_bytes() == b'keep existing artifact'


def test_failed_verification_never_publishes_or_changes_source(local_snapshot, monkeypatch):
    import hermes_state_conversion as conversion
    destination = local_snapshot.with_name('unpublished.db')
    before = local_snapshot.read_bytes()

    def reject(*args):
        raise RuntimeError('injected verification failure')

    monkeypatch.setattr(conversion, '_verify_preserved_rows', reject)
    with pytest.raises(RuntimeError, match='injected verification failure'):
        conversion.convert_local_snapshot(local_snapshot, destination)
    assert not destination.exists()
    assert local_snapshot.read_bytes() == before


def test_conversion_preserves_word_search_and_filters_trigram(local_snapshot):
    from hermes_state import SessionDB
    from hermes_state_common import FTS_TOOL_CONTENT_PREFIX_CHARS
    from hermes_state_conversion import convert_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        for session_id, source in [('scheduled', 'cron'), ('child', 'subagent')]:
            conn.execute('INSERT INTO sessions(id,source,started_at) VALUES (?,?,0)', (session_id, source))
            conn.execute('INSERT INTO messages(session_id,role,content,timestamp) VALUES (?,\'user\',?,0)', (session_id, source + 'needle'))
        historical = 'padding ' * FTS_TOOL_CONTENT_PREFIX_CHARS + 'historicaltail'
        conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES ('s','tool',?,0)", (historical,))
    destination = local_snapshot.with_name('search.db')
    convert_local_snapshot(local_snapshot, destination)
    with SessionDB(destination) as db:
        word = lambda term: db._conn.execute('SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?', (term,)).fetchall()
        assert word('historicaltail') and word('cronneedle') and word('subagentneedle')
        assert len(db._conn.execute("SELECT rowid FROM messages_fts_trigram WHERE messages_fts_trigram MATCH 'needle'").fetchall()) == 1
        db.append_message('s', 'tool', content='padding ' * FTS_TOOL_CONTENT_PREFIX_CHARS + 'newtail')
        assert not word('newtail')


@pytest.mark.parametrize('lost', ['ftsXproof', 'fts_custom_proof', 'unknown_table', 'message'])
def test_conversion_detects_real_row_loss(local_snapshot, monkeypatch, lost):
    import hermes_state_conversion as conversion
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute('CREATE TABLE messages_fts_user_evidence(value TEXT)')
        conn.execute("INSERT INTO messages_fts_user_evidence VALUES ('preserve evidence')")
        conn.executemany('INSERT INTO state_meta(key,value) VALUES (?,?)', [('ftsXproof', 'keep'), ('fts_custom_proof', 'keep')])
    conn.close()
    original_verify = conversion._verify_preserved_rows

    def damage_then_verify(conn, source):
        if lost == 'unknown_table':
            conn.execute('DELETE FROM messages_fts_user_evidence')
        elif lost == 'message':
            conn.execute('DELETE FROM messages')
        else:
            conn.execute('DELETE FROM state_meta WHERE key=?', (lost,))
        conn.commit()
        original_verify(conn, source)

    monkeypatch.setattr(conversion, '_verify_preserved_rows', damage_then_verify)
    before = local_snapshot.read_bytes()
    destination = local_snapshot.with_name('must-not-publish.db')
    with pytest.raises(RuntimeError, match='preserve source rows|row cardinality'):
        conversion.convert_local_snapshot(local_snapshot, destination)
    assert not destination.exists()
    assert local_snapshot.read_bytes() == before


def test_conversion_repairs_usage_key_without_losing_task_history(local_snapshot):
    from hermes_state_conversion import convert_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute("UPDATE sessions SET model='fixture', input_tokens=42, api_call_count=1 WHERE id='s'")
        conn.execute("INSERT INTO session_model_usage(session_id,model,task,input_tokens) VALUES ('s','fixture','vision',7)")
        conn.execute('ALTER TABLE session_model_usage RENAME TO old_usage')
        conn.execute('CREATE TABLE session_model_usage AS SELECT * FROM old_usage')
        conn.execute('DROP TABLE old_usage')
    conn.close()
    destination = local_snapshot.with_name('usage.db')
    convert_local_snapshot(local_snapshot, destination)
    with sqlite3.connect(destination) as conn:
        assert conn.execute('SELECT task,input_tokens FROM session_model_usage ORDER BY task').fetchall() == [('',42), ('vision',7)]
        assert any(row[1] == 'task' and row[5] > 0 for row in conn.execute('PRAGMA table_info(session_model_usage)'))
    conn.close()


def test_publication_race_preserves_other_artifact(local_snapshot, monkeypatch):
    import hermes_state_conversion as conversion
    destination = local_snapshot.with_name('raced.db')
    link = conversion.os.link

    def race(source, target):
        Path(target).write_bytes(b'other publisher won')
        return link(source, target)

    monkeypatch.setattr(conversion.os, 'link', race)
    before = local_snapshot.read_bytes()
    with pytest.raises(FileExistsError):
        conversion.convert_local_snapshot(local_snapshot, destination)
    assert destination.read_bytes() == b'other publisher won'
    assert local_snapshot.read_bytes() == before


def test_conversion_refuses_new_foreign_key_violation(local_snapshot, monkeypatch):
    import hermes_state_conversion as conversion
    verify = conversion._verify_preserved_rows

    def inject_violation(conn, source):
        conn.execute('CREATE TABLE extra_child(id TEXT REFERENCES sessions(id))')
        conn.execute("INSERT INTO extra_child VALUES ('missing-parent')")
        conn.commit()
        verify(conn, source)

    monkeypatch.setattr(conversion, '_verify_preserved_rows', inject_violation)
    destination = local_snapshot.with_name('invalid-reference.db')
    with pytest.raises(RuntimeError, match='foreign key'):
        conversion.convert_local_snapshot(local_snapshot, destination)
    assert not destination.exists()


def test_conversion_preserves_existing_orphan_without_new_violations(local_snapshot):
    from hermes_state_conversion import convert_local_snapshot
    with sqlite3.connect(local_snapshot) as conn:
        conn.execute('CREATE TABLE legacy_child(id TEXT REFERENCES sessions(id))')
        conn.execute("INSERT INTO legacy_child VALUES ('historical-orphan')")
    conn.close()
    destination = local_snapshot.with_name('preserved-orphan.db')
    convert_local_snapshot(local_snapshot, destination)
    with sqlite3.connect(destination) as conn:
        assert conn.execute('SELECT id FROM legacy_child').fetchall() == [('historical-orphan',)]
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == [('legacy_child', 1, 'sessions', 0)]
    conn.close()


def test_preservation_checks_ordinary_table_with_shadow_like_name(tmp_path):
    from hermes_state_conversion import _verify_preserved_rows
    source = tmp_path / 'source.db'
    target = tmp_path / 'target.db'
    for path in (source, target):
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE messages_fts_content(value TEXT)')
            if path == source:
                conn.execute("INSERT INTO messages_fts_content VALUES ('ordinary evidence')")
        conn.close()
    conn = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True)
    try:
        with pytest.raises(RuntimeError, match='preserve source rows'):
            _verify_preserved_rows(conn, source)
    finally:
        conn.close()


def test_offline_conversion_builds_each_index_once(local_snapshot, monkeypatch):
    from hermes_state_conversion import convert_local_snapshot
    original_connect = sqlite3.connect
    rebuilds = []

    def trace(statement):
        normalized = ''.join(statement.lower().split())
        if "values('rebuild')" in normalized:
            rebuilds.append(normalized)

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(sqlite3, 'connect', connect)
    convert_local_snapshot(local_snapshot, local_snapshot.with_name('single-build.db'))
    for table in ('messages_fts', 'messages_fts_trigram'):
        assert sum(statement.startswith(f'insertinto{table}({table})') for statement in rebuilds) == 1


@pytest.mark.parametrize('deadline', [float('nan'), float('inf')])
def test_snapshot_inspection_requires_finite_deadline(local_snapshot, deadline):
    from hermes_state_conversion import inspect_local_snapshot
    with pytest.raises(ValueError, match='finite'):
        inspect_local_snapshot(local_snapshot, timeout_seconds=deadline)


def test_conversion_disk_reserve_refuses_before_creating_work(local_snapshot, monkeypatch):
    import hermes_state_conversion as conversion
    from types import SimpleNamespace
    monkeypatch.setattr(conversion.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    before = {p.name for p in local_snapshot.parent.iterdir()}
    with pytest.raises(RuntimeError, match='disk reserve'):
        conversion.convert_local_snapshot(local_snapshot, local_snapshot.with_name('low-disk.db'))
    assert {p.name for p in local_snapshot.parent.iterdir()} == before


def test_conversion_admission_refusal_preserves_source(local_snapshot, monkeypatch):
    import hermes_state_common
    from contextlib import contextmanager
    from hermes_state_conversion import convert_local_snapshot

    @contextmanager
    def denied(*args):
        yield False

    monkeypatch.setattr(hermes_state_common, 'fts_rebuild_admission', denied)
    before = local_snapshot.read_bytes()
    destination = local_snapshot.with_name('not-admitted.db')
    with pytest.raises(RuntimeError, match='admission refused'):
        convert_local_snapshot(local_snapshot, destination)
    assert not destination.exists()
    assert local_snapshot.read_bytes() == before
