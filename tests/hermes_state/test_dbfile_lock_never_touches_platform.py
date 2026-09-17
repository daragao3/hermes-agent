"""hermes_state_dbfile.quarantine_cross_process_lock must not consult ``platform``.

It runs on every SessionDB open, including in every ``python -c`` child the
persistence conformance cells and the live-DB guard spawn. On Windows,
``platform.system()`` runs two WMI queries on first use; on CPython < 3.13.4 the
query thread abandoned after the 100 ms connect timeout (gh-130727) can close a
random live handle of the process, which under host load killed those children
with exit code 0xC000070A (STATUS_THREADPOOL_HANDLE_EXCEPTION) and an empty
stderr -- 2 of 12 children on 2026-09-17. ``sys.platform`` answers the same
question with no thread and no WMI.
"""

from __future__ import annotations

import platform

import hermes_state_dbfile


def _boom(*args, **kwargs):
    raise AssertionError("quarantine_cross_process_lock consulted platform.*")

def test_lock_acquire_and_release_without_platform(tmp_path, monkeypatch):
    for name in ("system", "uname", "machine", "release", "version", "win32_ver"):
        monkeypatch.setattr(platform, name, _boom)
    db = tmp_path / "state.db"
    with hermes_state_dbfile.quarantine_cross_process_lock(db, timeout=1.0) as acquired:
        assert acquired is True
        assert (tmp_path / "state.db.quarantine.lock").exists()

def test_lock_contention_path_without_platform(tmp_path, monkeypatch):
    """The timeout branch is the one a second process hits; it is platform-free too."""
    for name in ("system", "uname", "machine", "release", "version", "win32_ver"):
        monkeypatch.setattr(platform, name, _boom)
    db = tmp_path / "state.db"
    with hermes_state_dbfile.quarantine_cross_process_lock(db, timeout=1.0) as outer:
        assert outer is True
        # Re-entering from the same process contends on the same byte range on
        # Windows (msvcrt -> yields False at the deadline) and is a no-op re-lock
        # on POSIX (flock per open file description -> True): either outcome must
        # resolve without touching platform.
        with hermes_state_dbfile.quarantine_cross_process_lock(db, timeout=0.2) as inner:
            assert inner in (True, False)
