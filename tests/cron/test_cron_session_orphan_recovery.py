"""Startup recovery must close state.db cron sessions whose run died with its owner.

``cron/scheduler.py::run_job`` ends its session only in its own ``finally``
(``end_session(..., "cron_complete")``). A process that dies mid-run -- a
gateway replaced by ``hermes gateway run --replace``, a ``hermes cron run``
whose terminal closed -- never reaches it, and until 2026-09-07 nothing else
closed the row: the execution ledger got its ``unknown`` verdict and jobs.json
its stamp at the next scheduler start, but ``sessions.ended_at`` stayed NULL
until ``scripts/hermes-postgres-bridge.py``'s 24h idle reaper stamped it
``reaped_stale``. Measured on profiles/main: ``cron_1f8c450136b5_20260906_120033``
(gateway pid 16600, replaced 12:10) read RUNNING until 12:15:59 the next day.

The recovery hook is ``InProcessCronScheduler.recover_interrupted()``, which
already runs before the first tick. These tests drive that entry point with a
real ledger and a real ``SessionDB`` in a tempdir, and use only APIs that exist
on both sides of the fix so the RED direction can be demonstrated by running
the module against the parent commit's sources.

Ownership rule under test: a run claims its ledger row BEFORE it creates its
session, and the row stays non-terminal until the run's own teardown. So an
open cron session whose job has NO non-terminal row after recovery has no
process behind it; one whose job still has a live row elsewhere must be left
alone.
"""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import patch

import psutil
import pytest


def _unused_pid() -> int:
    pid = 4_000_000
    while psutil.pid_exists(pid):
        pid -= 1
    return pid


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the execution ledger at a tempdir and return the module."""
    from cron import executions

    monkeypatch.setattr(
        executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db"
    )
    return executions


@pytest.fixture
def session_db(tmp_path, monkeypatch):
    """A real SessionDB in the tempdir, and the default path pinned to it.

    ``_close_orphaned_cron_sessions`` opens ``SessionDB()`` with no path, the
    same call ``run_job`` makes, so the default must resolve to this file.
    """
    import hermes_state

    db_path = tmp_path / "state.db"
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", db_path)
    db = hermes_state.SessionDB(db_path=db_path)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def quiet_recovery():
    """Keep recover_interrupted() off jobs.json and off the event bus."""
    with patch("cron.jobs.mark_job_interrupted", return_value=True), \
         patch("events.gateway_integration.get_bus", return_value=None):
        yield


def _disown_row(ledger, execution_id: str, *, pid: int, process_started_at, process_id="dead-owner"):
    """Rewrite a ledger row so it belongs to some OTHER process."""
    with sqlite3.connect(ledger.EXECUTIONS_FILE) as conn:
        conn.execute(
            "UPDATE executions SET process_id=?, pid=?, process_started_at=? WHERE id=?",
            (process_id, pid, process_started_at, execution_id),
        )


def _dead_owner_run(ledger, job_id: str) -> str:
    row = ledger.create_execution(job_id, source="builtin")
    ledger.mark_execution_running(row["id"])
    _disown_row(ledger, row["id"], pid=_unused_pid(), process_started_at=1)
    return row["id"]


def _live_elsewhere_run(ledger, job_id: str) -> str:
    """A running row owned by a process that is provably alive: this one, under
    a foreign process_id, with its real start time so the liveness probe
    classifies it ``live`` rather than skipping it as our own."""
    row = ledger.create_execution(job_id, source="direct")
    ledger.mark_execution_running(row["id"])
    _disown_row(
        ledger, row["id"], pid=os.getpid(),
        process_started_at=ledger._process_start_time(os.getpid()),
        process_id="another-live-process",
    )
    return row["id"]


def _recover():
    from cron.scheduler_provider import InProcessCronScheduler

    return InProcessCronScheduler().recover_interrupted()


def test_dead_owner_run_closes_its_orphaned_session(ledger, session_db, quiet_recovery):
    """The evidence case: gateway replaced mid-run, session left RUNNING."""
    _dead_owner_run(ledger, "1f8c450136b5")
    session_db.create_session("cron_1f8c450136b5_20260906_120033", source="cron")
    assert session_db.get_session("cron_1f8c450136b5_20260906_120033")["ended_at"] is None

    recovered = _recover()

    assert recovered == 1, "the ledger recovery itself must be unchanged"
    row = session_db.get_session("cron_1f8c450136b5_20260906_120033")
    assert row["ended_at"] is not None, (
        "a session whose owner died must not read RUNNING until the 24h reaper"
    )
    assert row["end_reason"] == "cron_interrupted", (
        "must be distinguishable from cron_complete (the run finished) and "
        "from reaped_stale (the idle reaper guessed)"
    )
    assert row["ended_at"] >= row["started_at"]


def test_orphan_with_no_ledger_row_at_all_is_closed(ledger, session_db, quiet_recovery):
    """A run whose ledger row was already recovered (or pruned) by an earlier
    pass is still an orphan: no process holds it, so close it too."""
    session_db.create_session("cron_abcdef012345_20260907_020834", source="cron")

    assert _recover() == 0, "nothing for the ledger to recover this time"

    row = session_db.get_session("cron_abcdef012345_20260907_020834")
    assert row["ended_at"] is not None
    assert row["end_reason"] == "cron_interrupted"


def test_live_run_in_another_process_keeps_its_session_open(ledger, session_db, quiet_recovery):
    """The guard direction: a `hermes cron run` (or the desktop ticker) still
    inside a run of the job owns an open session that must survive."""
    _live_elsewhere_run(ledger, "1f8c450136b5")
    session_db.create_session("cron_1f8c450136b5_20260907_020834", source="cron")

    assert _recover() == 0, "a live owner must not be recovered as interrupted"

    row = session_db.get_session("cron_1f8c450136b5_20260907_020834")
    assert row["ended_at"] is None, "closing a live run's session would be data loss"
    assert row["end_reason"] is None


def test_a_job_with_both_a_live_run_and_an_orphan_is_left_alone(ledger, session_db, quiet_recovery):
    """Protection is per JOB: with a live run present, even the older orphan of
    the same job waits for a later pass rather than risk the live session."""
    _live_elsewhere_run(ledger, "1f8c450136b5")
    session_db.create_session("cron_1f8c450136b5_20260906_120033", source="cron")
    session_db.create_session("cron_1f8c450136b5_20260907_020834", source="cron")

    _recover()

    for sid in ("cron_1f8c450136b5_20260906_120033", "cron_1f8c450136b5_20260907_020834"):
        assert session_db.get_session(sid)["ended_at"] is None


def test_this_process_own_in_flight_run_keeps_its_session_open(ledger, session_db, quiet_recovery):
    """Rows owned by this process are never recovered and must protect their
    session too (Chronos calls recover_interrupted from a long-lived process)."""
    row = ledger.create_execution("0123456789ab", source="builtin")
    ledger.mark_execution_running(row["id"])
    session_db.create_session("cron_0123456789ab_20260907_120054", source="cron")

    _recover()

    assert session_db.get_session("cron_0123456789ab_20260907_120054")["ended_at"] is None


def test_only_cron_shaped_cron_source_rows_are_touched(ledger, session_db, quiet_recovery):
    """Other sources, odd ids, and already-ended rows are outside the blast radius."""
    session_db.create_session("cron_1f8c450136b5_20260906_120033", source="cli")
    session_db.create_session("cron_not_a_run_stamp", source="cron")
    session_db.create_session("cron_ffffffffffff_20260906_080004", source="cron")
    session_db.end_session("cron_ffffffffffff_20260906_080004", "cron_complete")

    _recover()

    assert session_db.get_session("cron_1f8c450136b5_20260906_120033")["ended_at"] is None, (
        "a non-cron source is not ours to close, whatever its id looks like"
    )
    assert session_db.get_session("cron_not_a_run_stamp")["ended_at"] is None, (
        "an id that is not run_job's shape cannot be mapped to a job, so leave it"
    )
    ended = session_db.get_session("cron_ffffffffffff_20260906_080004")
    assert ended["end_reason"] == "cron_complete", "first reason wins; never rewritten"


def test_session_store_failure_does_not_break_recovery(ledger, quiet_recovery):
    """This runs on the ticker's startup path: a state.db fault must cost only
    the prompt close, never the ledger verdict and never the scheduler."""
    _dead_owner_run(ledger, "1f8c450136b5")

    with patch("hermes_state.SessionDB", side_effect=sqlite3.OperationalError("locked")):
        recovered = _recover()

    assert recovered == 1
