"""Executor boundary: final revalidation, failure recording, survivor proof.

All fakes, all negative pids. The terminate function is injected; nothing in
this file can reach a real process.
"""

from claude_fleet_control.executor import WindowsTreeExecutor
from claude_fleet_control.models import TargetSummary
from tests.claude_fleet_control.conftest import NOW, cli_rec, rec


def _target(root, members):
    return TargetSummary(
        root_identity=root.identity, root_pid=root.pid,
        root_create_time=root.create_time,
        member_identities=tuple(sorted(m.identity for m in members)),
        member_count=len(members), total_rss=sum(m.rss for m in members),
        transcript_path="t.jsonl", transcript_mtime=NOW - 3600.0,
        idle_minutes=60.0, strike_key="k", strikes=2,
    )


def _executor(live_ref, kills, fail=None):
    def terminate(pid, *, force, expected_start_time, reason):
        assert force is True and reason.startswith("claude_fleet:")
        assert expected_start_time is not None
        if fail is not None:
            raise fail
        kills.append(pid)
        live_ref["records"] = [r for r in live_ref["records"] if r.pid > 0]  # tree gone

    return WindowsTreeExecutor(
        terminate_fn=terminate,
        snapshot_fn=lambda: list(live_ref["records"]),
        sleep_fn=lambda _s: None,
    )


def test_root_identity_mismatch_cancels_without_killing():
    root = cli_rec(-200)
    child = rec(-201, ppid=-200)
    recycled_root = cli_rec(-200, create_time=NOW - 5.0)  # same pid, new life
    kills = []
    executor = _executor({"records": [recycled_root, child]}, kills)
    report = executor.hard_terminate_tree(_target(root, (root, child)), plan_id="p")
    assert report.cancelled and not report.ok and kills == []


def test_recycled_member_pid_cancels_without_killing():
    root = cli_rec(-210)
    child = rec(-211, ppid=-210)
    recycled_child = rec(-211, ppid=-210, create_time=NOW - 3.0)
    kills = []
    executor = _executor({"records": [root, recycled_child]}, kills)
    report = executor.hard_terminate_tree(_target(root, (root, child)), plan_id="p")
    assert report.cancelled and kills == []


def test_terminate_failure_is_recorded_with_survivors():
    root = cli_rec(-220)
    child = rec(-221, ppid=-220)
    executor = _executor(
        {"records": [root, child]}, [], fail=OSError("taskkill said no")
    )
    report = executor.hard_terminate_tree(_target(root, (root, child)), plan_id="p")
    assert not report.ok and not report.cancelled
    assert "terminate failed" in report.detail
    assert set(report.surviving_identities) == {root.identity, child.identity}


def test_successful_kill_proves_exit_of_every_member():
    root = cli_rec(-230)
    child = rec(-231, ppid=-230)
    kills = []
    executor = _executor({"records": [root, child]}, kills)
    report = executor.hard_terminate_tree(_target(root, (root, child)), plan_id="p")
    assert report.ok and kills == [-230]  # one taskkill /T call, root only
    assert set(report.exited_identities) == {root.identity, child.identity}
    assert report.surviving_identities == ()


def test_survivor_is_reported_not_retried():
    root = cli_rec(-240)
    stubborn = rec(-241, ppid=-240)
    live = {"records": [root, stubborn]}

    def terminate(pid, *, force, expected_start_time, reason):
        live["records"] = [stubborn]  # root died, child survived

    executor = WindowsTreeExecutor(
        terminate_fn=terminate,
        snapshot_fn=lambda: list(live["records"]),
        sleep_fn=lambda _s: None,
    )
    report = executor.hard_terminate_tree(_target(root, (root, stubborn)), plan_id="p")
    assert not report.ok and not report.cancelled
    assert report.surviving_identities == (stubborn.identity,)
    assert report.exited_identities == (root.identity,)


def test_terminate_receives_the_planned_root_start_time_fingerprint():
    """2026-09-15: every enforce pass since 08-31 ended in ``terminate failed:
    refusing to force-kill PID <n> without a process start-time guard`` --
    the Windows guard in gateway.status.terminate_pid REQUIRES
    ``expected_start_time`` on a force kill and the executor never passed it.
    The planned root's create_time is the fingerprint the guard wants."""
    from claude_fleet_control.executor import start_time_fingerprint

    root = cli_rec(-250)
    child = rec(-251, ppid=-250)
    seen = []
    live = {"records": [root, child]}

    def terminate(pid, *, force, expected_start_time, reason):
        seen.append((pid, force, expected_start_time, reason))
        live["records"] = []

    executor = WindowsTreeExecutor(
        terminate_fn=terminate, snapshot_fn=lambda: list(live["records"]),
        sleep_fn=lambda _s: None,
    )
    report = executor.hard_terminate_tree(_target(root, (root, child)), plan_id="p9")
    assert report.ok
    assert seen == [(-250, True, start_time_fingerprint(root.create_time), "claude_fleet:p9")]
    assert isinstance(seen[0][2], int)


def test_fingerprint_units_agree_with_the_live_windows_guard(monkeypatch):
    """The executor's fingerprint must be the SAME unit terminate_pid derives
    from psutil (centiseconds), or the guard refuses with "process identity
    changed" instead -- a second way to never kill anything. Drive the real
    terminate_pid with a fake psutil reading and a fake taskkill."""
    import gateway.status as status
    from claude_fleet_control.executor import start_time_fingerprint

    create_time = 1789487080.37  # what psutil.Process(pid).create_time() returns
    monkeypatch.setattr(status, "_IS_WINDOWS", True)
    monkeypatch.setattr(status, "_get_process_start_time",
                        lambda pid: int(round(create_time * 100)))
    monkeypatch.setattr(status, "write_diag", lambda *a, **k: None)
    calls = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(status.subprocess, "run",
                        lambda *args, **kwargs: (calls.append(args[0]), _Done())[1])
    monkeypatch.setattr(status, "_wait_for_pid_death", lambda pid, timeout: True)

    status.terminate_pid(
        -260, force=True, expected_start_time=start_time_fingerprint(create_time),
        reason="claude_fleet:p10",
    )
    assert calls == [["taskkill", "/PID", "-260", "/T", "/F"]]
