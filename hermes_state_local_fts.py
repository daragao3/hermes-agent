"""Preserved local FTS diagnostic and bounded-merge APIs. No automatic repair owner."""
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
logger = logging.getLogger("hermes_state")

_FTS_INDEX_TABLES: Tuple[str, ...] = ("messages_fts", "messages_fts_trigram")

class StateDbProbeTimeout(Exception):
    """A bounded :func:`_db_opens_cleanly` probe ran out of budget.

    Deliberately an exception rather than a reason string. Callers treat a
    reason as "this database is corrupt" and escalate to destructive repair
    strategies, so "we ran out of time" must be impossible to confuse with
    "we found damage".
    """

    def __init__(self, stage: str, timeout_seconds: float) -> None:
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"health probe exceeded its {timeout_seconds:g}s budget during {stage}"
        )

def _arm_probe_deadline(
    conn: sqlite3.Connection, timeout_seconds: float
) -> Tuple[Callable[[], None], threading.Event]:
    """Abort *conn*'s in-flight statement after *timeout_seconds*.

    Returns ``(cancel, timed_out)``.

    ``sqlite3.Connection.interrupt`` is the only mechanism that reliably
    aborts a statement already executing inside SQLite. ``PRAGMA
    integrity_check`` is a single VDBE opcode, so a progress handler barely
    fires inside it — measured on the 5.1 GB state.db that motivated this:
    one callback in 3.5s at n=10000, versus ``interrupt()`` landing within
    ~50ms of the deadline.
    """
    timed_out = threading.Event()

    def _fire() -> None:
        timed_out.set()
        try:
            conn.interrupt()
        except Exception:  # pragma: no cover — connection already closed
            pass

    timer = threading.Timer(timeout_seconds, _fire)
    timer.daemon = True
    timer.start()
    return timer.cancel, timed_out

def _fts_integrity_check_sql(table: str) -> str:
    """The rank=1 form of the FTS5 ``'integrity-check'`` command.

    ``rank=1`` re-derives every term from the content source and compares it
    to the index. ``rank=0`` (the default) only checks the index against
    itself, which under external content detects neither of the two failure
    modes that matter: an index rowid whose ``messages`` row is gone, and
    index text that no longer matches the row it points at. Both are
    invisible to ``search_messages`` — it INNER JOINs ``messages`` on the
    index rowid, so an orphan is filtered out before ``snippet()`` sees it —
    so this statement is the only probe that surfaces them.
    """
    return f"INSERT INTO {table}({table}, rank) VALUES('integrity-check', 1)"

def _fts_indexes_present(conn: sqlite3.Connection) -> Tuple[str, ...]:
    """Return the FTS index tables that are queryable on *conn*."""
    present = []
    for table in _FTS_INDEX_TABLES:
        try:
            conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
        except sqlite3.OperationalError:
            continue
        present.append(table)
    return tuple(present)

def _fts_integrity_reason(conn: sqlite3.Connection) -> Optional[str]:
    """Run the rank=1 integrity-check on every present index.

    Returns ``None`` when every index verifies, else a joined reason string.
    Missing tables are skipped, so a database with no FTS index at all
    returns ``None``.

    Never converts an aborted statement into a reason: ``conn.interrupt()``
    surfaces as ``OperationalError: interrupted``, which is a
    ``DatabaseError`` and would otherwise be indistinguishable from real
    damage. That exception is re-raised for the caller's deadline handling
    to classify.
    """
    problems = []
    for table in _fts_indexes_present(conn):
        try:
            conn.execute(_fts_integrity_check_sql(table))
        except sqlite3.DatabaseError as exc:
            if _is_interrupted_error(exc):
                raise
            problems.append(f"{table}: {exc}")
    return "; ".join(problems) if problems else None

def _is_interrupted_error(exc: BaseException) -> bool:
    """True if *exc* is SQLite reporting an aborted statement.

    ``sqlite3.Connection.interrupt`` raises ``OperationalError:
    interrupted`` — verified against an FTS5 rank=1 integrity-check, which
    aborts within ~3ms of the deadline on a 171 MB index. "We ran out of
    time" must never be reported as "this index is corrupt".
    """
    return isinstance(exc, sqlite3.OperationalError) and "interrupted" in str(exc).lower()

def check_state_db_fts_integrity(
    db_path: Path, *, timeout_seconds: Optional[float] = None
) -> Optional[str]:
    """Verify the FTS indexes of the database at *db_path*, on its own budget.

    Returns ``None`` when every index verifies, else a reason string.

    Deliberately a *separate* probe from :func:`_db_opens_cleanly` rather than
    a stage inside it, because the two expensive checks scale differently on
    the same file. This one is CPU-bound on tokenisation and measured ~70s on
    the post-v32 production snapshot (4891 MB, 575,962 messages, 1.38 GB of
    indexed text). ``PRAGMA integrity_check`` is I/O-bound and fragmentation-
    sensitive: 116.8s on that compacted snapshot, but >12 minutes on the live
    fragmented file — the hang that put a budget on the probe in the first
    place.

    Sharing one deadline would therefore let the page-by-page scan eat the
    whole budget on exactly the databases that need checking, and the caller
    would be told "unknown" about the one thing it asked for.

    Raises:
        StateDbProbeTimeout: the budget was exhausted. Not a corruption signal.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    cancel_deadline: Optional[Callable[[], None]] = None
    timed_out: Optional[threading.Event] = None
    if timeout_seconds is not None:
        cancel_deadline, timed_out = _arm_probe_deadline(conn, timeout_seconds)
    try:
        return _fts_integrity_reason(conn)
    except sqlite3.DatabaseError as exc:
        if timed_out is not None and timed_out.is_set():
            raise StateDbProbeTimeout(
                "the FTS integrity-check", float(timeout_seconds)
            ) from exc
        if _is_interrupted_error(exc):
            raise
        return str(exc)
    finally:
        if cancel_deadline is not None:
            cancel_deadline()
        conn.close()

class SessionLocalFtsMixin:
    _FTS_MERGE_PAGES = 16

    def merge_fts(self, pages: int | None = None) -> int:
        """Do a BOUNDED amount of FTS5 segment merging.

        Unlike :meth:`optimize_fts`, which rewrites every segment into one
        and therefore costs O(total index size), the ``'merge'`` command
        stops after roughly *pages* pages have been written. That makes it
        safe to call repeatedly from the write path: the cost is capped no
        matter how large the index has grown, while segments are still kept
        from accumulating into the tens of thousands that slow every MATCH
        and lengthen the write-lock hold.

        Partial progress is the point — each call advances the merge a
        little, and FTS5 resumes where it left off on the next call.

        Skips any FTS table that does not exist, so it is safe to call
        unconditionally. Returns the number of FTS indexes it merged into.
        """
        budget = self._FTS_MERGE_PAGES if pages is None else pages
        merged = 0
        with self._lock:
            for tbl in self._FTS_TABLES:
                if not self._fts_table_exists(tbl):
                    continue
                try:
                    # 'merge' takes its page budget through the `rank`
                    # column — the plain ``VALUES('merge')`` form of the
                    # other FTS5 commands does not apply here.
                    self._conn.execute(
                        f"INSERT INTO {tbl}({tbl}, rank) VALUES('merge', ?)",
                        (budget,),
                    )
                    merged += 1
                except sqlite3.OperationalError as exc:
                    logger.warning("FTS merge failed for %s: %s", tbl, exc)
        return merged

    def check_fts_integrity(
        self, *, timeout_seconds: Optional[float] = None
    ) -> Dict[str, Optional[str]]:
        """Validate each FTS index against its content, strictly.

        Returns ``{table: None}`` when the index is healthy and
        ``{table: "<error>"}`` when it is not. Tables that do not exist are
        omitted, so an all-``None`` result on an empty dict means "nothing to
        check", not "healthy".

        Uses the ``rank=1`` form of ``'integrity-check'``, which re-derives the
        terms from the content table rather than only checking the index
        against itself. For ``messages_fts`` (external content) that is the
        difference between detecting and missing the two failure modes that
        matter: an index rowid with no surviving ``messages`` row, and index
        text that no longer matches the row it points at. The default rank=0
        form reports neither.

        Not cheap — it re-reads every indexed row, so this is a deliberate
        health probe (post-migration verification, ``doctor``-style checks),
        not something to call on a hot path. ``rebuild_fts()`` repairs whatever
        it reports.

        Note this is a write statement as far as SQLite is concerned; it cannot
        run on a read-only connection.

        Args:
            timeout_seconds: wall-clock budget for the whole check. ``None``
                (the default) is unbounded. When a budget is given and
                exhausted, the in-flight statement is aborted via
                ``conn.interrupt()`` and :class:`StateDbProbeTimeout` is
                raised — never a per-table reason. An aborted check has found
                nothing, and "we ran out of time" reported as ``{table:
                "interrupted"}`` would read as corruption and, on a caller
                wired to auto-repair, provoke a needless full rebuild.

        Raises:
            StateDbProbeTimeout: the budget was exhausted. Not a corruption
                signal.
        """
        results: Dict[str, Optional[str]] = {}
        with self._lock:
            cancel_deadline: Optional[Callable[[], None]] = None
            timed_out: Optional[threading.Event] = None
            if timeout_seconds is not None:
                cancel_deadline, timed_out = _arm_probe_deadline(
                    self._conn, timeout_seconds
                )
            try:
                for tbl in self._FTS_TABLES:
                    if not self._fts_table_exists(tbl):
                        continue
                    try:
                        self._conn.execute(_fts_integrity_check_sql(tbl))
                        results[tbl] = None
                    except sqlite3.DatabaseError as exc:
                        if timed_out is not None and timed_out.is_set():
                            raise StateDbProbeTimeout(
                                f"the {tbl} integrity-check", float(timeout_seconds)
                            ) from exc
                        if _is_interrupted_error(exc):
                            raise
                        results[tbl] = str(exc)
                        logger.warning(
                            "FTS integrity-check failed for %s: %s", tbl, exc
                        )
            finally:
                if cancel_deadline is not None:
                    cancel_deadline()
        return results
