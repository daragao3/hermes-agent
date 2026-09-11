"""Legacy inline prompts must migrate even across fork version-number collisions."""
import hashlib
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_schema import SessionSchemaMixin


class Migrator(SessionSchemaMixin):
    @staticmethod
    def _store_system_prompt(conn, prompt):
        digest = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        conn.execute('INSERT OR IGNORE INTO system_prompts(hash, prompt) VALUES (?, ?)', (digest, prompt))
        return digest


@pytest.mark.parametrize('version', [24, 30, 33])
def test_inline_prompt_migration_uses_data_state(version):
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute('INSERT INTO schema_version VALUES (?)', (version,))
        conn.execute("INSERT INTO sessions(id, source, started_at, system_prompt) VALUES ('s','cli',0,'retained prompt')")
        db = Migrator()
        db._run_data_migrations(conn.cursor(), version, False)
        row = conn.execute('SELECT s.system_prompt, p.prompt FROM sessions s '
                           'LEFT JOIN system_prompts p ON p.hash=s.system_prompt_hash').fetchone()
        assert row == (None, 'retained prompt')
        before = conn.total_changes
        db._run_data_migrations(conn.cursor(), version, False)
        assert conn.total_changes == before
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0] == version
    finally:
        conn.close()


def test_paused_migration_resumes_after_version_has_advanced():
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute('INSERT INTO schema_version VALUES (33)')
        conn.executemany('INSERT INTO sessions(id, source, started_at, system_prompt) VALUES (?, ?, 0, ?)',
                         [('a', 'cli', 'first'), ('b', 'cli', 'second')])

        class Paused(Migrator):
            def _store_system_prompt(self, cursor, prompt):
                if prompt == 'second':
                    raise sqlite3.OperationalError('database is locked')
                return super()._store_system_prompt(cursor, prompt)

        Paused()._run_data_migrations(conn.cursor(), 33, False)
        assert conn.execute("SELECT system_prompt FROM sessions WHERE id='b'").fetchone()[0] == 'second'
        assert conn.execute("SELECT system_prompt FROM sessions WHERE id='a'").fetchone()[0] is None
        Migrator()._run_data_migrations(conn.cursor(), 33, False)
        assert conn.execute('SELECT COUNT(*) FROM sessions WHERE system_prompt IS NOT NULL').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM system_prompts').fetchone()[0] == 2
    finally:
        conn.close()
