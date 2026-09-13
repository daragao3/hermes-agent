"""Authenticated exact target publication precedes terminal native visibility."""
from dataclasses import replace
from datetime import timezone
import sqlite3

import pytest
from hermes_state import SessionDB
from session_bridge.models import OriginKind, ProjectedMessage, Provider, SessionProjection
from session_bridge.store import SessionBridgeStore
from tests.session_bridge.test_claude_registrar import (
    SECRET, FakeFactory, FakeSource, candidate, derive_claude_visibility_identity,
    projection_for, registrar,
)


def setup_store(tmp_path):
    clock = [100.0]
    db = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(db, clock=lambda: clock[0], local_timezone=timezone.utc)
    source = candidate()
    identity = derive_claude_visibility_identity(source, SECRET)
    store.upsert_projection(SessionProjection(
        provider=Provider.CODEX, native_id="source-1", title=source.native_name,
        cwd=source.source_cwd, started_at=10.0, last_active=11.0,
        messages=(ProjectedMessage("u1", 0, "user", "request", 10.0),),
        native_path="C:/codex/source-1.jsonl", native_cursor="source-cursor",
        native_hash="source-hash", origin_kind=OriginKind.NATIVE,
    ))
    store.enqueue_claude_visibility_job(source, identity, SECRET)
    item = store.claim_claude_visibility_job(clock[0], 60, 25, "0.50", "0.02")
    return db, store, item, clock


def test_visible_publication_already_has_authenticated_target_and_lineage(tmp_path, monkeypatch):
    db, store, item, _clock = setup_store(tmp_path)
    try:
        original = store.commit_claude_visibility_job
        observations = []

        def observe_commit(*args):
            result = original(*args)
            with sqlite3.connect(str(db.db_path)) as observer:
                state = observer.execute("SELECT state FROM session_claude_visibility_jobs WHERE id=?", (item.job_id,)).fetchone()[0]
                link = observer.execute("SELECT to_session_id FROM session_links WHERE bridge_id=?", (result["bridge_id"],)).fetchone()
            observations.append((state, link))
            return result

        monkeypatch.setattr(store, "commit_claude_visibility_job", observe_commit)
        factory = FakeFactory()
        outcome = registrar(FakeSource([projection_for(item)]), factory, store).process(item)
        assert outcome.status == "visible"
        assert observations == [("claude_visible", ("claude:" + item.reserved_claude_uuid,))]
        assert store.claude_visibility_status(100.0)["lineage"]["unlinked_visible"] == 0
        assert factory.spawns == []
    finally:
        db.close()


def test_projection_write_failure_cannot_publish_visible_or_create_replacement(tmp_path, monkeypatch):
    db, store, item, clock = setup_store(tmp_path)
    try:
        def unavailable(_projection):
            raise sqlite3.OperationalError("fixture projection unavailable")
        monkeypatch.setattr(store, "upsert_projection", unavailable)
        factory = FakeFactory()
        outcome = registrar(FakeSource([projection_for(item)]), factory, store).process(item)
        assert outcome.status == "retry"
        assert outcome.error_code == "session_bridge_unavailable"
        assert db._conn.execute("SELECT state FROM session_claude_visibility_jobs WHERE id=?", (item.job_id,)).fetchone()[0] != "claude_visible"
        assert factory.spawns == []
        clock[0] = 161.0
        following = store.claim_claude_visibility_job(clock[0], 60, 25, "0.50", "0.02")
        assert following.reserved_claude_uuid == item.reserved_claude_uuid
        assert following.lease_kind == "reconciliation"
    finally:
        db.close()


def test_provenance_conflict_never_reaches_projection_publication(tmp_path, monkeypatch):
    db, store, item, _clock = setup_store(tmp_path)
    try:
        monkeypatch.setattr(store, "upsert_projection", lambda _projection: pytest.fail("unverified projection published"))
        invalid = replace(projection_for(item), origin_bridge_id="wrong")
        factory = FakeFactory()
        outcome = registrar(FakeSource([invalid]), factory, store).process(item)
        assert outcome.status == "failed"
        assert outcome.error_code == "bridge_conflict"
        assert factory.spawns == []
    finally:
        db.close()
