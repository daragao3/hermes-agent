"""The FTS triggers and the index they write to must live and die together.

``_fts_table_probe`` classifies SQLite's bare ``vtable constructor failed: <name>``
wrapper by ``sqlite_errorcode``: a structural failure (the fts5 xConnect could not read
the index's ``%_config`` shadow table -- SQLITE_ERROR) returns ``None``, so the store
OPENS with the index degraded instead of raising into every caller. See
``tests/test_readonly_fts_vtable_constructor_classification.py`` for that half.

This file pins the half that classification alone leaves broken. ``messages_fts_insert``
/ ``_update`` / ``_delete`` are still in ``sqlite_master`` referencing that index, and a
trigger body runs the constructor like any other statement -- so every canonical WRITE
through such a store raises the identical wrapper from
``hermes_state_messages.append_message`` -> ``conn.execute(_INSERT_MESSAGE_SQL)``. The
store reads fine and cannot be written to, with no repair path.

The invariant: **base FTS triggers present => the base index is writable.** The codebase
already keeps it everywhere else -- ``_init_schema`` drops the triggers when the runtime
has no FTS5 at all ("Existing FTS triggers would still fire though this runtime cannot
read their targets"), and ``_ensure_fts_cjk_schema`` drops the cjk triggers when the
cjk_unicode61 tokenizer will not load ("INSERTs must not fail at trigger time"). The base
index was the one family with no such arm.

Two mechanical notes for anyone editing these tests:

* A trigger fires happily on a connection that already has the vtable instantiated in its
  schema cache. Only a FRESH connection re-runs the constructor and fails, so every test
  here breaks the store on one connection and opens a NEW ``SessionDB`` to exercise it.
* Dropping ``messages_fts_data`` / ``_idx`` / ``_docsize`` does NOT reproduce this: a
  ``LIMIT 0`` probe reads ``%_config`` and nothing else. ``DROP TABLE messages_fts_config``
  is the one structural condition that yields the bare wrapper.

Measured 2026-09-19 on the agent-src venv (CPython 3.13.15 / SQLite 3.53.1).
Loops ``fts-trigger-index-invariant-unopenable-index-20260919``.
"""
import contextlib
import sqlite3
import uuid
from pathlib import Path

import hermes_state_schema
from hermes_state import SessionDB
from hermes_state_common import FTS_STALE_KEY
from hermes_state_schema import _FTS_BASE_TRIGGERS


def _seed(db_path: Path) -> str:
    """Bootstrap a real store with one indexed message, then close it."""
    db = SessionDB(db_path=db_path)
    try:
        session_id = db.create_session(session_id=str(uuid.uuid4()), source="cli")
        db.append_message(session_id, "user", "seeded while the index still worked")
    finally:
        db.close()
    return session_id


def _break_base_index(db_path: Path) -> None:
    """Make ``messages_fts`` unconstructable, touching neither ``messages`` nor the triggers."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE messages_fts_config")
        conn.commit()
    finally:
        conn.close()


def _index_constructs(db_path: Path) -> bool:
    """Can a FRESH connection instantiate the vtable? The whole defect lives in this gap."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("SELECT * FROM messages_fts LIMIT 0")
        return True
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def _schema_names(db_path: Path, kind: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}
    finally:
        conn.close()


def _stored_contents(db_path: Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT content FROM messages ORDER BY id")]
    finally:
        conn.close()


def test_the_probe_reproducer_really_breaks_a_fresh_connection(tmp_path):
    """Precondition control: without it every assertion below could pass vacuously."""
    db_path = tmp_path / "state.db"
    _seed(db_path)
    assert _index_constructs(db_path) is True

    _break_base_index(db_path)

    assert _index_constructs(db_path) is False
    assert "messages_fts_insert" in _schema_names(db_path, "trigger")


def test_canonical_write_survives_an_index_whose_constructor_fails(tmp_path):
    """The defect this file exists for: the open succeeds, the write must too."""
    db_path = tmp_path / "state.db"
    session_id = _seed(db_path)
    _break_base_index(db_path)

    db = SessionDB(db_path=db_path)
    try:
        db.append_message(session_id, "user", "written after the index broke")
    finally:
        db.close()

    assert _stored_contents(db_path) == [
        "seeded while the index still worked",
        "written after the index broke",
    ]


def test_opening_the_store_rebuilds_the_index_and_search_answers_again(tmp_path):
    """The repair, not merely the degrade: a fresh connection can construct the vtable."""
    db_path = tmp_path / "state.db"
    session_id = _seed(db_path)
    _break_base_index(db_path)

    db = SessionDB(db_path=db_path)
    try:
        db.append_message(session_id, "user", "zyzzyvamarker written after the index broke")
        hits = db.search_messages("zyzzyvamarker")
    finally:
        db.close()

    assert _index_constructs(db_path) is True
    assert [h for h in hits if "zyzzyvamarker" in (h.get("snippet") or "")]
    conn = sqlite3.connect(db_path)
    try:
        indexed = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'zyzzyvamarker'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert indexed == 1


def test_a_blocked_rebuild_detaches_the_triggers_rather_than_failing_the_write(tmp_path, monkeypatch):
    """Fail-closed leg: another process owns the rebuild authority, so the index cannot be
    repaired on this open. The write must still land, which means the triggers must be gone
    and the stale breadcrumb set for a later ``retry_deferred_fts_recovery``."""
    db_path = tmp_path / "state.db"
    session_id = _seed(db_path)
    _break_base_index(db_path)

    @contextlib.contextmanager
    def _refused(_db_path, *, timeout_seconds=None):
        yield False

    monkeypatch.setattr(hermes_state_schema, "fts_rebuild_admission", _refused)

    db = SessionDB(db_path=db_path)
    try:
        db.append_message(session_id, "user", "written while the rebuild was blocked")
        assert db._fts_stale is True
        assert db._fts_enabled is False
    finally:
        db.close()

    assert _schema_names(db_path, "trigger").isdisjoint(_FTS_BASE_TRIGGERS)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT 1 FROM state_meta WHERE key = ?", (FTS_STALE_KEY,)
        ).fetchone() is not None
    finally:
        conn.close()
    assert _stored_contents(db_path)[-1] == "written while the rebuild was blocked"
