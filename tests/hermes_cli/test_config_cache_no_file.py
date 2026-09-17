"""``load_config()`` must cache the "no config.yaml" case, not rebuild every call.

Why this exists
---------------
``_load_config_cache_sig`` used to return ``cache_sig = None`` when neither
``config.yaml`` nor a managed overlay existed ("nothing to cache on"), and
``_load_config_impl`` only stores an entry when ``cache_sig`` is not None. So a
process with no config file — a fresh install, an env-only container, and every
test's per-test tmp ``HERMES_HOME`` — rebuilt defaults + canonicalize +
env-expand + managed overlay on EVERY ``load_config*()`` call.

Measured 2026-09-17 on one ``AIAgent`` construction + one ``compress_context``
(tests/run_agent/test_in_place_compaction.py, host at 100% CPU): 194 calls,
4.4 s cumulative, all misses; with the sentinel signature 1.05 s. That, times
every test in the suite, was a large share of the load-timeout flakes in
tests that build a real agent (loops in-place-compaction-tests-load-timeouts-20260917).

The sentinel ``(-1, -1, 0, 0)`` can never equal a real ``(mtime_ns, size, ...)``
pair, so the entry is rebuilt the moment either file appears.
"""

from __future__ import annotations

import pytest

from hermes_cli import config as cfg


@pytest.fixture
def empty_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    cfg._LOAD_CONFIG_CACHE.clear()
    cfg._RAW_CONFIG_CACHE.clear()
    yield home
    cfg._LOAD_CONFIG_CACHE.clear()
    cfg._RAW_CONFIG_CACHE.clear()


def test_no_config_file_is_cached_after_first_load(empty_home, monkeypatch):
    """Second load with no config.yaml is a cache hit: same object, no rebuild."""
    assert not (empty_home / "config.yaml").exists()
    builds = []
    real = cfg.effective_default_config
    monkeypatch.setattr(cfg, "effective_default_config", lambda: builds.append(1) or real())

    first = cfg.load_config_readonly()
    second = cfg.load_config_readonly()

    assert builds == [1], f"defaults were rebuilt {len(builds)} times for a no-file home"
    # The readonly path's identity invariant: every hit sees the same stable object.
    assert second is first


def test_cache_sig_for_missing_files_is_a_sentinel(empty_home):
    user_sig, cache_sig = cfg._load_config_cache_sig(empty_home / "config.yaml")
    assert user_sig is None
    assert cache_sig is not None, "a None cache_sig disables caching for every no-file process"
    # Must never collide with a real (mtime_ns, size, managed_mtime_ns, managed_size).
    assert cache_sig[0] < 0 and cache_sig[1] < 0


def test_creating_config_yaml_invalidates_the_no_file_entry(empty_home, monkeypatch):
    """The sentinel must not pin defaults once a real config.yaml appears."""
    cfg.load_config_readonly()
    assert cfg.load_config_readonly().get("model") != "sentinel/model"

    (empty_home / "config.yaml").write_text("model: sentinel/model\n", encoding="utf-8")

    assert cfg.load_config_readonly()["model"] == "sentinel/model"
