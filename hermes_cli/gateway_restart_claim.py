"""Restart claims: make gateway bounces visible to, and coordinated across, sessions.

Added 2026-09-07. That day the gateway was bounced three times in 3h15m by three
different agent sessions (11:49, 14:44, 15:05), each deploying its own
just-merged fix, each individually authorised, none aware of the others. One
happened nine minutes after a fourth session's merge while that session was
still doing preflight for a bounce of its own; another landed between two of
its verification reads. Nothing was broken -- every drain happened to find zero
crons in flight -- but only by timing: a bounce drops any run in progress, and
the interpreter lineage flipped once along the way.

The open-loop claim gate (``~/.hermes/bin/loops.py``) could not see this. It
matches on TARGET, and "the gateway" is a shared RESOURCE every deploy touches,
so no session's task claim ever overlapped another's. This module gives the
resource its own claim:

* ``hermes gateway restart`` and ``hermes gateway run --replace`` open a loops
  record ``gateway-restart-<stamp>`` BEFORE stopping the incumbent, carrying
  the reason (``--reason``), the surface, the incumbent pid(s) and the actor,
  and close it (``done``) with the new pid(s) afterwards. Any session that
  runs ``loops.py check "gateway restart"`` sees it; so does the preflight
  below.
* The preflight REFUSES to bounce over another session's OPEN restart claim
  younger than :data:`OPEN_WINDOW_S` (a bounce in progress -- stacking a second
  boot on it is the failure mode agent memory calls boot stacking), and PRINTS
  any claim closed within :data:`RECENT_WINDOW_S` so the operator can compare
  their merge time against the last bounce before deciding a restart is owed.
  ``--ignore-restart-claim`` overrides the refusal; the advisory always prints.

Everything here is best-effort and never raises into the restart path: a
missing ``loops.py`` (another box), an unreadable registry, or a failed
subprocess degrades to a printed warning. A restart is an operator action that
must not be wedged by its own bookkeeping -- but the operator is TOLD the
bookkeeping is blind, because a silent degrade would train sessions to trust a
preflight that saw nothing.

The registry is read directly (read-only JSON) for the preflight and written
only through ``loops.py`` subprocesses, so the registry's own lock, witness
mirror and lost-write retry apply to every write this module makes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CLAIM_PREFIX = "gateway-restart-"
CLAIM_KEYWORDS = "gateway restart bounce replace relaunch deploy"

# Another session's OPEN claim younger than this means a bounce is in progress.
OPEN_WINDOW_S = 20 * 60
# DONE claims younger than this are reported so the operator can scope their deploy.
RECENT_WINDOW_S = 3 * 3600
# A DONE claim younger than this is probably still booting (port binds ~1-2 min
# after spawn; the roster registers later still) -- say so.
BOOTING_WINDOW_S = 3 * 60

# Set in the environment of a restart that already holds a claim so a child
# ``gateway run --replace`` it spawns does not open a second one.
CLAIM_ENV = "HERMES_GATEWAY_RESTART_CLAIM_ID"

_SUBPROCESS_TIMEOUT_S = 30


def _hermetic_block() -> Optional[str]:
    """Why this process must not touch the LIVE registry, or None.

    Under pytest with no explicit ``HERMES_LOOPS_REGISTRY`` the registry in
    scope is the box's real one. Measured 2026-09-07, the first hour this
    module existed: the existing gateway-restart tests drove the new hook and
    wrote 33 junk ``gateway-restart-<stamp>`` claims into the live registry,
    each of which ``loops.py check "gateway restart"`` then served to every
    session. A test that WANTS the registry points the env var at a temp file;
    everything else is inert here -- reads included, because a live blocking
    claim would otherwise make an unrelated restart test exit 2.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("HERMES_LOOPS_REGISTRY", "").strip():
        return "pytest without HERMES_LOOPS_REGISTRY: refusing to touch the live registry"
    return None


def loops_py_path() -> Optional[Path]:
    """``loops.py`` if this box has one, else None (the module is then inert)."""
    if _hermetic_block():
        return None
    override = os.environ.get("HERMES_LOOPS_PY", "").strip()
    candidate = Path(override) if override else Path.home() / ".hermes" / "bin" / "loops.py"
    return candidate if candidate.is_file() else None


def registry_path() -> Path:
    """Same resolution ``loops.py`` uses: ``HERMES_LOOPS_REGISTRY`` else the default."""
    override = os.environ.get("HERMES_LOOPS_REGISTRY", "").strip()
    return Path(override) if override else Path.home() / ".hermes" / "loops" / "claims.json"


def current_session() -> str:
    """Mirror of ``loops.py``'s actor derivation, so "another session" compares equal."""
    explicit = os.environ.get("HERMES_LOOP_SESSION", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "").strip()
    if host:
        return f"ccd:{host}"
    return f"pid:{os.getpid()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_s(rec: Dict[str, Any], now: datetime) -> Optional[float]:
    dt = _parse_ts(rec.get("updated_at"))
    return (now - dt).total_seconds() if dt else None


def _fmt_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "age unknown"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m ago"


def _holders(rec: Dict[str, Any]) -> List[str]:
    return [str(h.get("session") or "?") for h in rec.get("holders") or [] if isinstance(h, dict)]


def load_restart_records() -> tuple[List[Dict[str, Any]], Optional[str]]:
    """``(records with the restart prefix, error)``. Never raises.

    A missing registry is an empty registry (a fresh box, or one that has never
    bounced through this path). An unreadable one is reported as ``error`` --
    the same distinction ``loops.py`` draws between "empty" and "cannot see".
    """
    if _hermetic_block():
        return [], None
    path = registry_path()
    if not path.exists():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return [], f"{path}: {type(exc).__name__}: {exc}"
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return [], f"{path}: unexpected shape {type(records).__name__}"
    out = []
    for rec in records:
        if isinstance(rec, dict) and str(rec.get("id", "")).startswith(CLAIM_PREFIX):
            out.append(rec)
    return out, None


@dataclass
class Preflight:
    blocking: Optional[Dict[str, Any]] = None
    recent: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    now: datetime = field(default_factory=_now)

    def render(self) -> List[str]:
        """Human lines for the CLI. Empty when there is nothing to say."""
        lines: List[str] = []
        if self.error:
            lines.append(
                "⚠ Restart-claim registry unreadable -- cannot see other sessions' "
                f"gateway bounces: {self.error}"
            )
        for rec in self.recent:
            age = _age_s(rec, self.now)
            who = ", ".join(_holders(rec)) or "?"
            status = rec.get("status", "?")
            lines.append(
                f"ℹ Gateway restart claim {rec.get('id')} [{status}] {_fmt_age(age)} "
                f"by {who}: {rec.get('title') or '(no reason recorded)'}"
            )
            if status == "done" and age is not None and age < BOOTING_WINDOW_S:
                lines.append(
                    "    That bounce is seconds old: its replacement is probably still "
                    "booting. Poll :8642 and the subscriber roster before deciding "
                    "another restart is owed."
                )
            elif status == "done":
                lines.append(
                    "    If your change merged BEFORE that bounce, it is already live -- "
                    "compare the merge time with the running process StartTime."
                )
        if self.blocking is not None:
            rec = self.blocking
            lines.append(
                f"✗ A gateway bounce is IN PROGRESS: claim {rec.get('id')} opened "
                f"{_fmt_age(_age_s(rec, self.now))} by {', '.join(_holders(rec)) or '?'}: "
                f"{rec.get('title') or '(no reason recorded)'}"
            )
            lines.append(
                "    Refusing to stack a second boot on it. Wait for :8642 to bind and "
                "the roster to register, then re-check whether your change is already "
                "deployed. Override with --ignore-restart-claim only if that claim is "
                "stale (its holder died mid-restart)."
            )
        return lines


def preflight(*, now: Optional[datetime] = None) -> Preflight:
    """Classify the restart claims on record relative to ``now``."""
    now = now or _now()
    records, error = load_restart_records()
    me = current_session()
    result = Preflight(error=error, now=now)
    for rec in records:
        age = _age_s(rec, now)
        if age is None:
            continue
        if rec.get("status") != "done":
            if age <= OPEN_WINDOW_S:
                if me not in _holders(rec):
                    # Youngest blocking claim wins the report.
                    if result.blocking is None or age < (_age_s(result.blocking, now) or 0):
                        result.blocking = rec
                else:
                    result.recent.append(rec)
            elif age <= RECENT_WINDOW_S:
                # An open claim older than the window: its holder most likely died
                # mid-restart. Report, do not block.
                result.recent.append(rec)
        elif age <= RECENT_WINDOW_S:
            result.recent.append(rec)
    result.recent.sort(key=lambda r: _age_s(r, now) or 0)
    return result


def _run_loops(argv: Sequence[str]) -> tuple[bool, str]:
    blocked = _hermetic_block()
    if blocked:
        return False, blocked
    loops = loops_py_path()
    if loops is None:
        return False, "loops.py not found (set HERMES_LOOPS_PY or install ~/.hermes/bin/loops.py)"
    try:
        proc = subprocess.run(
            [sys.executable, str(loops), *argv],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return False, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    return proc.returncode == 0, out


def _fmt_pids(pids: Optional[Sequence[int]]) -> str:
    pids = [p for p in (pids or []) if p]
    return ", ".join(str(p) for p in pids) if pids else "none found"


@dataclass
class RestartClaim:
    """One bounce's record. ``opened`` False means the registry never saw it."""

    claim_id: str
    opened: bool = False
    closed: bool = False
    incumbent_pids: List[int] = field(default_factory=list)
    detail: str = ""

    @classmethod
    def open(
        cls,
        *,
        reason: Optional[str],
        surface: str,
        incumbent_pids: Optional[Sequence[int]] = None,
    ) -> "RestartClaim":
        """Record a bounce that is about to start. Never raises."""
        stamp = _now().astimezone().strftime("%Y%m%d-%H%M%S")
        claim_id = f"{CLAIM_PREFIX}{stamp}"
        pids = [int(p) for p in (incumbent_pids or []) if p]
        claim = cls(claim_id=claim_id, incumbent_pids=pids)
        title = (reason or "").strip() or "(no reason given -- pass --reason next time)"
        findings = (
            f"IN PROGRESS {_stamp()} via {surface} by {current_session()}: "
            f"stopping incumbent gateway pid(s) {_fmt_pids(pids)}. Reason: {title}"
        )
        ok, out = _run_loops(
            ["claim", claim_id, "--keywords", CLAIM_KEYWORDS, "--title", title, "--findings", findings]
        )
        claim.opened = ok
        claim.detail = out
        if ok:
            os.environ[CLAIM_ENV] = claim_id
        return claim

    def close(
        self,
        *,
        outcome: str,
        new_pids: Optional[Sequence[int]] = None,
        note: str = "",
    ) -> None:
        """Mark the bounce finished. Idempotent; never raises."""
        if self.closed or not self.opened:
            self.closed = True
            return
        self.closed = True
        findings = (
            f"{outcome} {_stamp()}: incumbent pid(s) {_fmt_pids(self.incumbent_pids)} "
            f"-> new gateway pid(s) {_fmt_pids(new_pids)}."
        )
        if note:
            findings += f" {note}"
        ok, out = _run_loops(["done", self.claim_id, "--findings", findings])
        if not ok:
            self.detail = out
        if os.environ.get(CLAIM_ENV) == self.claim_id:
            os.environ.pop(CLAIM_ENV, None)


def inherited_claim_id() -> Optional[str]:
    """The claim a parent restart already opened for this process, if any."""
    return os.environ.get(CLAIM_ENV, "").strip() or None


def guard_and_open(
    *,
    reason: Optional[str],
    surface: str,
    incumbent_pids: Optional[Sequence[int]],
    ignore_blocking: bool = False,
    printer=print,
) -> RestartClaim:
    """Preflight, print, refuse (exit 2) or open. The one call the CLI paths make.

    A child process whose parent already holds a claim (``CLAIM_ENV`` set) gets
    an unopened claim back and no preflight: the parent is the one bouncing.
    """
    inherited = inherited_claim_id()
    if inherited:
        return RestartClaim(claim_id=inherited, opened=False)
    pf = preflight()
    for line in pf.render():
        printer(line)
    if pf.blocking is not None and not ignore_blocking:
        sys.exit(2)
    if pf.blocking is not None:
        printer("  --ignore-restart-claim given: proceeding over the open claim.")
    claim = RestartClaim.open(reason=reason, surface=surface, incumbent_pids=incumbent_pids)
    if claim.opened:
        printer(f"✓ Restart claim {claim.claim_id} opened (loops registry)")
    else:
        printer(
            "⚠ Could not record a restart claim -- other sessions will not see this "
            f"bounce: {claim.detail}"
        )
    return claim
