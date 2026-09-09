from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.mirror_conversation import (
    MirrorConversationSync,
    TranscriptTail,
    conversational_turns,
    mirror_record_uuid,
    render_mirror_record,
    transcript_tail,
)
from session_bridge.models import (
    MIRROR_RECORD_KEY,
    OriginKind,
    ProjectedMessage,
    Provider,
    SessionProjection,
    is_mirrored_record,
)
from session_bridge.store import SessionBridgeStore

CLAUDE_UUID = "6d4b9f1e-3a2c-4c8e-9b1f-0f2a7c5d8e11"
SOURCE_NATIVE = "01a08476-520a-79c2-a907-d6d100d0a6a8"
SOURCE_ID = f"codex:{SOURCE_NATIVE}"
REGISTRATION_CWD = r"C:\Users\diego\.hermes"
PREFIX_USER_UUID = "9ccc7524-3d7e-4a33-a064-9697b6ade415"
PREFIX_ASSISTANT_UUID = "75c89ce6-cdb0-4b06-90e7-22bd99518810"


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def store(db):
    return SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)


def _message(
    event_id: str,
    content: str | None,
    *,
    role: str = "user",
    timestamp: float,
    tool_name: str | None = None,
) -> ProjectedMessage:
    return ProjectedMessage(
        native_event_id=event_id,
        ordinal=0,
        role=role,
        content=content,
        timestamp=timestamp,
        tool_name=tool_name,
        tool_calls=None,
        tool_call_id=None,
    )


def _source_projection(*messages: ProjectedMessage) -> SessionProjection:
    return SessionProjection(
        provider=Provider.CODEX,
        native_id=SOURCE_NATIVE,
        title="[Codex] a real request",
        cwd=REGISTRATION_CWD,
        started_at=10.0,
        last_active=max(message.timestamp for message in messages),
        messages=messages,
        native_path=f"C:/codex/{SOURCE_NATIVE}.jsonl",
        native_status="active",
        native_cursor="cursor-1",
        native_hash="hash-1",
        parser_version=3,
        origin_kind=OriginKind.NATIVE,
        origin_bridge_id=None,
    )


def _registration_prefix() -> list[dict]:
    """The records the registrar's ``claude -p`` run leaves in a mirror."""
    return [
        {
            "type": "custom-title",
            "customTitle": "[Codex] a real request",
            "sessionId": CLAUDE_UUID,
        },
        {
            "parentUuid": None,
            "isSidechain": False,
            "type": "user",
            "uuid": PREFIX_USER_UUID,
            "timestamp": "2026-09-09T13:59:51.209Z",
            "sessionId": CLAUDE_UUID,
            "cwd": REGISTRATION_CWD,
            "userType": "external",
            "entrypoint": "cli",
            "message": {
                "role": "user",
                "content": "This is a Hermes Session Bridge Claude visibility registration.\n"
                "Signed marker: HERMES_SESSION_BRIDGE_V1:abc.def",
            },
        },
        {
            "parentUuid": PREFIX_USER_UUID,
            "isSidechain": False,
            "type": "assistant",
            "uuid": PREFIX_ASSISTANT_UUID,
            "timestamp": "2026-09-09T13:59:52.927Z",
            "sessionId": CLAUDE_UUID,
            "cwd": REGISTRATION_CWD,
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "REGISTERED"}],
            },
        },
    ]


def _write_prefix(path: Path, records: list[dict] | None = None) -> bytes:
    payload = b"".join(
        json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        for record in (records or _registration_prefix())
    )
    path.write_bytes(payload)
    return payload


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _mirrored(path: Path) -> list[dict]:
    return [record for record in _records(path) if is_mirrored_record(record)]


def _text(record: dict) -> str:
    content = record["message"]["content"]
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content)


# --- conversational_turns -----------------------------------------------


def test_turns_keep_user_and_assistant_text_only() -> None:
    rows = [
        {"id": 1, "role": "user", "content": "first ask", "timestamp": 11.0},
        {"id": 2, "role": "assistant", "content": "on it", "timestamp": 12.0},
        {
            "id": 3,
            "role": "assistant",
            "content": None,
            "tool_calls": "[{}]",
            "timestamp": 13.0,
        },
        {
            "id": 4,
            "role": "tool",
            "content": "tool output",
            "tool_name": "shell",
            "timestamp": 14.0,
        },
        {"id": 5, "role": "user", "content": "   ", "timestamp": 15.0},
        {"id": 6, "role": "user", "content": "<skill>\ninjected", "timestamp": 16.0},
        {
            "id": 7,
            "role": "user",
            "content": "# AGENTS.md instructions for repo",
            "timestamp": 17.0,
        },
        {"id": 8, "role": "assistant", "content": "done", "timestamp": "bad"},
    ]

    turns = conversational_turns(rows)

    assert [(turn["message_id"], turn["role"], turn["content"]) for turn in turns] == [
        (1, "user", "first ask"),
        (2, "assistant", "on it"),
        (8, "assistant", "done"),
    ]
    assert turns[0]["timestamp"] == 11.0
    assert turns[2]["timestamp"] is None


def test_turns_redact_secrets_and_cap_length() -> None:
    long_text = "x" * 500
    rows = [
        {
            "id": 1,
            "role": "user",
            "content": "use Authorization: Bearer abc.def-123 please",
            "timestamp": 1.0,
        },
        {"id": 2, "role": "assistant", "content": long_text, "timestamp": 2.0},
    ]

    turns = conversational_turns(rows, message_chars=200)

    assert "abc.def-123" not in turns[0]["content"]
    assert "[REDACTED]" in turns[0]["content"]
    assert len(turns[1]["content"]) <= 200
    assert turns[1]["content"].endswith("[truncated by Hermes mirror]")


def test_turns_drop_the_bridges_own_registration_prompts() -> None:
    rows = [
        {
            "id": 1,
            "role": "user",
            "content": "This is a Hermes Session Bridge Claude visibility registration. "
            "Signed marker: HERMES_SESSION_BRIDGE_V1:abc.def",
            "timestamp": 1.0,
        },
        {"id": 2, "role": "assistant", "content": "REGISTERED", "timestamp": 2.0},
        {"id": 3, "role": "user", "content": "real work", "timestamp": 3.0},
    ]

    turns = conversational_turns(rows)

    # The registration prompt is excluded by the visibility lane's own test and
    # the bare REGISTERED acknowledgement by the preview renderer's; only the
    # human request survives.
    assert [turn["message_id"] for turn in turns] == [3]


# --- render_mirror_record ------------------------------------------------


def test_render_record_matches_desktop_transcript_shape_and_is_tagged() -> None:
    record = render_mirror_record(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        cwd=REGISTRATION_CWD,
        parent_uuid=PREFIX_ASSISTANT_UUID,
        turn={"message_id": 7, "role": "assistant", "content": "hi", "timestamp": 0.5},
    )

    assert record["type"] == "assistant"
    assert record["parentUuid"] == PREFIX_ASSISTANT_UUID
    assert record["sessionId"] == CLAUDE_UUID
    assert record["cwd"] == REGISTRATION_CWD
    assert record["isSidechain"] is False
    assert record["timestamp"] == "1970-01-01T00:00:00.500Z"
    assert record["message"]["role"] == "assistant"
    assert record["message"]["content"] == [{"type": "text", "text": "hi"}]
    assert record["message"]["model"] == "codex"
    assert record[MIRROR_RECORD_KEY] == {
        "version": 1,
        "source_session_id": SOURCE_ID,
        "message_id": 7,
    }
    assert is_mirrored_record(record)
    assert record["uuid"] == mirror_record_uuid(CLAUDE_UUID, SOURCE_ID, 7)
    # Deterministic: a re-render of the same source turn is the same record id.
    assert mirror_record_uuid(CLAUDE_UUID, SOURCE_ID, 7) == mirror_record_uuid(
        CLAUDE_UUID, SOURCE_ID, 7
    )
    assert mirror_record_uuid(CLAUDE_UUID, SOURCE_ID, 8) != record["uuid"]

    user = render_mirror_record(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        cwd=REGISTRATION_CWD,
        parent_uuid=record["uuid"],
        turn={"message_id": 8, "role": "user", "content": "ask", "timestamp": None},
    )
    assert user["message"] == {"role": "user", "content": "ask"}
    assert user["parentUuid"] == record["uuid"]


def test_transcript_tail_reads_leaf_uuid_and_first_cwd(tmp_path) -> None:
    path = tmp_path / "mirror.jsonl"
    _write_prefix(path)

    assert transcript_tail(path) == TranscriptTail(PREFIX_ASSISTANT_UUID, REGISTRATION_CWD)
    assert transcript_tail(tmp_path / "missing.jsonl") == TranscriptTail(None, None)


# --- MirrorConversationSync ----------------------------------------------


def test_sync_appends_source_turns_after_the_registration_prefix(
    store, tmp_path
) -> None:
    store.upsert_projection(
        _source_projection(
            _message("e1", "please fix the build", timestamp=50.0),
            _message("e2", "Looking at the failing step now.", role="assistant", timestamp=51.0),
            _message("e3", "thanks", timestamp=52.0),
        )
    )
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    prefix = _write_prefix(path)
    sync = MirrorConversationSync(store)

    result = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    assert result.status == "appended"
    assert result.appended == 3
    # Append-only: the registration prefix is byte-identical.
    assert path.read_bytes().startswith(prefix)
    mirrored = _mirrored(path)
    assert [(record["type"], _text(record)) for record in mirrored] == [
        ("user", "please fix the build"),
        ("assistant", "Looking at the failing step now."),
        ("user", "thanks"),
    ]
    # Chained from the prefix leaf, then from each other.
    assert mirrored[0]["parentUuid"] == PREFIX_ASSISTANT_UUID
    assert mirrored[1]["parentUuid"] == mirrored[0]["uuid"]
    assert mirrored[2]["parentUuid"] == mirrored[1]["uuid"]
    assert all(record["sessionId"] == CLAUDE_UUID for record in mirrored)
    assert all(record["cwd"] == REGISTRATION_CWD for record in mirrored)
    # Every prefix record is still present and untagged.
    assert len(_records(path)) == len(_registration_prefix()) + 3

    # A second pass with nothing new is idle and writes nothing.
    size = path.stat().st_size
    again = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )
    assert again.status == "idle"
    assert path.stat().st_size == size


def test_sync_appends_only_new_turns_on_later_passes(store, tmp_path) -> None:
    first = _message("e1", "first", timestamp=50.0)
    store.upsert_projection(_source_projection(first))
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    _write_prefix(path)
    sync = MirrorConversationSync(store)
    sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )
    leaf_before = _mirrored(path)[-1]["uuid"]

    store.upsert_projection(
        _source_projection(
            first,
            _message("e2", "second", role="assistant", timestamp=60.0),
        )
    )
    result = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    assert result.status == "appended"
    assert result.appended == 1
    mirrored = _mirrored(path)
    assert [_text(record) for record in mirrored] == ["first", "second"]
    assert mirrored[1]["parentUuid"] == leaf_before


def test_first_sync_caps_backfill_and_says_what_it_dropped(store, tmp_path) -> None:
    store.upsert_projection(
        _source_projection(
            *[
                _message(f"e{index}", f"turn {index}", timestamp=50.0 + index)
                for index in range(1, 6)
            ]
        )
    )
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    _write_prefix(path)
    sync = MirrorConversationSync(store, backfill_messages=2)

    result = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    assert result.appended == 3
    mirrored = _mirrored(path)
    assert "3 earlier message(s)" in _text(mirrored[0])
    assert [_text(record) for record in mirrored[1:]] == ["turn 4", "turn 5"]
    assert mirrored[0]["parentUuid"] == PREFIX_ASSISTANT_UUID
    assert mirrored[1]["parentUuid"] == mirrored[0]["uuid"]


def test_sync_falls_back_to_the_transcripts_cwd(store, tmp_path) -> None:
    store.upsert_projection(_source_projection(_message("e1", "hello", timestamp=50.0)))
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    _write_prefix(path)

    MirrorConversationSync(store).sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd="",
    )

    assert _mirrored(path)[0]["cwd"] == REGISTRATION_CWD


def test_sync_skips_a_transcript_without_a_chained_record(store, tmp_path) -> None:
    store.upsert_projection(_source_projection(_message("e1", "hello", timestamp=50.0)))
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    result = MirrorConversationSync(store).sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    assert result.status == "skipped"
    assert result.reason == "mirror transcript has no leaf record"
    assert path.read_text(encoding="utf-8") == "{}\n"


def test_sync_remembers_rows_that_produced_nothing(store, tmp_path) -> None:
    store.upsert_projection(
        _source_projection(_message("e1", "<skill>\ninjected only", timestamp=50.0))
    )
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    prefix = _write_prefix(path)
    sync = MirrorConversationSync(store)

    assert sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    ).status == "idle"
    assert path.read_bytes() == prefix
    ledger = store.get_state("session-bridge:claude-visibility:mirror-conversation")
    assert ledger[CLAUDE_UUID]["last_message_id"] >= 1
    assert ledger[CLAUDE_UUID]["mirrored"] == 0


def test_sync_terminates_an_unterminated_prefix_before_appending(store, tmp_path) -> None:
    store.upsert_projection(_source_projection(_message("e1", "hello", timestamp=50.0)))
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    prefix = _write_prefix(path).rstrip(b"\n")
    path.write_bytes(prefix)

    MirrorConversationSync(store).sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    records = _records(path)
    assert len(records) == len(_registration_prefix()) + 1
    assert is_mirrored_record(records[-1])


# --- Codex rollout reader ------------------------------------------------


def _rollout_line(record: dict) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"


def _rollout_message(role: str, text: str, *, stamp: str) -> dict:
    block_type = "output_text" if role == "assistant" else "input_text"
    return {
        "timestamp": stamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": f"msg_{role}_{stamp}",
            "role": role,
            "content": [{"type": block_type, "text": text}],
        },
    }


def _write_rollout(path: Path) -> bytes:
    lines = [
        _rollout_line(
            {
                "timestamp": "2026-09-08T02:57:18.957Z",
                "type": "session_meta",
                "payload": {"id": SOURCE_NATIVE, "cwd": REGISTRATION_CWD},
            }
        ),
        _rollout_line(
            _rollout_message("developer", "<app-context>", stamp="2026-09-08T02:57:19.411Z")
        ),
        _rollout_line(
            _rollout_message(
                "user",
                "<recommended_plugins>\nHere is a list",
                stamp="2026-09-08T02:57:19.411Z",
            )
        ),
        _rollout_line(
            _rollout_message(
                "user", "do a thorough /arch-review", stamp="2026-09-08T02:57:19.500Z"
            )
        ),
        _rollout_line(
            {
                "timestamp": "2026-09-08T02:57:20.000Z",
                "type": "response_item",
                "payload": {"type": "function_call", "name": "shell", "arguments": "{}"},
            }
        ),
        _rollout_line(
            _rollout_message(
                "assistant",
                "I'm using the arch-review skill to review the platform.",
                stamp="2026-09-08T02:57:26.849Z",
            )
        ),
        _rollout_line(
            {
                "timestamp": "2026-09-08T03:16:05.078Z",
                "type": "compacted",
                "payload": {
                    "message": "",
                    "replacement_history": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "do a thorough /arch-review"}
                            ],
                        }
                    ],
                },
            }
        ),
    ]
    payload = b"".join(lines)
    path.write_bytes(payload)
    return payload


def test_rollout_rows_resume_by_offset_and_skip_noise(tmp_path) -> None:
    from session_bridge.mirror_conversation import read_codex_rollout_rows

    path = tmp_path / "rollout.jsonl"
    complete = _write_rollout(path)
    partial = _rollout_line(
        _rollout_message("assistant", "half written", stamp="2026-09-08T03:20:00.000Z")
    )[:-10]
    path.write_bytes(complete + partial)

    rows, consumed = read_codex_rollout_rows(path, after_offset=None)

    assert [(row["role"], row["content"]) for row in rows] == [
        ("user", "<recommended_plugins>\nHere is a list"),
        ("user", "do a thorough /arch-review"),
        ("assistant", "I'm using the arch-review skill to review the platform."),
    ]
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    assert rows[1]["timestamp"] == pytest.approx(1788836239.5)
    # The unterminated line is not consumed; the offset stops before it.
    assert consumed == len(complete)

    # Finishing that line and adding one more yields exactly the new rows.
    finished = _rollout_line(
        _rollout_message("assistant", "half written", stamp="2026-09-08T03:20:00.000Z")
    )
    extra = _rollout_line(
        _rollout_message("user", "thanks", stamp="2026-09-08T03:21:00.000Z")
    )
    path.write_bytes(complete + finished + extra)
    rows, consumed = read_codex_rollout_rows(path, after_offset=consumed)
    assert [row["content"] for row in rows] == ["half written", "thanks"]
    assert consumed == len(complete) + len(finished) + len(extra)
    assert read_codex_rollout_rows(path, after_offset=consumed) == ([], consumed)

    # The injected-context user turn is dropped by the shared filter.
    turns = conversational_turns(read_codex_rollout_rows(path, after_offset=None)[0])
    assert [turn["content"] for turn in turns][:2] == [
        "do a thorough /arch-review",
        "I'm using the arch-review skill to review the platform.",
    ]


def _under_collected_source(store, rollout: Path) -> None:
    """The catalog holds ONE message for the thread; the rollout holds all."""
    projection = _source_projection(
        _message("e1", "do a thorough /arch-review", timestamp=1788836239.5)
    )
    from dataclasses import replace

    store.upsert_projection(replace(projection, native_path=str(rollout)))


def test_sync_reads_a_codex_source_from_its_rollout_file(store, tmp_path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    complete = _write_rollout(rollout)
    _under_collected_source(store, rollout)
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    _write_prefix(path)
    sync = MirrorConversationSync(store)

    result = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    assert result.status == "appended"
    assert [_text(record) for record in _mirrored(path)] == [
        "do a thorough /arch-review",
        "I'm using the arch-review skill to review the platform.",
    ]
    ledger = store.get_state("session-bridge:claude-visibility:mirror-conversation")
    assert ledger[CLAUDE_UUID]["mode"] == "rollout"
    assert ledger[CLAUDE_UUID]["last_message_id"] == len(complete)

    rollout.write_bytes(
        complete
        + _rollout_line(
            _rollout_message("user", "thanks", stamp="2026-09-08T03:21:00.000Z")
        )
    )
    again = sync.sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )
    assert again.appended == 1
    assert _text(_mirrored(path)[-1]) == "thanks"


def test_sync_pins_store_mode_when_the_rollout_is_missing(store, tmp_path) -> None:
    store.upsert_projection(_source_projection(_message("e1", "hello", timestamp=50.0)))
    path = tmp_path / f"{CLAUDE_UUID}.jsonl"
    _write_prefix(path)

    MirrorConversationSync(store).sync(
        claude_uuid=CLAUDE_UUID,
        source_session_id=SOURCE_ID,
        native_path=str(path),
        cwd=REGISTRATION_CWD,
    )

    ledger = store.get_state("session-bridge:claude-visibility:mirror-conversation")
    assert ledger[CLAUDE_UUID]["mode"] == "store"
    assert [_text(record) for record in _mirrored(path)] == ["hello"]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"backfill_messages": 0}, "backfill_messages must be a positive integer"),
        ({"message_chars": 10}, "message_chars must be at least 100"),
    ],
)
def test_sync_rejects_degenerate_bounds(store, kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        MirrorConversationSync(store, **kwargs)


def test_turns_drop_harness_envelope_user_turns_but_keep_quoting_assistants() -> None:
    from session_bridge.mirror_conversation import is_envelope_user_text

    rows = [
        {"id": 1, "role": "user", "content": "<environment_context>\n<cwd>C:/x</cwd>", "timestamp": 1.0},
        {"id": 2, "role": "user", "content": "  <task-notification>\n<task-id>x</task-id>", "timestamp": 2.0},
        {"id": 3, "role": "user", "content": "<heartbeat>\n<automation_id>a</automation_id>", "timestamp": 3.0},
        {"id": 4, "role": "user", "content": "<command-message>bye</command-message>", "timestamp": 4.0},
        {"id": 5, "role": "user", "content": "please look at <heartbeat> handling", "timestamp": 5.0},
        {"id": 6, "role": "assistant", "content": "The envelope is `<heartbeat>...</heartbeat>`.", "timestamp": 6.0},
    ]

    turns = conversational_turns(rows)

    assert [turn["message_id"] for turn in turns] == [5, 6]
    assert is_envelope_user_text("<system-reminder>\nx") is True
    assert is_envelope_user_text("hello <system-reminder>") is False
    assert is_envelope_user_text(None) is False
