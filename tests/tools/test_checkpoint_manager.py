"""Tests for tools/checkpoint_manager.py — CheckpointManager (v2 single-store)."""

import argparse
import json
import logging
import os
import stat
import shutil
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from tools.checkpoint_manager import (
    CheckpointManager,
    _init_store,
    _run_git,
    _git_env,
    _normalize_path,
    _MAX_FILES,
    _project_hash,
    _store_path,
    _ref_name,
    _project_meta_path,
    _touch_project,
    prune_checkpoints,
    maybe_auto_prune_checkpoints,
    store_status,
    clear_all,
    clear_legacy,
)


# Nearly every test here drives real ``git`` subprocesses, so the whole module
# is spawn-bound rather than compute-bound.  The suite-wide --timeout=30
# (pyproject.toml) is calibrated for in-process tests; it is not survivable
# here on a contended host, where a single spawn costs seconds rather than
# milliseconds.  Measured 2026-08-11 alongside 8+ concurrent pytest sweeps:
# a bare ``git --version`` took 2.75s, so even _init_store's six config
# spawns (~22s) straddled the 30s default and killed test_creates_git_store.
# Because --timeout-method=thread ``os._exit``es the whole pytest process, one
# such overrun aborts an entire tests/tools sweep -- so this is a sweep-integrity
# guard, not just a per-test allowance.  TestRealPruning overrides this with a
# larger budget; see its docstring for the per-spawn calibration data.
#
# Sized from a measured full-file run on that loaded host (80 passed in 46:14):
# the slowest test outside TestRealPruning was
# TestListCheckpoints::test_multiple_checkpoints_ordered at 157.5s, with a long
# tail of 86-143s siblings.  300s keeps ~1.9x margin over that worst case; 180s
# would have left only 13%, which is not a margin on a host whose spawn cost is
# itself the variable being absorbed.
pytestmark = pytest.mark.timeout(300)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def work_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "main.py").write_text("print('hello')\n")
    (d / "README.md").write_text("# Project\n")
    return d


@pytest.fixture()
def checkpoint_base(tmp_path):
    """Isolated checkpoint base — never writes to ~/.hermes/."""
    return tmp_path / "checkpoints"


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture()
def mgr(work_dir, checkpoint_base, monkeypatch):
    monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
    return CheckpointManager(enabled=True, max_snapshots=50)


@pytest.fixture()
def disabled_mgr(checkpoint_base, monkeypatch):
    monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
    return CheckpointManager(enabled=False)


# =========================================================================
# Store path + project hash
# =========================================================================

class TestStorePath:
    def test_store_is_single_shared_path(self, work_dir, checkpoint_base, monkeypatch):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        # All projects resolve to the same store (only refs/indexes are per-project).
        assert _store_path() == _store_path(checkpoint_base)
        assert _project_hash(str(work_dir)) != _project_hash(str(work_dir.parent / "other"))

    def test_project_hash_identifies_dir_and_expands_tilde(self, fake_home):
        project = fake_home / "project"
        project.mkdir()
        assert _project_hash(str(project)) == _project_hash(str(project))
        assert _project_hash(str(project)) != _project_hash(str(fake_home / "other"))
        # ~/project and its expanded form are the same project.
        assert _project_hash(f"~/{project.name}") == _project_hash(str(project))


# =========================================================================
# Store init + legacy migration
# =========================================================================

class TestStoreInit:
    def test_creates_git_store(self, work_dir, checkpoint_base, monkeypatch):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        store = _store_path(checkpoint_base)
        err = _init_store(store, str(work_dir))
        assert err is None
        assert (store / "HEAD").exists()
        assert (store / "objects").exists()
        assert (store / "info" / "exclude").exists()
        assert "node_modules/" in (store / "info" / "exclude").read_text()
        # The project dir itself never becomes a git repo.
        assert not (work_dir / ".git").exists()
        # Idempotent.
        assert _init_store(store, str(work_dir)) is None

    def test_legacy_migration_archives_prev2_repos(
        self, checkpoint_base, work_dir,
    ):
        """Pre-v2 per-project shadow repos get moved into legacy-<ts>/."""
        base = checkpoint_base
        base.mkdir(parents=True)
        # Simulate a pre-v2 repo directly under base
        fake_repo = base / "deadbeefcafebabe"
        fake_repo.mkdir()
        (fake_repo / "HEAD").write_text("ref: refs/heads/main\n")
        (fake_repo / "HERMES_WORKDIR").write_text(str(work_dir) + "\n")
        (fake_repo / "objects").mkdir()

        # Init store — should migrate the fake pre-v2 repo
        store = _store_path(base)
        err = _init_store(store, str(work_dir))
        assert err is None

        assert not fake_repo.exists()
        legacies = [p for p in base.iterdir() if p.name.startswith("legacy-")]
        assert len(legacies) == 1
        assert (legacies[0] / fake_repo.name).exists()
        assert (legacies[0] / fake_repo.name / "HEAD").exists()


# =========================================================================
# CheckpointManager — disabled
# =========================================================================

class TestDisabledManager:
    def test_disabled_manager_is_inert(self, disabled_mgr, work_dir):
        disabled_mgr.new_turn()
        assert disabled_mgr.ensure_checkpoint(str(work_dir)) is False


# =========================================================================
# CheckpointManager — taking checkpoints
# =========================================================================

class TestTakeCheckpoint:
    def test_first_checkpoint_dedups_and_skips_unsafe_dirs(self, mgr, work_dir):
        assert mgr.ensure_checkpoint(str(work_dir), "first") is True
        assert mgr.ensure_checkpoint(str(work_dir), "second") is False  # dedup'd
        # Never snapshot the filesystem root or the user's home.
        assert mgr.ensure_checkpoint("/", "root") is False
        assert mgr.ensure_checkpoint(str(Path.home()), "home") is False

    def test_new_turn_resets_dedup_but_needs_changes(self, mgr, work_dir):
        assert mgr.ensure_checkpoint(str(work_dir), "turn 1") is True
        mgr.new_turn()
        # Nothing changed on disk → no commit.
        assert mgr.ensure_checkpoint(str(work_dir), "no changes") is False
        mgr.new_turn()
        (work_dir / "main.py").write_text("print('modified')\n")
        assert mgr.ensure_checkpoint(str(work_dir), "turn 2") is True

    def test_no_changes_skips_commit(self, mgr, work_dir):
        mgr.ensure_checkpoint(str(work_dir), "initial")
        mgr.new_turn()
        assert mgr.ensure_checkpoint(str(work_dir), "no changes") is False

    def test_skip_root_dir(self, mgr):
        assert mgr.ensure_checkpoint("/", "root") is False

    def test_skip_home_dir(self, mgr):
        assert mgr.ensure_checkpoint(str(Path.home()), "home") is False

    @pytest.mark.parametrize("broad", ["/", "HOME"])
    def test_broad_dir_guard_fires_before_any_filesystem_walk(
        self, mgr, monkeypatch, broad,
    ):
        """The too-broad guard must short-circuit BEFORE ``_take`` walks anything.

        Asserting only ``is False`` (the two tests above) cannot tell a guard
        hit from a guard MISS that happened to bail later: ``_take`` also
        returns False once ``_dir_file_count`` exceeds _MAX_FILES.  On Windows
        that was the live path — ``Path("/").resolve()`` is the current drive's
        root ("C:\\"), never the literal "/" the guard compared against — so
        "/" fell through and rglob'd 50,000 entries of the whole C: drive
        before returning the expected False.  The test passed and took 8.4s.

        Spying on ``_dir_file_count`` turns that silent fallthrough into a
        failure.  Note the spy RECORDS rather than raises: ``ensure_checkpoint``
        wraps ``_take`` in a bare ``except Exception`` and returns False, so a
        raising spy is swallowed and the test passes against the very bug it
        is meant to pin.
        """
        walked = []

        def _spy_dir_file_count(path):
            walked.append(path)
            return _MAX_FILES + 1  # bail out of _take immediately

        monkeypatch.setattr(
            "tools.checkpoint_manager._dir_file_count", _spy_dir_file_count,
        )
        target = str(Path.home()) if broad == "HOME" else broad
        assert mgr.ensure_checkpoint(target, "broad") is False
        assert walked == [], (
            f"too-broad guard missed {target!r}: _dir_file_count walked {walked}"
        )

    def test_multiple_projects_share_store(self, mgr, tmp_path):
        """Two projects commit to the SAME shared store (dedup wins)."""
        a = tmp_path / "proj-a"
        a.mkdir()
        (a / "f.py").write_text("a\n")
        b = tmp_path / "proj-b"
        b.mkdir()
        (b / "g.py").write_text("b\n")

        assert mgr.ensure_checkpoint(str(a), "a") is True
        mgr.new_turn()
        assert mgr.ensure_checkpoint(str(b), "b") is True

        from tools.checkpoint_manager import CHECKPOINT_BASE as BASE
        # Exactly one store dir + two project metas
        assert (BASE / "store" / "HEAD").exists()
        assert (BASE / "store" / "projects" / f"{_project_hash(str(a))}.json").exists()
        assert (BASE / "store" / "projects" / f"{_project_hash(str(b))}.json").exists()


# =========================================================================
# CheckpointManager — listing
# =========================================================================

class TestListCheckpoints:
    def test_list_reports_newest_first(self, mgr, work_dir):
        assert mgr.list_checkpoints(str(work_dir)) == []

        mgr.ensure_checkpoint(str(work_dir), "first")
        result = mgr.list_checkpoints(str(work_dir))
        assert len(result) == 1
        assert result[0]["reason"] == "first"
        assert "hash" in result[0]
        assert "short_hash" in result[0]
        assert "timestamp" in result[0]

        mgr.new_turn()
        (work_dir / "main.py").write_text("v2\n")
        mgr.ensure_checkpoint(str(work_dir), "second")
        mgr.new_turn()
        (work_dir / "main.py").write_text("v3\n")
        mgr.ensure_checkpoint(str(work_dir), "third")

        result = mgr.list_checkpoints(str(work_dir))
        assert len(result) == 3
        assert result[0]["reason"] == "third"
        assert result[2]["reason"] == "first"

    def test_projects_share_one_store_but_list_separately(
        self, mgr, checkpoint_base, tmp_path,
    ):
        """Two projects commit to the SAME shared store, isolated per project."""
        a = tmp_path / "proj-a"
        a.mkdir()
        (a / "f.py").write_text("a\n")
        b = tmp_path / "proj-b"
        b.mkdir()
        (b / "g.py").write_text("b\n")

        assert mgr.ensure_checkpoint(str(a), "A-1") is True
        mgr.new_turn()
        assert mgr.ensure_checkpoint(str(b), "B-1") is True

        # Exactly one store dir + two project metas.
        assert (checkpoint_base / "store" / "HEAD").exists()
        projects = checkpoint_base / "store" / "projects"
        assert (projects / f"{_project_hash(str(a))}.json").exists()
        assert (projects / f"{_project_hash(str(b))}.json").exists()

        # Listing one project doesn't leak the other's checkpoints.
        assert [c["reason"] for c in mgr.list_checkpoints(str(a))] == ["A-1"]
        assert [c["reason"] for c in mgr.list_checkpoints(str(b))] == ["B-1"]


# =========================================================================
# Pruning: max_snapshots actually enforced (v2 fix)
# =========================================================================

# Measured git spawns for test_max_snapshots_trims_history's shape
# (max_snapshots=2, 4 snapshots).  Counted 2026-08-15 by wrapping
# tools.checkpoint_manager.subprocess.run; the old max_snapshots=3 / 6
# snapshots shape cost 75.
_TRIM_HISTORY_SPAWNS = 50

# Same, for test_steady_state_prune_snapshot_spawn_budget's shape: 2 seed
# snapshots to reach capacity + 1 at-capacity snapshot, max_snapshots=2.
_SPAWN_BUDGET_SPAWNS = 38

# A real git command in this file costs ~1.24x a bare ``git --version``
# (derived from the 2026-08-11 loaded-host pair: 2.75s probe, 3.4s/spawn
# across 75 spawns).  Used to price a test before running it.
_SPAWN_COST_VS_PROBE = 1.24

# Skip rather than run when the projection eats more than half the class's
# 600s timeout.  Half, not all: --timeout-method=thread ``os._exit``es the
# WHOLE pytest process, so overshooting the budget destroys the sweep's
# results instead of failing one test.  A skip is loud, cheap and honest;
# a session kill silently truncates the run (2026-08-11 aborted tests/tools
# at 12% while still printing a clean-looking result).
_SPAWN_BUDGET_SECONDS = 300.0

# Memoised result of _probe_git_spawn_cost().
_GIT_SPAWN_COST = None


def _probe_git_spawn_cost() -> float:
    """Wall-clock seconds for one bare ``git --version``.

    The module docstring's own calibration handle: sub-0.5s on a quiet host,
    2.746s on the 2026-08-11 contended one.  Cached per session — the probe
    is itself a spawn, and on the host it is meant to detect it is expensive.
    """
    global _GIT_SPAWN_COST
    if _GIT_SPAWN_COST is None:
        start = time.monotonic()
        subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=120,
        )
        _GIT_SPAWN_COST = time.monotonic() - start
    return _GIT_SPAWN_COST


def _require_affordable_spawns(spawn_count: int) -> None:
    """Skip if this host is too contended to afford ``spawn_count`` git spawns.

    These tests are spawn-bound, and process-spawn cost on Windows is not a
    property of the code under test — it swings ~14x with host contention
    (0.26s/spawn quiet, 3.6s/spawn under 8 concurrent sweeps).  No timeout
    value fixes that; see the TestRealPruning docstring.
    """
    probe = _probe_git_spawn_cost()
    projected = spawn_count * probe * _SPAWN_COST_VS_PROBE
    if projected > _SPAWN_BUDGET_SECONDS:
        pytest.skip(
            f"host too contended for a {spawn_count}-git-spawn test: a bare "
            f"`git --version` took {probe:.2f}s, projecting ~{projected:.0f}s "
            f"(budget {_SPAWN_BUDGET_SECONDS:.0f}s). Skipping beats letting "
            f"--timeout-method=thread os._exit the whole sweep."
        )


@pytest.mark.timeout(600)
class TestRealPruning:
    """Real snapshot+prune cycles — dozens of git spawns per test.

    Windows 2026-06-11: a git spawn costs 0.2-0.4s under redirected stdio,
    so these tests are spawn-bound (test_max_snapshots_trims_history ran
    ~30s pre-fix and straddled the suite-wide --timeout=30, whose thread
    method kills the whole session).  The spawn-budget test below pins the
    spawn COUNT so the fix can't silently regress.

    The wall-clock budget, though, is not a property of this code — it is a
    property of the host, and the variable to size against is MEASURED PER-SPAWN
    COST, not any single host metric:

        quiet host     (2026-06-11, post-fix): ~0.26s/spawn ->  18.35s
        contended host (2026-08-11, measured):  ~3.6s/spawn -> 255.9s

    Do NOT read commit-charge percentage as the predictor — it is a contributor,
    not the signal.  A 2026-06-11 run of this whole file finished 80 tests in
    72.3s at 97.2% commit; the 2026-08-11 run took 2774.6s at 97.5% commit.
    Near-identical commit, 38x the wall clock.  What differed was concurrency:
    the slow run overlapped 8+ other pytest sweeps.  To judge this file, time a
    bare ``git --version`` (2.746s on the slow host, sub-0.5s when quiet).

    Same 71 spawns, same code, 14x the wall clock — a bare ``git --version``
    alone cost 2.75s on the 08-11 host.  The old timeout(120) sat between
    those two points, so the test passed on an idle host and blew up on a
    loaded one.  Because the suite runs --timeout-method=thread, which
    ``os._exit``es the WHOLE pytest process rather than failing one test,
    that overrun aborted an entire tests/tools sweep at 12% (2026-08-11).
    timeout(600) clears the measured loaded-host cost with ~2.3x margin while
    staying bounded.  Individual git calls are independently capped by
    checkpoint_manager._GIT_TIMEOUT (30s), so a real hang still terminates —
    but only since 2026-08-16.  Before then that cap was nominal wherever a
    git subcommand left a grandchild alive: ``_run_git`` used ``subprocess.run(
    capture_output=True, timeout=N)``, whose Windows timeout path kills the
    direct child and then re-enters ``communicate()`` with NO timeout, blocking
    until every handle on the capture pipe closes — impossible while a
    surviving grandchild holds the inherited one (measured: a ``timeout=2``
    call returned after 24.3s).  ``git gc --prune=now`` — which
    prune_checkpoints and _enforce_size_cap both run — is the one probed git
    subcommand that spawns such a grandchild, so a slow gc could wedge there
    indefinitely.  ``_run_git`` now spawns via ``run_text_capture``
    (file-backed capture + tree-kill); see TestGitTimeoutIsBounded, which
    guards the routing.

    THAT HAZARD IS NOT WHY THESE TESTS WERE SLOW — do not conflate the two.
    The snapshot commands this class drives (add, write-tree, commit-tree,
    update-ref, log) are leaf processes: probed 2026-08-15, none of them spawns
    a descendant, so their 30s cap held even before the capture-pipe fix and
    the fix did not speed them up.  Their cost is N spawns times a per-spawn
    price set by host contention, and no timeout value rescues that — raising
    the clock only buys a slower failure.  test_max_snapshots_trims_history
    hung >900s and damaged two sweeps for this reason alone.

    So the lever is the SPAWN COUNT, not the clock.  Measured on this host:

        max_snapshots=3, 6 snapshots -> 75 spawns, 10.14s quiet
        max_snapshots=2, 4 snapshots -> 50 spawns,  5.67s quiet   <- now

    A 2026-08-15 ``pytest tests/tools -n auto`` sweep (8,572 tests) ranked the
    old 75-spawn shape the SLOWEST TEST IN THE DIRECTORY at 29.81s, against
    6.93s for the same test in a single-file run — 4.3x from spawn contention
    alone.  4 snapshots against a cap of 2 still exercises the whole contract
    (trimming happens, two commits are dropped, newest-first order survives
    the chain rebuild) for a third fewer processes.

    ``_require_affordable_spawns`` above then converts the residual risk from
    "session-killing hang" into "visible skip": it prices one real git spawn
    and skips when the projected cost would eat the budget, rather than
    letting --timeout-method=thread take the whole sweep down with it.
    """

    def test_max_snapshots_trims_history(self, work_dir, checkpoint_base, monkeypatch):
        _require_affordable_spawns(_TRIM_HISTORY_SPAWNS)
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        # Tiny cap to test enforcement.
        m = CheckpointManager(enabled=True, max_snapshots=2)

        for i in range(4):
            (work_dir / "main.py").write_text(f"v{i}\n")
            m.new_turn()
            m.ensure_checkpoint(str(work_dir), f"step-{i}")

        cps = m.list_checkpoints(str(work_dir))
        assert len(cps) == 2          # step-0 and step-1 trimmed away
        reasons = [c["reason"] for c in cps]
        # Newest first — step-3, step-2
        assert reasons[0] == "step-3"
        assert reasons[-1] == "step-2"

    def test_max_file_size_mb_skips_large_files(
        self, tmp_path, checkpoint_base, monkeypatch,
    ):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        wd = tmp_path / "proj"
        wd.mkdir()
        (wd / "small.py").write_text("tiny\n")
        big = wd / "weights.bin"
        big.write_bytes(b"\0" * (2 * 1024 * 1024))  # 2 MB

        m = CheckpointManager(enabled=True, max_snapshots=5, max_file_size_mb=1)
        assert m.ensure_checkpoint(str(wd), "initial") is True

        store = _store_path(checkpoint_base)
        ok, files, _ = _run_git(
            ["ls-tree", "-r", "--name-only", _ref_name(_project_hash(str(wd)))],
            store, str(wd),
        )
        assert ok
        names = set(files.splitlines())
        assert "small.py" in names
        assert "weights.bin" not in names  # filtered by size cap

    def test_steady_state_prune_snapshot_spawn_budget(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """A snapshot that triggers pruning must stay within a fixed git
        spawn budget, with no per-snapshot gc.

        Each spawn costs 0.2-0.4s on Windows under redirected stdio.  The
        pre-fix steady-state snapshot spawned ~20 git processes — 3 per
        kept commit to rebuild the chain, plus ``reflog expire`` and a full
        ``git gc --prune=now`` (1.5-2.2s alone) after EVERY at-capacity
        snapshot.  Object reclamation belongs to the maintenance paths
        (``prune_checkpoints`` daily sweep, ``_enforce_size_cap``), not the
        snapshot hot path.

        The ``<= 13`` assertion below is the one load-INDEPENDENT protection in
        this class, so skipping it on a contended host has a real cost: the gc
        tripwire goes dark for that run (this file has already lost the no-gc
        contract once to a merge — see the 0.17.0 casualty fixed by 4761bc486).
        Guarded anyway, because the alternative is worse: reaching this test's
        38 spawns on a host that cannot afford them lets --timeout-method=thread
        ``os._exit`` the whole process, which discards the results of every
        other test in the sweep, tripwire included.  One dark tripwire beats a
        truncated sweep that still prints a clean-looking summary.
        """
        _require_affordable_spawns(_SPAWN_BUDGET_SPAWNS)
        import tools.checkpoint_manager as cm

        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        m = CheckpointManager(enabled=True, max_snapshots=2)

        # Seed to capacity (no prune yet: count == max_snapshots).
        for i in range(2):
            (work_dir / "main.py").write_text(f"v{i}\n")
            m.new_turn()
            assert m.ensure_checkpoint(str(work_dir), f"seed-{i}") is True

        spawned = []
        # Wrap the helper _run_git actually spawns through.  This MUST track
        # whatever checkpoint_manager imports: when _run_git moved off
        # subprocess.run (2026-08-15, the grandchild-timeout fix), a wrapper
        # left on the old name counted zero spawns and every assertion below
        # passed vacuously — a silent false green on the exact regression this
        # test exists to catch.  The lower bound at the end is what makes that
        # failure mode loud instead of silent.
        real_run = cm.run_text_capture

        def counting_run(cmd, *args, **kwargs):
            if isinstance(cmd, (list, tuple)) and cmd and "git" in str(cmd[0]):
                spawned.append(cmd[1] if len(cmd) > 1 else "?")
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr("tools.checkpoint_manager.run_text_capture", counting_run)

        # This snapshot exceeds the cap and prunes seed-0.
        (work_dir / "main.py").write_text("v-final\n")
        m.new_turn()
        assert m.ensure_checkpoint(str(work_dir), "final") is True

        # Snapshot + prune budget: 8 for the snapshot (rev-parse, read-tree,
        # add, ls-files, diff-index, write-tree, commit-tree, update-ref)
        # + 4 for the prune (log, commit-tree x2, update-ref), +1 slack.
        assert len(spawned) <= 13, spawned
        assert "gc" not in spawned, spawned
        assert "reflog" not in spawned, spawned

        # Vacuity guard: an empty `spawned` satisfies all three assertions
        # above, so a wrapper pointed at a name _run_git no longer calls would
        # read as a pass.  A snapshot+prune cannot cost fewer than the 8 git
        # calls the budget above enumerates for the snapshot alone.
        assert len(spawned) >= 8, (
            f"only {len(spawned)} git spawns observed — the counting wrapper is "
            "not on the call path _run_git actually uses, so the budget "
            "assertions above are vacuous"
        )

        # The trim itself still happened, newest-first.
        monkeypatch.setattr("tools.checkpoint_manager.run_text_capture", real_run)
        cps = m.list_checkpoints(str(work_dir))
        assert [c["reason"] for c in cps] == ["final", "seed-1"]


# =========================================================================
# CheckpointManager — restoring
# =========================================================================

class TestRestore:
    def test_restore_unknown_hash_fails(self, mgr, work_dir):
        assert mgr.restore(str(work_dir), "abc123")["success"] is False  # no checkpoints
        mgr.ensure_checkpoint(str(work_dir), "initial")
        assert mgr.restore(str(work_dir), "deadbeef1234")["success"] is False

    def test_tilde_path_supports_diff_and_restore_flow(
        self, checkpoint_base, fake_home, monkeypatch,
    ):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        m = CheckpointManager(enabled=True, max_snapshots=50)
        project = fake_home / "project"
        project.mkdir()
        file_path = project / "main.py"
        file_path.write_text("original\n")

        tilde = f"~/{project.name}"
        assert m.ensure_checkpoint(tilde, "initial") is True
        m.new_turn()

        file_path.write_text("changed\n")
        cps = m.list_checkpoints(str(project))
        assert len(cps) == 1
        diff_result = m.diff(tilde, cps[0]["hash"])
        assert diff_result["success"] is True
        assert "main.py" in diff_result["diff"]

        restore_result = m.restore(tilde, cps[0]["hash"])
        assert restore_result["success"] is True
        assert file_path.read_text() == "original\n"


class TestSafeRestore:
    """Safe restore: preserve user hand-edits, revert only Hermes-authored changes.

    Inspired by Copilot CLI's /rewind, which "restores only the files Copilot
    changed, skipping any file whose contents no longer match what Copilot
    last wrote".
    """

    def _checkpoint(self, mgr, work_dir):
        assert mgr.ensure_checkpoint(str(work_dir), "initial") is True
        mgr.new_turn()
        cps = mgr.list_checkpoints(str(work_dir))
        assert cps
        return cps[0]["hash"]

    def test_safe_restore_skips_user_edited_file(self, mgr, work_dir):
        base = self._checkpoint(mgr, work_dir)

        # Hermes writes main.py and records it in the ledger.
        (work_dir / "main.py").write_text("agent version\n")
        mgr.record_agent_write(str(work_dir / "main.py"))

        # The user then hand-edits README.md (Hermes never wrote it).
        (work_dir / "README.md").write_text("user hand edit\n")

        result = mgr.restore(str(work_dir), base, safe=True)
        assert result["success"] is True
        # Hermes-authored change reverted...
        assert (work_dir / "main.py").read_text() == "print('hello')\n"
        # ...user's hand edit preserved.
        assert (work_dir / "README.md").read_text() == "user hand edit\n"
        assert "README.md" in result["skipped_user_edits"]
        assert "main.py" in result["restored_files"]

    def test_safe_restore_skips_file_user_edited_after_agent(self, mgr, work_dir):
        base = self._checkpoint(mgr, work_dir)

        # Hermes writes the file, then the user modifies it afterwards.
        (work_dir / "main.py").write_text("agent version\n")
        mgr.record_agent_write(str(work_dir / "main.py"))
        (work_dir / "main.py").write_text("user tweaked the agent's file\n")

        result = mgr.restore(str(work_dir), base, safe=True)
        assert result["success"] is True
        # Content no longer matches what Hermes last wrote → preserved.
        assert (work_dir / "main.py").read_text() == "user tweaked the agent's file\n"
        assert "main.py" in result["skipped_user_edits"]

    def test_safe_restore_restores_agent_deleted_file(self, mgr, work_dir):
        base = self._checkpoint(mgr, work_dir)

        (work_dir / "main.py").write_text("agent version\n")
        mgr.record_agent_write(str(work_dir / "main.py"))
        (work_dir / "main.py").unlink()

        result = mgr.restore(str(work_dir), base, safe=True)
        assert result["success"] is True
        assert (work_dir / "main.py").read_text() == "print('hello')\n"

    def test_safe_restore_falls_back_to_full_when_no_ledger(self, mgr, work_dir):
        """Empty ledger (pre-existing stores) → classic full restore."""
        base = self._checkpoint(mgr, work_dir)
        (work_dir / "main.py").write_text("changed without ledger\n")

        result = mgr.restore(str(work_dir), base, safe=True)
        assert result["success"] is True
        assert (work_dir / "main.py").read_text() == "print('hello')\n"
        # Fallback path: no per-file classification in the result.
        assert "skipped_user_edits" not in result

    def test_safe_restore_removes_agent_created_file_keeps_user_edit(self, mgr, work_dir):
        base = self._checkpoint(mgr, work_dir)

        # Hermes creates a brand-new file after the checkpoint...
        (work_dir / "agent.txt").write_text("agent file\n")
        mgr.record_agent_write(str(work_dir / "agent.txt"))
        # ...and the user hand-edits an existing one.
        (work_dir / "README.md").write_text("user edit\n")

        result = mgr.restore(str(work_dir), base, safe=True)
        assert result["success"] is True
        # User edit preserved; Hermes-created file removed (not in checkpoint).
        assert (work_dir / "README.md").read_text() == "user edit\n"
        assert not (work_dir / "agent.txt").exists()
        assert "README.md" in result["skipped_user_edits"]
        assert "agent.txt" in result["restored_files"]

    # -- size-capped files -------------------------------------------------
    #
    # ``max_file_size_mb`` keeps generated assets out of a checkpoint
    # (test_max_file_size_mb_skips_large_files). Safe restore then sees such a
    # file as "changed since the checkpoint and absent from it" — the same
    # shape as a file Hermes created — and the delete branch treats absence as
    # proof of authorship. For a capped file that is wrong: no checkpoint holds
    # a copy, so deleting it destroys the only one.

    @staticmethod
    def _capped_mgr(checkpoint_base, monkeypatch, cap_mb=1):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        return CheckpointManager(enabled=True, max_snapshots=50, max_file_size_mb=cap_mb)

    def test_safe_restore_keeps_an_oversize_file_the_cap_excluded(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """The file is in no checkpoint, so deleting it is unrecoverable."""
        m = self._capped_mgr(checkpoint_base, monkeypatch)
        corpus = work_dir / "corpus.jsonl"
        corpus.write_bytes(b"original\n" + b"x" * (2 * 1024 * 1024))
        base = self._checkpoint(m, work_dir)

        corpus.write_bytes(b"agent appended\n" + b"y" * (2 * 1024 * 1024))
        m.record_agent_write(str(corpus))

        result = m.restore(str(work_dir), base, safe=True)

        assert result["success"] is True
        assert corpus.exists(), "safe restore deleted a file no checkpoint holds"
        assert corpus.read_bytes().startswith(b"agent appended")
        assert "corpus.jsonl" in result.get("skipped_oversize", [])

    def test_safe_restore_does_not_report_a_kept_file_as_restored(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """Misreporting is what made the loss silent — the user was told
        "Restored" for a path that had just been unlinked."""
        m = self._capped_mgr(checkpoint_base, monkeypatch)
        corpus = work_dir / "corpus.jsonl"
        corpus.write_bytes(b"o" * (2 * 1024 * 1024))
        base = self._checkpoint(m, work_dir)

        corpus.write_bytes(b"a" * (2 * 1024 * 1024))
        m.record_agent_write(str(corpus))
        (work_dir / "main.py").write_text("agent version\n")
        m.record_agent_write(str(work_dir / "main.py"))

        result = m.restore(str(work_dir), base, safe=True)

        assert result["restored_files"] == ["main.py"]
        assert (work_dir / "main.py").read_text() == "print('hello')\n"

    def test_safe_restore_still_reverts_a_file_that_grew_past_the_cap(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """Regression guard for the tempting wrong fix.

        Dropping every oversize path from the restore plan would also strand
        this one — small enough to be checkpointed, then bloated by the agent.
        It IS in the checkpoint, so a prior version exists and reverting to it
        is exactly what the user asked for. The rule has to key on "absent from
        the checkpoint", not on "large now".
        """
        m = self._capped_mgr(checkpoint_base, monkeypatch)
        grew = work_dir / "grew.txt"
        grew.write_text("precious original\n")
        base = self._checkpoint(m, work_dir)

        grew.write_bytes(b"agent bloated it\n" + b"b" * (2 * 1024 * 1024))
        m.record_agent_write(str(grew))

        result = m.restore(str(work_dir), base, safe=True)

        assert result["success"] is True
        assert grew.read_text() == "precious original\n"
        assert "grew.txt" in result["restored_files"]
        assert "grew.txt" not in result.get("skipped_oversize", [])

    def test_the_cap_boundary_is_the_same_on_both_sides_of_the_round_trip(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """One threshold, checked from both ends.

        The checkpoint decides what to store and safe restore decides what may
        be deleted, and the safety of the pair rests on the two agreeing. A file
        at exactly the cap is stored (the test is strictly greater-than), so it
        must revert; one byte more is excluded, so it must be kept. Were the
        checkpoint side to drift to ``>=`` while restore kept ``>``, the at-cap
        file would be stored nowhere and recognised as capped nowhere — the
        exact gap that deletes it — and this fails.
        """
        cap = 1024 * 1024
        m = self._capped_mgr(checkpoint_base, monkeypatch, cap_mb=1)

        at_cap = work_dir / "at_cap.bin"
        over_cap = work_dir / "over_cap.bin"
        at_cap.write_bytes(b"o" * cap)
        over_cap.write_bytes(b"o" * (cap + 1))
        base = self._checkpoint(m, work_dir)

        at_cap.write_bytes(b"a" * cap)
        over_cap.write_bytes(b"a" * (cap + 1))
        m.record_agent_write(str(at_cap))
        m.record_agent_write(str(over_cap))

        result = m.restore(str(work_dir), base, safe=True)

        assert result["success"] is True
        # Stored, therefore recoverable, therefore reverted.
        assert at_cap.read_bytes() == b"o" * cap
        assert "at_cap.bin" in result["restored_files"]
        assert "at_cap.bin" not in result.get("skipped_oversize", [])
        # Never stored, therefore unrecoverable, therefore left alone.
        assert over_cap.read_bytes() == b"a" * (cap + 1)
        assert "over_cap.bin" in result.get("skipped_oversize", [])
        assert "over_cap.bin" not in result["restored_files"]

    def test_safe_restore_still_deletes_a_small_agent_created_file(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """The delete branch keeps working for the case it was written for."""
        m = self._capped_mgr(checkpoint_base, monkeypatch)
        base = self._checkpoint(m, work_dir)

        scratch = work_dir / "scratch.txt"
        scratch.write_text("agent scratch\n")
        m.record_agent_write(str(scratch))

        result = m.restore(str(work_dir), base, safe=True)

        assert not scratch.exists()
        assert "scratch.txt" in result["restored_files"]
        assert result["skipped_oversize"] == []
        assert "failed_deletes" not in result

    def test_safe_restore_does_not_report_a_failed_delete_as_restored(
        self, mgr, work_dir, monkeypatch,
    ):
        """A delete_target whose unlink fails stays on disk — reporting it in
        restored_files is the same silent misreport the oversize fix closed."""
        base = self._checkpoint(mgr, work_dir)

        stubborn = work_dir / "stubborn.txt"
        stubborn.write_text("agent scratch\n")
        mgr.record_agent_write(str(stubborn))

        import pathlib

        real_unlink = pathlib.Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if self.name == "stubborn.txt":
                raise OSError(13, "Permission denied")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "unlink", failing_unlink)
        result = mgr.restore(str(work_dir), base, safe=True)

        assert result["success"] is True
        assert stubborn.exists()
        assert "stubborn.txt" not in result["restored_files"]
        assert result["failed_deletes"] == ["stubborn.txt"]

    def test_unsafe_restore_overwrites_everything(self, mgr, work_dir):
        base = self._checkpoint(mgr, work_dir)
        (work_dir / "main.py").write_text("agent version\n")
        mgr.record_agent_write(str(work_dir / "main.py"))
        (work_dir / "README.md").write_text("user hand edit\n")

        result = mgr.restore(str(work_dir), base, safe=False)
        assert result["success"] is True
        assert (work_dir / "main.py").read_text() == "print('hello')\n"
        assert (work_dir / "README.md").read_text() == "# Project\n"

    def test_record_agent_write_disabled_manager_noop(self, checkpoint_base, work_dir, monkeypatch):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        m = CheckpointManager(enabled=False)
        m.record_agent_write(str(work_dir / "main.py"))  # must not raise
        assert not (checkpoint_base / "store").exists()


# =========================================================================
# CheckpointManager — working dir resolution
# =========================================================================

class TestWorkingDirResolution:
    def test_resolves_project_root_markers(self, tmp_path, fake_home):
        m = CheckpointManager(enabled=True)

        git_proj = tmp_path / "myproject"
        (git_proj / "src").mkdir(parents=True)
        (git_proj / ".git").mkdir()
        (git_proj / "src" / "main.py").write_text("x\n")
        assert m.get_working_dir_for_path(
            str(git_proj / "src" / "main.py")
        ) == str(git_proj)

        # pyproject.toml marker, reached through a ~ path.
        py_proj = fake_home / "pyproj"
        (py_proj / "src").mkdir(parents=True)
        (py_proj / "pyproject.toml").write_text("[project]\n")
        (py_proj / "src" / "file.py").write_text("x\n")
        assert m.get_working_dir_for_path(
            f"~/{py_proj.name}/src/file.py"
        ) == str(py_proj)

    def test_falls_back_to_parent(self, tmp_path, monkeypatch):
        m = CheckpointManager(enabled=True)
        filepath = tmp_path / "random" / "file.py"
        filepath.parent.mkdir(parents=True)
        filepath.write_text("x\n")

        import pathlib as _pl
        _real_exists = _pl.Path.exists

        def _guarded_exists(self):
            s = str(self)
            stop = str(tmp_path)
            # Match markers with the platform separator — with "/" the guard
            # never fires on Windows and ancestor markers (e.g. a Makefile in
            # the home dir) leak through, breaking the fallback assertion.
            if not s.startswith(stop) and any(
                s.endswith(os.sep + m) or s == os.sep + m
                for m in (".git", "pyproject.toml", "package.json",
                          "Cargo.toml", "go.mod", "Makefile", "pom.xml",
                          ".hg", "Gemfile")
            ):
                return False
            return _real_exists(self)

        monkeypatch.setattr(_pl.Path, "exists", _guarded_exists)
        assert m.get_working_dir_for_path(str(filepath)) == str(filepath.parent)


# =========================================================================
# Git env isolation
# =========================================================================

class TestGitEnvIsolation:
    def test_env_pins_store_worktree_and_ignores_ambient_git_state(
        self, fake_home, tmp_path, monkeypatch,
    ):
        store = tmp_path / "store"
        work = tmp_path / "work"

        monkeypatch.setenv("GIT_INDEX_FILE", "/some/index")
        env = _git_env(store, str(work))
        assert env["GIT_DIR"] == str(store)
        assert env["GIT_WORK_TREE"] == str(work.resolve())
        # An ambient index must never leak in.
        assert "GIT_INDEX_FILE" not in env
        # Global/system git config is neutralised (no user hooks, no gpgsign).
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert env["GIT_CONFIG_SYSTEM"] == os.devnull
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"

        index_file = store / "indexes" / "abc"
        env = _git_env(
            store, str(work), index_file=store / "indexes" / "abc",
        )
        # Compare as paths — the separator is platform-dependent.
        assert Path(env["GIT_INDEX_FILE"]) == index_file

        # ~ in the work tree is expanded.
        tilde_work = fake_home / "work"
        tilde_work.mkdir()
        env = _git_env(store, f"~/{tilde_work.name}")
        assert env["GIT_WORK_TREE"] == str(tilde_work.resolve())


# =========================================================================
# Error resilience
# =========================================================================

class TestErrorResilience:
    def test_run_git_allows_expected_nonzero_without_error_log(
        self, tmp_path, caplog,
    ):
        work = tmp_path / "work"
        work.mkdir()
        completed = subprocess.CompletedProcess(
            args=["git", "diff", "--cached", "--quiet"],
            returncode=1, stdout="", stderr="",
        )
        with patch("tools.checkpoint_manager.run_text_capture", return_value=completed):
            with caplog.at_level(logging.ERROR, logger="tools.checkpoint_manager"):
                ok, stdout, stderr = _run_git(
                    ["diff", "--cached", "--quiet"],
                    tmp_path / "store", str(work),
                    allowed_returncodes={1},
                )
        assert ok is False
        assert stdout == ""
        assert not caplog.records


    def test_run_git_missing_git_reports_git_not_found(
        self, tmp_path, monkeypatch, caplog,
    ):
        work = tmp_path / "work"
        work.mkdir()

        def raise_missing_git(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "git")

        monkeypatch.setattr(
            "tools.checkpoint_manager.run_text_capture", raise_missing_git,
        )
        with caplog.at_level(logging.ERROR, logger="tools.checkpoint_manager"):
            ok, _, stderr = _run_git(
                ["status"], tmp_path / "store", str(work),
            )
        assert ok is False
        assert stderr == "git not found"
        assert any(
            "Git executable not found" in r.getMessage() for r in caplog.records
        )

    def test_checkpoint_failure_does_not_raise(self, mgr, work_dir, monkeypatch):
        def broken_run_git(*args, **kwargs):
            raise OSError("git exploded")
        monkeypatch.setattr("tools.checkpoint_manager._run_git", broken_run_git)
        assert mgr.ensure_checkpoint(str(work_dir), "test") is False

        # ...and when git isn't installed at all.
        monkeypatch.setattr("shutil.which", lambda x: None)
        mgr._git_available = None
        assert mgr.ensure_checkpoint(str(work_dir), "test") is False


class TestTouchProjectMalformedMeta:
    """_touch_project must not raise when the project metadata file is corrupted.

    The try/except in _touch_project only catches ``(OSError, ValueError)``.
    When ``json.load`` succeeds but returns a non-dict (e.g. a list ``[]``,
    ``null``, or a scalar), the subsequent ``meta["workdir"] = ...`` raises
    ``TypeError: list indices must be integers…``.  This TypeError propagates
    uncaught out of ``_touch_project`` and up through ``_take`` into
    ``ensure_checkpoint``, where it is swallowed by the broad ``except
    Exception`` safety net — but the effect is that the checkpoint is silently
    skipped for the entire session.

    Fix: add ``if not isinstance(meta, dict): meta = {}`` after parsing,
    mirroring the same guard already present in ``_list_projects``.
    """

    def test_non_dict_meta_does_not_raise(self, tmp_path):
        store = tmp_path / "store"
        workdir = str(tmp_path / "project")
        _init_store(store, workdir)

        dir_hash = _project_hash(workdir)
        meta_path = _project_meta_path(store, dir_hash)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text("[]", encoding="utf-8")

        # Must not raise TypeError
        _touch_project(store, workdir)

        # Metadata file should now be a valid dict with last_touch updated
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "last_touch" in data
        assert "workdir" in data


# =========================================================================
# Security / input validation
# =========================================================================

class TestSecurity:
    def test_restore_rejects_argument_injection(self, mgr, work_dir):
        mgr.ensure_checkpoint(str(work_dir), "initial")
        result = mgr.restore(str(work_dir), "--patch")
        assert result["success"] is False
        assert "Invalid commit hash" in result["error"]
        assert "must not start with '-'" in result["error"]

        result = mgr.restore(str(work_dir), "-p")
        assert result["success"] is False
        assert "Invalid commit hash" in result["error"]

    def test_restore_rejects_invalid_hex_chars(self, mgr, work_dir):
        mgr.ensure_checkpoint(str(work_dir), "initial")
        result = mgr.restore(str(work_dir), "abc; rm -rf /")
        assert result["success"] is False
        assert "expected 4-64 hex characters" in result["error"]

        result = mgr.diff(str(work_dir), "abc&def")
        assert result["success"] is False
        assert "expected 4-64 hex characters" in result["error"]

    def test_restore_file_path_confined_to_working_dir(self, mgr, work_dir):
        mgr.ensure_checkpoint(str(work_dir), "initial")
        cps = mgr.list_checkpoints(str(work_dir))
        target_hash = cps[0]["hash"]

        result = mgr.restore(str(work_dir), target_hash, file_path="/etc/passwd")
        assert result["success"] is False
        assert "got absolute path" in result["error"]

        result = mgr.restore(str(work_dir), target_hash, file_path="../outside_file.txt")
        assert result["success"] is False
        assert "escapes the working directory" in result["error"]

        # Relative paths inside the working dir are accepted, nested included.
        result = mgr.restore(str(work_dir), target_hash, file_path="main.py")
        assert result["success"] is True

        (work_dir / "subdir").mkdir()
        (work_dir / "subdir" / "test.txt").write_text("hello")
        mgr.new_turn()
        mgr.ensure_checkpoint(str(work_dir), "second")
        cps = mgr.list_checkpoints(str(work_dir))
        result = mgr.restore(str(work_dir), cps[0]["hash"], file_path="subdir/test.txt")
        assert result["success"] is True


# =========================================================================
# GPG / global git config isolation
# =========================================================================

class TestGpgIsolation:
    def test_init_disables_commit_and_tag_signing(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        store = _store_path(checkpoint_base)
        _init_store(store, str(work_dir))
        for key in ("commit.gpgsign", "tag.gpgSign"):
            result = subprocess.run(
                ["git", "config", "--file", str(store / "config"), "--get", key],
                capture_output=True, text=True,
            )
            assert result.stdout.strip() == "false", key

    def test_checkpoint_works_with_global_gpgsign_and_broken_gpg(
        self, work_dir, checkpoint_base, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base)
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        (fake_home / ".gitconfig").write_text(
            "[user]\n    email = real@user.com\n    name = Real User\n"
            "[commit]\n    gpgsign = true\n"
            "[tag]\n    gpgSign = true\n"
            "[gpg]\n    program = /nonexistent/fake-gpg-binary\n"
        )
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.delenv("GPG_TTY", raising=False)
        monkeypatch.delenv("DISPLAY", raising=False)

        m = CheckpointManager(enabled=True)
        assert m.ensure_checkpoint(str(work_dir), reason="with-global-gpgsign") is True
        assert len(m.list_checkpoints(str(work_dir))) == 1


# =========================================================================
# prune_checkpoints + maybe_auto_prune_checkpoints
# =========================================================================

def _seed_legacy_repo(base: Path, name: str, workdir: Path, mtime: float = None) -> Path:
    """Create a minimal pre-v2 shadow repo directly under base."""
    shadow = base / name
    shadow.mkdir(parents=True)
    (shadow / "HEAD").write_text("ref: refs/heads/main\n")
    (shadow / "HERMES_WORKDIR").write_text(str(workdir) + "\n")
    (shadow / "info").mkdir()
    (shadow / "info" / "exclude").write_text("node_modules/\n")
    if mtime is not None:
        for p in shadow.rglob("*"):
            os.utime(p, (mtime, mtime))
        os.utime(shadow, (mtime, mtime))
    return shadow


class TestPruneCheckpointsLegacy:
    """Backwards-compat: prune still handles pre-v2 per-project shadow repos."""

    def test_deletes_orphan_when_workdir_missing(self, tmp_path):
        base = tmp_path / "checkpoints"
        alive_work = tmp_path / "alive"
        alive_work.mkdir()
        alive_repo = _seed_legacy_repo(base, "aaaa" * 4, alive_work)
        orphan_repo = _seed_legacy_repo(base, "bbbb" * 4, tmp_path / "was-deleted")

        result = prune_checkpoints(retention_days=0, checkpoint_base=base)

        assert result["scanned"] == 2
        assert result["deleted_orphan"] == 1
        assert result["deleted_stale"] == 0
        assert alive_repo.exists()
        assert not orphan_repo.exists()


    def test_noop_cases_delete_nothing(self, tmp_path):
        # Missing base.
        result = prune_checkpoints(checkpoint_base=tmp_path / "does-not-exist")
        assert result["scanned"] == 0
        assert result["deleted_orphan"] == 0

        base = tmp_path / "checkpoints"
        orphan = _seed_legacy_repo(base, "ffff" * 4, tmp_path / "gone")
        (base / "garbage-dir").mkdir()
        (base / "garbage-dir" / "random.txt").write_text("hi")

        # delete_orphans=False keeps orphans; non-shadow dirs aren't even scanned.
        result = prune_checkpoints(
            retention_days=0, delete_orphans=False, checkpoint_base=base,
        )
        assert result["scanned"] == 1
        assert result["deleted_orphan"] == 0
        assert orphan.exists()
        assert (base / "garbage-dir").exists()


class TestPruneCheckpointsV2:
    """v2 pruning walks the shared store's projects/ metadata."""

    def test_deletes_orphan_project_entry(self, tmp_path, monkeypatch):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)

        alive = tmp_path / "alive"
        alive.mkdir()
        (alive / "f").write_text("a")
        gone = tmp_path / "was-gone"
        gone.mkdir()
        (gone / "g").write_text("b")

        m = CheckpointManager(enabled=True)
        assert m.ensure_checkpoint(str(alive), "alive") is True
        m.new_turn()
        assert m.ensure_checkpoint(str(gone), "gone") is True

        # Simulate deletion of "gone"
        shutil.rmtree(gone)

        result = prune_checkpoints(retention_days=0, checkpoint_base=base)

        assert result["deleted_orphan"] >= 1
        # Alive project survives
        alive_hash = _project_hash(str(alive))
        assert (base / "store" / "projects" / f"{alive_hash}.json").exists()
        # Gone project metadata wiped
        gone_hash = _project_hash(str(gone))
        assert not (base / "store" / "projects" / f"{gone_hash}.json").exists()

    def test_retention_prunes_stale_projects_and_legacy_archives(
        self, tmp_path, monkeypatch,
    ):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)

        fresh = tmp_path / "fresh"
        fresh.mkdir()
        (fresh / "f").write_text("f")
        stale = tmp_path / "stale"
        stale.mkdir()
        (stale / "s").write_text("s")

        m = CheckpointManager(enabled=True)
        m.ensure_checkpoint(str(fresh), "fresh")
        m.new_turn()
        m.ensure_checkpoint(str(stale), "stale")

        # Backdate stale's last_touch to 60 days ago
        stale_hash = _project_hash(str(stale))
        meta_path = base / "store" / "projects" / f"{stale_hash}.json"
        meta = json.loads(meta_path.read_text())
        meta["last_touch"] = time.time() - 60 * 86400
        meta_path.write_text(json.dumps(meta))

        # A legacy-<ts>/ archive older than retention is wiped too.
        old_legacy = base / "legacy-20200101-000000"
        old_legacy.mkdir()
        (old_legacy / "junk").write_bytes(b"x" * 1000)
        old = time.time() - 60 * 86400
        for p in old_legacy.rglob("*"):
            os.utime(p, (old, old))
        os.utime(old_legacy, (old, old))

        result = prune_checkpoints(
            retention_days=30, delete_orphans=False, checkpoint_base=base,
        )

        assert result["deleted_stale"] >= 2
        fresh_hash = _project_hash(str(fresh))
        assert (base / "store" / "projects" / f"{fresh_hash}.json").exists()
        assert not meta_path.exists()
        assert not old_legacy.exists()


class TestPruneCheckpointsOrphanAllowlist:
    """P1 fix on PR #69141: the confirmation preview must bind to exactly
    what gets deleted. A project that only becomes orphaned *after* the
    preview was built (e.g. its workdir vanishes while a human is answering
    the y/N prompt) must survive a rescan-based prune unless its identity
    was in the previewed/approved set.
    """

    def test_v2_allowlist_restricts_deletion_to_approved_hash(self, tmp_path, monkeypatch):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)

        previewed = tmp_path / "previewed-gone"
        previewed.mkdir()
        (previewed / "f").write_text("a")
        newly_gone = tmp_path / "newly-gone"
        newly_gone.mkdir()
        (newly_gone / "f").write_text("b")

        m = CheckpointManager(enabled=True)
        assert m.ensure_checkpoint(str(previewed), "previewed") is True
        m.new_turn()
        assert m.ensure_checkpoint(str(newly_gone), "newly-gone") is True

        shutil.rmtree(previewed)
        shutil.rmtree(newly_gone)

        previewed_hash = _project_hash(str(previewed))
        newly_gone_hash = _project_hash(str(newly_gone))

        result = prune_checkpoints(
            retention_days=0, checkpoint_base=base,
            orphan_allowlist={previewed_hash},
        )

        assert result["deleted_orphan"] == 1
        assert not (base / "store" / "projects" / f"{previewed_hash}.json").exists()
        # Not in the allowlist -> survives this prune even though it is orphaned.
        assert (base / "store" / "projects" / f"{newly_gone_hash}.json").exists()

    def test_pre_v2_allowlist_restricts_deletion_to_approved_path(self, tmp_path):
        base = tmp_path / "checkpoints"
        previewed_repo = _seed_legacy_repo(base, "aaaa" * 4, tmp_path / "previewed-gone")
        newly_gone_repo = _seed_legacy_repo(base, "bbbb" * 4, tmp_path / "newly-gone")

        result = prune_checkpoints(
            retention_days=0, checkpoint_base=base,
            orphan_allowlist={str(previewed_repo)},
        )

        assert result["deleted_orphan"] == 1
        assert not previewed_repo.exists()
        assert newly_gone_repo.exists()

    def test_end_to_end_timing_change_during_confirmation_prompt(self, tmp_path, monkeypatch):
        """Reproduces the exact PR #69141 review scenario end-to-end through
        `hermes checkpoints prune`: the preview shows one pre-v2 orphan; a
        second project's workdir is removed by the input() callback while
        the human is "answering" the prompt. Only the previewed orphan may
        be deleted.
        """
        import hermes_cli.checkpoints as checkpoints_cli

        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)

        previewed_work = tmp_path / "was-deleted-before-preview"
        still_alive_work = tmp_path / "still-alive-during-preview"
        still_alive_work.mkdir()
        _seed_legacy_repo(base, "eeee" * 4, previewed_work)
        second_repo = _seed_legacy_repo(base, "ffff" * 4, still_alive_work)

        def _confirm_and_go_stale(_prompt):
            # Simulate the workdir disappearing after the preview was shown
            # but before the human's answer is processed.
            shutil.rmtree(still_alive_work)
            return "y"

        monkeypatch.setattr("builtins.input", _confirm_and_go_stale)

        args = argparse.Namespace(
            retention_days=0, max_size_mb=0, keep_orphans=False, force=False,
        )
        rc = checkpoints_cli.cmd_prune(args)

        assert rc == 0
        # The orphan shown in the preview is gone.
        assert not (base / ("eeee" * 4)).exists()
        # The one that only went orphan mid-confirmation must survive.
        assert second_repo.exists()


class TestMaybeAutoPruneCheckpoints:
    def test_prunes_once_then_skips_within_interval(self, tmp_path):
        base = tmp_path / "checkpoints"
        base.mkdir()
        # A corrupt marker is treated as "no prior run".
        (base / ".last_prune").write_text("not-a-timestamp")
        _seed_legacy_repo(base, "0000" * 4, tmp_path / "gone")

        out = maybe_auto_prune_checkpoints(
            checkpoint_base=base, min_interval_hours=24,
        )
        assert out["skipped"] is False
        assert out["result"]["deleted_orphan"] == 1
        assert (base / ".last_prune").exists()

        _seed_legacy_repo(base, "2222" * 4, tmp_path / "also-gone")
        second = maybe_auto_prune_checkpoints(
            checkpoint_base=base, min_interval_hours=24,
        )
        assert second["skipped"] is True
        assert (base / ("2222" * 4)).exists()


# =========================================================================
# store_status / clear_all / clear_legacy
# =========================================================================

class TestStoreStatus:
    def test_reports_projects_and_legacy(self, tmp_path, monkeypatch, work_dir):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)

        m = CheckpointManager(enabled=True)
        m.ensure_checkpoint(str(work_dir), "initial")

        # Add a legacy archive dir manually
        legacy = base / "legacy-20200101-000000"
        legacy.mkdir()
        (legacy / "junk").write_bytes(b"x" * 100)

        info = store_status()
        assert info["project_count"] == 1
        assert info["projects"][0]["workdir"] == str(work_dir.resolve())
        assert info["projects"][0]["commits"] >= 1
        assert info["projects"][0]["exists"] is True
        assert len(info["legacy_archives"]) == 1
        assert info["legacy_archives"][0]["size_bytes"] >= 100


class TestClearFunctions:
    def test_clear_all_wipes_base_then_is_a_noop(self, tmp_path, monkeypatch, work_dir):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)
        m = CheckpointManager(enabled=True)
        m.ensure_checkpoint(str(work_dir), "initial")
        assert base.exists()

        result = clear_all()
        assert result["deleted"] is True
        assert result["bytes_freed"] > 0
        assert not base.exists()

        # Second call on a now-missing base is a no-op, not an error.
        result = clear_all()
        assert result["deleted"] is False
        assert result["bytes_freed"] == 0

    def test_clear_legacy_only_removes_legacy_dirs(
        self, tmp_path, monkeypatch, work_dir,
    ):
        base = tmp_path / "checkpoints"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)
        m = CheckpointManager(enabled=True)
        m.ensure_checkpoint(str(work_dir), "initial")

        legacy = base / "legacy-20200101-000000"
        legacy.mkdir()
        (legacy / "junk").write_bytes(b"x" * 1000)
        # Archived shadow repos contain read-only git object files; on
        # Windows a plain rmtree dies on those — deletion must still work.
        ro = legacy / "read-only-object"
        ro.write_bytes(b"y" * 10)
        os.chmod(ro, stat.S_IREAD)

        result = clear_legacy()
        assert result["deleted"] == 1
        assert result["bytes_freed"] >= 1000
        assert not legacy.exists()
        # Store preserved
        assert (base / "store" / "HEAD").exists()

    def test_clear_all_on_missing_base_is_noop(self, tmp_path, monkeypatch):
        base = tmp_path / "does-not-exist"
        monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", base)
        result = clear_all()
        assert result["deleted"] is False
        assert result["bytes_freed"] == 0


# =========================================================================
# CHECKPOINT_BASE resolved at call time (hermetic-test poisoning guard)
# =========================================================================

@pytest.mark.timeout(60)
class TestCheckpointBaseHermeticResolution:
    """CHECKPOINT_BASE must resolve get_hermes_home() at CALL time, not import.

    Regression (2026-06-11): CHECKPOINT_BASE was a module-level constant
    evaluated at import (collection) time, which baked in the REAL ~/.hermes
    *before* the hermetic ``_hermetic_environment`` fixture redirects
    HERMES_HOME to a per-test tempdir.  Any test that reaches a checkpoint
    write path WITHOUT patching CHECKPOINT_BASE — e.g. via the agent
    tool-executor hot path (``ensure_checkpoint``) or the ``hermes
    checkpoints`` CLI, both of which use the module default — created (and
    pruned/cleared) the user's live ~/.hermes/checkpoints store.

    Mirrors the tools/process_registry CHECKPOINT_PATH -> _checkpoint_path()
    None-sentinel seam fix.  These tests DELIBERATELY do not patch
    CHECKPOINT_BASE, so they exercise the production default-resolution path.
    """

    def test_ensure_checkpoint_writes_under_per_test_hermes_home(self, work_dir):
        from hermes_constants import get_hermes_home

        # No monkeypatch of CHECKPOINT_BASE — same code path production hits.
        m = CheckpointManager(enabled=True, max_snapshots=5)
        assert m.ensure_checkpoint(str(work_dir), "hermetic-check") is True

        store_head = get_hermes_home() / "checkpoints" / "store" / "HEAD"
        assert store_head.exists(), (
            "checkpoint store resolved at import time (real ~/.hermes), not "
            "at call time (per-test HERMES_HOME) — CHECKPOINT_BASE must defer "
            "get_hermes_home() to call time"
        )

    def test_store_path_default_resolves_to_per_test_hermes_home(self):
        """Pure path resolution (no disk I/O) — the seam in isolation."""
        from hermes_constants import get_hermes_home

        assert _store_path().parent == get_hermes_home() / "checkpoints"


# =========================================================================
# Git subprocess timeouts are a real bound (grandchild-hang fix)
# =========================================================================

class TestGitTimeoutIsBounded:
    """``_GIT_TIMEOUT`` must be an actual bound, not a nominal kwarg.

    ``subprocess.run(..., capture_output=True, timeout=N)`` does NOT bound a
    command that leaves a grandchild alive on Windows.  CPython's timeout path
    kills only the direct child and then calls ``communicate()`` a second time
    with NO timeout; that call blocks until every handle on the capture pipe is
    closed, including the ones a surviving grandchild inherited.  Measured on
    this host 2026-08-15: ``subprocess.run(["cmd","/c","start /b ping -n 25
    127.0.0.1"], capture_output=True, timeout=2)`` returned after 24.3s.

    ``git gc --prune=now`` is the checkpoint store's grandchild-spawner (probed
    with psutil the same day: ``add -A``, ``write-tree`` and ``reflog expire``
    spawn no descendants, ``gc`` spawns a ``git.exe`` child), and it runs on
    ``_take`` -> ``_enforce_size_cap`` and from the daily auto-prune hook.  So
    every git call here goes through ``run_text_capture``, which captures into
    temp files instead of pipes and tree-kills on timeout.
    """

    def test_run_git_delegates_to_the_bounded_capture_helper(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """_run_git must route through run_text_capture, passing its timeout."""
        seen = {}

        def _fake(argv, **kwargs):
            seen["argv"] = list(argv)
            seen["kwargs"] = kwargs
            return subprocess.CompletedProcess(list(argv), 0, "out", "")

        monkeypatch.setattr("tools.checkpoint_manager.run_text_capture", _fake)
        ok, stdout, stderr = _run_git(
            ["rev-parse", "HEAD"], checkpoint_base / "store", str(work_dir),
            timeout=17,
        )

        assert (ok, stdout, stderr) == (True, "out", "")
        assert seen["argv"] == ["git", "rev-parse", "HEAD"]
        assert seen["kwargs"]["timeout"] == 17, (
            "the caller's timeout must reach the bounded helper unchanged"
        )
        assert seen["kwargs"]["cwd"] == str(_normalize_path(str(work_dir)))
        assert "GIT_DIR" in seen["kwargs"]["env"]

    def test_run_git_reports_timeout_instead_of_raising(
        self, work_dir, checkpoint_base, monkeypatch,
    ):
        """A bounded timeout still surfaces as the (False, "", msg) contract."""
        def _fake(argv, **kwargs):
            raise subprocess.TimeoutExpired(list(argv), kwargs["timeout"])

        monkeypatch.setattr("tools.checkpoint_manager.run_text_capture", _fake)
        ok, stdout, stderr = _run_git(
            ["gc", "--prune=now", "--quiet"], checkpoint_base / "store",
            str(work_dir), timeout=5,
        )

        assert ok is False
        assert stdout == ""
        assert "timed out after 5s" in stderr

    def test_module_makes_no_bare_subprocess_run_calls(self):
        """AST guard: no call site may reintroduce the unbounded stdlib path.

        ``subprocess.run(timeout=...)`` reads as bounded and is not, so a
        presence-of-timeout lint (tests/hermes_cli/test_subprocess_timeouts.py)
        would not catch a regression here.  Ban the call outright instead.
        """
        import ast

        from tools import checkpoint_manager

        source = Path(checkpoint_manager.__file__).read_text(encoding="utf-8")
        offenders = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ]
        assert not offenders, (
            "checkpoint_manager must spawn git via run_text_capture (file-backed "
            f"capture + tree-kill); bare subprocess.run at line(s) {offenders} "
            "does not bound a git command that spawns a grandchild on Windows"
        )

# =========================================================================
# Orphan pruning must not act on an unreachable volume
# =========================================================================

class TestOrphanPruneRequiresObservableDeletion:
    """A missing workdir is ambiguous: deleted, or just not mounted right now.

    Orphan pruning deletes a project's whole checkpoint history and runs
    unattended at startup (``maybe_auto_prune_checkpoints`` from the CLI and
    the gateway), so it must only fire when the deletion is something we
    actually observed — the parent directory present, the project gone. An
    unplugged drive, a share behind a downed VPN, or a bind-mount absent from
    this container must not cost the user their restore points.
    """

    def _project_with_history(self, work_dir, checkpoint_base, monkeypatch):
        monkeypatch.setattr(
            "tools.checkpoint_manager.CHECKPOINT_BASE", checkpoint_base
        )
        m = CheckpointManager(enabled=True, max_snapshots=10)
        m.ensure_checkpoint(str(work_dir), "initial")
        return m

    def _history_survives(self, checkpoint_base, work_dir):
        store = _store_path(checkpoint_base)
        return _project_meta_path(
            store, _project_hash(str(work_dir))
        ).exists()

    def test_absent_workdir_without_deletion_evidence_keeps_history(
        self, tmp_path, checkpoint_base, monkeypatch,
    ):
        """Two unmount shapes, both ambiguous → both keep their history.

        1. The whole mount disappears (parent missing too).
        2. The mount point outlives the volume as an empty dir — the classic
           static layout (fstab entry, container bind-mount) does not remove
           the mount point on unmount, and an empty parent looks exactly the
           same whether the volume was detached or the project deleted.
        """
        vanished_mount = tmp_path / "mnt-a"
        vanished = vanished_mount / "work" / "proj"
        vanished.mkdir(parents=True)
        (vanished / "main.py").write_text("print('x')\n")
        self._project_with_history(vanished, checkpoint_base, monkeypatch)

        mount_point = tmp_path / "mnt-b" / "volume"
        unmounted = mount_point / "proj"
        unmounted.mkdir(parents=True)
        (unmounted / "main.py").write_text("print('y')\n")
        self._project_with_history(unmounted, checkpoint_base, monkeypatch)

        shutil.rmtree(vanished_mount)
        shutil.rmtree(unmounted)
        assert not vanished.exists()
        assert mount_point.is_dir() and not any(mount_point.iterdir())

        prune_checkpoints(
            retention_days=0, delete_orphans=True, checkpoint_base=checkpoint_base,
        )

        assert self._history_survives(checkpoint_base, vanished), (
            "checkpoint history was deleted for a project whose volume was "
            "merely unmounted"
        )
        assert self._history_survives(checkpoint_base, unmounted), (
            "checkpoint history was deleted for a project whose mount point "
            "merely survived the unmount as an empty directory"
        )


    def test_populated_underlay_mountpoint_keeps_its_checkpoints(
        self, tmp_path, checkpoint_base, monkeypatch,
    ):
        """A detached volume exposing a populated underlay dir → keep history.

        An entry in the parent does not prove the project volume is attached.
        Unmounting swaps which directory is visible at the mount point's
        path: the mounted filesystem's root gives way to the *underlying*
        directory, whose own files (a ``.keep`` placeholder, sibling mount
        points) become visible. Those entries were never next to the project,
        so they must not corroborate an orphan classification — yet a naive
        "parent has any entry" guard treats them as proof of deletion.

        Simulate the detach faithfully: the directory visible at
        ``mnt/volume`` after the unmount is a *different* directory (new
        inode — the underlay) carrying a ``.keep`` placeholder.
        """
        mount_point = tmp_path / "mnt" / "volume"
        work_dir = mount_point / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "main.py").write_text("print('x')\n")
        self._project_with_history(work_dir, checkpoint_base, monkeypatch)

        # Detach: the directory that was mounted at the path (with the
        # project on it) stops being visible there; the underlay directory —
        # same path, different directory, its own contents — shows through,
        # exposing a placeholder. Renaming (rather than deleting) the mounted
        # directory keeps its inode alive, so the underlay directory is
        # guaranteed a distinct identity, exactly as in a real unmount.
        mount_point.rename(tmp_path / "detached-volume")
        mount_point.mkdir()
        (mount_point / ".keep").write_text("")
        assert not work_dir.exists()
        assert any(mount_point.iterdir())

        result = prune_checkpoints(
            retention_days=0, delete_orphans=True, checkpoint_base=checkpoint_base,
        )

        assert result["deleted_orphan"] == 0
        assert self._history_survives(checkpoint_base, work_dir), (
            "checkpoint history was deleted because underlay entries exposed "
            "by an unmount were mistaken for attachment evidence"
        )

    def test_recorded_parent_identity_survives_probe_failure_on_touch(
        self, tmp_path, checkpoint_base, monkeypatch,
    ):
        """A later failed evidence probe must not erase recorded identity."""
        from tools.checkpoint_manager import _register_project

        parent = tmp_path / "projects"
        work_dir = parent / "proj"
        work_dir.mkdir(parents=True)
        (work_dir / "main.py").write_text("print('x')\n")
        self._project_with_history(work_dir, checkpoint_base, monkeypatch)

        store = _store_path(checkpoint_base)
        meta_path = _project_meta_path(store, _project_hash(str(work_dir)))
        before = json.loads(meta_path.read_text())
        assert "workdir_parent_dev" in before
        assert "workdir_parent_ino" in before

        # Re-register while the evidence probe fails (e.g. transient I/O
        # error): the previously recorded identity must be preserved.
        monkeypatch.setattr(
            "tools.checkpoint_manager._volume_evidence", lambda _wd: {},
        )
        _register_project(store, str(work_dir))

        after = json.loads(meta_path.read_text())
        assert after["workdir_parent_dev"] == before["workdir_parent_dev"]
        assert after["workdir_parent_ino"] == before["workdir_parent_ino"]


# =========================================================================
# session_diff — cumulative "what changed" view that powers /diff session
# =========================================================================

class TestSessionDiff:
    def test_empty_when_nothing_changed(self, mgr, work_dir):
        """No checkpoints, and a checkpoint with no later edits, both report empty."""
        result = mgr.session_diff(str(work_dir))
        assert result["success"] is True
        assert result.get("empty") is True
        assert result["diff"] == ""

        mgr.ensure_checkpoint(str(work_dir), "baseline")
        result = mgr.session_diff(str(work_dir))
        assert result["success"] is True
        assert result.get("empty") is True
        assert result["diff"] == ""


    def test_includes_newly_added_files(self, mgr, work_dir):
        mgr.ensure_checkpoint(str(work_dir), "baseline")
        (work_dir / "feature.py").write_text("x = 1\n")

        result = mgr.session_diff(str(work_dir))
        assert result["success"] is True
        assert "feature.py" in result["diff"]
        assert "+x = 1" in result["diff"]
