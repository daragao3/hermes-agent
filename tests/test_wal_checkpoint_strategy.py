"""Tests for SessionDB WAL checkpoint strategy (issue #45383).

Verifies that periodic checkpoints use PASSIVE mode (safe for large DBs)
while close() and pre-VACUUM paths still use TRUNCATE.
"""

import sqlite3
import logging
from unittest.mock import MagicMock

import pytest

from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path):
    """Create a SessionDB with a temp database file."""
    db_path = tmp_path / "test_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    try:
        session_db.close()
    except Exception:
        pass


class TestTryWalCheckpointPassive:
    """_try_wal_checkpoint() should use PASSIVE mode for periodic use."""

    def test_checkpoint_uses_passive_mode(self, db):
        """PASSIVE checkpoint does not require exclusive lock — safe for large DBs."""
        # Capture the real connection's execute before mocking
        real_conn = db._conn
        execute_calls = []

        def tracking_execute(sql, *args, **kwargs):
            execute_calls.append(sql)
            return real_conn.execute(sql, *args, **kwargs)

        # sqlite3.Connection.execute is read-only (C extension) — replace _conn
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = tracking_execute
        mock_conn.fetchone.return_value = None
        db._conn = mock_conn

        db._try_wal_checkpoint()

        passive_calls = [c for c in execute_calls if "wal_checkpoint(PASSIVE)" in c]
        truncate_calls = [c for c in execute_calls if "wal_checkpoint(TRUNCATE)" in c]
        assert len(passive_calls) == 1, (
            f"Expected 1 PASSIVE checkpoint call, got {len(passive_calls)}"
        )
        assert len(truncate_calls) == 0, (
            "Periodic checkpoint should NOT use TRUNCATE"
        )

    def test_checkpoint_logs_warning_on_failure(self, db, caplog):
        """Failed PASSIVE checkpoint logs a warning instead of silent pass."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")
        db._conn = mock_conn

        with caplog.at_level(logging.WARNING):
            db._try_wal_checkpoint()

        assert any("WAL checkpoint (PASSIVE) failed" in r.message for r in caplog.records), (
            f"Expected warning log about PASSIVE checkpoint failure, got: {caplog.text}"
        )

    def test_checkpoint_returns_result_on_success(self, db):
        """Successful PASSIVE checkpoint does not raise."""
        db._try_wal_checkpoint()


class TestCloseUsesTruncate:
    """close() should still use TRUNCATE to shrink WAL on shutdown."""

    def test_close_uses_truncate_mode(self, db):
        """TRUNCATE at close is safe — no concurrent writers during shutdown."""
        real_conn = db._conn
        execute_calls = []

        def tracking_execute(sql, *args, **kwargs):
            execute_calls.append(sql)
            return real_conn.execute(sql, *args, **kwargs)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = tracking_execute
        db._conn = mock_conn

        db.close()

        truncate_calls = [c for c in execute_calls if "wal_checkpoint(TRUNCATE)" in c]
        assert len(truncate_calls) == 1, (
            f"Expected 1 TRUNCATE checkpoint at close, got {len(truncate_calls)}"
        )

    def test_close_logs_debug_on_failure(self, db, caplog):
        """Failed TRUNCATE at close logs debug (not warning — close is best-effort)."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = sqlite3.OperationalError("database is locked")
        db._conn = mock_conn

        with caplog.at_level(logging.DEBUG):
            db.close()

        assert any("WAL checkpoint (TRUNCATE) at close failed" in r.message for r in caplog.records), (
            f"Expected debug log about TRUNCATE failure at close, got: {caplog.text}"
        )


class TestCheckpointFrequency:
    """Checkpoint triggers every N writes."""

    def test_checkpoint_triggers_at_interval(self, db):
        """_try_wal_checkpoint is called every _CHECKPOINT_EVERY_N_WRITES writes."""
        call_count = [0]
        original = db._try_wal_checkpoint

        def counting_checkpoint():
            call_count[0] += 1
            original()

        db._try_wal_checkpoint = counting_checkpoint

        # Write exactly _CHECKPOINT_EVERY_N_WRITES sessions to trigger one checkpoint
        n = db._CHECKPOINT_EVERY_N_WRITES
        import time as _time
        for i in range(n):
            db._execute_write(lambda conn, _i=i: conn.execute(
                "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
                (f"sess_{_i}", "test", _time.time()),
            ))

        assert call_count[0] == 1, (
            f"Expected 1 checkpoint after {n} writes, got {call_count[0]}"
        )


class TestCloseSkipsCheckpointOnReadOnlyHandles:
    """A read_only handle must NOT attempt a checkpoint at close.

    Checkpointing writes to the main DB file, so it can never succeed on a
    ``mode=ro`` connection. Attempting it anyway is not merely futile: when
    another process holds the DB open (the normal case for these handles,
    which poll another profile's live state.db), the doomed PRAGMA sits in
    SQLite's Windows I/O retry loop for ~1.4s per close before failing, and
    the failure was swallowed at debug level. That was ~80% of the wall time
    of GET /api/profiles/sessions/sidebar.
    """

    def _readonly_db(self, tmp_path):
        db_path = tmp_path / "ro_state.db"
        writer = SessionDB(db_path=db_path)
        writer.close()
        return SessionDB(db_path=db_path, read_only=True)

    def test_readonly_close_issues_no_checkpoint(self, tmp_path):
        db = self._readonly_db(tmp_path)
        real_conn = db._conn
        execute_calls = []

        def tracking_execute(sql, *args, **kwargs):
            execute_calls.append(sql)
            return real_conn.execute(sql, *args, **kwargs)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = tracking_execute
        db._conn = mock_conn

        db.close()

        assert not [c for c in execute_calls if "wal_checkpoint" in c], (
            f"read_only close must issue no checkpoint, got: {execute_calls}"
        )
        assert mock_conn.close.called, "connection must still be closed"
        assert not hasattr(db, "_conn"), "_conn must still be deleted"
        real_conn.close()

    def test_writable_close_still_checkpoints(self, tmp_path):
        """The skip is keyed on read_only only — writable close is unchanged."""
        db = SessionDB(db_path=tmp_path / "rw_state.db")
        real_conn = db._conn
        execute_calls = []

        def tracking_execute(sql, *args, **kwargs):
            execute_calls.append(sql)
            return real_conn.execute(sql, *args, **kwargs)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = tracking_execute
        db._conn = mock_conn

        db.close()

        assert len([c for c in execute_calls if "wal_checkpoint(TRUNCATE)" in c]) == 1
        real_conn.close()

    def test_readonly_checkpoint_could_never_have_worked(self, tmp_path):
        """Pins the premise: the skipped PRAGMA fails on a mode=ro handle.

        If SQLite ever starts honouring it, this test fails and the skip above
        needs re-justifying rather than silently dropping real WAL truncation.
        """
        import sqlite3 as _sqlite3

        db_path = tmp_path / "premise.db"
        writer = SessionDB(db_path=db_path)
        writer.create_session("s1", "cli")
        # Leave the writer OPEN so the WAL is non-empty and unmerged.
        ro = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, isolation_level=None)
        try:
            with pytest.raises(_sqlite3.OperationalError):
                ro.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            ro.close()
            writer.close()
