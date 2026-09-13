"""Stable Codex seen sets must not repeatedly acquire the shared DB writer."""

from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider
from session_bridge.store import SessionBridgeStore
from tests.session_bridge.test_coordinator import (
    _BacklogCodexAdapter,
    _CODEX_SEEN_KEY,
    _codex_summary,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_terminal,peer_snapshot", [
    (False, None),
    (True, None),
    (False, []),
    (False, ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"]),
])
async def test_codex_seen_snapshot_only_writes_new_terminal_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_terminal: bool,
    peer_snapshot: list[str] | None,
) -> None:
    known = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    native = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" if new_terminal else known
    summary = _codex_summary(native, 300.0)
    now = [100.0]
    database = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(database, clock=lambda: now[0])
    try:
        store.set_state(_CODEX_SEEN_KEY, {"version": 1, "native_ids": [known]})
        writes = []
        original = store.set_state

        def record_write(key, value):
            if key == _CODEX_SEEN_KEY:
                writes.append(value)
            return original(key, value)

        monkeypatch.setattr(store, "set_state", record_write)
        now[0] = 200.0
        adapter = _BacklogCodexAdapter(
            inventory_batches=[[summary]],
            summaries_by_native_id={native: summary},
            operations=[],
        )
        if peer_snapshot is not None:
            inventory = adapter.list_inventory

            def publish_peer_change(*, archived):
                # The coordinator has loaded its seen set by this boundary.
                if not archived:
                    store.set_state(_CODEX_SEEN_KEY, {
                        "version": 1, "native_ids": peer_snapshot,
                    })
                return inventory(archived=archived)

            monkeypatch.setattr(adapter, "list_inventory", publish_peer_change)
        coordinator = SessionBridgeCoordinator(
            config=BridgeConfig(), store=store, adapters={Provider.CODEX: adapter},
        )
        result = await coordinator.scan_once(Provider.CODEX)
        assert result.failed == 0
        assert result.indexed == int(new_terminal)
        assert len(writes) == int(new_terminal) + int(peer_snapshot is not None)
        expected_ids = {known, native} if peer_snapshot is None else set(peer_snapshot)
        assert set(store.get_state(_CODEX_SEEN_KEY)["native_ids"]) == expected_ids
        updated = database._conn.execute(
            "SELECT updated_at FROM session_bridge_state WHERE key=?",
            (_CODEX_SEEN_KEY,),
        ).fetchone()[0]
        assert updated == (200.0 if new_terminal or peer_snapshot is not None else 100.0)
    finally:
        database.close()
