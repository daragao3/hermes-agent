"""Local credential recovery must compose with upstream profile and refresh isolation."""
from dataclasses import replace

import pytest

from agent import credential_pool as pools


@pytest.fixture
def scoped_cache(tmp_path, monkeypatch):
    home = [tmp_path / "profile-a"]
    root_auth = tmp_path / "root-auth.json"
    monkeypatch.setattr(pools, "get_hermes_home", lambda: home[0])
    monkeypatch.setattr(pools.auth_mod, "_global_auth_file_path", lambda: root_auth)
    monkeypatch.setattr(pools, "_auth_json_mtime", lambda: 0.0)
    loaded = []

    def load(provider):
        pool = object()
        loaded.append(pool)
        return pool

    monkeypatch.setattr(pools, "_load_pool_uncached", load)
    pools.invalidate_pool_cache()
    yield home, root_auth, loaded
    pools.invalidate_pool_cache()


def test_cache_reuses_only_within_the_same_profile(scoped_cache):
    home, _, loaded = scoped_cache
    first = pools.load_pool("openai-codex")
    assert pools.load_pool("openai-codex") is first
    home[0] = home[0].parent / "profile-b"
    assert pools.load_pool("openai-codex") is not first
    assert len(loaded) == 2


def test_root_store_change_invalidates_borrowing_profile(scoped_cache):
    _, root_auth, _ = scoped_cache
    first = pools.load_pool("openai-codex")
    root_auth.write_text("{}", encoding="utf-8")
    assert pools.load_pool("openai-codex") is not first


def test_store_change_during_load_is_not_cached(scoped_cache, monkeypatch):
    _, root_auth, loaded = scoped_cache
    original = pools._load_pool_uncached

    def changing(provider):
        result = original(provider)
        root_auth.write_text(" " * len(loaded), encoding="utf-8")
        return result

    monkeypatch.setattr(pools, "_load_pool_uncached", changing)
    first = pools.load_pool("openai-codex")
    assert pools.load_pool("openai-codex") is not first


def test_provider_invalidation_clears_all_profile_scopes(scoped_cache):
    home, _, _ = scoped_cache
    profile_a = home[0]
    first = pools.load_pool("openai-codex")
    home[0] = home[0].parent / "profile-b"
    second = pools.load_pool("openai-codex")
    pools.invalidate_pool_cache("openai-codex")
    assert pools.load_pool("openai-codex") is not second
    home[0] = profile_a
    assert pools.load_pool("openai-codex") is not first


def test_terminal_failure_does_not_quarantine_same_id_rotated_by_peer(monkeypatch):
    monkeypatch.setattr(pools, "get_pool_strategy", lambda provider: "fill-first")
    old = pools.PooledCredential(provider="openai-codex", id="entry", label="test",
                                 auth_type="oauth", priority=0, source="manual:device_code",
                                 access_token="old-test-bearer", refresh_token="spent-test-grant")
    fresh = replace(old, access_token="new-test-bearer", refresh_token="new-test-grant")
    pool = pools.CredentialPool("openai-codex", [fresh])
    pool._current_id = fresh.id
    monkeypatch.setattr(pool, "_persist", lambda **kwargs: None)
    pool._quarantine_terminal_chain(old, {"device_code"}, RuntimeError("terminal old grant"))
    assert pool._entries == [fresh]
    assert pool._current_id == fresh.id
