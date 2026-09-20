"""A ``unittest.mock`` double is refused where a db PATH is expected.

``MagicMock`` satisfies ``os.PathLike``: ``mock.__fspath__()`` returns
``"MagicMock/<mock name>/<id(mock)>"``, so ``Path(mock)`` is an ordinary RELATIVE
path and nothing downstream can tell it apart from a deliberate one. Before the
guard, handing a mock to ``SessionDB`` / ``hermes_state_registry.acquire``
materialised a REAL database three levels under the process CWD -- the repo or
worktree root during a test run -- plus its ``.fts_rebuild.lock`` and
``.quarantine.lock`` siblings. ``git worktree remove`` then refuses with the same
message a sibling session's unsaved edits produce (measured 2026-09-19 on
``tests/tools``).

The live-DB isolation guard structurally cannot catch this: it only refuses paths
under the REAL Hermes root, and these land under the CWD.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, NonCallableMagicMock

import pytest

import hermes_state
import hermes_state_registry
from hermes_state_guard import refuse_mock_db_path


def _dropping_names(root: Path):
    """Every path under *root* whose name betrays a mock repr."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("MagicMock*"))


class TestRefuseMockDbPath:
    """The helper itself: mocks are refused, real paths are not."""

    @pytest.mark.parametrize(
        "mock",
        [MagicMock(), Mock(), NonCallableMagicMock(), AsyncMock()],
        ids=["magicmock", "mock", "noncallable", "asyncmock"],
    )
    def test_every_mock_flavour_is_refused(self, mock):
        with pytest.raises(TypeError) as excinfo:
            refuse_mock_db_path(mock, where="probe")
        assert "probe" in str(excinfo.value)

    @pytest.mark.parametrize("value", [None, "state.db", Path("state.db")], ids=["none", "str", "path"])
    def test_real_paths_pass(self, value):
        """Positive control: the guard is not simply refusing everything."""
        refuse_mock_db_path(value, where="probe")

    def test_message_names_the_path_it_prevented(self):
        """The operator must be able to recognise the dropping the guard stopped."""
        with pytest.raises(TypeError) as excinfo:
            refuse_mock_db_path(MagicMock(), where="probe")
        assert "MagicMock/" in str(excinfo.value).replace(os.sep, "/")


class TestNoDirectoryIsMaterialised:
    """The behaviour that actually matters: nothing lands on disk."""

    def test_session_db_refuses_a_mock_and_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(TypeError):
            hermes_state.SessionDB(db_path=MagicMock())
        assert _dropping_names(tmp_path) == []

    def test_registry_acquire_refuses_a_mock_and_writes_nothing(self, tmp_path, monkeypatch):
        """``acquire`` must refuse BEFORE its own ``Path(db_path)``: after that
        conversion the mock is an ordinary relative Path and ``SessionDB``'s guard
        can no longer see it -- this is the arm that the real defect went through."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(TypeError):
            hermes_state_registry.acquire(MagicMock())
        assert _dropping_names(tmp_path) == []

    def test_a_real_path_still_opens(self, tmp_path, monkeypatch):
        """Positive control for both arms above: without it, a guard that refused
        every path would pass those two tests."""
        monkeypatch.chdir(tmp_path)
        db = hermes_state.SessionDB(db_path=tmp_path / "real" / "state.db")
        try:
            assert (tmp_path / "real" / "state.db").exists()
        finally:
            db.close()
