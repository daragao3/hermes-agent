"""Regressions for native conversations and user messages omitted by Codex API."""

import json
import sqlite3

import pytest

from hermes_state import SessionDB
from session_bridge.codex_adapter import CodexSourceAdapter, _normalize_summary
from session_bridge.store import SessionBridgeStore


class Client:
    def initialize(self, **kwargs):
        return {}

    def request(self, method, params, **kwargs):
        assert method == "thread/list"
        return {"data": [], "nextCursor": None}


def rollout(tmp_path, *, identity="thread", users=("question",)):
    path = tmp_path / "rollout.jsonl"
    rows = [{"type": "session_meta", "payload": {"id": identity}}]
    for i, content in enumerate(users):
        rows.append({
            "type": "response_item",
            "timestamp": f"2026-09-12T01:00:0{i}Z",
            "payload": {
                "id": f"user-{i}",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            },
        })
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def projection(path, items=()):
    summary = _normalize_summary(
        {
            "id": "thread",
            "createdAt": 1789174800,
            "updatedAt": 1789174810,
            "rolloutPath": str(path),
        },
        archived=False,
    )
    return CodexSourceAdapter(Client(), marker_secret=b"test-secret").project_thread(
        summary,
        response={"thread": {"id": "thread", "turns": [{"items": list(items)}]}},
    )


def test_native_user_survives_api_omission_and_rebuild(tmp_path):
    path = rollout(tmp_path)
    result = projection(
        path, [{"type": "agentMessage", "id": "answer", "text": "answer"}]
    )
    assert [(m.native_event_id, m.role) for m in result.messages] == [
        ("user-0", "user"),
        ("answer", "assistant"),
    ]
    assert result.messages[0].content == "question"
    db = SessionDB(tmp_path / "bridge.db")
    try:
        store = SessionBridgeStore(db)
        store.upsert_projection(result, rebuild=False)
        store.upsert_projection(result, rebuild=False)
        store.upsert_projection(result, rebuild=True)
        rows = db._conn.execute(
            "SELECT role, content FROM messages ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("user", "question"),
            ("assistant", "answer"),
        ]
    finally:
        db.close()


@pytest.mark.parametrize("native_id", ["user-0", "different-api-id"])
def test_native_user_already_in_api_is_not_duplicated(tmp_path, native_id):
    result = projection(
        rollout(tmp_path),
        [
            {
                "type": "userMessage",
                "id": native_id,
                "content": [{"type": "text", "text": "question"}],
            }
        ],
    )
    assert len(result.messages) == 1
    assert result.messages[0].native_event_id == native_id


def test_different_native_session_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="identity"):
        projection(rollout(tmp_path, identity="another-thread"))


def test_repeated_user_text_does_not_hide_a_distinct_missing_message(tmp_path):
    result = projection(
        rollout(tmp_path, users=("again", "again")),
        [
            {
                "type": "userMessage",
                "id": "user-1",
                "content": [{"type": "text", "text": "again"}],
            }
        ],
    )
    assert [m.native_event_id for m in result.messages] == ["user-0", "user-1"]


def test_truncated_native_record_defers_projection(tmp_path):
    path = rollout(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":')
    with pytest.raises(ValueError):
        projection(path)


def test_api_only_rebuild_cannot_delete_preserved_codex_user(tmp_path):
    path = rollout(tmp_path)
    complete = projection(
        path, [{"type": "agentMessage", "id": "answer", "text": "answer"}]
    )
    db = SessionDB(tmp_path / "bridge.db")
    try:
        store = SessionBridgeStore(db)
        store.upsert_projection(complete, rebuild=False)
        before = [
            tuple(row) for row in db._conn.execute("SELECT * FROM messages ORDER BY id")
        ]
        path.unlink()
        incomplete = projection(
            path, [{"type": "agentMessage", "id": "answer", "text": "answer"}]
        )
        with pytest.raises(ValueError, match="user messages"):
            store.upsert_projection(incomplete, rebuild=True)
        assert [
            tuple(row) for row in db._conn.execute("SELECT * FROM messages ORDER BY id")
        ] == before
    finally:
        db.close()


def test_metadata_inventory_recovers_old_api_omission_without_internal_threads(
    tmp_path,
):
    database = tmp_path / "state_5.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE threads (id TEXT, rollout_path TEXT, created_at INT, updated_at INT, source TEXT, cwd TEXT, title TEXT, archived INT, first_user_message TEXT)"
        )
        for identity, source, archived in [
            ("missing", "vscode", 0),
            ("archived", "cli", 1),
            ("internal", "exec", 0),
            ("agent", '{"subagent":{}}', 0),
        ]:
            conn.execute(
                "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    str(tmp_path / (identity + ".jsonl")),
                    10,
                    20,
                    source,
                    str(tmp_path),
                    "title",
                    archived,
                    "question",
                ),
            )
    adapter = CodexSourceAdapter(
        Client(), marker_secret=b"test-secret", native_home=tmp_path
    )
    inventory = adapter.list_reconciliation_inventory(include_archived=False)
    assert [s.native_id for s in inventory] == ["missing"]
    assert inventory[0].last_active == 20
    assert {
        s.native_id
        for s in adapter.list_reconciliation_inventory(include_archived=True)
    } == {"missing", "archived"}
    assert adapter.list_recent_inventory(archived=False, after=100) == []
