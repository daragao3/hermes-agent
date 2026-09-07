from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping

from .models import Provider, canonical_session_id

_VISIBILITY_ORIGIN_PREFIX = "claude-visibility:"
_BACKUP_MARKERS = (".junction-backup", ".real-", "recovery-backup")
_REPLACE_ATTEMPTS = 3
_REPLACE_RETRY_SECONDS = 0.05
_CLI_SESSION_ID_PATTERN = re.compile(r'"cliSessionId"\s*:\s*"([^"]+)"')
# Sources active within this window register UNARCHIVED so live cross-harness
# work surfaces directly in the desktop sidebar; anything older is historical
# backfill and lands archived (an unarchived default once buried the user's
# real sidebar under thousands of visible imports).
_RECENT_UNARCHIVED_SECONDS = 3 * 86_400
# cliSessionIds this worker has already auto-archived. Read and written whole,
# exactly like the auto-dismiss lane's state key.
#
# It exists to make auto-archiving happen AT MOST ONCE per record, which is what
# keeps this axis compatible with the invariant
# test_float_update_preserves_manual_unarchive pins: an operator's unarchived
# state must survive later cycles. Without the ledger a human who unarchives an
# idle mirror would simply lose it again on the next pass, and the worker would
# be fighting the user rather than tidying up after itself.
_MIRROR_AUTO_ARCHIVE_STATE_KEY = "session-bridge:claude-visibility:mirror-auto-archive"


def default_ccd_sessions_base() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Claude" / "claude-code-sessions"


def discover_ccd_registry_root(base: Path | None) -> Path | None:
    """Locate the desktop app's session-registry leaf directory.

    The registry lives two opaque scope levels below ``claude-code-sessions``.
    Prefer the leaf that already holds ``local_*.json`` records; fall back to
    a sole leaf directory; refuse to guess when ambiguous.
    """
    if base is None or not base.is_dir():
        return None
    leaves = [path for path in base.glob("*/*") if path.is_dir()]
    scored = sorted(
        ((len(list(leaf.glob("local_*.json"))), str(leaf), leaf) for leaf in leaves),
        reverse=True,
    )
    populated = [entry for entry in scored if entry[0] > 0]
    if populated:
        return populated[0][2]
    if len(leaves) == 1:
        return leaves[0]
    return None


def _ccd_user_data_dirs() -> tuple[Path, ...]:
    """Every Claude Code desktop userData dir this machine may run against.

    The subscription harness and the third-party/gateway harness are two modes
    of the same installed app, each with its own userData dir AND its own signed
    in account, so neither one's sidebar can ever show the other's records.
    """
    dirs: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(Path(appdata) / "Claude")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        dirs.append(Path(local_appdata) / "Claude-3p")
    return tuple(dirs)


def _account_uuid(user_data_dir: Path) -> str | None:
    try:
        raw = (user_data_dir / "config.json").read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("lastKnownAccountUuid") if isinstance(data, Mapping) else None
    return value if isinstance(value, str) and value else None


def _has_backup_marker(path: Path) -> bool:
    name = path.name.casefold()
    return any(marker.casefold() in name for marker in _BACKUP_MARKERS)


def _is_reparse_point(path: Path) -> bool:
    """Check the Windows reparse attribute without following the target."""
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return path.is_symlink()
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _resolved_key(path: Path) -> str:
    try:
        path = path.resolve()
    except OSError:
        pass
    return os.path.normcase(str(path))


def _regular_registry_record_count(root: Path) -> int:
    try:
        return sum(
            1
            for entry in os.scandir(root)
            if entry.name.startswith("local_")
            and entry.name.endswith(".json")
            and entry.is_file(follow_symlinks=False)
        )
    except OSError:
        return 0


def discover_ccd_registry_roots(
    user_data_dirs: Iterable[Path] | None = None,
) -> tuple[Path, ...]:
    """Resolve one live registry leaf per desktop harness.

    Selection is anchored on ``config.json``'s ``lastKnownAccountUuid`` rather
    than "the most populated leaf". The third-party store on this machine holds
    ``.junction-backup-*`` siblings that junction back into the subscription
    store and therefore contain MORE records than the harness's own real
    directory -- a population ranking silently resolves to the wrong harness.
    Rotated/backup siblings are excluded by name, and roots are de-duplicated by
    resolved path so a junctioned harness is written exactly once.
    """
    candidates = (
        tuple(user_data_dirs) if user_data_dirs is not None else _ccd_user_data_dirs()
    )
    roots: list[Path] = []
    seen: set[str] = set()
    for user_data_dir in candidates:
        account = _account_uuid(user_data_dir)
        if not account:
            continue
        account_dir = user_data_dir / "claude-code-sessions" / account
        if not account_dir.is_dir():
            continue
        leaves = [
            leaf
            for leaf in account_dir.iterdir()
            if leaf.is_dir() and not _has_backup_marker(leaf)
        ]
        if not leaves:
            continue
        leaf = max(leaves, key=lambda path: len(list(path.glob("local_*.json"))))
        key = _resolved_key(leaf)
        if key in seen:
            continue
        seen.add(key)
        roots.append(leaf)
    return tuple(roots)


def discover_ccd_convergence_roots(
    user_data_dirs: Iterable[Path] | None = None,
) -> tuple[Path, ...]:
    """Resolve every populated real account leaf whose policy should converge."""
    candidates = (
        tuple(user_data_dirs) if user_data_dirs is not None else _ccd_user_data_dirs()
    )
    accepted: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for user_data_dir in candidates:
        sessions = user_data_dir / "claude-code-sessions"
        try:
            accounts = sorted(sessions.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            continue
        for account in accounts:
            if (
                _has_backup_marker(account)
                or _is_reparse_point(account)
                or not account.is_dir()
            ):
                continue
            try:
                leaves = sorted(
                    account.iterdir(), key=lambda path: path.name.casefold()
                )
            except OSError:
                continue
            for leaf in leaves:
                if (
                    _has_backup_marker(leaf)
                    or _is_reparse_point(leaf)
                    or not leaf.is_dir()
                    or _regular_registry_record_count(leaf) == 0
                ):
                    continue
                key = _resolved_key(leaf)
                if key in seen:
                    continue
                seen.add(key)
                accepted.append((key, leaf))
    accepted.sort(key=lambda entry: entry[0])
    return tuple(leaf for _key, leaf in accepted)


def _temporary_record_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


def _serialized_record(record: Mapping[str, Any]) -> bytes:
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


def _atomic_write_record(path: Path, record: Mapping[str, Any]) -> None:
    temporary = _temporary_record_path(path)
    temporary.write_bytes(_serialized_record(record))
    last_error: OSError | None = None
    try:
        for _attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(_REPLACE_RETRY_SECONDS)
    finally:
        temporary.unlink(missing_ok=True)
    raise last_error if last_error is not None else OSError("replace failed")


def _publish_record_create_only(path: Path, record: Mapping[str, Any]) -> bool:
    """Atomically publish a complete record only while its name is absent."""
    temporary = _temporary_record_path(path)
    temporary.write_bytes(_serialized_record(record))
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


class _RecordWriteConflict(Exception):
    """The live record changed during every bounded update attempt."""


def _optimistic_transform_record(
    path: Path,
    transform: Callable[[MutableMapping[str, Any]], bool],
) -> bool:
    """Best-effort fresh-byte update; never knowingly replaces changed bytes."""
    for _attempt in range(_REPLACE_ATTEMPTS):
        original = path.read_bytes()
        try:
            parsed = json.loads(original.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("registry record unreadable") from None
        if not isinstance(parsed, dict):
            raise ValueError("registry record is not an object")
        if not transform(parsed):
            return False
        temporary = _temporary_record_path(path)
        temporary.write_bytes(_serialized_record(parsed))
        try:
            if path.read_bytes() != original:
                continue
            os.replace(temporary, path)
            return True
        finally:
            temporary.unlink(missing_ok=True)
    raise _RecordWriteConflict


class _MirrorFloatSkip(Exception):
    """Internal: this mirror cannot be floated safely; count it as skipped."""


class ClaudeMirrorFloatWorker:
    """Surface Claude visibility mirrors in the desktop app and float them.

    The Claude Code desktop sidebar lists its own session registry (one
    ``local_*.json`` record per session, linked to the transcript by
    ``cliSessionId``) — not the raw ``~/.claude/projects`` transcripts — so a
    CLI-registered visibility mirror is invisible there until a registry
    record exists. This worker, for every visible mirror:

    - writes a registry record if none references the mirror's Claude UUID
      (idempotent; the desktop discovers new records live, within minutes,
      no relaunch required), and
    - floats both the transcript file mtime (CLI resume picker ordering) and
      the record's ``lastActivityAt`` (desktop sidebar ordering) to the
      source session's ``last_active``.

    Setting times to the source activity (never "now") keeps repeated cycles
    idempotent; the minimum interval bounds write churn for continuously
    active sources. Only marker-owned visibility mirrors are ever touched,
    and every per-mirror failure is contained as a skip.

    ``isArchived`` propagation is LAZY: the desktop app discovers new
    records within minutes, but re-reads edited records on its own
    schedule — observed up to ~30 minutes behind, and an app restart alone
    does not force it (measured 2026-08-23: a 17:38 file edit still read
    stale at 22:47, live by 23:14). Get the flag right at creation; a
    post-hoc edit does propagate, but slowly and unsuitably for anything
    interactive. Bulk post-hoc flips also resurface LEGACY duplicate
    records (random pre-deterministic ids sharing one cliSessionId), so
    prefer creation-time correctness over store surgery.
    """

    def __init__(
        self,
        store: Any,
        *,
        min_interval_seconds: float = 900.0,
        registry_root: Path | None = None,
        registry_roots: Iterable[Path] | None = None,
        id_factory: Callable[[], str] | None = None,
        run_min_interval_seconds: float = 300.0,
        archive_idle_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        interval = float(min_interval_seconds)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("min_interval_seconds must be finite and positive")
        archive_idle: float | None = None
        if archive_idle_seconds is not None:
            archive_idle = float(archive_idle_seconds)
            if not math.isfinite(archive_idle) or archive_idle <= 0:
                raise ValueError(
                    "archive_idle_seconds must be finite and positive, or None "
                    "to leave the axis off"
                )
        run_interval = float(run_min_interval_seconds)
        if not math.isfinite(run_interval) or run_interval < 0:
            raise ValueError("run_min_interval_seconds must be finite and non-negative")
        if registry_root is not None and not isinstance(registry_root, Path):
            raise TypeError("registry_root must be a Path or None")
        roots: list[Path] = []
        if registry_root is not None:
            roots.append(registry_root)
        for root in registry_roots or ():
            if not isinstance(root, Path):
                raise TypeError("registry_roots must contain Path entries")
            if root not in roots:
                roots.append(root)
        self._store = store
        self._min_interval_seconds = interval
        self._registry_roots = tuple(roots)
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._run_min_interval_seconds = run_interval
        self._archive_idle_seconds = archive_idle
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._last_run_at: float | None = None

    def run_once(self) -> dict[str, int]:
        now = self._monotonic()
        if (
            self._last_run_at is not None
            and now - self._last_run_at < self._run_min_interval_seconds
        ):
            return {
                "examined": 0,
                "floated": 0,
                "skipped": 0,
                "registered": 0,
                "archived": 0,
                "throttled": 1,
            }
        self._last_run_at = now
        examined = floated = skipped = registered = archived = 0
        registry_index = self._load_registry_index()
        already_archived = self._load_auto_archived_ids()
        newly_archived: set[str] = set()
        live_ids: set[str] = set()
        for row in self._store.list_visible_claude_visibility_mirrors():
            examined += 1
            try:
                live_ids.add(str(row["claude_uuid"]))
            except (KeyError, TypeError):
                pass
            try:
                mirror_floated, mirror_registered, mirror_archived = self._float_one(
                    row, registry_index, already_archived, newly_archived
                )
            except (
                _MirrorFloatSkip,
                _RecordWriteConflict,
                OSError,
                TypeError,
                ValueError,
                KeyError,
            ):
                skipped += 1
                continue
            floated += int(mirror_floated)
            registered += int(mirror_registered)
            archived += int(mirror_archived)
        if newly_archived:
            # Prune to mirrors still visible: a record that has left the visible
            # set can no longer be archived by this worker, so remembering it
            # only grows the key. Pruned against live_ids rather than against
            # the ids examined WITHOUT error, so a mirror that merely skipped
            # this cycle keeps its entry and is not re-archived later.
            # Stored as a MAPPING because set_state refuses anything else; the
            # value carries the reason so the key reads like the auto-dismiss
            # one rather than an opaque id list.
            self._store.set_state(
                _MIRROR_AUTO_ARCHIVE_STATE_KEY,
                {
                    claude_uuid: "auto_archived"
                    for claude_uuid in sorted(
                        (already_archived | newly_archived) & live_ids
                    )
                },
            )
        return {
            "examined": examined,
            "floated": floated,
            "skipped": skipped,
            "registered": registered,
            "archived": archived,
            "throttled": 0,
        }

    def _load_auto_archived_ids(self) -> set[str]:
        """cliSessionIds already auto-archived once; unreadable state = empty.

        An unreadable ledger reads as "nothing archived yet", which is the
        FORGIVING direction here and deliberately so: the worst case is that one
        idle mirror is archived a second time after an operator revived it,
        which they can undo. The alternative default -- treating an unreadable
        ledger as "everything already archived" -- would silently disable the
        axis, which is the failure this whole change exists to end.
        """

        if self._archive_idle_seconds is None:
            return set()
        try:
            stored = self._store.get_state(_MIRROR_AUTO_ARCHIVE_STATE_KEY)
        except Exception:
            return set()
        if not isinstance(stored, Mapping):
            return set()
        return {entry for entry in stored if isinstance(entry, str)}

    def _float_one(
        self,
        row: Mapping[str, Any],
        registry_index: dict[str, Path],
        already_archived: frozenset[str] | set[str] = frozenset(),
        newly_archived: set[str] | None = None,
    ) -> tuple[bool, bool, bool]:
        claude_uuid = str(row["claude_uuid"])
        # _resolve_source_activity RAISES _MirrorFloatSkip when the source's
        # activity is unavailable, so an unknown-liveness mirror is skipped
        # before any archive decision is reached. That is the fail-CLOSED
        # direction, and it is the property that keeps this axis honest: we
        # archive on a positive measurement of idleness, never on the absence
        # of evidence of life.
        activity = self._resolve_source_activity(str(row["source_session_id"]))
        canonical_id = canonical_session_id(Provider.CLAUDE, claude_uuid)
        mirror = self._store.get_external_session(canonical_id)
        if not isinstance(mirror, Mapping):
            raise _MirrorFloatSkip("mirror catalog row missing")
        origin_bridge_id = mirror.get("origin_bridge_id")
        if not (
            isinstance(origin_bridge_id, str)
            and origin_bridge_id.startswith(_VISIBILITY_ORIGIN_PREFIX)
        ):
            raise _MirrorFloatSkip("mirror is not a visibility mirror")
        native_path = mirror.get("native_path")
        if not isinstance(native_path, str) or not native_path:
            raise _MirrorFloatSkip("mirror has no native path")

        floated = False
        mtime = os.stat(native_path).st_mtime
        if activity - mtime >= self._min_interval_seconds:
            os.utime(native_path, (activity, activity))
            floated = True

        registered = False
        archived = False
        if self._registry_roots:
            registered, record_floated, archived = self._ensure_registry_record(
                canonical_id,
                claude_uuid,
                activity,
                registry_index,
                already_archived,
                newly_archived,
            )
            floated = floated or record_floated
        return floated, registered, archived

    @property
    def _registry_root(self) -> Path | None:
        """Back-compat accessor: the primary harness registry root."""
        return self._registry_roots[0] if self._registry_roots else None

    def _ensure_registry_record(
        self,
        canonical_id: str,
        claude_uuid: str,
        activity: float,
        registry_index: dict[Path, dict[str, Path]],
        already_archived: frozenset[str] | set[str] = frozenset(),
        newly_archived: set[str] | None = None,
    ) -> tuple[bool, bool, bool]:
        activity_ms = int(activity * 1000)
        session_row: Mapping[str, Any] | None = None
        registered = False
        floated = False
        archived = False
        # Same rule the creation branch below applies via
        # _RECENT_UNARCHIVED_SECONDS, only evaluated on EVERY cycle instead of
        # once. A mirror registered while its source was active previously kept
        # its unarchived flag forever, because nothing re-ran the decision --
        # IdleChipArchiveWorker skips mirrors by design (they belong to this
        # worker), so the sidebar grew until a human swept it by hand.
        archive_floor: float | None = None
        if self._archive_idle_seconds is not None:
            archive_floor = self._wall_clock() - self._archive_idle_seconds
        # Deterministic record id derived from the session's own Claude UUID so
        # every harness store holds the SAME record id for one logical session.
        # A per-harness random id produced cross-harness duplicates once the
        # account union sync spread both variants into every store.
        if session_row is None:
            session_row = self._store.db.get_session(canonical_id) or {}
        record_id = f"local_{claude_uuid}"
        for root in self._registry_roots:
            index = registry_index.setdefault(root, {})
            existing = index.get(claude_uuid)
            if existing is None:
                title = (
                    session_row.get("title")
                    or f"[Bridge] {session_row.get('cwd') or 'untitled session'}"
                )
                cwd = session_row.get("cwd") or ""
                started_at = session_row.get("started_at")
                created_ms = (
                    int(float(started_at) * 1000)
                    if isinstance(started_at, (int, float))
                    and not isinstance(started_at, bool)
                    and math.isfinite(float(started_at))
                    else activity_ms
                )
                record = {
                    "sessionId": record_id,
                    "cliSessionId": claude_uuid,
                    "cwd": cwd,
                    "originCwd": cwd,
                    "createdAt": created_ms,
                    "lastActivityAt": activity_ms,
                    "model": session_row.get("model") or "claude-fable-5",
                    # Recently active sources surface unarchived; historical
                    # backfill lands archived (see _RECENT_UNARCHIVED_SECONDS).
                    "isArchived": (
                        self._wall_clock() - activity > _RECENT_UNARCHIVED_SECONDS
                    ),
                    "title": title,
                    "permissionMode": "default",
                    "alwaysAllowedReasons": [],
                    "sessionPermissionUpdates": [],
                }
                path = root / f"{record_id}.json"
                published = self._publish_record(path, record)
                if path.exists():
                    index[claude_uuid] = path
                registered = registered or published
                continue

            archive_due = (
                archive_floor is not None
                and claude_uuid not in already_archived
                and activity <= archive_floor
            )
            outcome = {"floated": False, "archived": False}

            def settle(record: MutableMapping[str, Any]) -> bool:
                changed = False
                recorded_ms = record.get("lastActivityAt")
                if (
                    not isinstance(recorded_ms, (int, float))
                    or isinstance(recorded_ms, bool)
                    or not math.isfinite(float(recorded_ms))
                ):
                    recorded_ms = 0
                if (
                    activity_ms - float(recorded_ms)
                    >= self._min_interval_seconds * 1000
                ):
                    record["lastActivityAt"] = activity_ms
                    outcome["floated"] = True
                    changed = True
                if archive_due and not record.get("isArchived"):
                    # Re-read liveness from the record INSIDE the transform
                    # rather than trusting the sample taken before it. The
                    # desktop app stamps lastActivityAt when a session is
                    # actually used, so a record fresher than the floor is
                    # evidence of life that post-dates our source reading, and
                    # archiving on a stale sample is exactly the mistake that
                    # hid 16 live sessions in the 2026-08-24 sweep.
                    current_ms = record.get("lastActivityAt")
                    if not (
                        isinstance(current_ms, (int, float))
                        and not isinstance(current_ms, bool)
                        and math.isfinite(float(current_ms))
                        and float(current_ms) / 1000.0 > archive_floor
                    ):
                        record["isArchived"] = True
                        outcome["archived"] = True
                        changed = True
                return changed

            if not _optimistic_transform_record(existing, settle):
                # False means either no update was due or every fresh-byte retry
                # conflicted. In both cases the current target remains authoritative.
                continue
            floated = floated or bool(outcome["floated"])
            if outcome["archived"]:
                archived = True
                if newly_archived is not None:
                    newly_archived.add(claude_uuid)
        return registered, floated, archived

    def _publish_record(self, path: Path, record: Mapping[str, Any]) -> bool:
        return _publish_record_create_only(path, record)

    def _load_registry_index(self) -> dict[Path, dict[str, Path]]:
        indexes: dict[Path, dict[str, Path]] = {}
        for root in self._registry_roots:
            index: dict[str, Path] = {}
            if root.is_dir():
                for path in root.glob("local_*.json"):
                    try:
                        match = _CLI_SESSION_ID_PATTERN.search(
                            path.read_text(encoding="utf-8")
                        )
                    except OSError:
                        continue
                    if match:
                        index[match.group(1)] = path
            indexes[root] = index
        return indexes

    def _resolve_source_activity(self, source_session_id: str) -> float:
        if ":" in source_session_id:
            # External (codex/claude) sources carry an indexed watermark.
            activity = self._store.get_external_activity(source_session_id)
        else:
            # Hermes sources are host-native rows in the local SessionDB.
            activity = self._hermes_last_active(source_session_id)
        if (
            not isinstance(activity, (int, float))
            or isinstance(activity, bool)
            or not math.isfinite(float(activity))
        ):
            raise _MirrorFloatSkip("source activity unavailable")
        return float(activity)

    def _hermes_last_active(self, source_session_id: str) -> float | None:
        rows = self._store.db.list_sessions_rich(
            id_query=source_session_id, limit=5, min_message_count=0
        )
        for row in rows:
            if row.get("id") == source_session_id:
                return row.get("last_active")
        return None


# Mirror records ([Codex]/[Hermes]/[Bridge]) are owned by the recency rule
# above and must never be re-archived here.
_MIRROR_TAG_PATTERN = re.compile(r"^\[(codex|hermes|bridge)\]", re.IGNORECASE)
# Chip briefs run in agent worktrees or Hermes profile workspaces.
_AUTOMATION_CWD_PATTERN = re.compile(
    r"([\\/]\.claude[\\/]worktrees[\\/]|[\\/]\.hermes[\\/]profiles[\\/])",
    re.IGNORECASE,
)
# First words of chip titles (imperative briefs). Deliberately conservative:
# a bypassPermissions session whose title starts outside this set is treated
# as the user's unless its cwd is an automation workspace.
# Scheduled-task fires are the OTHER automation shape, and they are invisible to
# both tests above by construction: the task runs in a REPO ROOT (no worktree, no
# profile path) and the app titles the session from the taskId, so the first word
# is a noun ("Capone ...", "Financier ...", "Fleet ..."), never an imperative verb.
# Measured 2026-09-02 over the live convergence store: _is_chip() was False on
# 7/7 unarchived scheduledTaskId records, while every one of them DID carry
# bypassPermissions. Each fire strands a record that never exits -- one task on a
# `15 1,4,7,10,13,16,19,22 * * *` cron is eight stranded records a day, and
# fifa-kickoff reached 78 before a one-off hand sweep on 2026-08-23 cleared them.
_SCHEDULED_TASK_FIELD = "scheduledTaskId"
_KIND_CHIP = "chip"
_KIND_TASK = "task"
# A record the harness marked as errored is left for a human: an errored fire is
# the shape most likely to have ended BLOCKED or without writing its capture, and
# those are exactly the records that must stay visible in the sidebar.
_ERROR_FIELDS = ("error", "errorAt")
# Open-loop claim registry. A session holding an OPEN claim is still on the hook
# for that target however idle it looks, so its record must stay visible.
_CLAIM_HOLDER_PREFIX = "ccd:"
_CLOSED_CLAIM_STATUSES = frozenset({"done", "closed"})


def default_loops_registry_path() -> Path:
    return Path.home() / ".hermes" / "loops" / "claims.json"


def read_open_claim_session_ids(path: Path) -> frozenset[str] | None:
    """Session ids holding an OPEN loops claim, or ``None`` if unreadable.

    ``None`` is NOT "no claims" — it is "the registry could not be read", and the
    caller must treat it the way ``loops.py check`` treats its exit 4: an
    unreadable registry is not a green gate, because holders may be invisible
    rather than absent. That distinction is the whole reason this returns an
    Optional instead of an empty set: on 2026-08-19 an unreadable registry read
    as EMPTY and a session then wrote its one record over five live claims.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(document, list):
        return None
    session_ids: set[str] = set()
    for row in document:
        if not isinstance(row, Mapping):
            return None
        if str(row.get("status", "")).lower() in _CLOSED_CLAIM_STATUSES:
            continue
        holders = row.get("holders")
        if not isinstance(holders, list):
            continue
        for holder in holders:
            session = holder.get("session") if isinstance(holder, Mapping) else None
            # `pid:<n>` holders name no session and are correctly ignored: a pid
            # is dead by the time anyone reads it and the number gets reused.
            if isinstance(session, str) and session.startswith(_CLAIM_HOLDER_PREFIX):
                session_ids.add(session[len(_CLAIM_HOLDER_PREFIX) :])
    return frozenset(session_ids)


# --- Capture observation (OBSERVE ONLY -- never gates an archive) -------------
#
# A scheduled-task fire can finish cleanly, report well, and write NOTHING
# durable: local_146a4406 "Applier gemini recheck read 20260824" made seven tool
# calls, all Bash/PowerShell, and no MemPalace or GBrain write. Measured
# 2026-09-03 over the 25 task records inside the 14-day scan window: 10 wrote a
# capture, 15 did not (6 of those made zero tool calls -- timing-gate stand-downs
# and errored fires, which have nothing to capture by construction).
#
# THIS IS DELIBERATELY NOT A GATE. Refusing to archive a capture-less record
# would strand 15 of 25 -- reopening the leak IdleChipArchiveWorker exists to
# close, and hitting hardest the fires that correctly did nothing. Diego's call,
# 2026-09-03. The observation exists so the source-side fix (the scheduled-task
# capture reminder hook) has a falsifier, not so the reaper can second-guess it.
#
# THE TRAP, measured: a SUBSTRING search of a transcript for capture tool names
# is a false positive on EVERY session on this host. Claude Code attaches the
# full MCP tool roster to the transcript, so "mempalace_add_drawer" appears
# verbatim in a session that never called it -- the proven capture-less session
# above greps as one hit. It fails toward "captured, safe to archive", which is
# the wrong direction. Parse `tool_use` blocks; never grep.
_CAPTURE_TOOL_BASENAMES = frozenset(
    {
        # MemPalace durable writes. Deletes and reconnects are not captures.
        "mempalace_add_drawer",
        "mempalace_update_drawer",
        "mempalace_diary_write",
        "mempalace_kg_add",
        # GBrain durable writes. Reads, reverts and restores are not captures.
        "put_page",
        "put_page_conditional",
        "add_timeline_entry",
        "add_link",
    }
)
_MCP_TOOL_PREFIX = "mcp__"


def default_claude_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def default_capture_miss_log_path() -> Path:
    return Path.home() / ".hermes" / "logs" / "task-session-capture-misses.jsonl"


def _project_slug(cwd: str) -> str:
    """Claude Code's per-project transcript directory name for ``cwd``.

    Every character that is not alphanumeric becomes ``-``, so
    ``C:\\Users\\diego\\.hermes`` becomes ``C--Users-diego--hermes``.
    """
    return "".join(ch if ch.isalnum() else "-" for ch in cwd)


def transcript_path_for(
    data: Mapping[str, Any],
    *,
    projects_root: Path,
) -> Path | None:
    """Locate a registry record's CLI transcript, or ``None``.

    Resolves the ``cwd`` slug first (O(1)) and falls back to a glob across
    project directories, because a session's transcript follows the cwd it
    STARTED in and a record's ``cwd`` can be rewritten afterwards.
    """
    cli_session_id = data.get("cliSessionId")
    if not isinstance(cli_session_id, str) or not cli_session_id:
        return None
    if "/" in cli_session_id or "\\" in cli_session_id or cli_session_id == "..":
        return None
    for field in ("cwd", "originCwd"):
        value = data.get(field)
        if not isinstance(value, str) or not value:
            continue
        candidate = projects_root / _project_slug(value) / f"{cli_session_id}.jsonl"
        if candidate.is_file():
            return candidate
    try:
        for candidate in projects_root.glob(f"*/{cli_session_id}.jsonl"):
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def transcript_wrote_capture(path: Path) -> bool | None:
    """Did this transcript contain a durable memory write?

    ``True``/``False`` on a readable transcript, ``None`` when it could not be
    read -- unknown is not "no", exactly as an unreadable claim registry is not
    "no claims". Returns as soon as the first capture call is seen.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                # PERFORMANCE ONLY -- removing this line changes no verdict, and
                # a mutation run confirmed it (the suite stayed green without
                # it). What defeats the roster false positive is the tool-NAME
                # check below, never this pre-filter: the roster attachment has
                # no tool_use block, so parsing it in full also yields nothing.
                # Do not read this line as the guard.
                if '"tool_use"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, Mapping):
                    continue
                message = entry.get("message")
                content = message.get("content") if isinstance(message, Mapping) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, Mapping):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if not isinstance(name, str):
                        continue
                    basename = name
                    if name.startswith(_MCP_TOOL_PREFIX):
                        basename = name.rsplit("__", 1)[-1]
                    if basename in _CAPTURE_TOOL_BASENAMES:
                        return True
    except OSError:
        return None
    return False


class CaptureMissRecorder:
    """Append a line for each archived task record that wrote no capture.

    The coordinator DISCARDS ``run_once``'s return value, so counters alone
    surface nowhere: the durable leg is this file. One JSON object per line,
    append-only, never read back by the worker.

    Every failure is swallowed. Observation must never break archiving -- a
    reaper that dies because it could not write a log line is worse than the
    gap it is reporting on.
    """

    def __init__(
        self,
        log_path: Path,
        *,
        projects_root: Path | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._log_path = log_path
        self._projects_root = (
            default_claude_projects_root() if projects_root is None else projects_root
        )
        self._wall_clock = wall_clock

    def __call__(self, data: Mapping[str, Any]) -> bool | None:
        transcript = transcript_path_for(data, projects_root=self._projects_root)
        captured = (
            None if transcript is None else transcript_wrote_capture(transcript)
        )
        if captured is True:
            return True
        record = {
            "observedAt": self._wall_clock(),
            "sessionId": data.get("sessionId"),
            "cliSessionId": data.get("cliSessionId"),
            "scheduledTaskId": data.get(_SCHEDULED_TASK_FIELD),
            "title": data.get("title"),
            "transcript": None if transcript is None else str(transcript),
            "capture": "missing" if captured is False else "unknown",
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass
        return captured


_CHIP_TITLE_VERBS = frozenset(
    """
    add adjudicate amend answer apply archive attach audit auto-recover backfill
    bound bump cap capture check clean classify clear close commit compact compile
    confirm correct cut decide dedupe delete deploy deregister detect diagnose
    disable dismiss document drain eliminate emit enable enforce enrich escalate
    establish evaluate expire extend falsify-check find finish fix flush gate
    give guard harden hunt identify implement improve inspect install instrument
    integrate investigate isolate judge kill land limit lock make measure merge
    migrate monitor normalize observe patch pin plan probe protect prove prune
    publish purge quarantine quiet raise re-arm re-home re-land re-measure reap
    rebuild recheck reconcile record recover reduce refactor refresh register
    reindex relaunch release remove rename repair replace report requeue rerun
    rescan reschedule reset resolve restart restore resume retire retry review
    rewrite root-cause rotate route run save scan schedule scope seal search seed
    separate settle share ship silence simplify soak-verify stabilize stage
    standardize stop strip surface survey sweep switch sync teach teardown test
    throttle tighten trace track triage tune unarchive unblock unify unpin unstick
    unwedge update upgrade validate verify watch wire wrap write
    """.split()
)


class IdleChipArchiveWorker:
    """Archive idle automation-chip records in the CCD desktop registries.

    Every chip session started in the desktop app leaves an unarchived
    ``local_*.json`` record that the sidebar shows forever (20-45/day on this
    host), burying the user's own sessions. This worker archives a record only
    when ALL of these hold:

    - the record is unarchived and not a bridge mirror (``[Codex]``/
      ``[Hermes]``/``[Bridge]`` titles belong to the mirror recency rule);
    - it ran under ``bypassPermissions`` AND looks automation-shaped: an
      imperative chip-verb title, or an agent-worktree / Hermes-profile cwd
      (the user's own bypass sessions have conversational titles and live
      cwds, so they are spared), or it carries ``scheduledTaskId``;
    - it carries no ``error``/``errorAt`` mark -- an errored record is the
      shape most likely to have ended blocked on a human or without writing
      its capture, so it stays visible;
    - the SESSION has been idle past ``idle_seconds`` across every harness
      store copy. Liveness must span all roots read in the same pass: only
      the current-account store updates live, and a union-synced copy's
      stale ``lastActivityAt`` lies about a running session (that exact
      mistake archived 16 live sessions during the 2026-08-24 one-off sweep
      before its corrective pass).

    The scan is bounded by file mtime (``lookback_seconds``): any record
    still unarchived was written recently — by the app at activity or by
    this worker's own edits — so old untouched files need never be read and
    the per-cycle cost tracks recent activity, not store size. Archived
    records are left byte-identical apart from ``isArchived``; nothing is
    ever deleted, and ``run_min_interval_seconds`` throttles full passes.

    Scheduled-task records get their OWN idle window, ``task_idle_seconds``,
    and the axis is OFF (``None``) unless a caller opts in: nothing inherits a
    new reaping axis it did not ask for. A shorter window than the chip one is
    the point — a cron firing eight times a day accumulates eight records
    inside a single 24h chip window, so a window sized to "this fire is over"
    rather than "this chip is stale" is what actually bounds the population.

    A session holding an OPEN loops claim is never archived on the task axis:
    ``open_claim_session_ids`` supplies the holder set, and returning ``None``
    from it (an unreadable registry) stands the task axis DOWN for that pass.
    That is deliberately the same reading ``loops.py check`` gives its exit 4 —
    unreadable is not a green gate, because holders may be invisible rather
    than absent — and it degrades to the status quo (nothing retires task
    records), never past it. The guard is scoped to the TASK axis on purpose:
    making the CHIP lane fail closed on a file that is documented to VANISH on
    this host would silently stop archiving that already works.

    Capture state is OBSERVED, never gated. ``capture_observer`` is called
    after a task record is archived and its verdict is counted into
    ``task_archived_without_capture`` / ``task_archived_capture_unknown``; it
    cannot change the outcome. Measured 2026-09-03 over the 25 task records
    inside the scan window: 15 wrote no capture, 6 of them because they made
    zero tool calls at all. Gating on capture would strand all 15 forever,
    which is the leak this worker exists to close. The source-side fix is the
    scheduled-task capture reminder hook; this counter is its falsifier.

    KNOWN LIMITATION, accepted deliberately (Diego, 2026-09-02). This worker
    reads registry FILES, and pin state is not in them: the ``pinned`` key
    appears on 0 of 4,055 records in the live convergence store, because the
    desktop app holds pins in its own state. So a PINNED scheduled-task
    session would still be archived here. Judged acceptable because these
    records are machine-authored cron fires, archiving is reopenable from the
    Archived list, and a task record carries no ``worktreePath`` (measured:
    0 of 159), so archive cleanup has nothing to destroy. If pin state ever
    becomes file-readable, gate on it here.
    """

    def __init__(
        self,
        *,
        registry_roots: Iterable[Path],
        idle_seconds: float = 86_400.0,
        task_idle_seconds: float | None = None,
        open_claim_session_ids: Callable[[], frozenset[str] | None] | None = None,
        capture_observer: Callable[[Mapping[str, Any]], bool | None] | None = None,
        lookback_seconds: float = 14 * 86_400.0,
        run_min_interval_seconds: float = 3600.0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        roots = tuple(registry_roots)
        for root in roots:
            if not isinstance(root, Path):
                raise TypeError("registry_roots must contain Path entries")
        idle = float(idle_seconds)
        if not math.isfinite(idle) or idle <= 0:
            raise ValueError("idle_seconds must be finite and positive")
        task_idle: float | None = None
        if task_idle_seconds is not None:
            task_idle = float(task_idle_seconds)
            if not math.isfinite(task_idle) or task_idle <= 0:
                raise ValueError(
                    "task_idle_seconds must be finite and positive, or None to "
                    "leave scheduled-task records alone"
                )
        lookback = float(lookback_seconds)
        if not math.isfinite(lookback) or lookback <= 0:
            raise ValueError("lookback_seconds must be finite and positive")
        # The relation is checked against the WIDEST armed window, not just the
        # chip one: a task window wider than half the lookback would let task
        # records age out of the mtime-bounded scan before they ever qualify,
        # which reads as "the axis is on" while archiving nothing.
        widest_idle = idle if task_idle is None else max(idle, task_idle)
        if lookback <= widest_idle * 2:
            raise ValueError(
                "lookback_seconds must exceed twice the widest idle window "
                "(idle_seconds, task_idle_seconds); otherwise records age past "
                "the scan window before they qualify"
            )
        run_interval = float(run_min_interval_seconds)
        if not math.isfinite(run_interval) or run_interval < 0:
            raise ValueError("run_min_interval_seconds must be finite and non-negative")
        self._registry_roots = roots
        self._idle_seconds = idle
        self._task_idle_seconds = task_idle
        self._open_claim_session_ids = open_claim_session_ids
        self._capture_observer = capture_observer
        self._lookback_seconds = lookback
        self._run_min_interval_seconds = run_interval
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._last_run_at: float | None = None

    def run_once(self) -> dict[str, int]:
        now = self._monotonic()
        if (
            self._last_run_at is not None
            and now - self._last_run_at < self._run_min_interval_seconds
        ):
            return {
                "examined": 0,
                "archived": 0,
                "skipped": 0,
                "throttled": 1,
                "task_archived_without_capture": 0,
                "task_archived_capture_unknown": 0,
            }
        self._last_run_at = now

        wall_now = self._wall_clock()
        mtime_floor = wall_now - self._lookback_seconds
        examined = archived = skipped = 0
        task_no_capture = task_capture_unknown = 0

        records: list[tuple[Path, dict[str, Any], tuple[str, str]]] = []
        group_last_ms: dict[tuple[str, str], float] = {}
        group_paths: dict[tuple[str, str], list[Path]] = {}
        scan_complete = True
        for root in self._registry_roots:
            try:
                entries = list(os.scandir(root))
            except OSError:
                skipped += 1
                scan_complete = False
                continue
            for entry in entries:
                if not (
                    entry.name.startswith("local_") and entry.name.endswith(".json")
                ):
                    continue
                try:
                    if entry.stat().st_mtime < mtime_floor:
                        continue
                    data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    skipped += 1
                    scan_complete = False
                    continue
                if not isinstance(data, dict):
                    skipped += 1
                    scan_complete = False
                    continue
                examined += 1
                path = Path(entry.path)
                key = self._group_key(data, entry.name)
                records.append((path, data, key))
                group_paths.setdefault(key, []).append(path)
                activity = self._activity_ms(data)
                if activity is not None:
                    group_last_ms[key] = max(group_last_ms.get(key, activity), activity)

        if not scan_complete:
            return {
                "examined": examined,
                "archived": 0,
                "skipped": skipped,
                "throttled": 0,
                "task_archived_without_capture": 0,
                "task_archived_capture_unknown": 0,
            }

        task_axis = self._task_idle_seconds is not None
        claimed_session_ids: frozenset[str] = frozenset()
        if task_axis and self._open_claim_session_ids is not None:
            claimed = self._open_claim_session_ids()
            if claimed is None:
                # Unreadable registry: stand the task axis down for this pass
                # rather than archive past holders we simply cannot see. That
                # restores today's behaviour (nothing retires task records), so
                # a missing claims.json degrades to the status quo, never past it.
                task_axis = False
            else:
                claimed_session_ids = claimed
        idle_floor_by_kind = {
            _KIND_CHIP: (wall_now - self._idle_seconds) * 1000,
        }
        if task_axis and self._task_idle_seconds is not None:
            idle_floor_by_kind[_KIND_TASK] = (
                wall_now - self._task_idle_seconds
            ) * 1000
        for path, data, key in records:
            kind = self._record_kind(data, task_axis=task_axis)
            if data.get("isArchived") or kind not in idle_floor_by_kind:
                continue
            # Checked ONCE, here, and deliberately not repeated inside
            # archive_if_still_eligible. The other guards are re-checked at
            # write time because their inputs (isArchived, lastActivityAt) live
            # in files Desktop can rewrite mid-pass. This one cannot change:
            # claimed_session_ids is frozen for the pass, and _group_key already
            # rejects a record whose sessionId moved under us. A re-check here
            # would be unreachable-by-construction code shaped like a guard.
            if self._holds_open_claim(data, claimed_session_ids):
                continue
            idle_floor_ms = idle_floor_by_kind[kind]
            if key not in group_last_ms or group_last_ms[key] >= idle_floor_ms:
                continue
            # Re-read every copy immediately before each mutation. Do not cache
            # this across copies: Desktop may advance another store between writes.
            fresh_activity = self._fresh_group_activity(group_paths[key])
            if fresh_activity is None or fresh_activity >= idle_floor_ms:
                continue

            def archive_if_still_eligible(
                current: MutableMapping[str, Any],
                *,
                kind: str = kind,
                idle_floor_ms: float = idle_floor_ms,
            ) -> bool:
                # Re-derive the kind from the record as it is NOW. A record
                # whose classification moved under us (title edited, error
                # stamped) is a skip, not a re-classification: the idle floor
                # was chosen for the kind we saw, and applying it to another
                # kind would archive on the wrong window.
                if (
                    current.get("isArchived")
                    or self._record_kind(current, task_axis=task_axis) != kind
                ):
                    return False
                if self._group_key(current, path.name) != key:
                    return False
                current_activity = self._activity_ms(current)
                if current_activity is None or current_activity >= idle_floor_ms:
                    return False
                latest_group_activity = self._fresh_group_activity(group_paths[key])
                if (
                    latest_group_activity is None
                    or latest_group_activity >= idle_floor_ms
                ):
                    return False
                return current.__setitem__("isArchived", True) is None

            try:
                changed = _optimistic_transform_record(path, archive_if_still_eligible)
            except (_RecordWriteConflict, OSError, ValueError):
                skipped += 1
                continue
            archived += int(changed)
            # Observe AFTER the write, and only on the task axis. After, because
            # the observation must not influence the decision -- it cannot, if
            # the decision is already made. Task axis only, because the capture
            # obligation this reports on is a scheduled-task obligation; a chip
            # is a foreground request whose answer went to the person who asked.
            if changed and kind == _KIND_TASK and self._capture_observer is not None:
                try:
                    captured = self._capture_observer(data)
                except Exception:
                    # An observer that raises is a broken observer, never a
                    # reason to stop archiving. Swallow and keep going.
                    captured = True
                if captured is False:
                    task_no_capture += 1
                elif captured is None:
                    task_capture_unknown += 1

        return {
            "examined": examined,
            "archived": archived,
            "skipped": skipped,
            "throttled": 0,
            "task_archived_without_capture": task_no_capture,
            "task_archived_capture_unknown": task_capture_unknown,
        }

    @staticmethod
    def _group_key(data: Mapping[str, Any], filename: str) -> tuple[str, str]:
        cli_session_id = data.get("cliSessionId")
        if isinstance(cli_session_id, str) and cli_session_id:
            return ("cliSessionId", cli_session_id)
        session_id = data.get("sessionId")
        if isinstance(session_id, str) and session_id:
            return ("sessionId", session_id)
        return ("filename", filename)

    @staticmethod
    def _activity_ms(data: Mapping[str, Any]) -> float | None:
        value = data.get("lastActivityAt")
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            return None
        return float(value)

    @classmethod
    def _fresh_group_activity(cls, paths: Iterable[Path]) -> float | None:
        latest: float | None = None
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(data, dict):
                return None
            activity = cls._activity_ms(data)
            if activity is None:
                return None
            latest = activity if latest is None else max(latest, activity)
        return latest

    @staticmethod
    def _holds_open_claim(
        data: Mapping[str, Any],
        claimed_session_ids: frozenset[str],
    ) -> bool:
        if not claimed_session_ids:
            return False
        session_id = data.get("sessionId")
        return isinstance(session_id, str) and session_id in claimed_session_ids

    @classmethod
    def _record_kind(
        cls,
        data: Mapping[str, Any],
        *,
        task_axis: bool,
    ) -> str | None:
        """Classify a registry record as ``chip``, ``task``, or not ours.

        With the task axis ARMED, ``task`` wins over ``chip`` when both would
        match: the two kinds are archived on different idle windows, and a
        scheduled-task record is a task first — its title happening to start
        with a chip verb ("Check ...", "Verify ...") says nothing about the
        shorter window a cron fire deserves.

        With the task axis OFF, ``scheduledTaskId`` is ignored entirely and the
        record falls through to the chip tests exactly as before. That matters:
        a handful of task titles DO start with a chip verb
        (``check-329-kill-row-verdict``), and letting the disabled axis claim
        them would silently NARROW chip coverage instead of leaving it alone.
        """
        title = data.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if _MIRROR_TAG_PATTERN.match(title):
            return None
        if data.get("permissionMode") != "bypassPermissions":
            return None
        if any(data.get(field) is not None for field in _ERROR_FIELDS):
            return None
        if task_axis:
            task_id = data.get(_SCHEDULED_TASK_FIELD)
            if isinstance(task_id, str) and task_id.strip():
                return _KIND_TASK
        first_word = title.split(" ", 1)[0].rstrip(":,.").lower() if title else ""
        if first_word in _CHIP_TITLE_VERBS:
            return _KIND_CHIP
        for field in ("cwd", "originCwd"):
            value = data.get(field)
            if isinstance(value, str) and _AUTOMATION_CWD_PATTERN.search(value):
                return _KIND_CHIP
        return None

    @classmethod
    def _is_chip(cls, data: Mapping[str, Any]) -> bool:
        return cls._record_kind(data, task_axis=False) == _KIND_CHIP
