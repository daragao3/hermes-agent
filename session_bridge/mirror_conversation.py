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

from .claude_visibility import (
    _is_codex_automation_envelope,
    _is_codex_injected_context,
    _is_codex_registration,
)
from .context_pack import _redact
from .models import MIRROR_RECORD_KEY, Provider
from .preview import _is_internal_bridge_message
from .store import SessionBridgeStore

_LOG = logging.getLogger(__name__)

MIRROR_RECORD_VERSION = 1
DEFAULT_BACKFILL_MESSAGES = 400
DEFAULT_MESSAGE_CHARS = 20_000
# Ordered by id, so a fetch page is a contiguous run of source history. Larger
# than the backfill cap so that one page suffices for a fresh mirror.
_FETCH_LIMIT = 2_000
_TRUNCATION_MARKER = " [truncated by Hermes mirror]"
# Bridge state key holding {claude_uuid: {"last_message_id", "leaf_uuid",
# "mirrored"}}. Read and written whole, like the auto-archive ledger.
_STATE_KEY = "session-bridge:claude-visibility:mirror-conversation"
_MIRROR_ENTRYPOINT = "hermes-session-bridge"


@dataclass(frozen=True)
class ConversationSyncResult:
    status: str  # "idle" | "appended" | "skipped"
    appended: int = 0
    reason: str | None = None


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
        leaf_uuid = _ledger_str(entry, "leaf_uuid")
        rows = self._store.list_conversation_messages_after(
            source_session_id, after_id=last_id, limit=_FETCH_LIMIT
        )
        if not rows:
            return ConversationSyncResult("idle")
        consumed_id = max(int(row["id"]) for row in rows)
        turns = conversational_turns(rows, message_chars=self._message_chars)
        dropped = 0
        if entry is None and len(turns) > self._backfill_messages:
            dropped = len(turns) - self._backfill_messages
            turns = turns[-self._backfill_messages :]
        if not turns:
            # Nothing displayable, but remember we looked so the same rows are
            # not re-filtered every cycle.
            ledger[claude_uuid] = _ledger_entry(entry, consumed_id, leaf_uuid, 0)
            self._save_ledger(ledger)
            return ConversationSyncResult("idle")

        path = Path(native_path)
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
            return ConversationSyncResult(
                "skipped", reason="mirror transcript has no leaf record"
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
        ledger[claude_uuid] = _ledger_entry(entry, consumed_id, parent, len(records))
        self._save_ledger(ledger)
        return ConversationSyncResult("appended", appended=len(records))

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
        ):
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
) -> dict[str, Any]:
    mirrored = _ledger_int(previous, "mirrored") or 0
    entry: dict[str, Any] = {
        "last_message_id": last_message_id,
        "mirrored": mirrored + appended,
    }
    if leaf_uuid is not None:
        entry["leaf_uuid"] = leaf_uuid
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
