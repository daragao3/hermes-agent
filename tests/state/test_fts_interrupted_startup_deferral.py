"""The old startup path commits repaired triggers before its rebuild transaction."""
import hashlib
import json
import sqlite3

import pytest

from hermes_state import SessionDB
from hermes_state_common import _FTS_TRIGGERS
from tests.state.test_fts_foreground_admission import _large, _snapshot


def _canonical_hash(path):
    return hashlib.sha256(json.dumps(_snapshot(path)["messages"], sort_keys=True).encode()).hexdigest()


def test_interrupted_old_startup_requires_explicit_durable_deferral(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        sid = db.create_session(session_id="old-startup", source="cli")
        db.append_message(sid, role="user", content="indexedneedle")
        for name in _FTS_TRIGGERS:
            db._conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        db._conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?, 'user', 'gapneedle', 1)", (sid,))
        db._conn.commit()
        original_hash = _canonical_hash(path)
        assert _snapshot(path)["stale"] is None
        armed, interrupted = [False], [False]

        def trace(sql):
            if "'rebuild'" in sql.lower():
                armed[0] = True

        def progress():
            if armed[0] and not interrupted[0]:
                interrupted[0] = True
                db._conn.interrupt()
            return int(armed[0])

        db._conn.set_trace_callback(trace)
        db._conn.set_progress_handler(progress, 1)
        try:
            # Interrupting FTS virtual-table setup can surface SQLITE_SCHEMA
            # rather than SQLITE_INTERRUPT; the actual interrupt call is asserted.
            with pytest.raises(sqlite3.OperationalError) as failure:
                db._init_fts(db._conn.cursor())
        finally:
            db._conn.set_trace_callback(None)
            db._conn.set_progress_handler(None, 0)
            db._conn.rollback()
        assert interrupted[0]
        assert failure.value.sqlite_errorcode in (sqlite3.SQLITE_INTERRUPT, sqlite3.SQLITE_SCHEMA)
        assert _canonical_hash(path) == original_hash
        # This is the dangerous original state: triggers look restored but the
        # gap was never rebuilt, and no preexisting stale marker was available.
        after_interrupt = _snapshot(path)
        assert len(after_interrupt["triggers"]) == len(_FTS_TRIGGERS)
        assert after_interrupt["stale"] is None
        assert db._conn.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'gapneedle'").fetchone()[0] == 0

        assert db.defer_fts_rebuild(reason="interrupted startup rebuild")
        deferred = _snapshot(path)
        assert deferred["stale"] == ("1",)
        assert not deferred["triggers"]
        assert _canonical_hash(path) == original_hash
        assert not db._conn.in_transaction
        _large(monkeypatch)
        with SessionDB(db_path=path) as peer:
            assert peer._fts_stale and not peer._fts_enabled
            assert peer.search_messages("gapneedle")
            assert peer.retry_deferred_fts_recovery() is False
