"""A mock parent agent must not make the delegate spawn path write a database.

``_open_child_session_db`` reads ``db_path`` off whatever object the parent's
``_session_db`` happens to be. A test that hands ``delegate_task`` a bare
``MagicMock()`` parent leaves ``_session_db`` auto-mocked, and because a mock is
``os.PathLike`` the child's dedicated handle used to open a REAL SessionDB at
``MagicMock/mock._session_db.db_path/<id>`` relative to the process CWD -- i.e. the
repo or worktree root under the test runner. Measured 2026-09-19 from
``tests/tools/test_subagent_steer.py::TestMissedSteerRetention``; the leftovers make
``git worktree remove`` refuse with the message a sibling's unsaved edits produce.

The contract this pins: a parent without a usable session store degrades to
``session_db=None`` (same as ``parent._session_db = None``), it does not invent a
database somewhere.
"""

from pathlib import Path
from unittest.mock import MagicMock

from tools.delegate_tool import _open_child_session_db


def _droppings(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("MagicMock*"))


def test_mock_parent_yields_no_handle_and_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parent = MagicMock()  # _session_db is auto-mocked -- exactly the offending shape

    assert _open_child_session_db(parent) is None
    assert _droppings(tmp_path) == []


def test_explicit_none_still_degrades_to_none(tmp_path, monkeypatch):
    """The pre-existing degradation contract is unchanged by the guard."""
    monkeypatch.chdir(tmp_path)
    parent = MagicMock()
    parent._session_db = None

    assert _open_child_session_db(parent) is None
    assert _droppings(tmp_path) == []


def test_a_real_parent_handle_still_gets_the_child_its_own_db(tmp_path, monkeypatch):
    """Positive control: the guard must not have broken the feature. Without this,
    a ``_open_child_session_db`` that returned None unconditionally would pass both
    tests above."""
    from hermes_state import SessionDB
    from hermes_state_registry import release_or_close

    monkeypatch.chdir(tmp_path)
    parent_db = SessionDB(db_path=tmp_path / "profile" / "state.db")
    parent = MagicMock()
    parent._session_db = parent_db
    child_db = None
    try:
        child_db = _open_child_session_db(parent)
        assert child_db is not None
        assert Path(child_db.db_path) == (tmp_path / "profile" / "state.db").resolve()
    finally:
        if child_db is not None:
            release_or_close(child_db)
        parent_db.close()
