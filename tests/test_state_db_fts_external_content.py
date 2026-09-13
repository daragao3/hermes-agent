"""Schema v32: ``messages_fts`` as an FTS5 external-content index over a view.

Inline FTS5 keeps a second, byte-for-byte copy of every indexed string in a
``messages_fts_content`` shadow table — 1273.9 MB of a 5120 MB production
state.db, measured 2026-08-11. External content drops that copy and re-reads
the text from ``messages`` on demand.

The subtlety these tests exist for: v11 moved this DB *away* from external
content, but only because the index had to start covering ``tool_name`` +
``tool_calls`` (#16751) while the schema pointed the FTS column straight at
``messages.content``. The ``messages_fts_source`` view supplies the 3-column
concat, so both requirements hold at once — and each test below pins one half
of that, so a future edit cannot quietly trade one for the other.

External content also changes two things that fail *silently* rather than
loudly, which the rest of the file covers:

* ``DELETE``/``UPDATE`` must hand FTS5 the OLD text through the ``'delete'``
  command so it retracts the right terms. Wrong text = a corrupt index that
  still answers queries.
* ``SELECT COUNT(*) FROM messages_fts`` counts the *view* (every message), not
  index entries — so it can no longer be used to assert that indexing happened.

THIS BRANCH DOES NOT CONVERT AN EXISTING INLINE INSTALL, which is why the tests
below assert PRESERVATION rather than the migration they were written for. A
fresh database still gets the external-content shape described above, but
``_init_fts`` branches on ``_db_has_legacy_inline_fts`` (the stored CREATE lacks
``tool_name``) — shape, not version — and deliberately leaves a legacy install
in its inline shape: *"OPT-IN v23 boundary: a legacy v22 inline install keeps
its inline schema + triggers (the v23 DDL would create the trigram source VIEW
and leave a mixed state)"*. So on such a database the second copy of the text
survives and the space win described above is NOT collected.

What holds on the preserved index regardless, and is what most of these tests
now pin: ``tool_name`` stays indexed, the delete/update triggers retract the
right terms, and an unindexed prefix is closed when the database is opened.

Measured 2026-09-13. Full reasoning: loops wave2-fts-preservation-tests-20260913.
"""
import sqlite3
import uuid
from pathlib import Path

import pytest

from hermes_state import SessionDB
from hermes_state_common import SCHEMA_VERSION


# NOTE: this module used to set HERMES_DISABLE_MESSAGE_TRIGRAM=1 here "to keep
# these tests focused and fast". Nothing on this branch reads that variable any
# more -- the trigram index is built unconditionally -- so the fixture was a
# no-op that made two tests below look broken (a second index shows up in
# check_fts_integrity(), and rebuild_fts() rebuilds two indexes rather than
# one). Removed rather than repaired: the tests now state the real index set.


def _seed(db_path: Path, count: int = 10) -> str:
    db = SessionDB(db_path=db_path)
    sid = db.create_session(session_id=str(uuid.uuid4()), source="cli")
    for i in range(count):
        db.append_message(sid, role="user", content=f"hello world {i}")
        db.append_message(
            sid,
            role="tool",
            content=f"pizza {i}",
            tool_name="browser_snapshot",
            tool_calls='{"name":"browser_snapshot"}',
        )
    db.close()
    return sid


def _match_count(conn: sqlite3.Connection, query: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (query,)
    ).fetchone()[0]


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    """FTS5 integrity-check in its strong (rank=1) form.

    The default rank=0 form only validates the index against its own content
    store; rank=1 re-derives the terms from the content table, which is what
    catches an index row whose text no longer matches (or no longer exists in)
    ``messages``. Under external content that is the failure mode that matters,
    so every trigger test below asserts through this.

    Kept as raw SQL rather than routed through ``SessionDB.check_fts_integrity``
    so the tests fail if the *statement* stops detecting corruption, not merely
    if the wrapper around it changes.
    """
    try:
        conn.execute("INSERT INTO messages_fts(messages_fts, rank) VALUES('integrity-check', 1)")
        return True
    except sqlite3.DatabaseError:
        return False


def _make_legacy_inline(db_path: Path, *, indexed_from_id: int = 0) -> str:
    """Build a DB and force it back to the legacy inline FTS shape.

    Stamped at the CURRENT schema version on purpose: this represents a legacy
    install that has already been carried up to today's version and kept its
    inline index, which is the state this branch preserves. Stamping the local
    v31 marker instead would only trip the migration-domain guard and prove
    nothing about FTS.

    ``indexed_from_id`` reproduces production's unindexed prefix: rows at or
    below it exist in ``messages`` but were never added to the index, which is
    the state that makes the new delete trigger dangerous (retracting terms
    that were never inserted is how a stale index becomes a corrupt one).
    """
    sid = _seed(db_path)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute("DELETE FROM sqlite_master WHERE name LIKE 'messages_fts%'")
    conn.execute("PRAGMA writable_schema=OFF")
    conn.close()

    concat = (
        "COALESCE(content,'')||' '||COALESCE(tool_name,'')"
        "||' '||COALESCE(tool_calls,'')"
    )
    new_concat = concat.replace("(content", "(new.content").replace(
        "(tool_name", "(new.tool_name"
    ).replace("(tool_calls", "(new.tool_calls")
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.executescript(
        f"""
CREATE VIRTUAL TABLE messages_fts USING fts5(content);
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, {new_concat});
END;
CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
  DELETE FROM messages_fts WHERE rowid = old.id;
END;
CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages BEGIN
  DELETE FROM messages_fts WHERE rowid = old.id;
  INSERT INTO messages_fts(rowid, content) VALUES (new.id, {new_concat});
END;
"""
    )
    conn.execute(
        f"INSERT INTO messages_fts(rowid, content) "
        f"SELECT id, {concat} FROM messages WHERE id > ?",
        (indexed_from_id,),
    )
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    conn.commit()
    conn.close()
    return sid


def test_open_preserves_the_legacy_inline_shape_and_its_shadow_table(tmp_path):
    """Opening a legacy inline install leaves it inline -- the opt-in boundary.

    The inverse of what this test asserted when the module was written for the
    conversion. Nothing here is an endorsement of paying for the second copy;
    it pins that this branch KNOWINGLY leaves it in place, so that adopting the
    conversion later shows up as this test failing rather than as a silent
    change of on-disk shape.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path)

    raw = sqlite3.connect(str(db_path))
    assert raw.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='messages_fts_content'"
    ).fetchone()[0] == 1, "precondition: the inline DB has the content shadow table"
    raw.close()

    db = SessionDB(db_path=db_path)
    try:
        # The open must not relabel the database either.
        assert (
            db._conn.execute("SELECT version FROM schema_version").fetchone()[0]
            == SCHEMA_VERSION
        )
        decl = " ".join(
            db._conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='messages_fts'"
            ).fetchone()[0].split()
        )
        assert "content='messages_fts_source'" not in decl, "must NOT be converted"
        assert "USING fts5(content)" in decl
        # The duplicate copy survives, and still holds real text: that is the
        # cost of the boundary, stated rather than implied.
        assert db._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='messages_fts_content'"
        ).fetchone()[0] == 1
        assert db._conn.execute(
            "SELECT COUNT(*) FROM messages_fts_content"
        ).fetchone()[0] > 0
    finally:
        db.close()


def test_preserved_inline_index_still_indexes_tool_name(tmp_path):
    """#16751 must hold on the preserved index too.

    This is the requirement that caused v11 to abandon external content in the
    first place. Preserving the inline shape must not quietly drop it.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path)
    db = SessionDB(db_path=db_path)
    try:
        assert _match_count(db._conn, "browser_snapshot") == 10
    finally:
        db.close()


def test_open_closes_an_unindexed_prefix_on_the_preserved_index(tmp_path):
    """An unindexed prefix is closed on open even though the index stays inline.

    Worth pinning because it is the surprise: this test was written believing
    the gap could only be closed by converting to external content ("under
    inline FTS this is impossible: 'rebuild' regenerates the index from
    messages_fts_content, so rows missing from that shadow copy stay missing").
    On this branch the preserved index is repopulated from ``messages``
    instead, so the prefix closes with the inline shape intact -- measured
    2026-09-13 as 15 indexed rows of 20 before the open and 20 after.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path, indexed_from_id=5)

    raw = sqlite3.connect(str(db_path))
    assert raw.execute("SELECT COUNT(*) FROM messages_fts_content").fetchone()[0] == 15
    assert raw.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 20
    raw.close()

    db = SessionDB(db_path=db_path)
    try:
        assert _match_count(db._conn, "hello") == 10
        assert _match_count(db._conn, "pizza") == 10
        assert _integrity_ok(db._conn)
    finally:
        db.close()


def test_delete_trigger_retracts_the_right_terms(tmp_path):
    """Deleting a formerly-unindexed row must not corrupt the index.

    id<=5 was never indexed by the fixture. If the open skipped its repopulate,
    the delete trigger would retract terms that were never inserted — integrity
    would fail here while ordinary searches kept looking fine.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path, indexed_from_id=5)
    db = SessionDB(db_path=db_path)
    try:
        db._conn.execute("DELETE FROM messages WHERE id IN (1, 9)")  # both 'hello' rows
        db._conn.commit()
        assert _match_count(db._conn, "hello") == 8
        assert _integrity_ok(db._conn)
    finally:
        db.close()


def test_update_trigger_retracts_the_old_text(tmp_path):
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path)
    db = SessionDB(db_path=db_path)
    try:
        db._conn.execute("UPDATE messages SET content='zebra' WHERE id=11")
        db._conn.commit()
        assert _match_count(db._conn, "zebra") == 1
        assert _match_count(db._conn, "hello") == 9, "old term must be retracted"
        assert _integrity_ok(db._conn)
    finally:
        db.close()


def test_bare_count_star_counts_index_rows_on_the_preserved_index(tmp_path):
    """The space win is NOT collected here, and COUNT(*) is why it looked like it was.

    This test previously read ``bare == messages == 20`` and PASSED on this
    branch -- for the wrong reason. Its own docstring said that equality means
    "the index is no longer external-content and the space win is gone", which
    is exactly the state of a preserved inline install; the numbers agreed only
    because the open re-indexes the unindexed prefix, so index rows reach the
    message count anyway. A green test asserting the opposite of the truth is
    worse than a red one, so the assertion is now on the fact that actually
    distinguishes the two shapes: whether a second copy of the text is on disk.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path, indexed_from_id=5)
    db = SessionDB(db_path=db_path)
    try:
        bare = db._conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        messages = db._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        shadow = db._conn.execute(
            "SELECT COUNT(*) FROM messages_fts_content"
        ).fetchone()[0]
        assert messages == 20
        # Inline: COUNT(*) is the index's own rows, which the shadow copy mirrors
        # one-for-one. Under external content the shadow table would not exist at
        # all, so this pairing is the discriminator -- not the bare number.
        assert bare == shadow
    finally:
        db.close()


def test_snippet_works_on_the_preserved_inline_index(tmp_path):
    """Search results must be unchanged by the boundary.

    Renamed: on a preserved inline index there IS a stored copy, so the old
    name ("without a stored copy") asserted something false here even while the
    body passed.
    """
    db_path = tmp_path / "state.db"
    _make_legacy_inline(db_path)
    db = SessionDB(db_path=db_path)
    try:
        rows = db.search_messages("pizza", limit=5)
        assert rows
        assert all(">>>pizza<<<" in r["snippet"] for r in rows)
    finally:
        db.close()


def test_a_corrupt_index_block_propagates_instead_of_failing_open(tmp_path):
    """A corrupt index block reaches the search caller raw. Deliberate, and costly.

    This test was written for the opposite contract -- "corrupt index b-tree →
    rebuild → retry → results", guarding the very symptom named in this
    module's own history: "a corrupt index surfaced 'database disk image is
    malformed' raw to every search caller". That guard
    (``_fts_runtime_rebuild_attempted``) no longer exists on this branch. The
    replacement is ``_enter_fts_fail_open``: detach the derived indexes and
    answer from canonical rows, because "a live search never runs the unbounded
    rebuild".

    But that replacement DOES NOT FIRE HERE, by an explicit decision in
    ``_is_fts_write_corruption_error``: it fails open only for corruption
    SQLite scopes to the virtual table (``SQLITE_CORRUPT_VTAB``, 267), on the
    stated grounds that "a bare malformed image is structural". Damaging an
    FTS index block raises bare ``SQLITE_CORRUPT`` (11), so the fail-open arm
    is unreachable for it and the error propagates.

    The cost, asserted below so it cannot be overlooked: the damage is confined
    to the FTS index and every canonical row is still readable, yet search
    raises. Whether that is the right call is a judgement about masking
    possible whole-file corruption versus keeping search alive; this test only
    pins which way the branch currently decides, and fails loudly if either the
    classifier or the policy moves.
    """
    db_path = tmp_path / "state.db"
    _seed(db_path)

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute(
        "UPDATE messages_fts_data SET block = randomblob(64) "
        "WHERE id = (SELECT MAX(id) FROM messages_fts_data)"
    )
    conn.close()

    db = SessionDB(db_path=db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError) as caught:
            db.search_messages("pizza", limit=25)
        assert "malformed" in str(caught.value)
        # WHY it propagates: not scoped to the vtable, so not fail-open eligible.
        assert getattr(caught.value, "sqlite_errorcode", None) == 11
        assert getattr(caught.value, "sqlite_errorcode", None) != getattr(
            sqlite3, "SQLITE_CORRUPT_VTAB", 267
        )
        assert db._is_fts_write_corruption_error(caught.value) is False
        # ...and the canonical rows were fine the whole time.
        assert db._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 20
    finally:
        db.close()


def test_search_ignores_orphaned_index_rowids(tmp_path):
    """An orphan degrades to a missing result, not an exception.

    ``search_messages`` INNER JOINs ``messages`` on the index rowid, so an
    index entry with no surviving message row is filtered out before
    ``snippet()`` can be evaluated on it. That bounds the blast radius of the
    one corruption class external content newly makes possible — but it also
    means searches cannot be used to *detect* it, which is why
    ``_integrity_ok`` (rank=1) is the health probe instead.
    """
    db_path = tmp_path / "state.db"
    _seed(db_path)
    db = SessionDB(db_path=db_path)
    try:
        # Manufacture an orphan, restoring the trigger verbatim so the trigger
        # count never drops and _init_schema's repair path stays out of it.
        ddl = db._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='messages_fts_delete'"
        ).fetchone()[0]
        db._conn.execute("DROP TRIGGER messages_fts_delete")
        db._conn.execute("DELETE FROM messages WHERE id = 3")
        db._conn.execute(ddl)
        db._conn.commit()

        assert not _integrity_ok(db._conn), "rank=1 must detect the orphan"
        rows = db.search_messages("hello", limit=25)
        assert len(rows) == 9, "orphan is skipped, not raised"

        # Two indexes are rebuilt, not one: the trigram index is built
        # unconditionally on this branch (see the note where the old
        # HERMES_DISABLE_MESSAGE_TRIGRAM fixture used to be).
        assert db.rebuild_fts() == 2
        assert _integrity_ok(db._conn), "'rebuild' repairs it"
    finally:
        db.close()


def test_check_fts_integrity_reports_the_orphan(tmp_path):
    """The health probe must report what searches cannot surface."""
    db_path = tmp_path / "state.db"
    _seed(db_path)
    db = SessionDB(db_path=db_path)
    try:
        # Every enabled index is reported, and the trigram is always enabled
        # on this branch, so the report is keyed on both.
        healthy = db.check_fts_integrity()
        assert set(healthy) == {"messages_fts", "messages_fts_trigram"}
        assert all(v is None for v in healthy.values())

        ddl = db._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='messages_fts_delete'"
        ).fetchone()[0]
        db._conn.execute("DROP TRIGGER messages_fts_delete")
        db._conn.execute("DELETE FROM messages WHERE id = 3")
        db._conn.execute(ddl)
        db._conn.commit()

        report = db.check_fts_integrity()
        assert set(report) == {"messages_fts", "messages_fts_trigram"}
        assert report["messages_fts"] is not None
        assert "malformed" in report["messages_fts"]

        db.rebuild_fts()
        repaired = db.check_fts_integrity()
        assert set(repaired) == {"messages_fts", "messages_fts_trigram"}
        assert all(v is None for v in repaired.values())
    finally:
        db.close()
