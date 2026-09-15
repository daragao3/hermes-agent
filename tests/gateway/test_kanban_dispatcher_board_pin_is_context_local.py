"""The auto-decompose board pin must be context-local, never ``os.environ``.

``_KanbanDispatcher.auto_decompose_tick`` pins the board a decomposition runs
against, because the decomposer connects with no ``board=`` kwarg and resolves
through ``kanban_db.get_current_board()``.  It used to do that by setting
``os.environ["HERMES_KANBAN_BOARD"] = slug`` and popping it in a ``finally``.

That is process-global, and while the key was absent ANY concurrent reader of
``os.environ`` anywhere in the gateway could die.  ``os._Environ.__iter__``
snapshots the key list but re-reads every value live, so ``dict(os.environ)``,
``os.environ.copy()``, ``.items()`` loops and ``dict.update(os.environ)`` all
raise ``KeyError(key)`` -- with the original unencoded key -- when a key
disappears mid-read.

Not hypothetical.  On 2026-09-15T05:15:47Z cron job ``jobflow-ats-url-resolve``
failed with ``KeyError: 'HERMES_KANBAN_BOARD'`` raised inside python-dotenv's
``env.update(os.environ)`` (``dotenv/main.py:307``), reached from
``cron.scheduler._reload_dotenv_and_publish_delivery_target``, 711ms into this
dispatcher's first tick after a gateway restart.  The reader was third-party:
there was no read of ours to guard, so only the writer could be fixed.

The cron readers-writer lock cannot cover this.  ``_ReadWriteLock`` keys on
``_job_mutates_process_globals``, which takes a job dict and classifies cron
JOBS; this dispatcher is an embedded gateway service running on a worker thread
via ``_to_thread_process_service`` -- an unlocked writer racing locked readers.

Two things must hold, and testing only the first would pass if the pin were
simply deleted (which would silently decompose against the wrong board):

1. the tick never touches ``os.environ``;
2. the board IS pinned for the duration of the call.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from gateway.kanban_watchers_dispatcher import _DispatcherSettings, _KanbanDispatcher
from hermes_cli import kanban_db

KEY = "HERMES_KANBAN_BOARD"
BOARDS = ["team-alpha", "team-beta"]


def _settings() -> _DispatcherSettings:
    return _DispatcherSettings(
        interval=60.0, max_spawn=1, max_in_progress=None, failure_limit=3,
        stale_timeout_seconds=900, reconcile_orphans=False,
        default_assignee=None, max_in_progress_per_profile=None,
    )


class _FakeKb:
    """Board enumeration only -- plus the REAL context-local pin under test."""

    DEFAULT_BOARD = "default"
    scoped_current_board = staticmethod(kanban_db.scoped_current_board)

    @staticmethod
    def list_boards(include_archived: bool = False) -> list:
        return [{"slug": slug} for slug in BOARDS]


class _RecordingDecomposer:
    """Stands in for ``hermes_cli.kanban_decompose``, recording what it observed."""

    def __init__(self) -> None:
        self.env_seen: list[Any] = []
        self.override_seen: list[Any] = []

    def list_triage_ids(self) -> list[str]:
        self.env_seen.append(os.environ.get(KEY))
        self.override_seen.append(kanban_db._CURRENT_BOARD_OVERRIDE.get())
        return []


@pytest.fixture
def decomposer(monkeypatch) -> _RecordingDecomposer:
    """Install the recording stub as the module ``auto_decompose_tick`` imports.

    ``from hermes_cli import kanban_decompose`` resolves by ``getattr`` on the
    package, so patching the package attribute is what actually binds; the
    ``sys.modules`` entry is set too for the not-yet-imported path.  If this
    stub failed to bind, ``auto_decompose_tick`` swallows the ImportError and
    returns 0 -- which would leave the recordings empty and fail the asserts
    below rather than passing vacuously.
    """
    import sys

    import hermes_cli

    stub = _RecordingDecomposer()
    monkeypatch.setattr(hermes_cli, "kanban_decompose", stub, raising=False)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_decompose", stub)
    monkeypatch.delenv(KEY, raising=False)
    return stub


def test_tick_never_writes_the_board_into_os_environ(decomposer):
    """THE REGRESSION: the pin must not be visible in process-global env."""
    dispatcher = _KanbanDispatcher(_FakeKb(), _settings())

    dispatcher.auto_decompose_tick(auto_decompose_per_tick=3)

    # Observed from INSIDE the pinned window, once per board.
    assert decomposer.env_seen == [None, None], (
        "auto_decompose_tick wrote the board slug into os.environ; a concurrent "
        "os.environ reader anywhere in the gateway can then raise KeyError"
    )
    assert KEY not in os.environ


def test_tick_still_pins_the_board_context_locally(decomposer):
    """POSITIVE CONTROL: deleting the pin outright must not pass this file.

    Without this, a fix that simply removed the env write would look correct
    while every decomposition silently ran against the wrong board.
    """
    dispatcher = _KanbanDispatcher(_FakeKb(), _settings())

    dispatcher.auto_decompose_tick(auto_decompose_per_tick=3)

    assert decomposer.override_seen == BOARDS


def test_pin_is_reset_after_the_tick(decomposer):
    """The ContextVar must not leak past the call (pooled worker threads)."""
    assert kanban_db._CURRENT_BOARD_OVERRIDE.get() is None

    _KanbanDispatcher(_FakeKb(), _settings()).auto_decompose_tick(auto_decompose_per_tick=3)

    assert kanban_db._CURRENT_BOARD_OVERRIDE.get() is None


def test_get_current_board_prefers_the_context_override_over_env(monkeypatch):
    """Why the swap is behaviour-preserving: the override is consulted FIRST.

    ``get_current_board`` only returns a slug for a board that EXISTS, so both
    resolution paths are stubbed out here -- this pins the PRECEDENCE, which is
    what makes ``scoped_current_board`` a drop-in for the env pin.
    """
    monkeypatch.setattr(kanban_db, "board_exists", lambda slug: True)
    monkeypatch.setenv(KEY, "from-env")

    assert kanban_db.get_current_board() == "from-env"
    with kanban_db.scoped_current_board("from-context"):
        assert kanban_db.get_current_board() == "from-context"
    assert kanban_db.get_current_board() == "from-env"
