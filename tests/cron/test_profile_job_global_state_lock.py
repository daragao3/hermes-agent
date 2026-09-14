"""A cron job that switches Hermes PROFILE must hold the writer lock.

``_job_profile_context`` mutates process-global state for the whole of a
profile job's run: it sets the module-global ``_hermes_home``, installs a
Hermes-home override, and snapshots/restores ``os.environ``. While it is
active, ``_get_hermes_home()`` returns that profile's home for EVERY thread in
the process, so a concurrently-running job resolves its ``script:`` slot under
the wrong profile and dies "Script not found".

That is not hypothetical. On 2026-08-19/20 a scan of 577 cron run outputs found
8 such failures across 6 different jobs -- applier_ready_sweep,
jaum_inbox_sweep_gate, devflow_pr_build_poll, tracker_operator_drain,
phantom_root_watch, devflow_observability -- and every one resolved under
``profiles/financier`` while a financier-profile job was running
(financier-snapshot-am 0 6, financier-digest-am 5 7, financier-digest-pm 20 16).
The applier's sweep collected nothing and still reported ``last_status: ok``.

The dispatch partition in ``tick()`` already treats profile jobs as sequential
(``workdir or profile``), but the sequential pool only stops sequential jobs
overlapping EACH OTHER. What excludes the parallel-pool readers is the
readers-writer lock -- and its writer test keyed on ``workdir`` ALONE, so a
profile job took the lock as a READER and ran alongside them. The two
classifications have to agree, which is why the rule now lives in one predicate.
"""

import threading


def test_predicate_covers_profile_not_just_workdir():
    """The single source of truth for "this job mutates process globals"."""
    import cron.scheduler as sched

    mutates = sched._job_mutates_process_globals

    # A profile job mutates _hermes_home + os.environ. This is the regression:
    # it was previously invisible to the lock.
    assert mutates({"profile": "financier"}) is True
    # A workdir job mutates TERMINAL_CWD -- the original reason for the lock.
    assert mutates({"workdir": "/project/a"}) is True
    assert mutates({"profile": "financier", "workdir": "/project/a"}) is True

    # Neither -> a pure reader, free to run on the parallel pool.
    assert mutates({}) is False
    assert mutates({"profile": None, "workdir": None}) is False
    # Blank and whitespace-only values are "unset", matching the partition in
    # tick() which strips before testing. A job carrying profile="" must stay
    # parallel or every job on the box would serialize.
    assert mutates({"profile": "", "workdir": ""}) is False
    assert mutates({"profile": "   ", "workdir": "  "}) is False


def test_partition_and_lock_agree_on_every_shape():
    """tick()'s sequential/parallel split and the lock must never disagree.

    They were written separately and drifted: the partition tested
    ``workdir or profile`` while the lock tested ``workdir``. A job in the
    disagreement window (profile, no workdir) is dispatched sequentially --
    which looks safe -- while taking the lock as a reader, which is what let it
    run alongside the parallel pool.
    """
    import cron.scheduler as sched

    shapes = [
        {},
        {"workdir": "/w"},
        {"profile": "financier"},
        {"profile": "financier", "workdir": "/w"},
        {"profile": "", "workdir": ""},
    ]
    for job in shapes:
        partition_says_sequential = bool(
            (job.get("workdir") or "").strip() or (job.get("profile") or "").strip()
        )
        assert sched._job_mutates_process_globals(job) is partition_says_sequential, job


def test_profile_context_does_not_leak_home_to_other_threads(tmp_path):
    """THE REGRESSION. A profile job's home must not follow other threads.

    ``set_hermes_home_override`` is a ContextVar -- explicitly context-local,
    and correct on its own. ``_job_profile_context`` ALSO assigned the
    module-global ``cron.scheduler._hermes_home``, and ``_get_hermes_home()``
    reads that global FIRST::

        return _hermes_home or get_hermes_home()

    so the global defeated the ContextVar for every other thread in the
    process. That is what made a concurrently-firing job resolve
    ``HERMES_HOME/scripts/<name>`` under profiles/financier.

    The lock cannot cover this: the ``script:`` slot runs at
    ``_run_job_impl``'s pre-run step, BEFORE the readers-writer lock is
    acquired for the agent portion. Only removing the global write fixes it.
    """
    import threading
    import cron.scheduler as sched

    profile_home = tmp_path / "profiles" / "financier"
    (profile_home / "scripts").mkdir(parents=True)

    inside_profile: dict = {}
    other_thread: dict = {}
    in_context = threading.Event()
    may_exit = threading.Event()

    def _observer():
        # Runs on its OWN thread, with no ContextVar override of its own --
        # exactly a parallel-pool job resolving its script slot.
        in_context.wait(timeout=5)
        other_thread["home"] = sched._get_hermes_home()
        may_exit.set()

    t = threading.Thread(target=_observer, daemon=True)
    t.start()

    from unittest.mock import patch

    with patch("hermes_cli.profiles.resolve_profile_env", return_value=str(profile_home)), \
         patch("hermes_cli.profiles.normalize_profile_name", side_effect=lambda p: p):
        with sched._job_profile_context("job-1", "financier"):
            inside_profile["home"] = sched._get_hermes_home()
            in_context.set()
            assert may_exit.wait(timeout=5), "observer thread never sampled"

    t.join(timeout=5)

    # The job's own thread DOES see the profile home -- profile isolation (#4707)
    # must be preserved, not thrown away to fix the leak.
    assert inside_profile["home"] == profile_home.resolve()

    # ...and no other thread does. This is the assertion that fails on the old
    # code, where the module-global made every thread agree with the profile job.
    assert other_thread["home"] != profile_home.resolve(), (
        "a concurrently-running job saw the profile job's Hermes home; it would "
        "resolve its script: slot under the wrong profile and die 'Script not found'"
    )


def test_writer_excludes_readers_for_the_profile_case():
    """The lock's own contract, stated for the profile job that now uses it."""
    import cron.scheduler as sched

    lock = sched._ReadWriteLock()
    lock.acquire_write()

    entered = threading.Event()

    def reader():
        lock.acquire_read()
        try:
            entered.set()
        finally:
            lock.release_read()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    # While the profile job holds the writer, no reader may enter.
    assert not entered.wait(timeout=0.5)
    lock.release_write()
    assert entered.wait(timeout=5), "reader never ran after the writer released"
    t.join(timeout=5)


def _hold_read_then_queue_writer(lock):
    """Reader holds the lock; a writer queues behind it. Returns (writer_in, thread, order)."""
    import time

    order = []
    lock.acquire_read()
    writer_in = threading.Event()

    def writer():
        lock.acquire_write()
        try:
            order.append("writer")
            writer_in.set()
        finally:
            lock.release_write()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not writer_in.is_set(), "writer entered while a reader held the lock"
    return writer_in, t, order


def _queue_reader(lock, order):
    entered = threading.Event()

    def reader():
        lock.acquire_read()
        try:
            order.append("reader")
            entered.set()
        finally:
            lock.release_read()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    return entered, t


def test_readers_keep_entering_while_a_writer_waits_inside_the_grace_period():
    """THE CONVOY (2026-09-13). Strict writer preference turned one 53-minute
    reader into a pool-wide queue: a 3-25 s writer waited behind it, and from
    then on every reader waited behind the writer until all four pool slots
    held jobs that had not started. Inside the grace period readers must
    still enter."""
    import cron.scheduler as sched

    lock = sched._ReadWriteLock(prefer_writer_after_s=30)
    writer_in, tw, order = _hold_read_then_queue_writer(lock)
    entered, tr = _queue_reader(lock, order)
    assert entered.wait(timeout=2), (
        "a reader queued behind a WAITING writer inside the grace period -- the convoy")
    tr.join(timeout=5)
    assert not writer_in.is_set()
    lock.release_read()
    assert writer_in.wait(timeout=5), "writer never ran after the readers drained"
    tw.join(timeout=5)
    assert order == ["reader", "writer"]


def test_writer_preference_returns_once_the_grace_period_elapses():
    """The bound: a writer that has waited longer than the grace period is
    preferred again, so a stream of short readers cannot starve it forever."""
    import time
    import cron.scheduler as sched

    lock = sched._ReadWriteLock(prefer_writer_after_s=0.3)
    writer_in, tw, order = _hold_read_then_queue_writer(lock)
    time.sleep(0.4)  # grace period elapsed while the writer waits
    entered, tr = _queue_reader(lock, order)
    assert not entered.wait(timeout=0.5), "a late reader jumped a writer past its grace period"
    lock.release_read()
    assert writer_in.wait(timeout=5)
    tw.join(timeout=5)
    assert entered.wait(timeout=5), "reader never ran after the writer released"
    tr.join(timeout=5)
    assert order == ["writer", "reader"]


def test_zero_grace_period_is_strict_writer_preference(monkeypatch):
    """``HERMES_CRON_WRITER_PREFERENCE_AFTER_SECONDS=0`` restores the old lock."""
    import cron.scheduler as sched

    monkeypatch.setenv("HERMES_CRON_WRITER_PREFERENCE_AFTER_SECONDS", "0")
    assert sched._writer_preference_after_seconds() == 0.0
    lock = sched._ReadWriteLock()  # reads the env at acquire time
    writer_in, tw, order = _hold_read_then_queue_writer(lock)
    entered, tr = _queue_reader(lock, order)
    assert not entered.wait(timeout=0.5)
    lock.release_read()
    assert writer_in.wait(timeout=5)
    tw.join(timeout=5)
    assert entered.wait(timeout=5)
    tr.join(timeout=5)
    assert order == ["writer", "reader"]
