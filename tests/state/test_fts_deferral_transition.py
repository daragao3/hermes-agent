"""Deferral remains atomic, admitted, and recoverable through the existing CLI."""
import sqlite3
from types import SimpleNamespace

import pytest

from hermes_state import SessionDB
from hermes_state_common import FTS_CJK_STALE_KEY, fts_rebuild_admission
from tests.state.test_fts_foreground_admission import _large, _seed_gap, _snapshot


def test_explicit_deferral_refuses_active_rebuild_admission(tmp_path):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        before = _snapshot(path)
        with fts_rebuild_admission(path, timeout_seconds=0) as admitted:
            assert admitted
            assert db.defer_fts_rebuild(reason="interrupted startup rebuild") is False
        assert _snapshot(path) == before
        assert db._fts_enabled and not db._fts_stale


def test_explicit_deferral_rolls_back_marker_and_partial_trigger_drop(tmp_path):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        before = _snapshot(path)

        def authorizer(operation, name, _table, _database, _source):
            if operation == sqlite3.SQLITE_DROP_TRIGGER and name == "messages_fts_delete":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db._conn.set_authorizer(authorizer)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                db.defer_fts_rebuild(reason="interrupted startup rebuild")
        finally:
            db._conn.set_authorizer(None)
        assert _snapshot(path) == before
        assert not db._conn.in_transaction
        assert db._fts_enabled and not db._fts_stale


def test_explicit_deferral_marks_existing_cjk_index_stale(tmp_path):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        db._conn.execute("CREATE VIRTUAL TABLE messages_fts_cjk USING fts5(content)")
        db._conn.execute("CREATE TRIGGER messages_fts_cjk_insert AFTER INSERT ON messages BEGIN INSERT INTO messages_fts_cjk(content) VALUES(new.content); END")
        db._conn.commit()
        assert db.defer_fts_rebuild(reason="interrupted startup rebuild")
        assert db.get_meta(FTS_CJK_STALE_KEY) == "1"
        assert not _snapshot(path)["triggers"]


@pytest.mark.parametrize("confirmed,free_bytes,expected_calls", [(False, 10**12, 0), (True, 0, 0), (True, 10**12, 1)])
def test_existing_cli_preflight_controls_explicit_maintenance(tmp_path, monkeypatch, confirmed, free_bytes, expected_calls):
    from hermes_cli import sessions_cmd

    path = tmp_path / "state.db"
    _seed_gap(path)
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        assert db._fts_stale
        calls = []
        original = db.optimize_fts_storage

        def maintenance(**kwargs):
            calls.append(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(db, "optimize_fts_storage", maintenance)
        monkeypatch.setattr(sessions_cmd.shutil, "disk_usage", lambda _path: SimpleNamespace(free=free_bytes))
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        sessions_cmd._cmd_optimize_storage(db, SimpleNamespace(yes=confirmed, no_vacuum=True))
        assert len(calls) == expected_calls
        assert db._fts_stale is (expected_calls == 0)


def test_read_only_store_does_not_offer_or_apply_deferral(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    _seed_gap(path)
    _large(monkeypatch)
    with SessionDB(db_path=path):
        pass
    with SessionDB(db_path=path, read_only=True) as db:
        before = _snapshot(path)
        assert not db.fts_optimize_available()
        assert not db.defer_fts_rebuild(reason="interrupted startup rebuild")
        assert _snapshot(path) == before


def test_unavailable_fts5_does_not_advertise_or_attempt_maintenance(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    _seed_gap(path, stale=True)
    monkeypatch.setattr(SessionDB, "_sqlite_supports_fts5", lambda *_args: False)
    with SessionDB(db_path=path) as db:
        assert db._fts_stale
        assert not db.fts_optimize_available()
        assert db.optimize_fts_storage(vacuum=False) == {"ok": False, "reason": "fts5_unavailable"}


def test_unexpected_maintenance_exception_rolls_back_connection(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    _seed_gap(path)
    _large(monkeypatch)
    with SessionDB(db_path=path) as db:
        before = _snapshot(path)

        def failure(cursor, **_kwargs):
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("INSERT INTO state_meta(key,value) VALUES('uncommitted_test', '1')")
            raise RuntimeError("unexpected maintenance failure")

        monkeypatch.setattr(db, "_recover_stale_fts", failure)
        with pytest.raises(RuntimeError, match="unexpected maintenance failure"):
            db.optimize_fts_storage(vacuum=False)
        assert not db._conn.in_transaction
        assert db.get_meta("uncommitted_test") is None
        assert _snapshot(path) == before


def test_foreground_transition_rollback_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    with SessionDB(db_path=path) as db:
        before = _snapshot(path)
        _large(monkeypatch)

        def authorizer(operation, name, _table, _database, _source):
            if operation == sqlite3.SQLITE_DROP_TRIGGER and name == "messages_fts_delete":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db._conn.set_authorizer(authorizer)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                db._run_admitted_startup_rebuild(db._conn.cursor(), lambda: pytest.fail("must not rebuild"))
        finally:
            db._conn.set_authorizer(None)
            db._conn.rollback()
        assert _snapshot(path) == before
        assert db._fts_enabled and not db._fts_stale
