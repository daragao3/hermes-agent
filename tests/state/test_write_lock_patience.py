"""Write-lock patience for the shared state.db (#74478).

A shared state.db is legitimately held for multi-second stretches by
sibling Hermes processes (VACUUM after auto-prune, TRUNCATE checkpoint at
close on a large WAL, a long FTS pass from an older still-running
install).  The old attempt-counted retry budget (15 x <=150ms jitter)
gave up in ~1-2s of retrying, so:

- ``append_message`` failed -> the conversation loop aborted the turn as
  ``session_persistence_failed`` ("No reply: ... session storage could
  not be written") even though the store was healthy and merely busy;
- ``SessionDB()`` open failed -> the CLI disabled persistence for the
  whole run ("Failed to initialize SessionDB ... database is locked").

These tests lock the DB from a second connection for a bounded window and
assert the three contracts: transcript writes ride out long holds, open
rides out long holds, and exhausted patience raises an error that names
the real cause instead of reading like disk damage.
"""

import sqlite3
import threading
import time

import pytest

from hermes_state import SessionDB


def _hold_write_lock(db_path, hold_s, started_evt):
    """Hold the SQLite write lock on *db_path* for *hold_s* seconds."""
    conn = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        started_evt.set()
        time.sleep(hold_s)
        conn.execute("COMMIT")
    finally:
        conn.close()


def _hold_write_lock_until(db_path, started_evt, release_evt, max_hold_s=60.0):
    """Hold the write lock until *release_evt* is set (or *max_hold_s* elapses).

    A test that asserts patience RUNS OUT must outlast the write attempt, and
    the attempt has no usable upper bound: ``PRAGMA busy_timeout`` is a floor,
    not a ceiling. Measured on this host, ``BEGIN IMMEDIATE`` against a held
    lock on the 1s-timeout connection gave up anywhere between 1.47s and 3.98s
    (six consecutive samples: 1.875, 3.984, 1.469, 2.500, 3.813, 3.250) — the
    busy handler backs off in coarse increments and Windows sleep granularity
    under load stretches every one of them. A fixed ``time.sleep`` hold is
    therefore a race the test loses whenever the wait overshoots it.

    ``max_hold_s`` is only a backstop against a hung test, never the budget.
    """
    conn = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        started_evt.set()
        release_evt.wait(max_hold_s)
        conn.execute("COMMIT")
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path):
    d = SessionDB(db_path=tmp_path / "state.db")
    yield d
    d.close()


class TestTranscriptWritePatience:
    def test_append_message_survives_multi_second_lock_hold(self, db, monkeypatch):
        """A transcript append must ride out a lock held well past the old
        ~1-2s attempt-counted budget instead of aborting the turn.

        The hold is ended by the WRITE's own retry path, not by a clock. A
        fixed ``time.sleep`` hold cannot pin this contract: ``PRAGMA
        busy_timeout`` is a floor, not a ceiling (see
        ``_hold_write_lock_until``), so ``BEGIN IMMEDIATE`` frequently
        outlasts the hold unaided and the append then succeeds WITHOUT the
        patience loop ever running — the test goes green either way. Measured
        2026-09-13 against the previous fixed 3.0s hold, with the locked/busy
        retry in ``_execute_write`` neutered: 9 of 17 runs still PASSED, so it
        missed a total patience regression about half the time, and presented
        as a flaky red rather than a deterministic one.

        So the holder waits on an event only the patience path can set, and
        the release is additionally floored at *min_hold_s* to keep the
        stimulus a genuinely multi-second hold. Both halves are then
        deterministic: the lock is provably still held when the write retries,
        however far the busy handler wanders.

        Budget SIZE is pinned separately and race-free by
        ``test_transcript_patience_outlasts_routine_patience``; this test
        pins that the retry loop actually carries a write through a long hold.
        """
        db.create_session("s1", "cli")

        min_hold_s = 3.0  # stimulus: still a genuinely multi-second hold
        started, release = threading.Event(), threading.Event()
        retries = []

        holder = threading.Thread(
            target=_hold_write_lock_until,
            args=(db.db_path, started, release),
            # Backstop below _TRANSCRIPT_WRITE_PATIENCE_S: if the retry path
            # never fires, the holder lets go and this fails on the `retries`
            # assertion below instead of on a confusing 60s lock error.
            kwargs={"max_hold_s": 30.0},
        )
        holder.start()
        try:
            assert started.wait(5.0)
            floor_at = time.monotonic() + min_hold_s
            real_sleep = SessionDB._sleep_before_write_retry

            def _release_once_patient(self, deadline, patience_s):
                # Reached only when a write was refused and _execute_write
                # chose to keep waiting — i.e. proof the patience loop is live.
                retries.append(time.monotonic())
                if time.monotonic() >= floor_at:
                    release.set()
                return real_sleep(self, deadline, patience_s)

            monkeypatch.setattr(
                SessionDB, "_sleep_before_write_retry", _release_once_patient
            )

            t0 = time.monotonic()
            msg_id = db.append_message(
                session_id="s1", role="user", content="survived the lock"
            )
            attempt_s = time.monotonic() - t0
        finally:
            release.set()  # never park the holder on a failed attempt
            holder.join(timeout=10.0)
        assert not holder.is_alive()
        # The patience loop ran: without it the append dies the moment the
        # busy handler gives up, which is mid-hold by construction here.
        assert retries, "append_message never entered the write-patience retry loop"
        # ...and it carried the write through a hold far longer than the old
        # attempt-counted budget (15 attempts x <=150ms ~= 2.25s).
        assert attempt_s >= min_hold_s > 2.25
        assert isinstance(msg_id, int)
        msgs = db.get_messages("s1")
        assert any(m["content"] == "survived the lock" for m in msgs)

    def test_transcript_patience_outlasts_routine_patience(self, db):
        """append_message must be given MORE patience than routine writes —
        the invariant that lets background writers give up while the
        turn-critical append keeps waiting."""
        assert db._TRANSCRIPT_WRITE_PATIENCE_S > db._WRITE_PATIENCE_S
        # Both budgets must comfortably exceed the old ~2.25s worst case
        # (15 attempts x 150ms) that lost races against real maintenance.
        assert db._WRITE_PATIENCE_S >= 10.0
        assert db._TRANSCRIPT_WRITE_PATIENCE_S >= 30.0

    def test_exhausted_patience_names_the_real_cause(self, db, monkeypatch):
        """When patience genuinely runs out, the error must say the lock was
        held by another process — not read like disk/permission damage."""
        monkeypatch.setattr(SessionDB, "_WRITE_PATIENCE_S", 0.2)

        # Held until the attempt has finished, NOT for a fixed span: see
        # _hold_write_lock_until. With a 2.0s sleep this raced the busy
        # handler's overshoot and passed the write through ~1 run in 6.
        started, release = threading.Event(), threading.Event()
        holder = threading.Thread(
            target=_hold_write_lock_until, args=(db.db_path, started, release)
        )
        holder.start()
        try:
            assert started.wait(5.0)
            with pytest.raises(sqlite3.OperationalError) as excinfo:
                db.set_meta("k", "v")  # routine write, short patience
        finally:
            release.set()
            holder.join(timeout=10.0)
        assert not holder.is_alive()
        text = str(excinfo.value)
        assert "another Hermes process" in text
        assert "healthy" in text

    def test_write_succeeds_immediately_when_uncontended(self, db):
        """Patience must cost nothing when there is no contention."""
        db.create_session("s2", "cli")
        t0 = time.monotonic()
        db.append_message(session_id="s2", role="user", content="fast")
        assert time.monotonic() - t0 < 5.0  # loose: no patience-length stall


class TestOpenLockPatience:
    def test_open_survives_multi_second_lock_hold(self, tmp_path):
        """SessionDB() open must wait out a sibling's lock hold instead of
        disabling persistence for the whole run."""
        db_path = tmp_path / "state.db"
        # Create + close so the schema exists (open still runs reconcile DDL
        # through the same 1s-timeout connection).
        SessionDB(db_path=db_path).close()

        started = threading.Event()
        holder = threading.Thread(
            target=_hold_write_lock, args=(db_path, 3.0, started)
        )
        holder.start()
        try:
            assert started.wait(5.0)
            db = SessionDB(db_path=db_path)  # must NOT raise
        finally:
            holder.join(timeout=10.0)
        assert not holder.is_alive()
        try:
            db.create_session("s-open", "cli")
            db.append_message(session_id="s-open", role="user", content="ok")
            assert len(db.get_messages("s-open")) == 1
        finally:
            db.close()

    def test_open_propagates_non_lock_errors_immediately(self, tmp_path):
        """A non-lock open failure must not sit in the patience loop."""
        # A directory is not openable as a database file — raises an
        # OperationalError that is NOT the locked/busy class.
        bad_path = tmp_path / "state.db"
        bad_path.mkdir()
        t0 = time.monotonic()
        with pytest.raises(sqlite3.Error):
            SessionDB(db_path=bad_path)
        # Must fail well before a full patience window (loose bound).
        assert time.monotonic() - t0 < 15.0
