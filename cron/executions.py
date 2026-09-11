"""Profile-local durable audit ledger for cron execution attempts.

The ledger records what is known about each attempt; it is not a retry queue. Interrupted attempts
become ``unknown`` only after their exact owner process is proved gone. Terminal states are
immutable.
"""

from __future__ import annotations

import os
import contextlib
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from cron.ledger import ledger_transaction, open_ledger, prepare_ledger
from hermes_constants import get_default_hermes_root, get_hermes_home
from hermes_time import now as _hermes_now

# Optional test override. Production resolves the path at transaction time so dashboard operations
# that temporarily enter another profile cannot leak that profile's records into the import-time
# home.
EXECUTIONS_FILE: Optional[Path] = None
MAX_TERMINAL_EXECUTIONS = 10000
_MAX_PROBE_ERROR_LENGTH = 500
_MAX_ADMISSION_LIVENESS_PROBES = 8
logger = logging.getLogger(__name__)
HANDOFF_ADOPTION_GRACE_SECONDS = 30.0
_TERMINAL_STATES = ("completed", "failed", "unknown")
_lock = threading.RLock()
_PROCESS_ID = uuid.uuid4().hex


# --- executions ledger --------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    return open_ledger(EXECUTIONS_FILE or (get_hermes_home().resolve() / "cron" / "executions.db"))


def _initialize_schema(conn: sqlite3.Connection) -> None:
    prepare_ledger(conn, db_label="cron/executions.db")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS executions (
             id TEXT PRIMARY KEY,
             job_id TEXT NOT NULL,
             source TEXT NOT NULL,
             process_id TEXT NOT NULL,
             pid INTEGER NOT NULL,
             process_started_at INTEGER,
             status TEXT NOT NULL CHECK(status IN
               ('claimed','running','completed','failed','unknown')),
             handoff_pending INTEGER NOT NULL DEFAULT 0,
             handoff_started_at REAL,
             claimed_at TEXT NOT NULL,
             started_at TEXT,
             finished_at TEXT,
             error TEXT
           )"""
    )
    from hermes_cli.sqlite_util import add_column_if_missing

    add_column_if_missing(
        conn, "executions", "handoff_pending",
        "handoff_pending INTEGER NOT NULL DEFAULT 0",
    )
    add_column_if_missing(
        conn, "executions", "handoff_started_at", "handoff_started_at REAL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_job_claimed "
        "ON executions(job_id, claimed_at DESC, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_status_claimed "
        "ON executions(status, claimed_at DESC, id DESC)"
    )
    add_column_if_missing(conn, "executions", "scheduled_instant", "scheduled_instant TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_occurrence "
        "ON executions(job_id, scheduled_instant) WHERE status='completed'"
    )


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    with ledger_transaction(_lock, _connect, _initialize_schema) as conn:
        yield conn


def _fetch(conn: sqlite3.Connection, execution_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
    return dict(row) if row is not None else None


def _emit_execution_state(
    record: Optional[Dict[str, Any]], *, delivery_outcome: Optional[str] = None
) -> None:
    """Project durable state to monitoring without affecting ledger behavior."""
    try:
        from agent.monitoring.cron_health import emit_execution_state

        emit_execution_state(record, delivery_outcome=delivery_outcome)
    except Exception:
        pass


def _process_start_time(pid: int) -> Optional[int]:
    try:
        from gateway.status import get_process_start_time
        return get_process_start_time(pid)
    except Exception:
        return None


def _owner_is_live(pid: int, started_at: Optional[int]) -> bool:
    try:
        from gateway.status import _pid_exists
        if not _pid_exists(pid):
            return False
    except Exception:
        # Fail safe: inability to prove death must not rewrite state. Keep that
        # behaviour -- but say so. Silently returning True makes the caller
        # skip recovery, so an interrupted attempt keeps a stale 'running' row
        # forever and jobs.json never learns the run ended, with nothing
        # anywhere recording why. This is also the ONLY branch that can make
        # recover_interrupted_executions() return 0 for a genuinely dead owner
        # (a recycled PID is rejected by the process_started_at comparison
        # below, which is centisecond-resolution), so it is the first thing to
        # look for when that count is unexpectedly 0.
        logger.warning(
            "Could not probe liveness of pid %s; treating its execution as "
            "still owned and skipping recovery (fail-safe).",
            pid,
            exc_info=True,
        )
        return True
    if started_at is None:
        return pid == os.getpid()
    current = _process_start_time(pid)
    return current is not None and current == started_at


def _prune_unlocked(conn: sqlite3.Connection) -> None:
    conn.execute(
        """DELETE FROM executions WHERE id IN (
             SELECT id FROM executions
             WHERE status IN ('completed','failed','unknown')
             ORDER BY finished_at DESC, claimed_at DESC, id DESC LIMIT -1 OFFSET ?
           )""",
        (max(0, int(MAX_TERMINAL_EXECUTIONS)),),
    )


def create_execution(
    job_id: str, *, source: str, scheduled_instant: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a claimed attempt before executor/provider dispatch."""
    from cron.occurrences import scheduled_instant as canonical_instant

    now = _hermes_now().isoformat()
    execution_id = uuid.uuid4().hex
    pid = os.getpid()
    with _transaction() as conn:
        conn.execute(
            """INSERT INTO executions
               (id, job_id, source, process_id, pid, process_started_at,
                status, claimed_at, scheduled_instant)
               VALUES (?, ?, ?, ?, ?, ?, 'claimed', ?, ?)""",
            (execution_id, str(job_id), str(source), _PROCESS_ID, pid,
             _process_start_time(pid), now, canonical_instant(scheduled_instant)),
        )
        record = _fetch(conn, execution_id)
    _emit_execution_state(record)
    return record  # type: ignore[return-value]


def set_execution_occurrence(execution_id: str, instant: Optional[str]) -> None:
    """Bind the store-claimed snapshot before a provider hands it to a worker."""
    from cron.occurrences import scheduled_instant

    with _transaction() as conn:
        cur = conn.execute(
            "UPDATE executions SET scheduled_instant=? WHERE id=? AND status='claimed' "
            "AND handoff_pending=0 AND process_id=? AND pid=?",
            (scheduled_instant(instant), execution_id, _PROCESS_ID, os.getpid()),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Cron occurrence could not be bound before dispatch")


def mark_execution_handoff_pending(execution_id: str) -> Optional[Dict[str, Any]]:
    """Fence restart recovery while an external worker is adopting a claim."""
    with _transaction() as conn:
        cur = conn.execute(
            """UPDATE executions
               SET handoff_pending=1, handoff_started_at=?
               WHERE id=? AND status='claimed'
                 AND process_id=? AND pid=?""",
            (time.time(), execution_id, _PROCESS_ID, os.getpid()),
        )
        if cur.rowcount != 1:
            return None
        record = _fetch(conn, execution_id)
    _emit_execution_state(record)
    return record


def adopt_claimed_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Atomically transfer and start an attempt in its worker process.

    The dispatching gateway creates the row before spawning a restart-safe
    worker.  Adoption is the single ``claimed`` → ``running`` gate: only the
    winner may acknowledge ownership or run side effects.
    """
    pid = os.getpid()
    process_started_at = _process_start_time(pid)
    now = _hermes_now().isoformat()
    with _transaction() as conn:
        cur = conn.execute(
            """UPDATE executions
               SET process_id=?, pid=?, process_started_at=?,
                   status='running', started_at=?, handoff_pending=0,
                   handoff_started_at=NULL
               WHERE id=? AND status='claimed' AND handoff_pending=1""",
            (_PROCESS_ID, pid, process_started_at, now, execution_id),
        )
        if cur.rowcount != 1:
            return None
        record = _fetch(conn, execution_id)
    _emit_execution_state(record)
    return record


def mark_execution_running(execution_id: str) -> Optional[Dict[str, Any]]:
    """Transition one claimed attempt to running exactly once."""
    now = _hermes_now().isoformat()
    with _transaction() as conn:
        cur = conn.execute(
            """UPDATE executions
               SET status='running', started_at=?, handoff_pending=0,
                   handoff_started_at=NULL
               WHERE id=? AND status='claimed' AND handoff_pending=0
                 AND process_id=? AND pid=?""",
            (now, execution_id, _PROCESS_ID, os.getpid()),
        )
        if cur.rowcount != 1:
            return None
        record = _fetch(conn, execution_id)
    _emit_execution_state(record)
    return record


def finish_execution(
    execution_id: str, *, success: bool, error: Optional[str] = None,
    delivery_outcome: Optional[str] = None,
    allow_handoff: bool = True,
) -> Optional[Dict[str, Any]]:
    """Write a terminal result once; terminal attempts cannot be rewritten."""
    now = _hermes_now().isoformat()
    status = "completed" if success else "failed"
    detail = None if success else (str(error) if error else "unknown failure")
    with _transaction() as conn:
        cur = conn.execute(
            """UPDATE executions
               SET status=?, finished_at=?, error=?, handoff_pending=0,
                   handoff_started_at=NULL
               WHERE id=? AND status IN ('claimed','running')
                 AND process_id=? AND pid=? AND (? OR handoff_pending=0)""",
            (status, now, detail, execution_id, _PROCESS_ID, os.getpid(), allow_handoff),
        )
        if cur.rowcount != 1:
            return None
        _prune_unlocked(conn)
        record = _fetch(conn, execution_id)
    _emit_execution_state(record, delivery_outcome=delivery_outcome)
    return record


def recover_interrupted_execution_records() -> List[Dict[str, Any]]:
    """Mark provably abandoned attempts unknown without scheduling retries."""
    now = _hermes_now().isoformat()
    changed = 0
    recovered: List[Dict[str, Any]] = []
    with _transaction() as conn:
        rows = conn.execute(
            """SELECT id, status, process_id, pid, process_started_at,
                      handoff_pending, handoff_started_at
               FROM executions
               WHERE status IN ('claimed','running')"""
        ).fetchall()
        for row in rows:
            if row["process_id"] == _PROCESS_ID:
                continue
            if _owner_is_live(int(row["pid"]), row["process_started_at"]):
                continue
            handoff_started_at = row["handoff_started_at"]
            if (
                row["handoff_pending"]
                and handoff_started_at is not None
                and time.time() - float(handoff_started_at)
                < HANDOFF_ADOPTION_GRACE_SECONDS
            ):
                continue
            cur = conn.execute(
                """UPDATE executions
                   SET status='unknown', finished_at=?, error=?,
                       handoff_pending=0, handoff_started_at=NULL
                   WHERE id=? AND status=? AND process_id=? AND pid=?
                     AND handoff_pending=?
                     AND handoff_started_at IS ?""",
                (now,
                 "Scheduler restarted after this execution's owner exited before a durable "
                 "terminal state; whether side effects ran is unknown.",
                 row["id"], row["status"], row["process_id"], row["pid"],
                 row["handoff_pending"], row["handoff_started_at"]),
            )
            changed += cur.rowcount
            if cur.rowcount:
                record = _fetch(conn, row["id"])
                if record is not None:
                    recovered.append(record)
        if changed:
            _prune_unlocked(conn)
    for record in recovered:
        _emit_execution_state(record)
    return recovered


def recover_interrupted_executions() -> int:
    return len(recover_interrupted_execution_records())


def list_executions(
    *, job_id: Optional[str] = None, limit: int = 50, before_claimed_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return indexed, newest-first execution history with cursor pagination."""
    clauses: List[str] = []
    params: List[Any] = []
    if job_id is not None:
        clauses.append("job_id=?")
        params.append(str(job_id))
    if before_claimed_at is not None:
        clauses.append("claimed_at < ?")
        params.append(str(before_claimed_at))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    with _transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM executions" + where
            + " ORDER BY claimed_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Return one exact execution attempt, or ``None`` when it is absent."""
    with _transaction() as conn:
        row = conn.execute(
            "SELECT * FROM executions WHERE id=?",
            (str(execution_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def latest_execution(job_id: str) -> Optional[Dict[str, Any]]:
    rows = list_executions(job_id=job_id, limit=1)
    return rows[0] if rows else None


def latest_executions(job_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Load latest execution for many jobs in one indexed query."""
    clean = [str(job_id) for job_id in dict.fromkeys(job_ids) if job_id]
    if not clean:
        return {}
    placeholders = ",".join("?" for _ in clean)
    with _transaction() as conn:
        rows = conn.execute(
            f"""SELECT e.* FROM executions e
                WHERE e.job_id IN ({placeholders})
                  AND e.id=(SELECT e2.id FROM executions e2
                            WHERE e2.job_id=e.job_id
                            ORDER BY e2.claimed_at DESC, e2.id DESC LIMIT 1)""",
            clean,
        ).fetchall()
    return {row["job_id"]: dict(row) for row in rows}


def _connect_path(path, *, create: bool) -> sqlite3.Connection:
    """Explicit-path census connection; readonly probes never migrate or create."""
    path = Path(path).resolve()
    if create:
        conn = open_ledger(path)
        try:
            _initialize_schema(conn)
            conn.commit()
        except BaseException:
            conn.close()
            raise
        return conn
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
def _probe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:_MAX_PROBE_ERROR_LENGTH]


def _canonical_hermes_root():
    return get_default_hermes_root()


def amend_execution_after_abandon(
    execution_id: str,
    *,
    abandon_error: str,
    success: bool,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Replace only this execution's provisional deadline verdict.

    Terminal rows are otherwise immutable. This narrow compare-and-swap
    is the exception because the soft deadline explicitly leaves its
    worker running: ``failed`` means "still running at the deadline",
    not a known terminal outcome. Exact error matching prevents a late
    worker from rewriting any later or independently reached failure.
    """
    now = _hermes_now().isoformat()
    status = "completed" if success else "failed"
    detail = None if success else (str(error) if error else "unknown failure")
    with _transaction() as conn:
        cur = conn.execute(
            """UPDATE executions SET status=?, finished_at=?, error=?
               WHERE id=? AND status='failed' AND error=? AND process_id=? AND pid=?""",
            (status, now, detail, execution_id, abandon_error, _PROCESS_ID, os.getpid()),
        )
        if cur.rowcount != 1:
            return None
        _prune_unlocked(conn)
        record = _fetch(conn, execution_id)
    _emit_execution_state(record)
    return record


def _classify_nonterminal_rows(rows) -> List[Dict[str, Any]]:
    census: List[Dict[str, Any]] = []
    for sqlite_row in rows:
        row = dict(sqlite_row)
        pid = int(row["pid"])
        recorded_start = row["process_started_at"]
        evidence: Dict[str, Any] = {
            "process_id": row["process_id"],
            "pid": pid,
            "process_started_at": recorded_start,
        }
        try:
            from gateway.status import _pid_exists

            pid_exists = _pid_exists(pid)
        except Exception as exc:
            evidence["reason"] = "pid_probe_error"
            evidence["probe_error"] = _probe_error(exc)
            liveness = "unprovable"
        else:
            evidence["pid_exists"] = pid_exists
            if pid_exists is None:
                evidence["reason"] = "pid_probe_indeterminate"
                liveness = "unprovable"
            elif not pid_exists:
                evidence["reason"] = "pid_not_found"
                liveness = "dead"
            elif recorded_start is None:
                evidence["reason"] = "recorded_process_start_time_missing"
                liveness = "unprovable"
            else:
                try:
                    observed_start = _process_start_time(pid)
                except Exception as exc:
                    evidence["reason"] = "process_start_time_probe_error"
                    evidence["probe_error"] = _probe_error(exc)
                    liveness = "unprovable"
                else:
                    evidence["observed_process_started_at"] = observed_start
                    if observed_start is None:
                        evidence["reason"] = "observed_process_start_time_unavailable"
                        liveness = "unprovable"
                    elif observed_start == recorded_start:
                        evidence["reason"] = "process_start_time_matches"
                        liveness = "live"
                    else:
                        evidence["reason"] = "process_start_time_mismatch"
                        liveness = "dead"
        row["owner_liveness"] = liveness
        row["owner_liveness_evidence"] = evidence
        census.append(row)
    return census


def _nonterminal_execution_census_path(path, *, create: bool) -> List[Dict[str, Any]]:
    with _lock, contextlib.closing(_connect_path(path, create=create)) as conn, conn:
        rows = conn.execute(
            """SELECT * FROM executions
               WHERE status IN ('claimed','running')
               ORDER BY claimed_at, id"""
        ).fetchall()
    return _classify_nonterminal_rows(rows)


def nonterminal_execution_census() -> List[Dict[str, Any]]:
    """Return every claimed/running row in this profile's execution ledger."""
    return _nonterminal_execution_census_path(EXECUTIONS_FILE or (get_hermes_home().resolve() / "cron" / "executions.db"), create=True)


def nonterminal_execution_job_ids() -> set:
    """Storage-only set of job ids that still hold a claimed/running row.

    Like :func:`nonterminal_execution_counts`, this never probes an owner
    process: it answers "which jobs does the ledger still consider in flight",
    not "which of those owners are alive". Run it AFTER
    :func:`recover_interrupted_execution_records` and the answer is exactly the
    set of jobs whose run may still be live somewhere (a live owner, an
    unprovable one, or this very process) -- the set a recovery pass must not
    touch. Descriptive only, never admission or recovery authority.
    """
    with _transaction() as conn:
        rows = conn.execute(
            """SELECT DISTINCT job_id FROM executions
               WHERE status IN ('claimed','running')"""
        ).fetchall()
    return {str(row["job_id"]) for row in rows}


def nonterminal_execution_counts() -> Dict[str, int]:
    """Storage-only claimed/running counts for scheduler observability.

    Unlike ``nonterminal_execution_census()``, this does not probe each owner
    process. The ticker calls it twice per iteration, so liveness classification
    here would turn a bounded heartbeat write into a process-enumeration stall.
    These are descriptive counts, never admission or recovery authority.
    """
    with _transaction() as conn:
        rows = conn.execute(
            """SELECT status, COUNT(*) AS n FROM executions
               WHERE status IN ('claimed','running') GROUP BY status"""
        ).fetchall()
    counts = {"claimed": 0, "running": 0}
    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    return counts


def live_execution_for_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a non-terminal execution of ``job_id`` in ANOTHER process whose
    owner is PROVABLY alive.

    ``None`` means "no proof of a live run elsewhere", which deliberately lumps
    together "the owner is dead" and "liveness could not be determined". A
    caller gating admission must treat only a non-None result as grounds to
    refuse: refusing on an unprovable probe would leave the job unfireable with
    no recovery path, reintroducing the exact wedge the fire-claim TTL exists
    to prevent.

    That is the opposite of :func:`_owner_is_live`'s fail-safe-to-True, and the
    asymmetry is intentional. On the recovery path "assume still owned" is
    cheap and self-correcting — the next restart re-probes. As an admission
    gate it is neither.

    **Rows owned by THIS process are excluded, and that exclusion is load
    bearing.** Their pid is alive by definition, so a stale one — a row whose
    ``finish_execution`` never landed, e.g. an abandoned soft-deadline run —
    would read as a live run forever. Nothing cleans it either:
    :func:`recover_interrupted_execution_records` skips rows whose
    ``process_id`` is ``_PROCESS_ID``, precisely because it cannot distinguish
    them from its own in-flight work. In a long-lived gateway that combination
    would wedge the job permanently. The in-process case is already owned by
    ``cron.scheduler``'s ``_in_flight`` registry (Guard #3), which is exact
    rather than inferred, so this function answers the strictly cross-process
    question and the two compose without overlap.

    Rows are probed newest-first and the scan stops at the first live owner, so
    the blocking case normally costs exactly one probe. The sqlite read is
    finished (and both locks released) before any probing begins, so a slow
    ``psutil`` call never holds the ledger lock.
    """
    with _transaction() as conn:
        rows = conn.execute(
            """SELECT * FROM executions
               WHERE job_id=? AND status IN ('claimed','running')
                 AND process_id<>?
               ORDER BY claimed_at DESC, id DESC
               LIMIT ?""",
            (job_id, _PROCESS_ID, _MAX_ADMISSION_LIVENESS_PROBES),
        ).fetchall()

    for row in rows:
        # One row at a time: _classify_nonterminal_rows probes every row it is
        # given, and the point here is to stop at the first proven-live owner.
        classified = _classify_nonterminal_rows([row])[0]
        if classified["owner_liveness"] == "live":
            return classified
    return None


def _cross_profile_execution_ledgers() -> tuple:
    root = _canonical_hermes_root().resolve()
    candidates = [root / "cron" / "executions.db"]
    profiles = root / "profiles"
    if profiles.is_dir():
        candidates.extend(
            profile / "cron" / "executions.db"
            for profile in sorted(profiles.iterdir(), key=lambda path: path.name)
            if profile.is_dir()
        )
    return tuple(path.resolve() for path in candidates if path.is_file())


def cross_profile_nonterminal_execution_census() -> List[Dict[str, Any]]:
    """Return a read-only, lossless census from every existing profile ledger."""
    rows: List[Dict[str, Any]] = []
    for ledger in _cross_profile_execution_ledgers():
        for row in _nonterminal_execution_census_path(ledger, create=False):
            row["execution_ledger"] = str(ledger)
            rows.append(row)
    rows.sort(key=lambda row: (row["claimed_at"], row["id"], row["execution_ledger"]))
    return rows
