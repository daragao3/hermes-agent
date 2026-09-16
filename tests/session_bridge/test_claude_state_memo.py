"""Guards for the ``_ClaudeStateMemo`` reuse added on 2026-09-15.

The persistent Claude scan used to read, JSON-decode, validate, re-encode and
rewrite its cursor and fingerprint state rows on every cycle -- about 80 ms
of serialisation per scan against the live rows, at ~1.1 scans/s. The memo
keeps the decoded mappings across cycles, keyed on the row's exact text.

As with ``_ClaudeSortMemo`` (test_claude_sort_memo.py), the load-bearing
property is NOT "it is faster" but "a load through the memo returns exactly
what an uncached decode of the row would return", including after the row
changes underneath it -- by this process, by another writer, or by vanishing.
Most of this file is that equivalence. The efficiency guard is a DETERMINISTIC
count of real decodes rather than a wall-clock ceiling: this box runs a fleet
of concurrent sessions and the sort memo's 2 s ceiling already flakes on it.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import pytest

from hermes_state import SessionDB
import session_bridge.coordinator as coordinator_module
from session_bridge.claude_adapter import (
    ClaudeCursor,
    ClaudeSourceAdapter,
    encode_claude_cursor,
)
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import (
    _CLAUDE_CURSOR_KEY,
    _CLAUDE_FINGERPRINT_KEY,
    _CLAUDE_STAGED_KEY,
    SessionBridgeCoordinator,
    _ClaudeStateMemo,
    _decode_claude_cursors,
    _decode_claude_fingerprints,
)
from session_bridge.models import Provider
from session_bridge.store import SessionBridgeStore, decode_state_json

_MARKER_SECRET = b"synthetic-claude-state-memo-secret"
_STATE_KEYS = (_CLAUDE_FINGERPRINT_KEY, _CLAUDE_STAGED_KEY, _CLAUDE_CURSOR_KEY)


# --------------------------------------------------------------------------
# corpus helpers -- a real ClaudeSourceAdapter over a tmp projects root
# --------------------------------------------------------------------------


def _record(native_id: str, index: int) -> bytes:
    return (
        json.dumps(
            {
                "type": "user",
                "sessionId": native_id,
                "uuid": f"event-{native_id}-{index:04d}",
                "timestamp": f"2026-07-13T10:{index // 60:02d}:{index % 60:02d}Z",
                "cwd": "C:/synthetic/claude",
                "gitBranch": "main",
                "isSidechain": False,
                "message": {"role": "user", "content": f"message {index:04d}"},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _transcript(root: Path, native_id: str, count: int) -> Path:
    path = root / "project" / f"{native_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(_record(native_id, i) for i in range(count)))
    return path


def _append(path: Path, native_id: str, start: int, count: int) -> None:
    with path.open("ab") as stream:
        stream.write(
            b"".join(_record(native_id, i) for i in range(start, start + count))
        )


def _coordinator(store: Any, root: Path) -> SessionBridgeCoordinator:
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: ClaudeSourceAdapter(root, marker_secret=_MARKER_SECRET)
        },
    )


class _DecodeCounter:
    """Count the real row decodes the coordinator performs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        original = coordinator_module.decode_state_json

        def _counting(key: str, raw: str) -> dict[str, Any]:
            self.calls += 1
            return original(key, raw)

        monkeypatch.setattr(coordinator_module, "decode_state_json", _counting)


async def _memo_view(
    coordinator: SessionBridgeCoordinator,
) -> dict[str, dict[str, Any]]:
    """Every state row as the coordinator's loaders (memo path) return it."""
    return {
        _CLAUDE_FINGERPRINT_KEY: await coordinator._load_claude_fingerprints(
            _CLAUDE_FINGERPRINT_KEY
        ),
        _CLAUDE_STAGED_KEY: await coordinator._load_claude_fingerprints(
            _CLAUDE_STAGED_KEY
        ),
        _CLAUDE_CURSOR_KEY: await coordinator._load_claude_cursors(),
    }


def _disk_view(store: SessionBridgeStore) -> dict[str, dict[str, Any]]:
    """Every state row decoded from disk by the real decoders, memo bypassed."""
    return {
        _CLAUDE_FINGERPRINT_KEY: _decode_claude_fingerprints(
            store.get_state(_CLAUDE_FINGERPRINT_KEY)
        ),
        _CLAUDE_STAGED_KEY: _decode_claude_fingerprints(
            store.get_state(_CLAUDE_STAGED_KEY)
        ),
        _CLAUDE_CURSOR_KEY: _decode_claude_cursors(store.get_state(_CLAUDE_CURSOR_KEY)),
    }


# --------------------------------------------------------------------------
# the memo itself
# --------------------------------------------------------------------------


def test_memo_misses_on_absent_row_different_text_and_non_text_writes() -> None:
    memo = _ClaudeStateMemo()
    memo.store("k", '{"a":1}', {"a": 1})
    assert memo.lookup("k", '{"a":1}') == {"a": 1}
    assert memo.lookup("k", '{"a":2}') is None, "different text must miss"
    assert memo.lookup("other", '{"a":1}') is None, "keys are independent"
    # A vanished row is not a hit AND evicts what was there.
    assert memo.lookup("k", None) is None
    assert memo.lookup("k", '{"a":1}') is None
    # A store whose set_state reports no text cannot be seeded.
    memo.store("k", None, {"a": 1})
    assert len(memo) == 0
    memo.store("k", '{"a":1}', {"a": 1})
    memo.forget("k")
    assert memo.lookup("k", '{"a":1}') is None


def test_memo_hands_out_and_keeps_copies() -> None:
    memo = _ClaudeStateMemo()
    source = {"x": {"mtime_ns": 1, "size": 2}}
    memo.store("k", "raw", source)
    source["y"] = {"mtime_ns": 3, "size": 4}
    served = memo.lookup("k", "raw")
    assert served == {"x": {"mtime_ns": 1, "size": 2}}, "store must copy its input"
    assert served is not None
    served["z"] = {"mtime_ns": 5, "size": 6}
    assert memo.lookup("k", "raw") == {"x": {"mtime_ns": 1, "size": 2}}, (
        "a caller mutating what it was handed must not change the memo"
    )


# --------------------------------------------------------------------------
# the store surface the memo relies on
# --------------------------------------------------------------------------


def test_set_state_returns_the_exact_text_get_state_json_reads_back(
    tmp_path: Path,
) -> None:
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        value = {"version": 1, "sessions": {"b": {"size": 2, "mtime_ns": 1}, "a": {}}}
        written = store.set_state("key", value)
        assert isinstance(written, str)
        assert store.get_state_json("key") == written
        assert decode_state_json("key", written) == store.get_state("key") == value
        assert store.get_state_json("missing") is None
        assert store.get_state("missing") is None
    finally:
        db.close()


def test_set_state_still_refuses_what_it_refused_before(tmp_path: Path) -> None:
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        with pytest.raises(TypeError):
            store.set_state("key", ["not", "a", "mapping"])  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            store.set_state("key", {"nan": float("nan")})
        assert store.get_state_json("key") is None
    finally:
        db.close()


def test_decode_state_json_rejects_a_non_object_row() -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        decode_state_json("key", "[1, 2]")


# --------------------------------------------------------------------------
# equivalence with the uncached path, through real scans
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memo_loads_equal_uncached_decodes_across_a_changing_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing guard.

    Runs the real persistent scan over a corpus that changes between cycles
    (appends, a rewrite, a new file, a deletion) and after EVERY cycle compares
    the coordinator's memo-served view of all three state rows with a fresh
    decode of the rows on disk.
    """

    root = tmp_path / "projects"
    alpha = _transcript(root, "alpha", 3)
    beta = _transcript(root, "beta", 2)
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, root)
        counter = _DecodeCounter(monkeypatch)

        adapter = coordinator._adapter(Provider.CLAUDE)

        async def _cycle() -> None:
            # discover() is TTL-cached inside the adapter; the corpus edits
            # below are about the STATE rows, so let every cycle see them.
            adapter._discover_cache = None
            await coordinator.scan_once(Provider.CLAUDE)
            memo_view = await _memo_view(coordinator)
            assert memo_view == _disk_view(store)
            for key in _STATE_KEYS:
                if store.get_state_json(key) is not None:
                    assert memo_view[key] == _decode_row(store, key)

        await _cycle()
        assert _disk_view(store)[_CLAUDE_CURSOR_KEY].keys() == {"alpha", "beta"}

        # Nothing changed: the loads that open the next cycle must decode nothing.
        counter.calls = 0
        await _cycle()
        assert counter.calls == 0, "an unchanged row must be served from the memo"

        _append(alpha, "alpha", 3, 2)
        await _cycle()
        assert (
            _disk_view(store)[_CLAUDE_CURSOR_KEY]["alpha"].offset
            == alpha.stat().st_size
        )

        beta.write_bytes(_record("beta", 0))  # rewrite that shrinks past the head
        _transcript(root, "gamma", 1)
        await _cycle()
        assert "gamma" in _disk_view(store)[_CLAUDE_FINGERPRINT_KEY]

        alpha.unlink()
        await _cycle()
        await _cycle()
    finally:
        db.close()


def _decode_row(store: SessionBridgeStore, key: str) -> dict[str, Any]:
    raw = store.get_state_json(key)
    assert raw is not None
    decoded = decode_state_json(key, raw)
    if key == _CLAUDE_CURSOR_KEY:
        return _decode_claude_cursors(decoded)
    return _decode_claude_fingerprints(decoded)


@pytest.mark.asyncio
async def test_a_write_by_another_writer_is_seen_even_on_a_frozen_clock(
    tmp_path: Path,
) -> None:
    """The memo keys on row TEXT, never on ``updated_at``.

    The clock here is frozen, so every write carries the same stamp -- a memo
    keyed on the stamp would serve the stale mapping. A second store on the
    same database stands in for another process.
    """

    root = tmp_path / "projects"
    _transcript(root, "alpha", 2)
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, root)
        await coordinator.scan_once(Provider.CLAUDE)
        assert (await coordinator._load_claude_cursors()).keys() == {"alpha"}

        other = SessionBridgeStore(db, clock=lambda: 1_000.0)
        foreign_cursor = ClaudeCursor(offset=1, head_length=1, head_hash="ab" * 32)
        other.set_state(
            _CLAUDE_CURSOR_KEY,
            {
                "version": 1,
                "sessions": {"foreign": encode_claude_cursor(foreign_cursor)},
            },
        )
        other.set_state(
            _CLAUDE_FINGERPRINT_KEY,
            {"version": 1, "sessions": {"foreign": {"mtime_ns": 7, "size": 8}}},
        )
        assert await coordinator._load_claude_cursors() == {"foreign": foreign_cursor}
        assert await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY) == {
            "foreign": {"mtime_ns": 7, "size": 8}
        }

        # And a row that vanishes reads as empty, not as the last decode.
        db._conn.execute(  # type: ignore[union-attr]
            "DELETE FROM session_bridge_state WHERE key = ?", (_CLAUDE_CURSOR_KEY,)
        )
        db._conn.commit()  # type: ignore[union-attr]
        assert await coordinator._load_claude_cursors() == {}
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_caller_mutating_a_loaded_mapping_does_not_poison_the_memo(
    tmp_path: Path,
) -> None:
    """A cycle that fails midway leaves half-applied edits in ITS mapping only."""

    root = tmp_path / "projects"
    _transcript(root, "alpha", 2)
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, root)
        await coordinator.scan_once(Provider.CLAUDE)
        loaded = await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY)
        loaded["ghost"] = {"mtime_ns": 1, "size": 1}
        loaded.pop("alpha")
        assert await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY) == (
            _decode_claude_fingerprints(store.get_state(_CLAUDE_FINGERPRINT_KEY))
        )
        cursors = await coordinator._load_claude_cursors()
        cursors.clear()
        assert (await coordinator._load_claude_cursors()).keys() == {"alpha"}
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_save_the_decoder_would_reject_is_not_seeded(tmp_path: Path) -> None:
    """The memo must never be MORE permissive than a real decode.

    A fingerprint the strict decoder rejects is persisted exactly as before,
    and the next load raises exactly as an uncached load of that row would.
    """

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, tmp_path / "projects")
        await coordinator._save_claude_fingerprints(
            _CLAUDE_FINGERPRINT_KEY, {"alpha": {"mtime_ns": -1, "size": 0}}
        )
        assert len(coordinator._claude_state_memo) == 0
        with pytest.raises(RuntimeError, match="invalid Claude fingerprint state"):
            _decode_claude_fingerprints(store.get_state(_CLAUDE_FINGERPRINT_KEY))
        with pytest.raises(RuntimeError, match="invalid Claude fingerprint state"):
            await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_cursor_saves_seed_exactly_what_the_decoder_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cursor seeding mirrors the decoder instead of running it.

    So it must agree with the decoder on every case that shapes the seed: an
    entry whose encoding fails is dropped; an id the decoder would strip
    disables the seed and the next load decodes for real.
    """

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, tmp_path / "projects")
        counter = _DecodeCounter(monkeypatch)
        good = ClaudeCursor(offset=10, head_length=10, head_hash="cd" * 32)
        bad = ClaudeCursor(offset=-1, head_length=10, head_hash="cd" * 32)
        assert encode_claude_cursor(bad) is None

        await coordinator._save_claude_cursors({"alpha": good, "beta": bad})
        assert counter.calls == 0
        assert await coordinator._load_claude_cursors() == {"alpha": good}
        assert counter.calls == 0, "the seed must serve the load that follows"
        assert await coordinator._load_claude_cursors() == _decode_claude_cursors(
            store.get_state(_CLAUDE_CURSOR_KEY)
        )

        await coordinator._save_claude_cursors({" alpha ": good})
        assert await coordinator._load_claude_cursors() == {"alpha": good}
        assert counter.calls == 1, "an unmirrorable id must fall back to a real decode"
        assert await coordinator._load_claude_cursors() == _decode_claude_cursors(
            store.get_state(_CLAUDE_CURSOR_KEY)
        )
    finally:
        db.close()


# --------------------------------------------------------------------------
# stores without the raw-text surface take the old path, unchanged
# --------------------------------------------------------------------------


class _PlainStore:
    """The shape every fake store in this suite has: get_state/set_state only."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.reads = 0

    def get_state(self, key: str) -> dict[str, Any] | None:
        self.reads += 1
        state = self.states.get(key)
        return json.loads(json.dumps(state)) if state is not None else None

    def set_state(self, key: str, value: Mapping[str, Any]) -> None:
        self.states[key] = json.loads(json.dumps(dict(value)))


@pytest.mark.asyncio
async def test_a_store_without_raw_text_is_read_uncached_every_time(
    tmp_path: Path,
) -> None:
    store = _PlainStore()
    coordinator = _coordinator(store, tmp_path / "projects")
    cursor = ClaudeCursor(offset=4, head_length=4, head_hash="ef" * 32)
    await coordinator._save_claude_cursors({"alpha": cursor})
    await coordinator._save_claude_fingerprints(
        _CLAUDE_FINGERPRINT_KEY, {"alpha": {"mtime_ns": 1, "size": 4}}
    )
    assert len(coordinator._claude_state_memo) == 0, "nothing to key on -> no memo"
    for _ in range(3):
        assert await coordinator._load_claude_cursors() == {"alpha": cursor}
        assert await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY) == {
            "alpha": {"mtime_ns": 1, "size": 4}
        }
    assert store.reads == 6, "every load must reach get_state on a plain store"
    assert len(coordinator._claude_state_memo) == 0


# --------------------------------------------------------------------------
# efficiency guard -- deterministic, not wall-clock
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unchanged_rows_cost_zero_decodes_at_production_scale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 cycles of loads over rows of 5,000 sessions decode each row ONCE.

    The counted decode is the real ``decode_state_json``; the seed path makes
    even that one decode unnecessary after a save, so the count after the
    saves is zero. A regression that dropped the memo or keyed it wrongly
    would decode 40 times here.
    """

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        store = SessionBridgeStore(db, clock=lambda: 1_000.0)
        coordinator = _coordinator(store, tmp_path / "projects")
        counter = _DecodeCounter(monkeypatch)
        cursors = {
            f"session-{i:05d}": ClaudeCursor(
                offset=i + 1, head_length=i + 1, head_hash=f"{i:064x}"
            )
            for i in range(5_000)
        }
        fingerprints = {
            f"session-{i:05d}": {"mtime_ns": 1_700_000_000_000_000_000 + i, "size": i}
            for i in range(5_000)
        }
        await coordinator._save_claude_cursors(cursors)
        await coordinator._save_claude_fingerprints(
            _CLAUDE_FINGERPRINT_KEY, fingerprints
        )
        for _ in range(20):
            assert await coordinator._load_claude_cursors() == cursors
            assert (
                await coordinator._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY)
                == fingerprints
            )
        assert counter.calls == 0

        # A fresh coordinator (a restart) decodes each row exactly once, then
        # serves the memo.
        restarted = _coordinator(store, tmp_path / "projects")
        for _ in range(20):
            assert await restarted._load_claude_cursors() == cursors
            assert (
                await restarted._load_claude_fingerprints(_CLAUDE_FINGERPRINT_KEY)
                == fingerprints
            )
        assert counter.calls == 2
    finally:
        db.close()
