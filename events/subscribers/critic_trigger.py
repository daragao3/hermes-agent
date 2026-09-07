"""CriticSubscriber — post-hoc Critic trigger.

Listens for AGENT_FAILURE_CLUSTER events emitted by CronEventEmitter and
invokes critic_retro.py with --cluster scoping so Critic produces a
focused retro for the cluster within ~30 minutes (per Hermes Revival §6).

Subprocess-based invocation (not in-process) because:
  - Critic loads its own profile-scoped environment (~/.hermes/profiles/critic/)
  - Critic retro can take longer than the subscriber poll interval
  - Subscriber must not block other events on the bus

Debounces same-(source, failure_type) clusters within a configurable
window to avoid storming Critic when a cluster persists across multiple
detection windows.

CRASH VISIBILITY (2026-09-07).  Until this change the spawn discarded both
halves of the failure signal: ``stderr=subprocess.DEVNULL`` threw the traceback
away and nothing ever called ``wait()``/``poll()``, so the exit code went with
it.  Most of ``critic_retro.main()`` runs outside its only try/except, so an
exception anywhere in it killed the run before the retro file was written --
leaving no retro, no changelog entry, no ``auto_apply_error`` and no bus event.
The single observable difference from a healthy cycle that found nothing was a
MISSING file in ``profiles/critic/workspace/retros/``, and nothing checked for
it.  One concrete instance was fixed on 2026-09-06 (a dict-valued
``payload.error``); that removed one trigger, not the silence.

So now: stdout+stderr go to a per-invocation log, the child is tracked, and
``poll()`` reaps finished children and emits AGENT_ERROR for a non-zero exit.
Reaping happens on EVERY poll rather than inside ``handle()`` -- ``handle()``
only runs when another AGENT_FAILURE_CLUSTER arrives, which can be days later.

Two halves, deliberately.  ``critic_retro.py`` announces crashes it can catch
itself (it has the traceback and the cluster context); this side is the
BACKSTOP for what a Python handler cannot see -- an import-time failure, a
SyntaxError, a hard kill, or a bus that was down when the script tried.  The
child prints ``CRITIC_RETRO_CRASH_ANNOUNCED`` to stderr only when its own emit
SUCCEEDED, and this side then stays quiet, so a crash pages exactly once.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from events.bus import EventBus
from events.schema import Event, EventType, Priority
from events.subscribers.base import BaseSubscriber
from hermes_constants import real_executable

logger = logging.getLogger(__name__)

# Default Critic retro script location.  Caller can override via
# ``critic_script_path`` (used by tests).
DEFAULT_CRITIC_SCRIPT = (
    Path.home() / ".hermes" / "profiles" / "critic" / "workspace" / "critic_retro.py"
)
DEFAULT_DEBOUNCE_SECONDS = 300

# Per-invocation stdout+stderr capture for spawned retros.  Kept only for a run
# that FAILED: a successful run's artifact is the retro file itself, and an
# unbounded log directory is its own operational problem.
DEFAULT_RETRO_LOG_DIR = Path.home() / ".hermes" / "logs" / "critic-retro"

# Ceiling on tracked children, so a pathological spawn rate cannot grow this
# list without bound.  Well above any realistic concurrency: retros take
# seconds and one cluster key is debounced for DEFAULT_DEBOUNCE_SECONDS.
MAX_TRACKED_RETROS = 32

# How much of the captured log rides along in the AGENT_ERROR payload.  Enough
# to name the exception without putting a whole traceback through Telegram.
LOG_TAIL_CHARS = 1200

# HANDSHAKE WITH THE OTHER HALF.  critic_retro.py prints this exact token to
# stderr -- and only when its OWN bus announcement succeeded -- so this
# subscriber can stay quiet instead of paging about the same crash twice.  The
# literal is duplicated rather than imported because the two files live in
# different repositories (~/.hermes vs ~/.hermes/agent-src).  Both sides pin it
# in a test; if you change it here, change
# profiles/critic/workspace/critic_retro.py:CRASH_ANNOUNCED_MARKER too.
CRASH_ANNOUNCED_MARKER = "CRITIC_RETRO_CRASH_ANNOUNCED"


class CriticSubscriber(BaseSubscriber):
    subscriber_id = "critic-trigger"
    poll_interval_seconds = 5
    event_types = [EventType.AGENT_FAILURE_CLUSTER]

    def __init__(
        self,
        bus: EventBus,
        critic_script_path: Optional[Path] = None,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
        retro_log_dir: Optional[Path] = None,
    ):
        super().__init__(bus)
        self.critic_script_path = Path(critic_script_path or DEFAULT_CRITIC_SCRIPT)
        self.debounce_seconds = debounce_seconds
        self.retro_log_dir = Path(retro_log_dir or DEFAULT_RETRO_LOG_DIR)
        # cluster_key -> monotonic timestamp of last invocation
        self._last_invoked: Dict[str, float] = {}
        # Spawned retros still running, reaped by poll().  Without this the
        # exit code is discarded and a crashed run is indistinguishable from a
        # quiet one -- see the module docstring.
        self._inflight: List[dict] = []

    def poll(self) -> int:
        """Reap finished retros, then process new events.

        Reaping belongs here, not in handle(): handle() only runs when another
        AGENT_FAILURE_CLUSTER arrives, and clusters can be days apart, so a
        crash would sit unreported until the next one.  poll() runs every
        poll_interval_seconds regardless.  Guarded so a reaping bug can never
        stop the subscriber consuming events.
        """
        try:
            self._reap_finished_retros()
        except Exception:
            logger.exception("CriticSubscriber: reaping spawned retros failed")
        return super().poll()

    def _reap_finished_retros(self) -> None:
        """Emit AGENT_ERROR for every tracked retro that exited non-zero."""
        if not self._inflight:
            return
        still_running: List[dict] = []
        for rec in self._inflight:
            try:
                rc = rec["proc"].poll()
            except Exception:
                logger.exception(
                    "CriticSubscriber: could not poll retro for %s",
                    rec.get("cluster_key"),
                )
                continue  # unpollable handle: nothing to judge, stop tracking
            if rc is None:
                still_running.append(rec)
                continue
            if not isinstance(rc, int):
                # A real Popen.returncode is int or None.  Anything else is a
                # test double; judging it would invent a failure.
                continue
            if rc == 0:
                self._discard_log(rec)
                continue
            try:
                self._announce_retro_failure(rec, rc)
            except Exception:
                logger.exception(
                    "CriticSubscriber: failed to announce retro exit %s for %s",
                    rc, rec.get("cluster_key"),
                )
        self._inflight = still_running

    def _read_log_tail(self, log_path: Optional[Path]) -> str:
        if log_path is None:
            return ""
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL_CHARS:]
        except OSError:
            return ""

    def _discard_log(self, rec: dict) -> None:
        """A successful run's artifact is the retro file; drop its log."""
        log_path = rec.get("log_path")
        if log_path is None:
            return
        try:
            Path(log_path).unlink()
        except OSError:
            pass

    def _announce_retro_failure(self, rec: dict, returncode: int) -> bool:
        """Put a crashed retro on the bus.  Returns whether it emitted.

        Stays quiet when the child already announced its own crash (it prints
        CRASH_ANNOUNCED_MARKER only after a SUCCESSFUL emit), so one crash pages
        once.  When the marker is absent -- an import-time failure, a hard kill,
        or a bus that was down for the child -- this is the only announcement
        there will be, and the log file is kept as the diagnosable artifact.
        """
        tail = self._read_log_tail(rec.get("log_path"))
        if CRASH_ANNOUNCED_MARKER in tail:
            logger.warning(
                "CriticSubscriber: retro for %s exited %s (already announced "
                "by the child); log %s",
                rec.get("cluster_key"), returncode, rec.get("log_path"),
            )
            return False
        logger.error(
            "CriticSubscriber: retro for %s exited %s; log %s",
            rec.get("cluster_key"), returncode, rec.get("log_path"),
        )
        self.bus.emit(
            event_type=EventType.AGENT_ERROR,
            source="critic-retro",
            payload={
                "error": (
                    f"critic_retro exited {returncode} for cluster "
                    f"{rec.get('cluster_key')} without announcing a crash"
                ),
                "returncode": returncode,
                "cluster": rec.get("cluster_key"),
                "log": str(rec.get("log_path")) if rec.get("log_path") else None,
                "log_tail": tail,
            },
            priority=Priority.HIGH,
        )
        return True

    def _open_retro_log(self, cluster_key: str):
        """Return (path, write-handle) for this invocation's capture file.

        (None, None) when the directory is unusable -- capture is an
        improvement on discarding output, never a reason not to run the retro.
        """
        try:
            self.retro_log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
            safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in cluster_key)
            path = self.retro_log_dir / f"{stamp}_{safe}.log"
            return path, open(path, "wb")
        except OSError:
            logger.warning(
                "CriticSubscriber: cannot capture retro output under %s",
                self.retro_log_dir, exc_info=True,
            )
            return None, None

    def handle(self, event: Event) -> None:
        source = event.payload.get("source") or event.source
        failure_type = event.payload.get("failure_type", "unknown")
        cluster_key = f"{source}:{failure_type}"

        now = time.monotonic()
        prev = self._last_invoked.get(cluster_key)
        if prev is not None and (now - prev) < self.debounce_seconds:
            logger.info(
                "CriticSubscriber: debounced cluster %s (last invoked %ds ago)",
                cluster_key, int(now - prev),
            )
            return

        if not self.critic_script_path.exists():
            logger.warning(
                "CriticSubscriber: critic_retro.py not found at %s — skipping",
                self.critic_script_path,
            )
            return

        cmd: List[str] = [
            real_executable(),
            str(self.critic_script_path),
            "--cluster",
            f"agent={source},type={failure_type}",
        ]
        log_path, log_handle = self._open_retro_log(cluster_key)
        try:
            # Non-blocking subprocess (NOT fully detached on Windows).
            # Popen returns immediately; poll() reaps the exit code later.
            #
            # stdout and stderr are captured to log_path rather than discarded.
            # Discarding them is what made a crashed retro invisible: the
            # traceback went to DEVNULL and the exit code was never read.
            #
            # Windows caveat: without creationflags=DETACHED_PROCESS|
            # CREATE_NEW_PROCESS_GROUP the child inherits the gateway's
            # Job Object, so a gateway kill terminates an in-flight Critic
            # retro. Acceptable for v1 — retros are idempotent and the
            # next cluster event will re-trigger. Promote to true detach
            # in v2 if retro loss is observed in production.
            proc = subprocess.Popen(
                cmd,
                stdout=log_handle or subprocess.DEVNULL,
                stderr=subprocess.STDOUT if log_handle else subprocess.DEVNULL,
                close_fds=True,
            )
            self._last_invoked[cluster_key] = now
            self._inflight.append({
                "proc": proc,
                "cluster_key": cluster_key,
                "log_path": log_path,
                "spawned_at": now,
            })
            if len(self._inflight) > MAX_TRACKED_RETROS:
                del self._inflight[:-MAX_TRACKED_RETROS]
            logger.info(
                "CriticSubscriber: invoked Critic for cluster %s (log %s)",
                cluster_key, log_path,
            )
        except OSError as e:
            logger.exception(
                "CriticSubscriber: failed to spawn Critic for %s: %s",
                cluster_key, e,
            )
            # Do NOT re-raise — base subscriber would count it toward the
            # circuit breaker.  Subprocess spawn failure is observable via
            # the log; the next cluster event will retry.
        finally:
            # The child holds its own duplicate of the handle; the parent must
            # let go or the log file stays open for the gateway's lifetime.
            if log_handle is not None:
                try:
                    log_handle.close()
                except OSError:
                    pass
