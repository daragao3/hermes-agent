"""Hydrate a Claude visibility mirror with its source conversation.

A visibility mirror is the ``claude -p`` registration session the registrar
runs once per Codex/Hermes source. The desktop sidebar row IS that session, so
until 2026-09-09 every ``[Codex]`` row opened to the registration prompt and
``REGISTERED`` -- the row proved the source existed and showed nothing of it.
Diego's rule for the sidebar is that a ``[Codex]`` row shows the Codex
conversation, and this module is what makes that true.

HOW: after registration the mirror transcript (``native_path``) is APPEND-ONLY
extended with one Claude-transcript record per conversational source message,
in source order, each tagged with a top-level ``hermesMirror`` provenance
object. Append-only is load-bearing three ways:

* the registration prefix -- the signed marker turn the registrar wrote and
  ``_read_exact`` verified -- is never rewritten, so origin detection, the
  registrar's identity checks and the characterization gates keep the bytes
  they already validated;
* the claude adapter's incremental cursor stays valid (its head hash covers
  the untouched prefix and it resumes from its byte offset), so a hydrated
  mirror never forces a rebuild scan;
* the desktop app reads the file on open, so a growing file is a growing
  conversation with no record mutation -- and record mutation is the one
  thing the app ignores (see agent memory
  ``reference_ccd_app_owns_session_state_files_are_downstream``).

The ``hermesMirror`` tag is what keeps the mirror from becoming a second copy
of the source inside the bridge: ``claude_adapter._is_eligible_record`` treats a
tagged record as ineligible, so it is never projected as a message, never
counted as a human turn (the mirror stays ``BRIDGE_PLACEHOLDER``, not a
continuation), and never harvested for bridge markers. That last point is not
theoretical: agent sessions on this box quote marker strings constantly, and an
untagged mirrored turn quoting one would raise
``ConflictingClaudeBridgeMarkers`` on the mirror's own scan.

WHAT IS MIRRORED: user and assistant text only -- no tool calls, no tool
results, no reasoning -- with the same exclusions the visibility candidate
builder and the preview renderer already apply (Codex injected context,
automation envelopes, the bridge's own registration prompts) and the same
secret redaction. Each message is capped; the initial backfill is capped and
announces what it dropped, so a 16k-message source does not become a 16k-line
transcript in one write.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .claude_adapter import _is_cli_command_bookkeeping
from .claude_visibility import (
    _is_codex_automation_envelope,
    _is_codex_injected_context,
    _is_codex_registration,
)
from .context_pack import _redact
from .models import (
    MIRROR_RECORD_KEY,
    REGISTRATION_RECORD_KEY,
    TEARDOWN_RECORD_KEY,
    Provider,
    is_mirrored_record,
    is_registration_record,
    is_teardown_record,
)
from .preview import _is_internal_bridge_message
from .sidebar import is_meaningful_user_text
from .store import SessionBridgeStore

_LOG = logging.getLogger(__name__)

MIRROR_RECORD_VERSION = 1
REGISTRATION_HIDE_VERSION = 1
# Ledger key recording that hide_registration_prefix has settled a mirror
# ("hidden" or "absent"), so the prefix is not re-read on every cycle.
_LEDGER_PREFIX_KEY = "registration_prefix"
TEARDOWN_HIDE_VERSION = 1
# Ledger key recording that hide_cli_teardown has settled a mirror ("hidden" or
# "absent"). The registrar waits for the CLI to exit before it commits the job
# (claude_registrar: ``process.write("/exit\r")`` then ``process.wait``), so
# every teardown record is on disk before the float worker first sees the
# mirror and settling once is sound.
_LEDGER_TEARDOWN_KEY = "cli_teardown"
DEFAULT_BACKFILL_MESSAGES = 400
DEFAULT_MESSAGE_CHARS = 20_000
# Ordered by id, so a fetch page is a contiguous run of source history. Larger
# than the backfill cap so that one page suffices for a fresh mirror.
_FETCH_LIMIT = 2_000
_TRUNCATION_MARKER = " [truncated by Hermes mirror]"
# Bridge state key holding {claude_uuid: {"last_message_id", "leaf_uuid",
# "mirrored"}}. Read and written whole, like the auto-archive ledger. Public
# because the float worker reads ``mirrored`` to decide whether a mirror has
# anything to title itself from (see ClaudeMirrorFloatWorker._derive_mirror_title).
MIRROR_CONVERSATION_STATE_KEY = "session-bridge:claude-visibility:mirror-conversation"
_STATE_KEY = MIRROR_CONVERSATION_STATE_KEY
_MIRROR_ENTRYPOINT = "hermes-session-bridge"


@dataclass(frozen=True)
class ConversationSyncResult:
    status: str  # "idle" | "appended" | "skipped"
    appended: int = 0
    reason: str | None = None
    # True when this pass hid the mirror's registration prompt (once per mirror).
    hidden: bool = False
    # True when this pass hid the CLI's /exit bookkeeping records (once per mirror).
    teardown_hidden: bool = False


class MirrorConversationSync:
    """Append new source conversation turns to a visibility mirror transcript."""

    def __init__(
        self,
        store: SessionBridgeStore,
        *,
        backfill_messages: int = DEFAULT_BACKFILL_MESSAGES,
        message_chars: int = DEFAULT_MESSAGE_CHARS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(backfill_messages, int) or backfill_messages < 1:
            raise ValueError("backfill_messages must be a positive integer")
        if not isinstance(message_chars, int) or message_chars < 100:
            raise ValueError("message_chars must be at least 100")
        self._store = store
        self._backfill_messages = backfill_messages
        self._message_chars = message_chars
        self._clock = clock

    def sync(
        self,
        *,
        claude_uuid: str,
        source_session_id: str,
        native_path: str,
        cwd: str,
    ) -> ConversationSyncResult:
        ledger = self._load_ledger()
        entry = ledger.get(claude_uuid)
        last_id = _ledger_int(entry, "last_message_id")
        # "First hydration" means no rows consumed yet -- not "no ledger entry":
        # settling the registration prefix below can create the entry on a
        # cycle that mirrors nothing, and the backfill cap must still apply
        # when the first rows arrive.
        first_sync = last_id is None
        leaf_uuid = _ledger_str(entry, "leaf_uuid")
        mode = self._source_mode(entry, source_session_id)
        path = Path(native_path)
        # Hide the registration prompt before anything else, once per mirror.
        # This runs inside the float worker's cycle, serialized with the
        # append below, so the in-place rewrite never races the bridge's own
        # writer. It is recorded in the ledger even when there is nothing to
        # mirror this cycle, so a quiet source is not re-read every pass.
        hidden = False
        teardown_hidden = False
        settled = False
        if _ledger_str(entry, _LEDGER_PREFIX_KEY) is None:
            state = hide_registration_prefix(path)
            if state != "unreadable":
                entry = {
                    **(entry or {}),
                    _LEDGER_PREFIX_KEY: "absent" if state == "absent" else "hidden",
                }
                ledger[claude_uuid] = entry
                hidden = state == "hidden"
                settled = True
                if hidden:
                    _LOG.info("hid registration prompt of mirror %s", claude_uuid)
        # Same contract for the CLI's own /exit bookkeeping after the answer.
        if _ledger_str(entry, _LEDGER_TEARDOWN_KEY) is None:
            state = hide_cli_teardown(path)
            if state != "unreadable":
                entry = {
                    **(entry or {}),
                    _LEDGER_TEARDOWN_KEY: "absent" if state == "absent" else "hidden",
                }
                ledger[claude_uuid] = entry
                teardown_hidden = state == "hidden"
                settled = True
                if teardown_hidden:
                    _LOG.info("hid CLI teardown records of mirror %s", claude_uuid)
        if mode == "rollout":
            rollout = self._codex_rollout_path(source_session_id)
            if rollout is None:
                if settled:
                    self._save_ledger(ledger)
                return ConversationSyncResult(
                    "skipped",
                    reason="codex rollout file is not readable",
                    hidden=hidden,
                    teardown_hidden=teardown_hidden,
                )
            rows, consumed_id = read_codex_rollout_rows(
                rollout, after_offset=last_id
            )
        else:
            rows = self._store.list_conversation_messages_after(
                source_session_id, after_id=last_id, limit=_FETCH_LIMIT
            )
            consumed_id = max((int(row["id"]) for row in rows), default=-1)
        if not rows:
            if settled:
                self._save_ledger(ledger)
            return ConversationSyncResult(
                "idle", hidden=hidden, teardown_hidden=teardown_hidden
            )
        turns = conversational_turns(rows, message_chars=self._message_chars)
        dropped = 0
        if first_sync and len(turns) > self._backfill_messages:
            dropped = len(turns) - self._backfill_messages
            turns = turns[-self._backfill_messages :]
        if not turns:
            # Nothing displayable, but remember we looked so the same rows are
            # not re-filtered every cycle.
            ledger[claude_uuid] = _ledger_entry(
                entry, consumed_id, leaf_uuid, 0, mode=mode
            )
            self._save_ledger(ledger)
            return ConversationSyncResult(
                "idle", hidden=hidden, teardown_hidden=teardown_hidden
            )

        if leaf_uuid is None or not cwd:
            tail = transcript_tail(path)
            if leaf_uuid is None:
                leaf_uuid = tail.leaf_uuid
            if not cwd:
                # The mirror catalog row carries no cwd; the registration
                # records the registrar wrote do, and it is the cwd the
                # desktop app already files this session under.
                cwd = tail.cwd or ""
        if leaf_uuid is None:
            if settled:
                self._save_ledger(ledger)
            return ConversationSyncResult(
                "skipped",
                reason="mirror transcript has no leaf record",
                hidden=hidden,
                teardown_hidden=teardown_hidden,
            )

        records: list[dict[str, Any]] = []
        parent = leaf_uuid
        if dropped:
            notice = _notice_record(
                claude_uuid=claude_uuid,
                source_session_id=source_session_id,
                cwd=cwd,
                parent_uuid=parent,
                dropped=dropped,
                timestamp=turns[0]["timestamp"],
            )
            records.append(notice)
            parent = notice["uuid"]
        for turn in turns:
            record = render_mirror_record(
                claude_uuid=claude_uuid,
                source_session_id=source_session_id,
                cwd=cwd,
                parent_uuid=parent,
                turn=turn,
            )
            records.append(record)
            parent = record["uuid"]

        _append_records(path, records)
        ledger[claude_uuid] = _ledger_entry(
            entry, consumed_id, parent, len(records), mode=mode
        )
        self._save_ledger(ledger)
        return ConversationSyncResult(
            "appended",
            appended=len(records),
            hidden=hidden,
            teardown_hidden=teardown_hidden,
        )

    def _source_mode(
        self, entry: Mapping[str, Any] | None, source_session_id: str
    ) -> str:
        """Where this mirror's turns come from; fixed on first hydration.

        A Codex source is read from its on-disk rollout: the catalog's copy of
        a Codex thread comes through the app-server under a read budget, and a
        long thread that exceeded it is cached as a one-message summary for
        good (measured 2026-09-09: a 65 MB, 333-reply thread held ONE stored
        message). The rollout is complete and resumes by byte offset. Hermes
        sources are host-native rows and read from the store. The mode is
        pinned in the ledger so a mirror never mixes the two id spaces.
        """
        pinned = _ledger_str(entry, "mode")
        if pinned in ("rollout", "store"):
            return pinned
        if source_session_id.startswith(f"{Provider.CODEX.value}:"):
            return "rollout" if self._codex_rollout_path(source_session_id) else "store"
        return "store"

    def _codex_rollout_path(self, source_session_id: str) -> Path | None:
        try:
            row = self._store.get_external_session(source_session_id)
        except Exception:
            return None
        if not isinstance(row, Mapping):
            return None
        native_path = row.get("native_path")
        if not isinstance(native_path, str) or not native_path:
            return None
        path = Path(native_path)
        try:
            if not path.is_file():
                return None
        except OSError:
            return None
        return path

    def _load_ledger(self) -> dict[str, dict[str, Any]]:
        try:
            stored = self._store.get_state(_STATE_KEY)
        except Exception:
            return {}
        if not isinstance(stored, Mapping):
            return {}
        return {
            key: dict(value)
            for key, value in stored.items()
            if isinstance(key, str) and isinstance(value, Mapping)
        }

    def _save_ledger(self, ledger: Mapping[str, Mapping[str, Any]]) -> None:
        self._store.set_state(_STATE_KEY, dict(ledger))


def conversational_turns(
    rows: Sequence[Mapping[str, Any]], *, message_chars: int = DEFAULT_MESSAGE_CHARS
) -> list[dict[str, Any]]:
    """Reduce stored message rows to displayable user/assistant text turns.

    Mirrors the preview renderer's ``_sanitized_conversation`` plus the
    visibility lane's Codex exclusions, so what a mirror shows is exactly the
    conversation the lane judged the source by.
    """
    turns: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        role = str(row.get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        if row.get("tool_name") or row.get("tool_call_id") or row.get("tool_calls"):
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "user" and (
            _is_codex_injected_context(content)
            or _is_codex_automation_envelope(content)
            or _is_codex_registration(content)
            or is_envelope_user_text(content)
        ):
            continue
        if role == "assistant" and is_automation_reply_envelope(content):
            continue
        redacted = _redact(content).strip()
        if not redacted or _is_internal_bridge_message(redacted):
            continue
        if len(redacted) > message_chars:
            redacted = redacted[: message_chars - len(_TRUNCATION_MARKER)].rstrip()
            redacted += _TRUNCATION_MARKER
        timestamp = row.get("timestamp")
        if (
            not isinstance(timestamp, (int, float))
            or isinstance(timestamp, bool)
            or not math.isfinite(float(timestamp))
        ):
            timestamp = None
        else:
            timestamp = float(timestamp)
        turns.append(
            {
                "message_id": int(row["id"]),
                "role": role,
                "content": redacted,
                "timestamp": timestamp,
            }
        )
    return turns


_ROLLOUT_TEXT_BLOCK_TYPES = frozenset({"input_text", "output_text", "text"})
# User turns that are harness or tool envelopes, not something a person typed:
# Codex's own context injections, Claude Code's notifications and slash-command
# bookkeeping (present in threads the Codex importer copied from Claude), and
# the bridge's automation heartbeats. Rendered verbatim they are what Diego
# called "broken formatting" in a mirror row (2026-09-09). Prefix match on the
# stripped text; assistant prose that QUOTES a tag is untouched.
_ENVELOPE_USER_PREFIXES = (
    "<environment_context>",
    "<user_action>",
    "<turn_aborted>",
    "<permissions instructions>",
    "<app-context>",
    "<task-notification>",
    "<system-reminder>",
    "<local-command-",
    "<command-name>",
    "<command-message>",
    "<heartbeat>",
    "<codex_delegation>",
    "<cross-session-message",
    "<ci-monitor-event",
)


def is_envelope_user_text(value: object) -> bool:
    return isinstance(value, str) and value.lstrip().startswith(_ENVELOPE_USER_PREFIXES)


def is_automation_reply_envelope(value: object) -> bool:
    """An assistant turn that is a Codex automation's heartbeat REPLY, whole.

    A Codex thread with automations attached answers every ``<heartbeat>``
    wake with ``<heartbeat><automation_id/><decision/><message/></heartbeat>``
    -- protocol, not conversation. The user-side wake was already dropped by
    ``is_envelope_user_text``; the reply was not, and Diego saw 147 of them
    in one ``[Codex]`` row on 2026-09-09 ("hypermark garbage"). Whole-content
    only: an assistant that quotes or explains the envelope inside prose is
    kept, exactly like the user-side rule.
    """
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return (
        stripped.startswith("<heartbeat>")
        and stripped.endswith("</heartbeat>")
        and "<decision>" in stripped
    )


def read_codex_rollout_rows(
    path: Path, *, after_offset: int | None
) -> tuple[list[dict[str, Any]], int]:
    """Message rows from a Codex rollout file, resumable by byte offset.

    Returns ``(rows, consumed_offset)``: one row per ``response_item`` message
    with a user or assistant role found in COMPLETE lines after
    ``after_offset``, and the offset just past the last complete line read
    (the value to pass back next time). Each row's ``id`` is the byte offset
    of its line, which is monotonic in file order and therefore serves as the
    message id the ledger and the deterministic record uuid key on.

    ``compacted`` entries are skipped on purpose: their ``replacement_history``
    re-states earlier messages, and a second copy is exactly what a display
    transcript must not carry. A trailing line without its newline is a write
    in progress and is left for the next pass.
    """
    start = 0 if after_offset is None or after_offset < 0 else int(after_offset)
    rows: list[dict[str, Any]] = []
    consumed = start
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if start >= size:
            return [], start
        stream.seek(start)
        offset = start
        for raw in stream:
            line_start = offset
            offset += len(raw)
            if not raw.endswith(b"\n"):
                break
            consumed = offset
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("type") != "response_item":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            content = payload.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(
                    block["text"]
                    for block in content
                    if isinstance(block, dict)
                    and block.get("type") in _ROLLOUT_TEXT_BLOCK_TYPES
                    and isinstance(block.get("text"), str)
                )
            else:
                continue
            if not text.strip():
                continue
            rows.append(
                {
                    "id": line_start,
                    "role": role,
                    "content": text,
                    "timestamp": _epoch_from_iso(record.get("timestamp")),
                }
            )
    return rows, consumed


def _epoch_from_iso(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def render_mirror_record(
    *,
    claude_uuid: str,
    source_session_id: str,
    cwd: str,
    parent_uuid: str,
    turn: Mapping[str, Any],
) -> dict[str, Any]:
    """One Claude-transcript record for one source turn.

    The shape follows what the registrar's own ``claude -p`` run writes (the
    fields the desktop app reads to render a turn) plus the ``hermesMirror``
    provenance tag that makes the bridge's own adapter skip it.
    """
    role = str(turn["role"])
    message_id = int(turn["message_id"])
    record_uuid = mirror_record_uuid(claude_uuid, source_session_id, message_id)
    content = str(turn["content"])
    if role == "assistant":
        message: dict[str, Any] = {
            "id": f"mirror_{message_id}",
            "type": "message",
            "role": "assistant",
            "model": _source_label(source_session_id),
            "content": [{"type": "text", "text": content}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
        }
    else:
        message = {"role": "user", "content": content}
    return {
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "type": role,
        "uuid": record_uuid,
        "timestamp": _iso_timestamp(turn.get("timestamp")),
        "sessionId": claude_uuid,
        "cwd": cwd,
        "userType": "external",
        "entrypoint": _MIRROR_ENTRYPOINT,
        MIRROR_RECORD_KEY: {
            "version": MIRROR_RECORD_VERSION,
            "source_session_id": source_session_id,
            "message_id": message_id,
        },
        "message": message,
    }


def first_mirrored_title_text(path: Path) -> str | None:
    """Text a mirror can be titled from: first real USER turn, else first ASSISTANT turn.

    Walks the mirror transcript once, in file order. The first
    ``hermesMirror``-tagged user record whose text passes the sidebar's
    ``is_meaningful_user_text`` (so an "ok" or a bare ack does not become a
    title) wins, wherever it sits. Only when the whole transcript holds no such
    user turn does the first meaningful assistant turn stand in -- measured
    2026-09-09: 15 of 16 hydrated fallback-titled mirrors held assistant turns
    ONLY, because their chip- and import-driven Codex sources had nothing but
    harness envelopes for user turns and hydration filters those out. The
    backfill notice (``message_id`` 0, "[Hermes mirror] N earlier message(s)
    ...") is skipped by id, never by text, so a source turn that happens to
    quote the notice still counts. Malformed lines are skipped; ``None`` means
    the mirror holds nothing to title from yet. Raises ``OSError`` for an
    unreadable file so the caller decides what an unreadable mirror means.
    """
    first_assistant: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not is_mirrored_record(record):
                continue
            if record[MIRROR_RECORD_KEY].get("message_id") == 0:
                continue
            role = record.get("type")
            content = _mirrored_record_text(record)
            if content is None or not is_meaningful_user_text(content):
                continue
            if role == "user":
                return content
            if role == "assistant" and first_assistant is None:
                first_assistant = content
    return first_assistant


def _mirrored_record_text(record: Mapping[str, Any]) -> str | None:
    """Plain text of a mirrored record in either shape render_mirror_record writes."""
    message = record.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return "".join(parts) if parts else None
    return None


def mirror_record_uuid(claude_uuid: str, source_session_id: str, message_id: int) -> str:
    """Deterministic per (mirror, source message): a re-append is a no-op id."""
    namespace = uuid.UUID(claude_uuid)
    return str(uuid.uuid5(namespace, f"{source_session_id}:{message_id}"))


@dataclass(frozen=True)
class TranscriptTail:
    leaf_uuid: str | None
    cwd: str | None


def transcript_tail(path: Path) -> TranscriptTail:
    """The last chained record's uuid (the parent for an append) and the cwd."""
    leaf: str | None = None
    cwd: str | None = None
    try:
        with path.open("rb") as stream:
            for raw in stream:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                value = record.get("uuid")
                if isinstance(value, str) and value:
                    leaf = value
                recorded_cwd = record.get("cwd")
                if cwd is None and isinstance(recorded_cwd, str) and recorded_cwd:
                    cwd = recorded_cwd
    except OSError:
        return TranscriptTail(None, None)
    return TranscriptTail(leaf, cwd)


def transcript_leaf_uuid(path: Path) -> str | None:
    return transcript_tail(path).leaf_uuid


def _notice_record(
    *,
    claude_uuid: str,
    source_session_id: str,
    cwd: str,
    parent_uuid: str,
    dropped: int,
    timestamp: float | None,
) -> dict[str, Any]:
    text = (
        f"[Hermes mirror] {dropped} earlier message(s) of {source_session_id} "
        "are not mirrored here; open the source session for the full history."
    )
    return render_mirror_record(
        claude_uuid=claude_uuid,
        source_session_id=source_session_id,
        cwd=cwd,
        parent_uuid=parent_uuid,
        turn={
            "message_id": 0,
            "role": "user",
            "content": text,
            "timestamp": timestamp,
        },
    )


def _append_records(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    payload = b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for record in records
    )
    with path.open("r+b") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if size > 0:
            stream.seek(size - 1)
            if stream.read(1) != b"\n":
                stream.seek(0, os.SEEK_END)
                stream.write(b"\n")
        stream.seek(0, os.SEEK_END)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def hide_registration_prefix(path: Path, *, now: float | None = None) -> str:
    """Hide a mirror's registration prompt from the desktop app, once.

    The prompt the registrar pasted (``build_claude_registration_prompt``: the
    preamble, the signed marker, the bounded metadata) is the first record of
    every mirror, so every ``[Codex]`` row opened on ~1.1 KB of bridge
    boilerplate before the conversation. The desktop app hides a ``user``
    record carrying ``isMeta: true`` from its conversation view, so this marks
    the prompt record ``isMeta`` and tags it ``hermesRegistration`` -- the tag
    is what keeps ``claude_adapter._detect_origin`` harvesting the marker from
    a record the adapter otherwise ignores (see ``_is_hidden_registration_record``).

    Only the FIRST main-chain user record is a candidate, and only when it
    reads as a registration prompt; a transcript shaped any other way is left
    byte-identical. The one record is
    re-serialized in place and every other byte of the file is preserved, so
    the adapter's head hash changes (it covers the first 64 KiB) and the next
    scan is a REBUILD of a file whose parse is otherwise identical -- measured
    before landing, see the loops record named in the module docstring.

    The assistant's ``REGISTERED`` reply is left alone on purpose: the app's
    renderer dispatches assistant records before it looks at ``isMeta``, so
    marking it would change nothing the user sees while removing the one
    eligible record that still carries the mirror's cwd and timestamps.

    Returns ``"hidden"`` (rewritten now), ``"already"`` (tagged earlier),
    ``"absent"`` (no hideable prompt) or ``"unreadable"``.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "unreadable"
    lines = data.split(b"\n")
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        # File order is not chronological: Claude Code can append the prompt
        # AFTER the answer it caused (claude_adapter, measured 2026-08-25; 4 of
        # 172 live mirrors on 2026-09-09 open with the REGISTERED record). So
        # the candidate is the first USER record, wherever the answer sits.
        if record.get("type") != "user":
            continue
        if is_registration_record(record):
            return "already"
        if record.get("isSidechain") or is_mirrored_record(record):
            return "absent"
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not _is_codex_registration(content):
            return "absent"
        record["isMeta"] = True
        record[REGISTRATION_RECORD_KEY] = {
            "version": REGISTRATION_HIDE_VERSION,
            "hidden_at": _iso_timestamp(now),
        }
        lines[index] = json.dumps(
            record, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        payload = b"\n".join(lines)
        try:
            with path.open("r+b") as stream:
                stream.write(payload)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            return "unreadable"
        return "hidden"
    return "absent"


def _bookkeeping_text(record: dict[str, Any]) -> str | None:
    """The record's text when every content block is text; else None."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not content:
        return None
    texts: list[str] = []
    for block in content:
        if (
            not isinstance(block, dict)
            or block.get("type") != "text"
            or not isinstance(block.get("text"), str)
        ):
            return None
        texts.append(block["text"])
    return "\n".join(texts)


def hide_cli_teardown(path: Path, *, now: float | None = None) -> str:
    """Hide the CLI's own ``/exit`` bookkeeping from the desktop app, once.

    On the success branch the registrar types ``/exit`` and waits for the CLI
    to exit before it commits the job (``claude_registrar``), and Claude Code
    records that slash command and its farewell as two USER records after the
    ``REGISTERED`` reply -- ``<command-name>/exit</command-name>...`` and
    ``<local-command-stdout>Goodbye!</local-command-stdout>``. Whether they
    land is a CLI timing race, not a version: 26 of 172 live mirrors carried
    them on 2026-09-09, interleaved in time with mirrors that did not. The
    desktop app renders them as turns of the ``[Codex]`` row (its transcript
    API lists them, and its renderer turns ``<command-name>`` into a slash
    echo), so this marks every main-chain user record whose WHOLE content is
    CLI command bookkeeping ``isMeta`` and tags it ``hermesTeardown``.

    The candidate predicate is ``claude_adapter._is_cli_command_bookkeeping``,
    the same whole-content rule that already keeps these records out of the
    human-turn count -- so ``isMeta`` (which makes a record ineligible for the
    adapter altogether) removes nothing the adapter classified by: such a
    record was never a human turn, never carried a marker, and only ever
    projected as a display message. Measured on copies of all 172 live mirrors
    before landing (loops ``exit-bookkeeping-mirror-visibility-20260909``).

    Sidechain records and the bridge's own mirrored turns are never candidates,
    and a record already ``isMeta`` (the CLI marks its own
    ``<local-command-caveat>`` that way) is left alone. Each changed record is
    re-serialized in place and every other byte of the file is preserved, the
    way ``hide_registration_prefix`` does it; the registration prompt itself is
    not bookkeeping and is never touched here.

    Returns ``"hidden"`` (at least one record rewritten now), ``"already"``
    (tagged earlier, nothing new to hide), ``"absent"`` (no bookkeeping
    record) or ``"unreadable"``.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "unreadable"
    lines = data.split(b"\n")
    changed = False
    already = False
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        if record.get("isSidechain") or is_mirrored_record(record):
            continue
        if is_teardown_record(record):
            already = True
            continue
        if record.get("isMeta"):
            continue
        text = _bookkeeping_text(record)
        if text is None or not _is_cli_command_bookkeeping(text):
            continue
        record["isMeta"] = True
        record[TEARDOWN_RECORD_KEY] = {
            "version": TEARDOWN_HIDE_VERSION,
            "hidden_at": _iso_timestamp(now),
        }
        lines[index] = json.dumps(
            record, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        changed = True
    if not changed:
        return "already" if already else "absent"
    payload = b"\n".join(lines)
    try:
        with path.open("r+b") as stream:
            stream.write(payload)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return "unreadable"
    return "hidden"


def _source_label(source_session_id: str) -> str:
    prefix, _, _ = source_session_id.partition(":")
    return prefix if prefix in {Provider.CODEX.value, Provider.HERMES.value} else "hermes"


def _iso_timestamp(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(
        float(value)
    ):
        moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        moment = datetime.now(tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ledger_entry(
    previous: Mapping[str, Any] | None,
    last_message_id: int,
    leaf_uuid: str | None,
    appended: int,
    *,
    mode: str,
) -> dict[str, Any]:
    mirrored = _ledger_int(previous, "mirrored") or 0
    entry: dict[str, Any] = {
        "mode": mode,
        "last_message_id": last_message_id,
        "mirrored": mirrored + appended,
    }
    if leaf_uuid is not None:
        entry["leaf_uuid"] = leaf_uuid
    prefix_state = _ledger_str(previous, _LEDGER_PREFIX_KEY)
    if prefix_state is not None:
        entry[_LEDGER_PREFIX_KEY] = prefix_state
    teardown_state = _ledger_str(previous, _LEDGER_TEARDOWN_KEY)
    if teardown_state is not None:
        entry[_LEDGER_TEARDOWN_KEY] = teardown_state
    return entry


def _ledger_int(entry: Mapping[str, Any] | None, key: str) -> int | None:
    if entry is None:
        return None
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _ledger_str(entry: Mapping[str, Any] | None, key: str) -> str | None:
    if entry is None:
        return None
    value = entry.get(key)
    return value if isinstance(value, str) and value else None
