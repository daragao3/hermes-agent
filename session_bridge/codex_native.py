"""Read-only native evidence for the local Codex catalog, never sidebar proof."""

from collections import defaultdict
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3

from agent.transports.codex_event_projector import CodexEventProjector
from .models import ProjectedMessage


def native_records(path: Path, native_id: str) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    if (
        not records
        or records[0].get("type") != "session_meta"
        or records[0].get("payload", {}).get("id") != native_id
    ):
        raise ValueError("Codex native rollout identity mismatch")
    return records


def native_users(records: list[dict]) -> list[tuple[int, ProjectedMessage]]:
    users = []
    seen = set()
    for index, record in enumerate(records):
        payload = record.get("payload", {})
        if (
            record.get("type") != "response_item"
            or payload.get("type") != "message"
            or payload.get("role") != "user"
        ):
            continue
        identity = payload.get("id")
        # Raw input events without a native message identity are a separate
        # archival format; do not invent identities or promote those events.
        if not isinstance(identity, str) or not identity or identity in seen:
            continue
        converted = (
            CodexEventProjector()
            .project_item({
                "type": "userMessage",
                "id": identity,
                "content": payload.get("content"),
            })
            .messages
        )
        if len(converted) != 1 or not converted[0].get("content"):
            continue
        timestamp = datetime.fromisoformat(
            record["timestamp"].replace("Z", "+00:00")
        ).timestamp()
        users.append((
            index,
            ProjectedMessage(
                native_event_id=identity,
                ordinal=0,
                role="user",
                content=converted[0]["content"],
                timestamp=timestamp,
            ),
        ))
        seen.add(identity)
    return users


def supplement_native_users(
    path: str | None, native_id: str, projected: list[ProjectedMessage]
) -> list[ProjectedMessage]:
    if not path or not Path(path).exists():
        return projected
    records = native_records(Path(path), native_id)
    by_id = {message.native_event_id: i for i, message in enumerate(projected)}
    anchors = {}
    for index, record in enumerate(records):
        identity = record.get("payload", {}).get("id")
        if record.get("type") == "response_item" and identity in by_id:
            anchors[index] = by_id[identity]
    users = native_users(records)
    reserved = {
        by_id[user.native_event_id]
        for _, user in users
        if user.native_event_id in by_id
    }
    unmatched = {
        i for i, message in enumerate(projected) if message.role == "user"
    } - reserved
    missing = []
    for index, user in users:
        match = by_id.get(user.native_event_id)
        if match is None:
            match = next(
                (i for i in sorted(unmatched) if projected[i].content == user.content),
                None,
            )
        if match is not None:
            unmatched.discard(match)
            anchors[index] = match
        else:
            missing.append((index, user))
    additions = defaultdict(list)
    for index, user in missing:
        following = next((anchors[i] for i in sorted(anchors) if i > index), None)
        preceding = [anchors[i] for i in sorted(anchors) if i < index]
        position = (
            following
            if following is not None
            else preceding[-1] + 1
            if preceding
            else 0
        )
        additions[position].append(user)
    result = []
    for i in range(len(projected) + 1):
        result.extend(additions[i])
        if i < len(projected):
            result.append(projected[i])
    return result


def local_inventory(home: Path, *, include_archived: bool) -> list[dict]:
    database = home / "state_5.sqlite"
    if not database.exists():
        return []
    # A read-only metadata census avoids the API's timestamp-only cursor and
    # catches old arrivals behind the drained frontier. No history DB is opened.
    conn = sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
    )
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, rollout_path, created_at, updated_at, source, cwd, title, archived, first_user_message FROM threads WHERE source IN ('cli', 'vscode', 'appServer') AND (archived = 0 OR ?)",
            (include_archived,),
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for row in rows:
        if not row["first_user_message"]:
            path = Path(row["rollout_path"])
            if not path.is_file():
                continue
            try:
                users = native_users(native_records(path, row["id"]))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                logging.getLogger(__name__).warning(
                    "codex_native_inventory rollout_unreadable; retry next census"
                )
                continue
            if not users:
                continue
        entries.append({
            "id": row["id"],
            "rolloutPath": row["rollout_path"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "source": row["source"],
            "cwd": row["cwd"],
            "title": row["title"],
            "archived": bool(row["archived"]),
        })
    return entries
