"""Explicit offline migration support for the independent local schema history.

Inspection is read-only. It neither authorizes a version relabel nor opens the
source through SessionDB (whose normal constructor performs migrations).
"""
import math
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from hermes_state_bridge_schema import SessionBridgeSchemaMixin


_REPLACED_FTS_METADATA = (
    'fts_rebuild_high_water', 'fts_rebuild_progress',
    'fts_tool_full_content_high_water', 'fts_storage_version',
    'fts_optimize_available', 'fts_stale', 'fts_rebuild_deferral', 'fts_cjk_stale',
)
_DERIVED_FTS_TABLES = {
    name + suffix
    for name in ('messages_fts', 'messages_fts_trigram', 'messages_fts_cjk')
    for suffix in ('', '_data', '_idx', '_content', '_docsize', '_config')
}


def inspect_local_snapshot(path: Path, *, timeout_seconds: float = 30.0) -> dict:
    """Validate a detached local-v33 snapshot without changing its contents.

    Require a checkpointed rollback-journal snapshot. Reading a live WAL store
    can create shared-memory sidecars; the later snapshot producer must handle
    that separately, rather than pretending this inspection is a live backup.
    This establishes source eligibility, not successful target conversion.
    """
    path = Path(path).resolve(strict=True)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('Inspection deadline must be finite and positive')
    with path.open('rb') as source:
        header = source.read(100)
    if header[:16] != b'SQLite format 3\x00':
        raise ValueError('Unknown SQLite snapshot history')
    if header[18:20] != b'\x01\x01' or any(
        Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')
    ):
        raise ValueError('Snapshot must be detached and checkpointed before inspection')
    deadline = time.monotonic() + timeout_seconds
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn.execute('BEGIN')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'schema_version' not in tables:
            raise ValueError('Unknown schema history: missing version')
        versions = conn.execute('SELECT version FROM schema_version').fetchall()
        if versions not in ([(33,)], [(34,)]):
            raise ValueError('Unknown schema history: expected one local33/local34 version row')
        source_version = versions[0][0]
        required = {'sessions', 'messages', 'session_bridge_migrations', 'state_meta'}
        if not required <= tables:
            raise ValueError('Incomplete local33 schema')
        SessionBridgeSchemaMixin._validate_v33_sidebar_resolution_schema(conn.cursor())
        if source_version == 34:
            from hermes_state_bridge_schema import desktop_registry_value_hash
            baseline_columns = {r[1] for r in conn.execute('PRAGMA table_info(desktop_registry_baselines)')}
            if ('value_hash' not in baseline_columns or 'value_json' in baseline_columns
                    or 'desktop_registry_values' not in tables
                    or conn.execute("SELECT 1 FROM session_bridge_migrations WHERE migration_name='desktop_registry_values_v34'").fetchone() is None):
                raise ValueError('Incomplete local34 registry schema')
            for digest, value in conn.execute('SELECT value_hash,value_json FROM desktop_registry_values'):
                if not isinstance(value, str) or desktop_registry_value_hash(value) != digest:
                    raise ValueError('Invalid local34 registry content address')
            if conn.execute('SELECT 1 FROM desktop_registry_baselines b LEFT JOIN desktop_registry_values v ON b.value_hash=v.value_hash WHERE v.value_hash IS NULL LIMIT 1').fetchone():
                raise ValueError('Missing local34 registry value')
        declaration = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ).fetchone()
        columns = [row[1] for row in conn.execute('PRAGMA table_info(messages_fts)')]
        if (declaration is None or columns != ['content'] or
                "content='messages_fts_source'" not in ''.join(declaration[0].split())):
            raise ValueError('Unknown local33 FTS layout')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='view' AND name='messages_fts_source'").fetchone() is None:
            raise ValueError('Incomplete local33 FTS source view')
        if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Snapshot schema/data integrity check failed')
        return {
            'source_domain': f'hermes-local-{source_version}',
            'source_version': source_version,
            'fts_layout': 'single-column-external',
            'sessions': conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],
            'messages': conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0],
            'tables': sorted(tables),
            'bridge_migrations': [row[0] for row in conn.execute(
                'SELECT migration_name FROM session_bridge_migrations ORDER BY migration_name')],
        }
    finally:
        conn.close()


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _verify_preserved_rows(conn, source):
    """Every original non-derived row must survive, including unknown tables.

    EXCEPT checks row values without moving transcripts into Python memory.
    Row cardinality is checked separately; migrations may add accounting/ledger
    records but cannot silently discard original values.
    """
    conn.execute('ATTACH DATABASE ? AS original', (source.as_uri() + '?mode=ro',))
    tables = [r[0] for r in conn.execute("SELECT name FROM original.sqlite_master WHERE type='table'")]
    derived_tables = {row[1] for row in conn.execute('PRAGMA original.table_list')
                      if row[1] in _DERIVED_FTS_TABLES and row[2] in ('virtual', 'shadow')}
    for table in tables:
        if table == 'schema_version' or table.startswith('sqlite_') or table in derived_tables:
            continue
        name = _quoted(table)
        columns = [r[1] for r in conn.execute(f'PRAGMA original.table_info({name})')]
        projection = ', '.join(_quoted(c) for c in columns)
        target_projection = projection
        if table == 'sessions':
            # Local stores may already have deduplicated prompts. Compare the
            # logical prompt on BOTH sides, rather than NULL against its text.
            if 'system_prompt_hash' in columns and 'system_prompts' in tables:
                projection = ', '.join(
                    'COALESCE((SELECT prompt FROM original.system_prompts '
                    'WHERE hash=original.sessions.system_prompt_hash), system_prompt)'
                    if c == 'system_prompt' else _quoted(c) for c in columns)
            target_projection = ', '.join(
                'COALESCE((SELECT prompt FROM system_prompts WHERE hash=sessions.system_prompt_hash), system_prompt)'
                if c == 'system_prompt' else _quoted(c) for c in columns)
        if table == 'desktop_registry_baselines' and 'value_json' in columns:
            target_projection = ', '.join(
                '(SELECT value_json FROM main.desktop_registry_values v WHERE v.value_hash=desktop_registry_baselines.value_hash)'
                if c == 'value_json' else _quoted(c) for c in columns)
        # FTS bookkeeping is deliberately replaced by the new complete index.
        parameters = _REPLACED_FTS_METADATA if table == 'state_meta' else ()
        where = ' WHERE key NOT IN (' + ','.join('?' for _ in parameters) + ')' if parameters else ''
        if conn.execute(
            f'SELECT {projection} FROM original.{name}{where} EXCEPT '
            f'SELECT {target_projection} FROM main.{name}{where} LIMIT 1',
            parameters + parameters,
        ).fetchone() is not None:
            raise RuntimeError(f'Conversion did not preserve source rows in {table}')
        if table not in ('state_meta', 'session_bridge_migrations', 'session_model_usage'):
            old_count = conn.execute(f'SELECT COUNT(*) FROM original.{name}').fetchone()[0]
            new_count = conn.execute(f'SELECT COUNT(*) FROM main.{name}').fetchone()[0]
            if old_count != new_count:
                raise RuntimeError(f'Conversion changed row cardinality in {table}')
    previous_violations = {tuple(row) for row in conn.execute('PRAGMA original.foreign_key_check')}
    converted_violations = {tuple(row) for row in conn.execute('PRAGMA main.foreign_key_check')}
    if converted_violations - previous_violations:
        raise RuntimeError('Conversion introduced a foreign key violation')
    conn.execute('DETACH DATABASE original')


def convert_local_snapshot(source: Path, destination: Path, *, timeout_seconds=300.0) -> dict:
    """Convert an offline snapshot and publish only a verified, closed artifact.

    The source is never passed to a writer. A unique work directory is retained
    on failure for diagnosis. Publication creates a new link and cannot overwrite
    another artifact; production cutover is a separate operation.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    report = inspect_local_snapshot(source, timeout_seconds=timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    if shutil.disk_usage(destination.parent).free < source.stat().st_size * 3 + 256 * 1024**2:
        raise RuntimeError('Insufficient disk reserve for offline conversion')
    work = Path(tempfile.mkdtemp(prefix='.hermes-conversion-', dir=destination.parent))
    staged = work / 'state.db'

    def check_deadline(*_):
        if time.monotonic() >= deadline:
            raise TimeoutError('Offline conversion deadline exceeded')

    original = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1)
    clone = sqlite3.connect(staged)
    try:
        original.backup(clone, pages=256, progress=check_deadline)
    finally:
        original.close()
        clone.close()
    # Validate the actual copied snapshot, not merely the pre-copy source.
    inspect_local_snapshot(staged, timeout_seconds=max(0.001, deadline - time.monotonic()))
    return _finish_local_snapshot_conversion(source, destination, staged, report, deadline)


def _finish_local_snapshot_conversion(source, destination, staged, report, deadline):
    """Finish an owned, already validated copy, including an interrupted FTS rebuild.

    Internal operational boundary: the original copy and source-inspection
    evidence must already exist. Full preservation verification still runs
    before publication; this never accepts a partially migrated core schema.
    """
    from hermes_state import SessionDB
    from hermes_state_common import FTS_SQL, FTS_TRIGRAM_SQL, SCHEMA_VERSION, fts_rebuild_admission
    from hermes_state_schema import SessionSchemaMixin

    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    staged = Path(staged)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if staged.is_symlink():
        raise ValueError('Conversion working copy must not be a symlink')
    staged = staged.resolve(strict=True)
    if (staged == source or staged.parent.parent != destination.parent.resolve()
            or not staged.parent.name.startswith('.hermes-conversion-')):
        raise ValueError('Conversion working copy is outside its owned staging directory')
    with closing(sqlite3.connect(staged.as_uri() + '?mode=ro', uri=True)) as guard:
        if guard.execute('SELECT version FROM schema_version').fetchall() != [(report['source_version'],)]:
            raise ValueError('Conversion working copy has already entered core migration')
    # The original three-copy reserve has already paid for this existing copy.
    if shutil.disk_usage(destination.parent).free < source.stat().st_size * 2 + 256 * 1024**2:
        raise RuntimeError('Insufficient disk reserve to finish offline conversion')

    def check_deadline():
        if time.monotonic() >= deadline:
            raise TimeoutError('Offline conversion deadline exceeded')

    check_deadline()

    def fts_catalog(conn):
        return tuple(tuple(row) for row in conn.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name IN ('messages_fts_trigram','messages_fts_trigram_src',"
            "'messages_fts_trigram_insert','messages_fts_trigram_update','messages_fts_trigram_delete') "
            "ORDER BY type,name"))

    completed_fts_catalog = None

    class OfflineConversionDB(SessionDB):
        def _init_schema(self):
            self._conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            super()._init_schema(_offline_local33_conversion=True)

        def _migrate_trigram_cron_exclusion(self, cursor):
            # The unpublished clone was just rebuilt from CURRENT source-filtered
            # DDL under admission. Replaying the historic v29/v30 full rebuild
            # would scan a potentially multi-GB transcript twice. Require the
            # same completed catalog here; final FTS integrity verification still
            # proves index/data agreement before anything can be published.
            if completed_fts_catalog is None or fts_catalog(cursor) != completed_fts_catalog:
                raise RuntimeError('Offline FTS conversion completion proof changed')
            return True

    with fts_rebuild_admission(staged) as admitted:
        if not admitted:
            raise RuntimeError('Offline conversion FTS admission refused')
        with closing(sqlite3.connect(staged)) as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            # These are disposable derived indexes in the unpublished copy only.
            # Canonical messages, bridge ledgers and unknown source objects stay.
            for table in ('messages_fts', 'messages_fts_trigram'):
                for suffix in ('insert', 'update', 'delete'):
                    conn.execute(f'DROP TRIGGER IF EXISTS {table}_{suffix}')
                conn.execute(f'DROP TABLE IF EXISTS {table}')
            conn.execute('DROP VIEW IF EXISTS messages_fts_trigram_src')
            conn.executescript(FTS_SQL + FTS_TRIGRAM_SQL)
            SessionSchemaMixin._rebuild_fts_indexes(conn.cursor())
            conn.commit()
            completed_fts_catalog = fts_catalog(conn)
        # Release admission before initialization takes its own existing gate.
    with OfflineConversionDB(staged) as db:
        if db._conn.execute('SELECT version FROM schema_version').fetchall()[0][0] != SCHEMA_VERSION:
            raise RuntimeError('Offline migration chain did not complete')
        for table in ('messages_fts', 'messages_fts_trigram'):
            db._conn.execute(f"INSERT INTO {table}({table}, rank) VALUES ('integrity-check', 1)")
        if db._conn.execute('PRAGMA quick_check').fetchall()[0][0] != 'ok':
            raise RuntimeError('Converted database integrity check failed')
        db.set_meta('schema_conversion_source_domain', report['source_domain'])
        db.set_meta('schema_conversion_source_version', str(report['source_version']))
        db.set_meta('schema_conversion_target_version', str(SCHEMA_VERSION))
    # A normal open must now work without the explicit conversion entry point.
    with SessionDB(staged) as reopened:
        if reopened.get_meta('schema_conversion_source_domain') != report['source_domain']:
            raise RuntimeError('Conversion provenance did not survive reopen')
    # URI processing must be enabled on THIS connection for the attached source
    # to honor mode=ro. Normal SessionDB connections intentionally do not enable it.
    with closing(sqlite3.connect(staged.as_uri() + '?mode=rw', uri=True)) as verification:
        verification.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        _verify_preserved_rows(verification, source)
    check_deadline()
    # Materialize a standalone rollback-journal artifact even on a WAL runtime.
    with closing(sqlite3.connect(staged)) as conn:
        if conn.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
            raise RuntimeError('Converted snapshot did not detach from WAL')
    os.link(staged, destination)  # atomic fail-if-exists, no replacement race
    staged.unlink()  # remove only our exact temporary link; keep work directory
    return {**report, 'target_version': SCHEMA_VERSION, 'destination': str(destination)}
