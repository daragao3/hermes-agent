from __future__ import annotations

import json
import os
from datetime import timezone
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.claude_visibility import (
    ClaudeVisibilityCandidate,
    derive_claude_visibility_identity,
)
from session_bridge.mirror_float import (
    ClaudeMirrorFloatWorker,
    discover_ccd_convergence_roots,
    discover_ccd_registry_roots,
)
from session_bridge.models import (
    OriginKind,
    ProjectedMessage,
    Provider,
    SessionProjection,
)
from session_bridge.store import SessionBridgeStore

_SECRET = b"mirror-float-test-secret"


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def _message(event_id: str, content: str, *, role: str = "user") -> ProjectedMessage:
    return ProjectedMessage(
        native_event_id=event_id,
        ordinal=0,
        role=role,
        content=content,
        timestamp=10.0 + len(event_id),
        tool_calls=None,
        tool_call_id=None,
    )


def _projection(
    *messages: ProjectedMessage,
    provider: Provider = Provider.CLAUDE,
    native_id: str = "native-1",
    last_active: float = 20.0,
    native_path: str | None = None,
    origin_kind: OriginKind = OriginKind.NATIVE,
    origin_bridge_id: str | None = None,
) -> SessionProjection:
    return SessionProjection(
        provider=provider,
        native_id=native_id,
        title=f"{provider.value} session",
        cwd="C:/workspace/project",
        started_at=10.0,
        last_active=last_active,
        messages=messages,
        native_path=native_path or f"C:/{provider.value}/{native_id}.jsonl",
        native_status="active",
        native_cursor=f"cursor-{native_id}",
        native_hash=f"hash-{native_id}",
        git_branch=None,
        parser_version=3,
        origin_kind=origin_kind,
        origin_bridge_id=origin_bridge_id,
    )


def _identity(
    suffix: str,
    *,
    provider: Provider = Provider.CODEX,
) -> tuple[ClaudeVisibilityCandidate, object]:
    source_session_id = (
        f"codex:source-{suffix}"
        if provider is Provider.CODEX
        else f"hermes-source-{suffix}"
    )
    candidate = ClaudeVisibilityCandidate(
        source_session_id=source_session_id,
        source_provider=provider,
        native_name=f"[{provider.value.title()}] Request {suffix}",
        source_cwd="C:/work/project",
        git_root="C:/work/project",
        git_branch="main",
        git_head=f"head-{suffix}",
        worktree_id=f"worktree-{suffix}",
        eligible_at=100.0,
    )
    return candidate, derive_claude_visibility_identity(candidate, _SECRET)


def _seed_visible_mirror(
    db: SessionDB,
    store: SessionBridgeStore,
    tmp_path: Path,
    *,
    suffix: str = "1",
    provider: Provider = Provider.CODEX,
    source_last_active: float = 5_000.0,
    mirror_mtime: float = 1_000.0,
    create_mirror_file: bool = True,
    origin_bridge_id: str | None = None,
):
    candidate, identity = _identity(suffix, provider=provider)
    if provider is Provider.CODEX:
        store.upsert_projection(
            _projection(
                _message(f"source-{suffix}", "meaningful request"),
                provider=Provider.CODEX,
                native_id=candidate.source_session_id.removeprefix("codex:"),
                last_active=source_last_active,
            )
        )
    else:
        db.create_session(session_id=candidate.source_session_id, source="hermes")
        db.append_message(
            session_id=candidate.source_session_id,
            role="user",
            content="meaningful request",
            timestamp=source_last_active,
        )
    store.enqueue_claude_visibility_job(candidate, identity, _SECRET)
    claim = store.claim_claude_visibility_job(100.0, 60, 25, "0.50", "0.02")
    store.commit_claude_visibility_job(
        identity.job_id, claim.lease_digest, "a" * 64, 100.0
    )
    mirror_path = tmp_path / f"{identity.claude_uuid}.jsonl"
    if create_mirror_file:
        mirror_path.write_text("{}\n", encoding="utf-8")
        os.utime(mirror_path, (mirror_mtime, mirror_mtime))
    store.upsert_projection(
        _projection(
            _message(f"target-{suffix}", "signed registration"),
            native_id=identity.claude_uuid,
            native_path=str(mirror_path),
            origin_kind=OriginKind.BRIDGE_PLACEHOLDER,
            origin_bridge_id=origin_bridge_id or identity.bridge_id,
        )
    )
    return identity, mirror_path


def test_store_lists_only_visible_claude_visibility_mirrors(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(db, store, tmp_path, suffix="1")
    registered_candidate, registered_identity = _identity("2")
    store.upsert_projection(
        _projection(
            _message("source-2", "meaningful request"),
            provider=Provider.CODEX,
            native_id="source-2",
        )
    )
    store.enqueue_claude_visibility_job(
        registered_candidate, registered_identity, _SECRET
    )

    rows = store.list_visible_claude_visibility_mirrors()

    assert rows == [
        {
            "source_session_id": "codex:source-1",
            "claude_uuid": identity.claude_uuid,
        }
    ]


def test_floats_mirror_to_source_activity(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0)

    result = worker.run_once()

    assert result == {
        "examined": 1,
        "floated": 1,
        "skipped": 0,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 0,
    }
    assert mirror_path.stat().st_mtime == pytest.approx(5_000.0)


def _registry_records(registry_root: Path) -> list[dict]:
    import json

    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(registry_root.glob("local_*.json"))
    ]


def test_creates_ccd_registry_record_for_visible_mirror(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=registry,
        id_factory=lambda: "11111111-2222-4333-8444-555555555555",
    )

    result = worker.run_once()

    assert result["registered"] == 1
    records = _registry_records(registry)
    assert len(records) == 1
    record = records[0]
    # Record id is DERIVED from cliSessionId, not minted per-harness, so every
    # harness store holds the same filename for one logical session.
    assert record["sessionId"] == f"local_{identity.claude_uuid}"
    assert record["cliSessionId"] == identity.claude_uuid
    assert record["lastActivityAt"] == 5_000_000
    assert record["title"] == "claude session"
    assert record["cwd"] == "C:/workspace/project"
    # Mirrors land archived so imported automation traffic never buries the
    # user's real sessions in the sidebar.
    assert record["isArchived"] is True
    assert record["permissionMode"] == "default"


def test_recently_active_mirror_registers_unarchived(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=registry,
        wall_clock=lambda: 6_000.0,
    )

    result = worker.run_once()

    assert result["registered"] == 1
    record = _registry_records(registry)[0]
    # A source active within the recency window surfaces directly in the
    # sidebar; only historical backfill lands archived.
    assert record["isArchived"] is False


def test_stale_mirror_registers_archived(db, tmp_path) -> None:
    from session_bridge.mirror_float import _RECENT_UNARCHIVED_SECONDS

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=registry,
        wall_clock=lambda: 5_000.0 + _RECENT_UNARCHIVED_SECONDS + 1.0,
    )

    result = worker.run_once()

    assert result["registered"] == 1
    assert _registry_records(registry)[0]["isArchived"] is True


def test_float_update_preserves_manual_unarchive(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    record_path = registry / f"local_{identity.claude_uuid}.json"
    record_path.write_text(
        json.dumps(
            {
                "sessionId": f"local_{identity.claude_uuid}",
                "cliSessionId": identity.claude_uuid,
                "lastActivityAt": 1_000,
                "isArchived": False,
                "title": "kept",
            }
        ),
        encoding="utf-8",
    )
    worker = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    )

    worker.run_once()

    record = json.loads(record_path.read_text(encoding="utf-8"))
    # The float path only advances lastActivityAt; an operator's (or the
    # recency rule's) unarchived state must survive subsequent cycles.
    assert record["lastActivityAt"] == 5_000_000
    assert record["isArchived"] is False


def _seed_unarchived_record(registry: Path, identity, *, last_activity: int) -> Path:
    registry.mkdir(exist_ok=True)
    record_path = registry / f"local_{identity.claude_uuid}.json"
    record_path.write_text(
        json.dumps(
            {
                "sessionId": f"local_{identity.claude_uuid}",
                "cliSessionId": identity.claude_uuid,
                "lastActivityAt": last_activity,
                "isArchived": False,
                "title": "[Codex] a mirror",
            }
        ),
        encoding="utf-8",
    )
    return record_path


_FOUR_DAYS_AFTER = 5_000.0 + 4 * 86_400
_ONE_HOUR_AFTER = 5_000.0 + 3_600


def test_idle_mirror_is_auto_archived_when_axis_enabled(db, tmp_path) -> None:
    """The creation-time recency rule, applied continuously instead of once.

    A mirror whose source has gone idle past the threshold is archived on a
    later cycle. Without this the rule fires only at creation, so mirrors of
    sources that were active at registration stay unarchived forever and the
    sidebar fills until a human sweeps it.
    """

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    record_path = _seed_unarchived_record(
        tmp_path / "registry", identity, last_activity=5_000_000
    )

    ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=tmp_path / "registry",
        archive_idle_seconds=3 * 86_400,
        wall_clock=lambda: _FOUR_DAYS_AFTER,
    ).run_once()

    assert json.loads(record_path.read_text(encoding="utf-8"))["isArchived"] is True


def test_idle_mirror_is_left_alone_when_axis_is_off(db, tmp_path) -> None:
    """Default is OFF: nobody inherits a new reaping axis by upgrading."""

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    record_path = _seed_unarchived_record(
        tmp_path / "registry", identity, last_activity=5_000_000
    )

    ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=tmp_path / "registry",
        wall_clock=lambda: _FOUR_DAYS_AFTER,
    ).run_once()

    assert json.loads(record_path.read_text(encoding="utf-8"))["isArchived"] is False


def test_active_mirror_is_not_auto_archived(db, tmp_path) -> None:
    """Liveness is read from the SOURCE session, not the record's own stamp."""

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    record_path = _seed_unarchived_record(
        tmp_path / "registry", identity, last_activity=5_000_000
    )

    ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=tmp_path / "registry",
        archive_idle_seconds=3 * 86_400,
        wall_clock=lambda: _ONE_HOUR_AFTER,
    ).run_once()

    assert json.loads(record_path.read_text(encoding="utf-8"))["isArchived"] is False


def test_auto_archive_never_overrides_a_manual_unarchive(db, tmp_path) -> None:
    """Each record is auto-archived AT MOST ONCE, so a human's undo is final.

    test_float_update_preserves_manual_unarchive pins that the float path may
    not flip an operator's unarchived state. This axis must not smuggle that
    flip back in: once a record has been auto-archived, the worker records it
    and never touches its archive flag again, whatever the operator does next.
    """

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    record_path = _seed_unarchived_record(registry, identity, last_activity=5_000_000)

    def _worker() -> ClaudeMirrorFloatWorker:
        return ClaudeMirrorFloatWorker(
            store,
            min_interval_seconds=900.0,
            registry_root=registry,
            archive_idle_seconds=3 * 86_400,
            wall_clock=lambda: _FOUR_DAYS_AFTER,
            run_min_interval_seconds=0.0,
        )

    _worker().run_once()
    assert json.loads(record_path.read_text(encoding="utf-8"))["isArchived"] is True

    # The operator brings it back deliberately.
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["isArchived"] = False
    record_path.write_text(json.dumps(record), encoding="utf-8")

    _worker().run_once()

    assert json.loads(record_path.read_text(encoding="utf-8"))["isArchived"] is False


def test_float_update_retries_and_preserves_concurrent_archive_change(
    db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    record_path = registry / f"local_{identity.claude_uuid}.json"
    record_path.write_text(
        json.dumps(
            {
                "sessionId": f"local_{identity.claude_uuid}",
                "cliSessionId": identity.claude_uuid,
                "lastActivityAt": 1_000,
                "isArchived": False,
            }
        ),
        encoding="utf-8",
    )
    actual_read = Path.read_bytes
    calls = {"target": 0}

    def racing_read(path: Path) -> bytes:
        if path == record_path:
            calls["target"] += 1
            if calls["target"] == 2:
                concurrent = json.loads(actual_read(path).decode("utf-8"))
                concurrent["isArchived"] = True
                concurrent["desktopField"] = "preserved"
                path.write_text(json.dumps(concurrent), encoding="utf-8")
        return actual_read(path)

    monkeypatch.setattr(Path, "read_bytes", racing_read)

    result = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert result["floated"] == 1
    assert record["lastActivityAt"] == 5_000_000
    assert record["isArchived"] is True
    assert record["desktopField"] == "preserved"
    assert not list(registry.glob(f".{record_path.name}.*.tmp"))


def test_create_collision_never_overwrites_concurrent_destination(
    db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(db, store, tmp_path)
    registry = tmp_path / "registry"
    registry.mkdir()
    destination = registry / f"local_{identity.claude_uuid}.json"
    concurrent = {
        "sessionId": f"local_{identity.claude_uuid}",
        "cliSessionId": identity.claude_uuid,
        "lastActivityAt": 123,
        "desktopOwned": True,
    }
    from session_bridge import mirror_float

    actual_publish = mirror_float._publish_record_create_only

    def publish_after_desktop(path: Path, record) -> bool:
        path.write_text(json.dumps(concurrent), encoding="utf-8")
        return actual_publish(path, record)

    monkeypatch.setattr(
        "session_bridge.mirror_float._publish_record_create_only",
        publish_after_desktop,
    )

    result = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    assert result["registered"] == 0
    assert json.loads(destination.read_text(encoding="utf-8")) == concurrent
    assert not list(registry.glob(f".{destination.name}.*.tmp"))


def test_registry_record_title_falls_back_to_cwd_not_uuid(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(db, store, tmp_path)
    # Wipe the catalog title to force the fallback path.
    store.db._conn.execute(
        "UPDATE sessions SET title = NULL WHERE id = ?",
        (f"claude:{identity.claude_uuid}",),
    )
    store.db._conn.commit()
    registry = tmp_path / "registry"
    registry.mkdir()
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0,
                                     registry_root=registry)

    result = worker.run_once()

    assert result["registered"] == 1
    record = _registry_records(registry)[0]
    assert "[Bridge]" in record["title"]
    assert identity.claude_uuid not in record["title"]


def test_registry_record_ids_are_identical_across_harnesses(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, _ = _seed_visible_mirror(db, store, tmp_path)
    root_a = tmp_path / "registry-a"
    root_b = tmp_path / "registry-b"
    root_a.mkdir()
    root_b.mkdir()
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0,
                                     registry_roots=[root_a, root_b])

    result = worker.run_once()

    assert result["registered"] == 1
    names_a = {p.name for p in root_a.glob("local_*.json")}
    names_b = {p.name for p in root_b.glob("local_*.json")}
    assert names_a == names_b == {f"local_{identity.claude_uuid}.json"}


def test_registry_record_is_idempotent_by_cli_session_id(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()

    first = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()
    second = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    assert first["registered"] == 1
    assert second["registered"] == 0
    assert len(_registry_records(registry)) == 1


def test_registry_record_floats_on_new_source_activity(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db,
        store,
        tmp_path,
        suffix="1",
        source_last_active=5_000.0,
        mirror_mtime=1_000.0,
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    store.upsert_projection(
        _projection(
            _message("source-1-later", "another meaningful request"),
            provider=Provider.CODEX,
            native_id="source-1",
            last_active=9_000.0,
        )
    )
    result = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    assert result["floated"] == 1
    records = _registry_records(registry)
    assert len(records) == 1
    assert records[0]["lastActivityAt"] == 9_000_000


def test_registry_tolerates_malformed_foreign_record(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "local_broken.json").write_text("{not json", encoding="utf-8")
    foreign = registry / "local_foreign.json"
    foreign.write_text('{"sessionId": "local_foreign"}', encoding="utf-8")

    result = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_root=registry
    ).run_once()

    assert result["registered"] == 1
    assert foreign.read_text(encoding="utf-8") == '{"sessionId": "local_foreign"}'


def test_run_once_is_internally_throttled(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    clock = {"now": 0.0}
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        run_min_interval_seconds=300.0,
        monotonic=lambda: clock["now"],
    )

    first = worker.run_once()
    clock["now"] = 10.0
    second = worker.run_once()
    clock["now"] = 400.0
    third = worker.run_once()

    assert first["examined"] == 1
    assert second == {
        "examined": 0,
        "floated": 0,
        "skipped": 0,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 1,
    }
    assert third["examined"] == 1


def test_discover_registry_root_picks_single_leaf(tmp_path) -> None:
    from session_bridge.mirror_float import discover_ccd_registry_root

    base = tmp_path / "claude-code-sessions"
    leaf = base / "org-a" / "user-b"
    leaf.mkdir(parents=True)
    (leaf / "local_x.json").write_text("{}", encoding="utf-8")
    empty = base / "org-a" / "user-c"
    empty.mkdir(parents=True)

    assert discover_ccd_registry_root(base) == leaf
    assert discover_ccd_registry_root(tmp_path / "absent") is None


def test_skips_bump_within_min_interval(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=1_500.0, mirror_mtime=1_000.0
    )
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0)

    result = worker.run_once()

    assert result == {
        "examined": 1,
        "floated": 0,
        "skipped": 0,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 0,
    }
    assert mirror_path.stat().st_mtime == pytest.approx(1_000.0)


def test_skips_missing_mirror_file_without_raising(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(db, store, tmp_path, create_mirror_file=False)
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0)

    result = worker.run_once()

    assert result == {
        "examined": 1,
        "floated": 0,
        "skipped": 1,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 0,
    }


def test_refuses_mirror_with_foreign_origin(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _, mirror_path = _seed_visible_mirror(
        db,
        store,
        tmp_path,
        origin_bridge_id="sidebar:not-a-visibility-mirror",
    )
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0)

    result = worker.run_once()

    assert result == {
        "examined": 1,
        "floated": 0,
        "skipped": 1,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 0,
    }
    assert mirror_path.stat().st_mtime == pytest.approx(1_000.0)


def test_config_parses_claude_visibility_float_activity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from session_bridge.config import BridgeConfig

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "session_bridge": {
                "claude_visibility": {"enabled": True, "float_activity": True}
            }
        },
    )

    config = BridgeConfig.load(path=tmp_path / "session_bridge.toml")

    assert config.claude_visibility.float_activity is True
    assert ClaudeMirrorFloatWorker is not None


def test_config_float_activity_defaults_false_and_rejects_non_bool(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from session_bridge.config import BridgeConfig

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"session_bridge": {}},
    )
    assert (
        BridgeConfig.load(
            path=tmp_path / "session_bridge.toml"
        ).claude_visibility.float_activity
        is False
    )

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"session_bridge": {"claude_visibility": {"float_activity": "yes"}}},
    )
    with pytest.raises(ValueError, match="float_activity"):
        BridgeConfig.load(path=tmp_path / "session_bridge.toml")


def _serve_runtime_coordinator(db, monkeypatch, *, float_activity: bool):
    from dataclasses import replace

    from session_bridge.catalog import UnifiedCatalog
    from session_bridge.cli import ProductionBackend
    from session_bridge.config import BridgeConfig, ClaudeVisibilityConfig

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    backend = ProductionBackend(
        replace(
            BridgeConfig(),
            claude_visibility=replace(
                ClaudeVisibilityConfig(),
                enabled=True,
                float_activity=float_activity,
            ),
        )
    )
    backend._db = db
    backend._store = store
    backend._catalog = UnifiedCatalog(db, store)
    monkeypatch.setattr("session_bridge.cli.resolve_marker_key", lambda: b"k" * 32)
    monkeypatch.setattr(
        "session_bridge.cli.resolve_cli_executable", lambda name: (name,)
    )
    return backend._provider_runtime(
        targets=False, catalog_only=False, providers=(Provider.CLAUDE,)
    )


def test_serve_runtime_wires_mirror_float_when_configured(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = Path("C:/sentinel-registry")
    other = Path("C:/sentinel-registry-3p")
    monkeypatch.setattr(
        "session_bridge.cli.discover_ccd_registry_roots", lambda: (sentinel, other)
    )
    coordinator = _serve_runtime_coordinator(db, monkeypatch, float_activity=True)
    assert isinstance(coordinator._mirror_float, ClaudeMirrorFloatWorker)
    assert coordinator._mirror_float._registry_roots == (sentinel, other)
    assert coordinator._mirror_float._registry_root == sentinel


def test_serve_runtime_omits_mirror_float_when_disabled(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _serve_runtime_coordinator(db, monkeypatch, float_activity=False)
    assert coordinator._mirror_float is None


def _make_harness(
    user_data_dir: Path, account: str, workspace: str, records: int
) -> Path:
    """Build a Claude Code desktop userData dir with one populated registry leaf."""
    user_data_dir.mkdir(parents=True, exist_ok=True)
    (user_data_dir / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": account}), encoding="utf-8"
    )
    leaf = user_data_dir / "claude-code-sessions" / account / workspace
    leaf.mkdir(parents=True, exist_ok=True)
    for index in range(records):
        (leaf / f"local_{index}.json").write_text(
            json.dumps({"cliSessionId": f"uuid-{index}"}), encoding="utf-8"
        )
    return leaf


def test_discover_registry_roots_covers_every_harness(tmp_path) -> None:
    main_leaf = _make_harness(tmp_path / "Claude", "acct-main", "ws-main", 3)
    third_party_leaf = _make_harness(tmp_path / "Claude-3p", "acct-3p", "ws-3p", 2)

    roots = discover_ccd_registry_roots(
        (tmp_path / "Claude", tmp_path / "Claude-3p")
    )

    assert set(roots) == {main_leaf, third_party_leaf}


def test_discover_registry_roots_ignores_backup_siblings(tmp_path) -> None:
    """A recovery backup can hold MORE records than the live leaf.

    The 3P store on this machine carries `.junction-backup-*` siblings that
    junction back into the subscription store, so ranking leaves by population
    silently resolves to the wrong harness.
    """
    leaf = _make_harness(tmp_path / "Claude-3p", "acct-3p", "ws-3p", 2)
    account_dir = leaf.parent
    decoy = account_dir / "ws-3p.junction-backup-20260809T2031384958"
    decoy.mkdir()
    for index in range(50):
        (decoy / f"local_b{index}.json").write_text(
            json.dumps({"cliSessionId": f"backup-{index}"}), encoding="utf-8"
        )
    (account_dir / "recovery-backup-20260809T2031384958").mkdir()
    (account_dir / "ws-3p.real-20260728").mkdir()

    roots = discover_ccd_registry_roots((tmp_path / "Claude-3p",))

    assert roots == (leaf,)


def test_discover_registry_roots_dedupes_shared_leaf(tmp_path) -> None:
    leaf = _make_harness(tmp_path / "Claude", "acct", "ws", 2)

    roots = discover_ccd_registry_roots((tmp_path / "Claude", tmp_path / "Claude"))

    assert roots == (leaf,)


def test_discover_registry_roots_skips_harness_without_account(tmp_path) -> None:
    (tmp_path / "Claude-3p").mkdir()

    assert discover_ccd_registry_roots((tmp_path / "Claude-3p",)) == ()


def test_convergence_roots_include_populated_non_current_accounts(tmp_path) -> None:
    current = _make_harness(tmp_path / "Claude", "acct-current", "ws-current", 2)
    other = (
        tmp_path
        / "Claude"
        / "claude-code-sessions"
        / "acct-other"
        / "ws-other"
    )
    other.mkdir(parents=True)
    (other / "local_other.json").write_text("{}", encoding="utf-8")

    assert discover_ccd_registry_roots((tmp_path / "Claude",)) == (current,)
    assert discover_ccd_convergence_roots((tmp_path / "Claude",)) == (
        current,
        other,
    )


def test_convergence_roots_exclude_empty_and_backup_residue(tmp_path) -> None:
    current = _make_harness(tmp_path / "Claude", "acct-current", "ws-current", 1)
    sessions = tmp_path / "Claude" / "claude-code-sessions"
    (sessions / "acct-empty" / "ws-empty").mkdir(parents=True)
    for account, workspace in (
        ("acct-backup", "ws.junction-backup-20260828"),
        ("acct-recovery-backup", "ws"),
        ("acct.real-20260828", "ws"),
        ("acct-ok", "recovery-backup-20260828"),
        ("acct-ok", "ws.real-20260828"),
    ):
        leaf = sessions / account / workspace
        leaf.mkdir(parents=True, exist_ok=True)
        (leaf / "local_decoy.json").write_text("{}", encoding="utf-8")

    assert discover_ccd_convergence_roots((tmp_path / "Claude",)) == (current,)


def test_convergence_roots_exclude_reparse_points_before_resolving(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _make_harness(tmp_path / "Claude", "acct-current", "ws-current", 1)
    sessions = tmp_path / "Claude" / "claude-code-sessions"
    account_reparse = sessions / "acct-reparse"
    account_reparse.mkdir()
    account_leaf = account_reparse / "ws"
    account_leaf.mkdir()
    (account_leaf / "local_a.json").write_text("{}", encoding="utf-8")
    workspace_reparse = sessions / "acct-other" / "ws-reparse"
    workspace_reparse.mkdir(parents=True)
    (workspace_reparse / "local_b.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "session_bridge.mirror_float._is_reparse_point",
        lambda path: path in {account_reparse, workspace_reparse},
    )

    assert discover_ccd_convergence_roots((tmp_path / "Claude",)) == (current,)


def test_convergence_roots_dedupe_resolved_aliases(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _make_harness(tmp_path / "Claude", "acct-a", "ws-a", 1)
    second = (
        tmp_path / "Claude" / "claude-code-sessions" / "acct-b" / "ws-b"
    )
    second.mkdir(parents=True)
    (second / "local_b.json").write_text("{}", encoding="utf-8")
    actual_resolve = Path.resolve

    def resolve_alias(path: Path, *args, **kwargs) -> Path:
        if path == second:
            return actual_resolve(first, *args, **kwargs)
        return actual_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_alias)

    assert discover_ccd_convergence_roots((tmp_path / "Claude",)) == (first,)


def test_worker_registers_record_in_every_harness(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _seed_visible_mirror(
        db,
        store,
        tmp_path,
        provider=Provider.CODEX,
        source_last_active=5_000.0,
        mirror_mtime=1_000.0,
    )
    root_a = tmp_path / "registry-main"
    root_b = tmp_path / "registry-3p"
    root_a.mkdir()
    root_b.mkdir()
    worker = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, registry_roots=(root_a, root_b)
    )

    result = worker.run_once()

    assert result["registered"] == 1
    assert len(list(root_a.glob("local_*.json"))) == 1
    assert len(list(root_b.glob("local_*.json"))) == 1


def test_hermes_source_resolves_via_canonical_fallback(db, tmp_path) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _, mirror_path = _seed_visible_mirror(
        db,
        store,
        tmp_path,
        provider=Provider.HERMES,
        source_last_active=5_000.0,
        mirror_mtime=1_000.0,
    )
    worker = ClaudeMirrorFloatWorker(store, min_interval_seconds=900.0)

    result = worker.run_once()

    assert result == {
        "examined": 1,
        "floated": 1,
        "skipped": 0,
        "registered": 0,
        "archived": 0,
        "hydrated": 0,
        "retitled": 0,
        "throttled": 0,
    }
    assert mirror_path.stat().st_mtime == pytest.approx(5_000.0)


def test_hydrates_visible_mirror_with_source_conversation(db, tmp_path) -> None:
    from session_bridge.mirror_conversation import MirrorConversationSync
    from session_bridge.models import is_mirrored_record

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    # The seed writes an unchained placeholder; give the mirror the registration
    # turn the registrar really leaves, so there is a leaf to append after.
    leaf = "9ccc7524-3d7e-4a33-a064-9697b6ade415"
    mirror_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": leaf,
                "parentUuid": None,
                "sessionId": identity.claude_uuid,
                "cwd": "C:/work/project",
                "message": {"role": "user", "content": "signed registration"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        conversation_sync=MirrorConversationSync(store),
    )

    result = worker.run_once()

    assert result["examined"] == 1
    assert result["hydrated"] == 1
    records = [
        json.loads(line)
        for line in mirror_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["uuid"] for record in records][0] == leaf
    mirrored = [record for record in records if is_mirrored_record(record)]
    assert len(mirrored) == 1
    assert mirrored[0]["parentUuid"] == leaf
    assert mirrored[0]["message"]["content"] == "meaningful request"
    assert mirrored[0]["cwd"] == "C:/work/project"

    # Second cycle: nothing new to mirror.
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        conversation_sync=MirrorConversationSync(store),
    )
    assert worker.run_once()["hydrated"] == 0


def test_hydration_failure_does_not_stop_the_float_pass(db, tmp_path) -> None:
    class _Broken:
        def sync(self, **_kwargs):
            raise OSError("disk says no")

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    _, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    worker = ClaudeMirrorFloatWorker(
        store, min_interval_seconds=900.0, conversation_sync=_Broken()
    )

    result = worker.run_once()

    assert result["floated"] == 1
    assert result["hydrated"] == 0
    assert result["skipped"] == 0


# --- Titles derived from the first mirrored user turn (2026-09-09) -----------
#
# A registry record whose catalog row carries no title used to be called
# "[Bridge] <cwd>", which Diego called meaningless. Once the mirror has
# mirrored at least one source turn, the record is titled from the first
# mirrored USER turn through the same sanitiser the registration title uses.

_REGISTRATION_LEAF = "9ccc7524-3d7e-4a33-a064-9697b6ade415"


def _clear_catalog_title(store: SessionBridgeStore, claude_uuid: str) -> None:
    store.db._conn.execute(
        "UPDATE sessions SET title = NULL WHERE id = ?", (f"claude:{claude_uuid}",)
    )
    store.db._conn.commit()


def _write_registration_leaf(mirror_path: Path, claude_uuid: str) -> None:
    """Give the mirror the registration turn the registrar really leaves."""
    mirror_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": _REGISTRATION_LEAF,
                "parentUuid": None,
                "sessionId": claude_uuid,
                "cwd": "C:/work/project",
                "message": {"role": "user", "content": "signed registration"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _titled_worker(store: SessionBridgeStore, registry: Path, *, hydrate: bool):
    from session_bridge.mirror_conversation import MirrorConversationSync

    return ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=registry,
        conversation_sync=MirrorConversationSync(store) if hydrate else None,
    )


@pytest.mark.parametrize(
    ("provider", "prefix"),
    [(Provider.CODEX, "[Codex] "), (Provider.HERMES, "[Hermes] ")],
)
def test_new_record_is_titled_from_first_mirrored_user_turn(
    db, tmp_path, provider, prefix
) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, provider=provider, source_last_active=5_000.0
    )
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()

    result = _titled_worker(store, registry, hydrate=True).run_once()

    # Hydration runs BEFORE registration, so the very first record already
    # carries the derived title -- the desktop app honours fields at creation
    # and ignores later mutation while it runs.
    assert result["registered"] == 1
    assert result["hydrated"] == 1
    assert result["retitled"] == 0
    record = _registry_records(registry)[0]
    assert record["title"] == prefix + "meaningful request"
    assert "[Bridge]" not in record["title"]


def test_new_record_keeps_fallback_until_a_turn_is_mirrored(db, tmp_path) -> None:
    """Without hydration the ledger shows nothing mirrored: fallback stands."""
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()

    _titled_worker(store, registry, hydrate=False).run_once()

    record = _registry_records(registry)[0]
    assert record["title"].startswith("[Bridge] ")


def test_fallback_titled_record_is_retitled_once_after_hydration(
    db, tmp_path
) -> None:
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()
    # Cycle 1 ran while hydration was off: the record wears the fallback.
    _titled_worker(store, registry, hydrate=False).run_once()
    path = next(registry.glob("local_*.json"))
    before = json.loads(path.read_text(encoding="utf-8"))
    assert before["title"].startswith("[Bridge] ")
    assert "lastFocusedAt" not in before

    # Cycle 2 with hydration: the turn lands, then the record is retitled.
    result = _titled_worker(store, registry, hydrate=True).run_once()

    assert result["hydrated"] == 1
    assert result["retitled"] == 1
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["title"] == "[Codex] meaningful request"
    # Everything but the title is byte-for-byte what was there.
    assert {k: v for k, v in after.items() if k != "title"} == {
        k: v for k, v in before.items() if k != "title"
    }

    # Cycle 3: nothing left to do, and a later rename by Diego is never undone.
    assert _titled_worker(store, registry, hydrate=True).run_once()["retitled"] == 0
    renamed = dict(after, title="what Diego typed")
    path.write_text(json.dumps(renamed), encoding="utf-8")
    assert _titled_worker(store, registry, hydrate=True).run_once()["retitled"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "what Diego typed"


def test_non_fallback_title_is_never_touched(db, tmp_path) -> None:
    """Control: a record titled by the catalog keeps that title through hydration."""
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()
    _titled_worker(store, registry, hydrate=False).run_once()
    path = next(registry.glob("local_*.json"))
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "claude session"

    result = _titled_worker(store, registry, hydrate=True).run_once()

    assert result["hydrated"] == 1
    assert result["retitled"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "claude session"


def test_focused_fallback_record_is_never_retitled(db, tmp_path) -> None:
    """A row the app has opened keeps its name even if it is still the fallback."""
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()
    _titled_worker(store, registry, hydrate=False).run_once()
    path = next(registry.glob("local_*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["title"].startswith("[Bridge] ")
    record["lastFocusedAt"] = 5_000_001
    path.write_text(json.dumps(record), encoding="utf-8")

    result = _titled_worker(store, registry, hydrate=True).run_once()

    assert result["hydrated"] == 1
    assert result["retitled"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == record["title"]


def test_derived_title_skips_backfill_notice_and_caps_at_120(db, tmp_path) -> None:
    from session_bridge.mirror_conversation import MirrorConversationSync

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    long_request = "please " + "audit the whole fleet controller config " * 6
    assert len(long_request) > 120
    # Two source turns with a backfill cap of one: the mirror gets the notice
    # record first ("[Hermes mirror] 1 earlier message(s) ...") and then only
    # the SECOND turn, which is the one that must become the title.
    store.upsert_projection(
        _projection(
            _message("source-1", "first request that is dropped by the cap"),
            _message("source-1b", long_request),
            provider=Provider.CODEX,
            native_id="source-1",  # the seed's Codex source for suffix "1"
            last_active=5_000.0,
        )
    )
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        registry_root=registry,
        conversation_sync=MirrorConversationSync(store, backfill_messages=1),
    )

    result = worker.run_once()

    assert result["hydrated"] == 2  # notice + one turn
    title = _registry_records(registry)[0]["title"]
    assert title.startswith("[Codex] please audit the whole fleet")
    assert "Hermes mirror" not in title
    assert "dropped by the cap" not in title
    assert len(title) <= 120
    # sidebar_title caps at 120 INCLUDING its own "[Claude] " prefix (9 chars),
    # so after the "[Codex] " swap the longest possible title is 119.
    assert title == "[Codex] " + long_request[:111].rstrip()


def _reseed_codex_source(store: SessionBridgeStore, *messages: ProjectedMessage) -> None:
    """Replace the seed's Codex source (suffix "1") conversation wholesale.

    upsert_projection APPENDS messages, so the seed's "meaningful request"
    user turn is deleted first; otherwise it would (correctly) win the title.
    """
    store.db._conn.execute("DELETE FROM messages WHERE session_id = ?", ("codex:source-1",))
    store.db._conn.commit()
    store.upsert_projection(
        _projection(
            *messages,
            provider=Provider.CODEX,
            native_id="source-1",
            last_active=5_000.0,
        )
    )


def test_mirror_with_no_user_turn_is_titled_from_first_assistant_turn(
    db, tmp_path
) -> None:
    """15 of 16 live fallback mirrors on 2026-09-09 held assistant turns only."""
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _reseed_codex_source(
        store,
        _message("a1", "I'll start with the timing gate, judged in UTC.", role="assistant"),
        _message("a2", "Second reply that must not win.", role="assistant"),
    )
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()

    result = _titled_worker(store, registry, hydrate=True).run_once()

    assert result["hydrated"] == 2
    record = _registry_records(registry)[0]
    assert record["title"] == "[Codex] I'll start with the timing gate, judged in UTC."


def test_user_turn_wins_over_an_earlier_assistant_turn(db, tmp_path) -> None:
    """The assistant fallback is a fallback: any real user turn outranks it."""
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(db, store, tmp_path)
    _reseed_codex_source(
        store,
        _message("a1", "Assistant opened the thread first.", role="assistant"),
        _message("u1", "ok"),  # ack only: not meaningful, must not win either
        _message("u2", "the real request typed later"),
    )
    _clear_catalog_title(store, identity.claude_uuid)
    _write_registration_leaf(mirror_path, identity.claude_uuid)
    registry = tmp_path / "registry"
    registry.mkdir()

    _titled_worker(store, registry, hydrate=True).run_once()

    assert _registry_records(registry)[0]["title"] == "[Codex] the real request typed later"


def test_run_once_hides_the_registration_prompt_of_a_visible_mirror(db, tmp_path) -> None:
    """The worker is the ONLY caller of the prefix hide, and only for visible jobs.

    It runs in the same cycle as hydration, so the in-place rewrite and the
    append never race; the mirrored turns still chain from the registration
    answer, whose uuid the rewrite leaves untouched.
    """
    from session_bridge.claude_visibility import _CURRENT_CODEX_REGISTRATION_PREAMBLE
    from session_bridge.mirror_conversation import MirrorConversationSync
    from session_bridge.models import is_mirrored_record, is_registration_record

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    prompt_uuid = "9ccc7524-3d7e-4a33-a064-9697b6ade415"
    answer_uuid = "75c89ce6-cdb0-4b06-90e7-22bd99518810"
    mirror_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": prompt_uuid,
                "parentUuid": None,
                "isSidechain": False,
                "sessionId": identity.claude_uuid,
                "cwd": "C:/work/project",
                "message": {
                    "role": "user",
                    "content": _CURRENT_CODEX_REGISTRATION_PREAMBLE
                    + "abc.def\nBounded metadata: {}\nYou must reply exactly REGISTERED.",
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "uuid": answer_uuid,
                "parentUuid": prompt_uuid,
                "isSidechain": False,
                "sessionId": identity.claude_uuid,
                "cwd": "C:/work/project",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "REGISTERED"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        conversation_sync=MirrorConversationSync(store),
    )

    result = worker.run_once()

    assert result["hydrated"] == 1
    records = [
        json.loads(line)
        for line in mirror_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["uuid"] == prompt_uuid
    assert records[0]["isMeta"] is True
    assert is_registration_record(records[0])
    assert records[1]["uuid"] == answer_uuid and "isMeta" not in records[1]
    mirrored = [record for record in records if is_mirrored_record(record)]
    assert len(mirrored) == 1 and mirrored[0]["parentUuid"] == answer_uuid


def test_run_once_hides_the_cli_teardown_of_a_visible_mirror(db, tmp_path) -> None:
    """The worker hides the CLI's /exit bookkeeping in the same cycle as the
    prefix hide, for visible jobs only; the mirrored turn still chains from the
    farewell record, whose uuid the rewrite leaves untouched."""
    from session_bridge.claude_visibility import _CURRENT_CODEX_REGISTRATION_PREAMBLE
    from session_bridge.mirror_conversation import MirrorConversationSync
    from session_bridge.models import (
        is_mirrored_record,
        is_registration_record,
        is_teardown_record,
    )

    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    identity, mirror_path = _seed_visible_mirror(
        db, store, tmp_path, source_last_active=5_000.0, mirror_mtime=1_000.0
    )
    prompt_uuid = "9ccc7524-3d7e-4a33-a064-9697b6ade415"
    answer_uuid = "75c89ce6-cdb0-4b06-90e7-22bd99518810"
    exit_uuid = "1e1e1e1e-1e1e-4e1e-8e1e-1e1e1e1e1e1e"
    farewell_uuid = "2e2e2e2e-2e2e-4e2e-8e2e-2e2e2e2e2e2e"

    def record(kind, uuid, parent, content):
        return {
            "type": kind,
            "uuid": uuid,
            "parentUuid": parent,
            "isSidechain": False,
            "sessionId": identity.claude_uuid,
            "cwd": "C:/work/project",
            "message": {"role": kind, "content": content},
        }

    mirror_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                record(
                    "user",
                    prompt_uuid,
                    None,
                    _CURRENT_CODEX_REGISTRATION_PREAMBLE
                    + "abc.def\nBounded metadata: {}\nYou must reply exactly REGISTERED.",
                ),
                record("assistant", answer_uuid, prompt_uuid, [{"type": "text", "text": "REGISTERED"}]),
                record(
                    "user",
                    exit_uuid,
                    answer_uuid,
                    "<command-name>/exit</command-name>\n<command-message>exit</command-message>\n<command-args></command-args>",
                ),
                record(
                    "user",
                    farewell_uuid,
                    exit_uuid,
                    "<local-command-stdout>Goodbye!</local-command-stdout>",
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    worker = ClaudeMirrorFloatWorker(
        store,
        min_interval_seconds=900.0,
        conversation_sync=MirrorConversationSync(store),
    )

    result = worker.run_once()

    assert result["hydrated"] == 1
    records = [
        json.loads(line)
        for line in mirror_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["isMeta"] is True and is_registration_record(records[0])
    assert records[1]["uuid"] == answer_uuid and "isMeta" not in records[1]
    for index, uuid in ((2, exit_uuid), (3, farewell_uuid)):
        assert records[index]["uuid"] == uuid
        assert records[index]["isMeta"] is True
        assert is_teardown_record(records[index])
        assert not is_registration_record(records[index])
    mirrored = [item for item in records if is_mirrored_record(item)]
    assert len(mirrored) == 1 and mirrored[0]["parentUuid"] == farewell_uuid
