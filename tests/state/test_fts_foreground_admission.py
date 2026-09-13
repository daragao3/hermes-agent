"""Real temporary stores exercise foreground deferral and maintenance recovery."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

import hermes_state_schema
from hermes_state import SessionDB
from hermes_state_common import FTS_STALE_KEY, _FTS_TRIGGERS


def _seed_gap(path, *, stale=False):
    with SessionDB(db_path=path) as db:
        sid = db.create_session(session_id="foreground-policy", source="cli")
        db.append_message(sid, role="user", content="indexedneedle")
    with sqlite3.connect(path) as conn:
        for name in _FTS_TRIGGERS:
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES (?, 'user', 'gapneedle', 1)", (sid,))
        if stale:
            conn.execute("INSERT INTO state_meta(key,value) VALUES (?, '1')", (FTS_STALE_KEY,))
    return sid


def _large(monkeypatch):
    # Lower the policy boundary, not fake the database or its logical-size probe.
    monkeypatch.setattr(hermes_state_schema, "_FTS_FOREGROUND_REBUILD_MAX_BYTES", 1, raising=False)


def _snapshot(path):
    with sqlite3.connect(path) as conn:
        return {
            "messages": conn.execute("SELECT id,session_id,role,content FROM messages ORDER BY id").fetchall(),
            "schema": conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(),
            "stale": conn.execute("SELECT value FROM state_meta WHERE key=?", (FTS_STALE_KEY,)).fetchone(),
            "triggers": conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'messages_fts_%'").fetchall(),
        }


@pytest.mark.parametrize("stale", [False, True], ids=["missing-triggers", "stale-recovery"])
def test_large_repair_defers_across_opens_and_retry(tmp_path, monkeypatch, stale):
    path = tmp_path / "state.db"
    sid = _seed_gap(path, stale=stale)
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        assert db._fts_stale and not db._fts_enabled
        assert _snapshot(path)["stale"] == ("1",)
        assert not _snapshot(path)["triggers"]
        db.append_message(sid, role="user", content="afterdeferralneedle")
        assert db.search_messages("gapneedle")
        assert db.search_messages("afterdeferralneedle")
        assert db.retry_deferred_fts_recovery() is False
        assert db._fts_stale and not db._fts_enabled
    with SessionDB(db_path=path) as reopened:
        assert reopened._fts_stale and not reopened._fts_enabled
        assert reopened.search_messages("afterdeferralneedle")


@pytest.mark.parametrize("stale", [False, True])
def test_small_repairs_remain_automatic(tmp_path, stale):
    path = tmp_path / "state.db"
    _seed_gap(path, stale=stale)
    with SessionDB(db_path=path) as db:
        assert db._fts_enabled and not db._fts_stale
        assert db.search_messages("gapneedle")
        assert db._conn.execute("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'gapneedle'").fetchone()[0] == 1


def test_healthy_large_open_does_not_degrade(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        sid = db.create_session(session_id="healthy", source="cli")
        db.append_message(sid, role="user", content="healthyneedle")
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        assert db._fts_enabled and not db._fts_stale
        assert db.search_messages("healthyneedle")


def test_explicit_maintenance_recovers_without_leaking_to_concurrent_open(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    _seed_gap(path)
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        assert db._fts_stale
        assert db.fts_optimize_available()
        original = db._recover_stale_fts_locked

        def ordinary_open():
            with SessionDB(db_path=path) as peer:
                return peer._fts_stale, peer._fts_enabled

        def checked(cursor, *, legacy):
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(ordinary_open).result(timeout=15) == (True, False)
            return original(cursor, legacy=legacy)

        monkeypatch.setattr(db, "_recover_stale_fts_locked", checked)
        result = db.optimize_fts_storage(vacuum=False)
        assert result["ok"], result
        assert not db._fts_stale and db._fts_enabled
        assert _snapshot(path)["stale"] is None
        db._conn.execute("INSERT INTO messages_fts(messages_fts,rank) VALUES('integrity-check',1)")
        assert db.search_messages("gapneedle")


def test_interrupt_rolls_back_maintenance_and_preserves_stale_state(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    _seed_gap(path)
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        assert db._fts_stale
        before = _snapshot(path)
        armed = [False]
        interrupted = [False]

        def trace(sql):
            if "'rebuild'" in sql.lower():
                armed[0] = True

        def progress():
            if armed[0] and not interrupted[0]:
                interrupted[0] = True
                db._conn.interrupt()
                return 1
            return 0

        db._conn.set_trace_callback(trace)
        db._conn.set_progress_handler(progress, 1)
        try:
            result = db.optimize_fts_storage(vacuum=False)
        finally:
            db._conn.set_trace_callback(None)
            db._conn.set_progress_handler(None, 0)
        assert interrupted[0], "must interrupt a real FTS rebuild statement"
        assert not result["ok"]
        assert _snapshot(path) == before
        assert not db._conn.in_transaction
        assert db._fts_stale and not db._fts_enabled
        assert db.search_messages("gapneedle")
        assert db.retry_deferred_fts_recovery() is False
        assert db.optimize_fts_storage(vacuum=False)["ok"]
