"""Scratch workspaces are ephemeral — the DIRECTORY must go, not just its contents.

A worker is launched with ``cwd=workspace`` and completes its own task
in-process (the ``kanban_complete`` tool), so ``_cleanup_workspace`` ran
``shutil.rmtree(ws, ignore_errors=True)`` from inside ``ws``. On Windows a
directory that is any process's cwd cannot be removed: the contents went, the
final ``rmdir`` failed with WinError 32, and ``ignore_errors`` hid it. Two
finished tasks (t_c08c3016, t_2d452c95 on 2026-09-17) left empty dirs under
``~/.hermes/kanban/workspaces/``.

Two layers fix it: the completing process steps out of the workspace before
``rmtree``; and the dispatcher's reclaim phase sweeps leftover dirs whose task
is finished, for the case where a *different* process (a worker's terminal
shell running ``hermes kanban complete``) still held the cwd.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_db_workspace as kbw


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB (same shape as test_kanban_db)."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _scratch_task(conn, title: str = "probe") -> tuple[str, Path]:
    """Create a scratch task with a materialised workspace holding one file."""
    task_id = kb.create_task(conn, title=title)
    ws = kbw.resolve_workspace(kb.get_task(conn, task_id))
    kbw.set_workspace_path(conn, task_id, ws)
    (ws / "notes.txt").write_text("scratch\n", encoding="utf-8")
    return task_id, ws


# ---------------------------------------------------------------------------
# Layer 1: the completing process steps out of its own workspace
# ---------------------------------------------------------------------------


def test_complete_task_removes_scratch_dir_that_is_the_process_cwd(kanban_home, monkeypatch):
    """Completing from inside the workspace (the in-process worker shape) removes the dir itself."""
    with kbc.connect() as conn:
        task_id, ws = _scratch_task(conn)
        monkeypatch.chdir(ws)

        assert kb.complete_task(conn, task_id, result="DONE")

    assert not ws.exists(), "scratch workspace directory must be gone, not just emptied"
    # The step-out lands on the managed workspaces root, never somewhere random.
    assert Path(os.getcwd()).resolve() == ws.parent.resolve()


def test_complete_task_removes_scratch_dir_when_cwd_is_a_subdirectory(kanban_home, monkeypatch):
    """A cwd deeper inside the workspace (worker `cd`'d into a subdir) is stepped out of too."""
    with kbc.connect() as conn:
        task_id, ws = _scratch_task(conn)
        sub = ws / "src" / "pkg"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)

        assert kb.complete_task(conn, task_id, result="DONE")

    assert not ws.exists()
    assert Path(os.getcwd()).resolve() == ws.parent.resolve()


def test_step_out_is_a_noop_when_cwd_is_elsewhere(kanban_home, tmp_path, monkeypatch):
    """Completion must not move a process whose cwd is unrelated to the workspace."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with kbc.connect() as conn:
        task_id, ws = _scratch_task(conn)
        assert kb.complete_task(conn, task_id, result="DONE")

    assert not ws.exists()
    assert Path(os.getcwd()).resolve() == elsewhere.resolve()


def test_deferred_parent_cleanup_steps_out_of_the_parent_workspace(kanban_home, monkeypatch):
    """The child-completion path that reaps a deferred parent uses the same removal."""
    with kbc.connect() as conn:
        parent, parent_ws = _scratch_task(conn, "parent")
        child = kb.create_task(conn, title="child")
        kb.link_tasks(conn, parent, child)
        kb.complete_task(conn, parent, result="handoff")
        assert parent_ws.exists(), "deferred while the child is active"

        monkeypatch.chdir(parent_ws)
        kb.complete_task(conn, child, result="built")

    assert not parent_ws.exists()
    assert Path(os.getcwd()).resolve() == parent_ws.parent.resolve()


# ---------------------------------------------------------------------------
# Layer 2: the dispatcher sweeps what a finished task could not remove itself
# ---------------------------------------------------------------------------


def test_sweep_reaps_only_finished_scratch_tasks(kanban_home, monkeypatch):
    """Leftover dirs of done/archived scratch tasks go; everything else stays."""
    root = kb.workspaces_root()
    with kbc.connect() as conn:
        done_id, done_ws = _scratch_task(conn, "done")
        kb.complete_task(conn, done_id, result="DONE")
        assert not done_ws.exists()
        done_ws.mkdir()  # the empty leftover a held cwd leaves behind

        archived_id, archived_ws = _scratch_task(conn, "archived")
        kb.archive_task(conn, archived_id)
        archived_ws.mkdir(exist_ok=True)

        running_id, running_ws = _scratch_task(conn, "running")
        kb.claim_task(conn, running_id)

        failed_id, failed_ws = _scratch_task(conn, "failed")
        conn.execute("UPDATE tasks SET status = 'failed' WHERE id = ?", (failed_id,))
        conn.commit()

        deferred_parent, deferred_ws = _scratch_task(conn, "deferred parent")
        active_child = kb.create_task(conn, title="active child")
        kb.link_tasks(conn, deferred_parent, active_child)
        kb.complete_task(conn, deferred_parent, result="handoff")
        assert deferred_ws.exists()

        stranger = root / "t_notatask"
        stranger.mkdir()

        removed = kbw.sweep_stale_scratch_workspaces(conn)

    assert sorted(removed) == sorted([done_id, archived_id])
    assert not done_ws.exists()
    assert not archived_ws.exists()
    assert running_ws.exists(), "a running task's workspace is live"
    assert failed_ws.exists(), "failed tasks keep their workspace for retry/inspection"
    assert deferred_ws.exists(), "a parent with an active child stays deferred"
    assert stranger.exists(), "an entry with no task row is never guessed at"


def test_sweep_skips_a_done_task_whose_recorded_path_is_elsewhere(kanban_home, tmp_path):
    """``<root>/<id>`` is only reaped when it IS the task's recorded workspace."""
    root = kb.workspaces_root()
    elsewhere = tmp_path / "explicit-scratch"
    elsewhere.mkdir()
    with kbc.connect() as conn:
        task_id = kb.create_task(conn, title="explicit path")
        kbw.set_workspace_path(conn, task_id, elsewhere)
        kb.complete_task(conn, task_id, result="DONE")
        lookalike = root / task_id
        lookalike.mkdir(parents=True)

        removed = kbw.sweep_stale_scratch_workspaces(conn)

    assert removed == []
    assert lookalike.exists()


def test_sweep_tolerates_a_missing_workspaces_root(kanban_home):
    with kbc.connect() as conn:
        assert not kb.workspaces_root().exists()
        assert kbw.sweep_stale_scratch_workspaces(conn) == []


def test_dispatch_tick_runs_the_sweep(kanban_home):
    """A dispatcher tick with nothing to spawn still reaps the leftover."""
    with kbc.connect() as conn:
        done_id, done_ws = _scratch_task(conn, "done")
        kb.complete_task(conn, done_id, result="DONE")
        done_ws.mkdir()

        res = kbd.dispatch_once(conn, spawn_fn=lambda task, workspace, board=None: 42)

    assert not res.spawned
    assert not done_ws.exists()


# ---------------------------------------------------------------------------
# `hermes kanban gc` reaps archived scratch workspaces with the same removal
# ---------------------------------------------------------------------------


def _gc_args() -> argparse.Namespace:
    return argparse.Namespace(event_retention_days=30, log_retention_days=30)


def test_gc_removes_an_archived_scratch_dir_that_is_the_process_cwd(kanban_home, monkeypatch, capsys):
    """Running gc from inside an archived task's leftover workspace removes the dir itself."""
    from hermes_cli import kanban_ops

    with kbc.connect() as conn:
        task_id, ws = _scratch_task(conn, "archived")
        kb.archive_task(conn, task_id)
    ws.mkdir(exist_ok=True)  # the empty leftover a held cwd leaves behind
    monkeypatch.chdir(ws)

    assert kanban_ops._cmd_gc(_gc_args()) == 0

    assert not ws.exists()
    assert Path(os.getcwd()).resolve() == ws.parent.resolve()
    assert "GC complete: 1 workspace(s)" in capsys.readouterr().out


def test_gc_leaves_non_archived_scratch_dirs_alone(kanban_home, capsys):
    from hermes_cli import kanban_ops

    with kbc.connect() as conn:
        running_id, running_ws = _scratch_task(conn, "running")
        kb.claim_task(conn, running_id)
        done_id, done_ws = _scratch_task(conn, "done")
        kb.complete_task(conn, done_id, result="DONE")
        done_ws.mkdir(exist_ok=True)

    assert kanban_ops._cmd_gc(_gc_args()) == 0

    assert running_ws.exists(), "a running task's workspace is live"
    assert done_ws.exists(), "gc only reaps ARCHIVED tasks; done leftovers are the dispatcher sweep's"
    assert "GC complete: 0 workspace(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The real Windows semantic: a foreign process's cwd pins the directory
# ---------------------------------------------------------------------------


@pytest.mark.windows_only
class TestForeignCwdHolder:
    """Windows refuses ``rmdir`` on any process's cwd; POSIX unlinks it regardless."""

    def test_completion_survives_and_the_sweep_finishes_after_the_holder_exits(
        self, kanban_home,
    ):
        with kbc.connect() as conn:
            task_id, ws = _scratch_task(conn)
            # ``Popen`` returns before the child's loader has opened its cwd
            # handle; wait for the child to report it is inside ``ws`` (its
            # ``os.getcwd()`` proves the handle is held) before completing.
            holder = subprocess.Popen(
                [
                    sys.executable, "-c",
                    "import os, sys, time; os.getcwd(); "
                    "sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)",
                ],
                cwd=str(ws), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            try:
                assert holder.stdout.readline().strip() == "ready"
                # Completion never blocks on the pinned dir: contents go, dir stays.
                assert kb.complete_task(conn, task_id, result="DONE")
                assert ws.is_dir()
                assert list(ws.iterdir()) == []
                # The holder is still alive, so the sweep cannot finish yet either.
                assert kbw.sweep_stale_scratch_workspaces(conn) == []
                assert ws.is_dir()
            finally:
                holder.kill()
                holder.wait(timeout=30)
                holder.stdout.close()

            deadline = time.monotonic() + 10
            removed: list[str] = []
            while time.monotonic() < deadline:
                removed = kbw.sweep_stale_scratch_workspaces(conn)
                if removed:
                    break
                time.sleep(0.2)

        assert removed == [task_id]
        assert not ws.exists()

    def test_gc_does_not_count_a_dir_pinned_by_a_foreign_cwd(self, kanban_home, capsys):
        from hermes_cli import kanban_ops

        with kbc.connect() as conn:
            task_id, ws = _scratch_task(conn, "archived")
            kb.archive_task(conn, task_id)
        ws.mkdir(exist_ok=True)
        holder = subprocess.Popen(
            [
                sys.executable, "-c",
                "import os, sys, time; os.getcwd(); "
                "sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)",
            ],
            cwd=str(ws), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "ready"
            assert kanban_ops._cmd_gc(_gc_args()) == 0
            assert ws.is_dir(), "pinned by the holder's cwd"
            assert "GC complete: 0 workspace(s)" in capsys.readouterr().out
        finally:
            holder.kill()
            holder.wait(timeout=30)
            holder.stdout.close()
