"""``vtable constructor failed`` must be classified by errcode, not by message.

SQLite prints ``vtable constructor failed: <name>`` whenever an fts5 xConnect
returns an error it did not annotate itself, so the message is destroyed while
``sqlite_errorcode`` survives.  Measured on SQLite 3.53.1 with one injected
fault (an authorizer returning ``SQLITE_DENY``):

    plain table  -> DatabaseError(23 SQLITE_AUTH) "access to messages.id is prohibited"
    fts5 vtable  -> DatabaseError(23 SQLITE_AUTH) "vtable constructor failed: messages_fts"

``_fts_table_probe`` treated that text as "corrupt vtable" and re-raised it, so
the condition reached ``GET /api/sessions`` as a 500 — and, because a WRITABLE
open probes through the same helper, ``_open_probed``'s one-writable-open heal
raised the identical error instead of repairing anything.

Seen live twice, both times as a flaky 500 that was green on retry and both times
on a store the test itself had just bootstrapped:
``test_dashboard_param_clamps.py::TestSessionPaginationClamps::test_in_range_limit_accepted``
(single GET) and ``test_web_server.py::TestWebServerEndpoints::
test_concurrent_first_load_reads_all_succeed_on_fresh_store`` (one of N concurrent
first-load reads).  Those two own the end-to-end contract; this module owns the
classification underneath them.

Both directions are pinned here:

* a structurally unreadable index (``SQLITE_ERROR``) degrades — the store stays
  openable read-only AND writable, with FTS off, exactly as a missing FTS5
  module does;
* a transient code (``SQLITE_IOERR`` — the #100436 window a ``mode=ro`` reader
  sees while the writer checkpoints) is retried by ``_open_read_only`` and still
  propagates once the budget is spent;
* a corruption-class code is NEVER swallowed, so a genuinely damaged index still
  reaches the heal / forensic-backup path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hermes_state import SessionDB

SQLITE_CORRUPT_VTAB = getattr(sqlite3, "SQLITE_CORRUPT_VTAB", 267)


def _bootstrap_store(db_path: Path) -> None:
    """A real v23 store, created the way the dashboard's bootstrap creates one."""
    db = SessionDB(db_path=db_path)
    db.create_session("vtable-test", source="cli")
    db.append_message("vtable-test", role="user", content="hello world")
    db.close()


def _break_fts_constructor(db_path: Path) -> None:
    """Make the fts5 constructor's ``%_config`` read fail.

    This is the ONLY condition that yields the bare wrapper at ``LIMIT 0``: the
    constructor reads ``%_config`` and nothing else, so dropping ``_data`` /
    ``_idx`` / ``_docsize`` leaves the probe passing.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("DROP TABLE messages_fts_config")
    finally:
        conn.close()


def _wrapped(errorcode: int, table: str = "messages_fts") -> sqlite3.OperationalError:
    """The exception SQLite raises when an fts5 xConnect fails without a message."""
    exc = sqlite3.OperationalError(f"vtable constructor failed: {table}")
    exc.sqlite_errorcode = errorcode
    return exc


class TestUnreadableIndexDegrades:
    def test_read_only_open_survives_an_unreadable_fts_index(self, tmp_path):
        """The read path degrades to no-FTS instead of 500-ing every endpoint."""
        from hermes_cli.web_server_sessions import _open_session_db_at_path

        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)
        _break_fts_constructor(db_path)

        db = _open_session_db_at_path(db_path, read_only=True)
        try:
            assert db._fts_enabled is False
            # The store itself is fine: canonical rows still read.
            assert db.get_session("vtable-test") is not None
        finally:
            db.close()

    def test_writable_open_survives_an_unreadable_fts_index(self, tmp_path):
        """A writable open probes through the same helper, so the heal that
        ``_open_probed`` attempts must not raise the error it is healing.

        The writable open ALSO repairs the index (detach the triggers with the stale
        breadcrumb, restore the absent ``%_config`` shadow, rebuild), so
        ``_fts_enabled`` comes back True here while the read-only open one test above
        stays degraded -- a ``mode=ro`` handle may repair nothing, and only
        ``_connect_and_init`` reaches ``_init_schema``. That asymmetry is the point of
        both tests standing next to each other. The repair itself and the canonical
        write it exists to protect are pinned in
        ``tests/test_fts_unopenable_index_trigger_invariant.py``.

        Read the asymmetry as mechanism, not as drift, and do NOT "fix" the two tests
        into agreement: in the read-only case the probe RETURNS None rather than
        raising, so ``_open_probed`` never fails and never reaches its ``acquire()``
        heal -- which is why False is still correct one test above. Were the probe ever
        to raise there instead, that heal would repair the index and the read-only
        expectation would have to move too.

        The canonical-read assertion below is deliberately independent of the repair:
        it pins "the writable open does not RAISE", which is this module's own subject.
        If the repair is ever removed or gated, ``_fts_enabled is True`` goes red for a
        reason that has nothing to do with the errcode classification, and that second
        assertion is what keeps this module still testing what it was written for.
        """
        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)
        _break_fts_constructor(db_path)

        db = SessionDB(db_path=db_path)
        try:
            assert db._fts_enabled is True
            assert db.get_session("vtable-test") is not None
        finally:
            db.close()


class TestErrcodeClassification:
    def test_structural_failure_reports_the_index_as_degraded(self, tmp_path):
        """SQLITE_ERROR behind the wrapper: index unusable, store accessible."""
        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)
        db = SessionDB(db_path=db_path, read_only=True)
        try:
            cursor = db._conn.cursor()

            class _Failing:
                def execute(self, _sql):
                    raise _wrapped(sqlite3.SQLITE_ERROR)

            assert db._fts_table_probe(_Failing(), "messages_fts") is None
            assert db._fts_table_probe(cursor, "messages_fts") is True
        finally:
            db.close()

    @pytest.mark.parametrize(
        "errorcode",
        [sqlite3.SQLITE_CORRUPT, SQLITE_CORRUPT_VTAB, sqlite3.SQLITE_NOTADB],
    )
    def test_corruption_class_is_never_swallowed(self, tmp_path, errorcode):
        """A genuinely damaged index must still reach the heal / forensic path."""
        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)
        db = SessionDB(db_path=db_path, read_only=True)
        try:
            class _Corrupt:
                def execute(self, _sql):
                    raise _wrapped(errorcode)

            with pytest.raises(sqlite3.DatabaseError, match="vtable constructor failed"):
                db._fts_table_probe(_Corrupt(), "messages_fts")
        finally:
            db.close()


class TestMaskedTransientIoError:
    def test_read_only_open_retries_a_masked_io_error(self, tmp_path, monkeypatch):
        """#100436's window reached through the constructor carries no "disk I/O
        error" text, so the message-based retry test never fired."""
        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)

        real_probe = SessionDB._fts_table_probe
        attempts = {"n": 0}

        def flaky(self, cursor, table_name):
            if table_name == "messages_fts" and attempts["n"] < 2:
                attempts["n"] += 1
                raise _wrapped(sqlite3.SQLITE_IOERR)
            return real_probe(self, cursor, table_name)

        monkeypatch.setattr(SessionDB, "_fts_table_probe", flaky)

        db = SessionDB(db_path=db_path, read_only=True)
        try:
            assert attempts["n"] == 2
            assert db._fts_enabled is True
        finally:
            db.close()

    def test_a_persistent_masked_io_error_still_propagates(self, tmp_path, monkeypatch):
        """The retry budget is bounded: a real storage fault is not hidden."""
        db_path = tmp_path / "state.db"
        _bootstrap_store(db_path)

        def always_ioerr(self, cursor, table_name):
            raise _wrapped(sqlite3.SQLITE_IOERR)

        monkeypatch.setattr(SessionDB, "_fts_table_probe", always_ioerr)

        with pytest.raises(sqlite3.OperationalError, match="vtable constructor failed"):
            SessionDB(db_path=db_path, read_only=True)
