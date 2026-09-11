"""A profile ``state.db`` that is not a session store reads ABSENT -- and an
unreadable one must still SURFACE.

``state.db`` is a filename shared by two INDEPENDENT schema owners.
``hermes_state.SessionDB`` creates the full session schema;
``tools/async_delegation.py::_connect`` opens the SAME path and creates ONLY
its own ``async_delegations`` table. Whichever runs first in a profile decides
what the file holds. Measured 2026-09-08:
``~/.hermes/profiles/matcher/state.db`` is 12,288 bytes, valid SQLite under
WAL, and holds exactly one table -- ``async_delegations``. It passes
``is_file()``, opens read-only fine, and raises
``sqlite3.OperationalError: no such table: sessions`` on every real query.

``SessionBridgeStore`` never hits that raise, and the reason is one layer
deeper than the discovery guard: ``_discover_hermes_profile_db_paths`` really
does accept the file on ``is_file()`` alone, and ``_acquire_profile_database``
really does hand out a live read-only handle for it. What stops the raise is
``_profile_catalog_compatible``, which asks ``PRAGMA table_info(sessions)`` /
``(messages)``. A PRAGMA against a MISSING table returns an EMPTY row set and
does NOT raise, so the required-column subset check fails and the profile is
skipped. All six ``_native_hermes_databases`` call sites gate on it.

That guard's docstring targets PRE-BRIDGE profile databases. It subsumes the
never-a-session-store case by accident, and until this file NO test pinned that
case against it -- weakening or removing the guard would reintroduce
``no such table: sessions`` at all six call sites at once with nothing going
red. These tests are that pin. Verified by mutation 2026-09-08: making
``_profile_catalog_compatible`` return True unconditionally turns every test in
``TestNonSessionProfileStoreReadsAbsent`` red.

THE COUNTERWEIGHT IS LOAD-BEARING. ``8ca1e62d64`` / ``57bdfafc26`` exist
precisely so an unreadable profile store stops being silently dropped, and
``SessionDB.has_session_schema`` (``e37c151f54``) deliberately RAISES rather
than returning False on a corrupt, locked or I/O-failing database for the same
reason. A file that pinned only the quiet direction would invite a future "fix"
that buys quiet by swallowing real failures -- so
``TestUnreadableProfileStoreStillSurfaces`` pins the opposite direction, and
the two classes fail in opposite directions under that fix.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.store import _PROFILE_SHADOW_SOURCE, SessionBridgeStore
from tools.async_delegation import _connect as _async_delegation_connect


PROFILE = "matcher"

# A root row whose ``source`` marks it a POINTER at a profile database. Both
# ``get_native_session_snapshot`` and ``get_sidebar_preview_source`` reach the
# profile handles only for a shadow, so without this row those two would never
# consult a profile at all and would pass with the guard removed.
SHADOW = "claude:11111111-2222-3333-4444-555555555555"


def _never_a_session_store(path: Path) -> Path:
    """Build the file EXACTLY as ``tools/async_delegation.py::_connect`` does.

    Calling the production function rather than restating its DDL is the point:
    if async delegation is ever changed to initialise through ``SessionDB``,
    these fixtures stop being hostile and the tests say so instead of quietly
    guarding a case that no longer exists.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    _async_delegation_connect(path).close()
    return path


def _unreadable_store(path: Path) -> Path:
    """A file SQLite opens and then refuses to read: ``file is not a database``.

    Deliberately NOT a zero-byte or truncated file: length measures WHEN you
    looked, not what the file is (under WAL the schema lives in the ``-wal``
    until the first checkpoint), and an empty file is a legitimate
    not-yet-initialised store rather than an unreadable one.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database" * 800)
    return path


def _store(tmp_path: Path, profile_path: Path):
    """A real store whose ONLY profile is *profile_path*.

    ``hermes_profile_db_paths`` is a real constructor parameter, so the profile
    side is the hostile file and the root side is a throwaway database. No live
    database is opened and no write lock is taken anywhere.
    """

    root = SessionDB(tmp_path / "state.db")
    root.ensure_session(SHADOW, source=_PROFILE_SHADOW_SOURCE, cwd="C:/workspace")
    return SessionBridgeStore(
        root, hermes_profile_db_paths=lambda: ((PROFILE, profile_path),)
    )


@pytest.fixture
def hostile_store(tmp_path: Path):
    profile_path = _never_a_session_store(tmp_path / "profiles" / PROFILE / "state.db")
    store = _store(tmp_path, profile_path)
    try:
        yield store
    finally:
        store.close_profile_databases()
        store.db.close()


@pytest.fixture
def corrupt_store(tmp_path: Path):
    profile_path = _unreadable_store(tmp_path / "profiles" / PROFILE / "state.db")
    store = _store(tmp_path, profile_path)
    try:
        yield store
    finally:
        store.close_profile_databases()
        store.db.close()


class TestNonSessionProfileStoreReadsAbsent:
    """Direction 1: the profile is SKIPPED, and no ``OperationalError`` escapes."""

    def test_the_fixture_is_valid_sqlite_without_a_sessions_table(
        self, tmp_path: Path
    ) -> None:
        """Guard the guard's premise: a broken fixture would pass every test below.

        Read ``sqlite_master``. Do NOT classify this file from ``st_size`` or a
        header sniff -- at 0, 4,096 and 12,288 bytes the failing query is
        byte-identical.
        """

        path = _never_a_session_store(tmp_path / "profiles" / PROFILE / "state.db")
        connection = sqlite3.connect(path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            connection.close()
        assert tables == {"async_delegations"}

        database = SessionDB(path, read_only=True)
        try:
            assert database.has_session_schema() is False
            with pytest.raises(
                sqlite3.OperationalError, match="no such table: sessions"
            ):
                database.get_session(SHADOW)
        finally:
            database.close()

    def test_catalog_guard_reports_a_non_session_store_incompatible(
        self, tmp_path: Path
    ) -> None:
        """``PRAGMA table_info`` on a missing table is EMPTY, not an error."""

        path = _never_a_session_store(tmp_path / "profiles" / PROFILE / "state.db")
        database = SessionDB(path, read_only=True)
        try:
            SessionBridgeStore._install_profile_read_compatibility(database)
            assert SessionBridgeStore._database_columns(database, "sessions") == set()
            assert SessionBridgeStore._profile_catalog_compatible(database) is False
        finally:
            database.close()

    def test_claude_visibility_sources_skip_it(self, hostile_store) -> None:
        assert hostile_store.list_claude_visibility_hermes_sources(0.0, 10) == ()

    def test_sidebar_candidates_skip_it(self, hostile_store) -> None:
        assert hostile_store.list_sidebar_candidates(after=0.0, limit=10) == []

    def test_launch_metadata_is_none(self, hostile_store) -> None:
        assert hostile_store.get_session_launch_metadata(SHADOW) is None

    def test_native_snapshot_raises_keyerror_not_operationalerror(
        self, hostile_store
    ) -> None:
        """``KeyError`` is the documented not-found contract for this method."""

        with pytest.raises(KeyError):
            hostile_store.get_native_session_snapshot(SHADOW)

    def test_preview_source_raises_keyerror_not_operationalerror(
        self, hostile_store
    ) -> None:
        with pytest.raises(KeyError):
            hostile_store.get_sidebar_preview_source(SHADOW)


class TestUnreadableProfileStoreStillSurfaces:
    """Direction 2, the counterweight: "cannot be read" is not "absent".

    Buying direction 1 by catching ``sqlite3.Error`` anywhere on this path would
    also silence a corrupt, locked or I/O-failing profile database -- exactly
    what ``8ca1e62d64`` was landed to stop. These tests fail on that fix while
    the class above keeps passing, which is the whole point of pinning both.
    """

    def test_catalog_guard_raises_on_a_corrupt_store(self, tmp_path: Path) -> None:
        """It must RAISE, not return False. False means "not a session store"."""

        path = _unreadable_store(tmp_path / "profiles" / PROFILE / "state.db")
        probe = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                probe.execute("SELECT name FROM sqlite_master").fetchall()
        finally:
            probe.close()
        # The integrated SessionDB now probes during read-only construction,
        # before a catalog handle can be returned. Keep the same error contract.
        with pytest.raises(sqlite3.DatabaseError):
            with SessionDB(path, read_only=True) as database:
                SessionBridgeStore._profile_catalog_compatible(database)

    def test_catalog_guard_raises_on_an_io_failing_store(self, tmp_path: Path) -> None:
        """A disk I/O error is not a schema verdict either.

        The connection is stubbed rather than a real failing disk; everything
        else -- the handle, the lock, the guard -- is production code.
        """

        path = _never_a_session_store(tmp_path / "profiles" / PROFILE / "state.db")
        database = SessionDB(path, read_only=True)

        class _IOFailingConnection:
            def execute(self, *args: object, **kwargs: object) -> object:
                raise sqlite3.OperationalError("disk I/O error")

        healthy = database._conn
        database._conn = _IOFailingConnection()  # type: ignore[assignment]
        try:
            with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                SessionBridgeStore._profile_catalog_compatible(database)
        finally:
            database._conn = healthy
            database.close()

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda store: store.list_claude_visibility_hermes_sources(0.0, 10),
                id="claude_visibility",
            ),
            pytest.param(
                lambda store: store.list_sidebar_candidates(after=0.0, limit=10),
                id="sidebar_candidates",
            ),
            pytest.param(
                lambda store: store.get_session_launch_metadata(SHADOW),
                id="launch_metadata",
            ),
            pytest.param(
                lambda store: store.get_native_session_snapshot(SHADOW),
                id="native_snapshot",
            ),
        ],
    )
    def test_cross_profile_reads_report_a_corrupt_profile_store(
        self, corrupt_store, call
    ) -> None:
        """The error escapes to the caller instead of degrading to empty.

        On today's tree the raise comes from
        ``_install_profile_read_compatibility``, one layer above the catalog
        guard -- this pins the BEHAVIOUR, not the layer, so a future blanket
        ``except sqlite3.Error: continue`` around the profile loop is caught
        here wherever it is placed.
        """

        with pytest.raises(sqlite3.DatabaseError):
            call(corrupt_store)
