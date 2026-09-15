"""``_build_safe_env`` must survive a key vanishing from ``os.environ`` mid-read.

``os.environ`` is process-global and other threads mutate it.  Copying it is
NOT atomic: ``os._Environ.__iter__`` snapshots the key list
(``keys = list(self._data)``) but each value is re-read live, so
``dict(os.environ)`` / ``.copy()`` / ``.items()`` / ``dict.update(os.environ)``
raise ``KeyError(key)`` if a key is removed between the two steps.

``_build_safe_env`` read ``os.environ`` twice -- an unguarded ``.items()``
comprehension, then ``if key in os.environ: env[key] = os.environ[key]``
(check-then-act).  Both are raise sites, and the two reads could also observe
different states of the same mutation.

The vanishing key is simulated deterministically rather than with threads, so
this cannot flake.  ``_VanishingEnviron`` mimics the real class exactly: it
yields the key from its snapshot and then reports it missing.
"""

from __future__ import annotations

from collections.abc import MutableMapping

import pytest

from tools import mcp_tool_config


class _VanishingEnviron(MutableMapping):
    """``os.environ`` where ``vanish`` disappears after the key snapshot.

    Deliberately NOT a ``dict`` subclass.  ``dict(x)`` and ``dict.update(x)``
    take a fast C path for dict subclasses that copies the underlying storage
    without calling ``__iter__``/``__getitem__``, so a dict-based fake silently
    refuses to reproduce the bug -- which is what ``test_vanishing_key_would_
    break_a_naive_copy`` exists to catch.  ``os._Environ`` is a MutableMapping,
    so this mirrors the real thing and inherits the real ``.get()`` (which
    swallows KeyError) and the real ``ItemsView``.
    """

    def __init__(self, data: dict, vanish: str) -> None:
        self._data = dict(data)
        self._vanish = vanish

    def __iter__(self):
        # os._Environ.__iter__ yields from a snapshot taken BEFORE the removal,
        # so the vanished key is still listed.
        return iter([*self._data, self._vanish])

    def __getitem__(self, key):
        if key == self._vanish:
            raise KeyError(key)  # os._Environ re-raises with the original key
        return self._data[key]

    def __len__(self) -> int:
        return len(self._data) + 1

    def __setitem__(self, key, value) -> None:
        self._data[key] = value

    def __delitem__(self, key) -> None:
        del self._data[key]


def test_vanishing_key_would_break_a_naive_copy():
    """Control: proves the fixture actually models the failure being fixed.

    Without this, a green test below could mean the fixture never raises.
    """
    environ = _VanishingEnviron({"PATH": "/usr/bin"}, vanish="HERMES_KANBAN_BOARD")

    with pytest.raises(KeyError, match="HERMES_KANBAN_BOARD"):
        dict(environ)
    with pytest.raises(KeyError, match="HERMES_KANBAN_BOARD"):
        {}.update(environ)


def test_build_safe_env_survives_a_key_vanishing_mid_read(monkeypatch):
    """THE REGRESSION: no KeyError, and the vanished key is simply absent."""
    environ = _VanishingEnviron({"PATH": "/usr/bin"}, vanish="HERMES_KANBAN_BOARD")
    monkeypatch.setattr(mcp_tool_config.os, "environ", environ)

    env = mcp_tool_config._build_safe_env(None)

    assert "HERMES_KANBAN_BOARD" not in env
    assert env.get("PATH") == "/usr/bin"


def test_snapshot_keeps_a_kanban_key_that_is_present(monkeypatch):
    """POSITIVE CONTROL: the Kanban passthrough still works.

    Dropping the passthrough entirely would pass the test above.
    """
    monkeypatch.setattr(
        mcp_tool_config.os, "environ",
        {"PATH": "/usr/bin", "HERMES_KANBAN_BOARD": "team-alpha", "HERMES_KANBAN_DB": "/db"},
    )

    env = mcp_tool_config._build_safe_env(None)

    assert env["HERMES_KANBAN_BOARD"] == "team-alpha"
    assert env["HERMES_KANBAN_DB"] == "/db"


def test_snapshot_reads_through_get_and_never_raises():
    """``_environ_snapshot`` itself: a vanished key is dropped, not fatal."""
    environ = _VanishingEnviron({"A": "1", "B": "2"}, vanish="GONE")

    import tools.mcp_tool_config as mod

    real_environ, mod.os.environ = mod.os.environ, environ
    try:
        snapshot = mod._environ_snapshot()
    finally:
        mod.os.environ = real_environ

    assert snapshot == {"A": "1", "B": "2"}
