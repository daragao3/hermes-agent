"""Gateway paths that must follow the active profile's home, not the launch one.

Why this exists
---------------
``gateway/run.py::_profile_runtime_scope`` sets a context-local home override around a WHOLE
TURN of a multiplexed profile ("Scope config/skills/memory AND credentials to a profile for
one turn"), and ``cron/scheduler.py`` does the same per profile tick. A module-scope
``X = get_hermes_home() / ...`` is resolved once at import, so it silently keeps pointing at
whichever profile's home the process launched under.

Covered here:
  * ``gateway/sticker_cache.py`` — reached from the Telegram adapter during a turn, and it
    both READS and WRITES, so one profile's sticker descriptions land in another's cache.
  * ``gateway/mirror.py`` — its own docstring says it "works from CLI, cron and gateway
    contexts", and ``cron/scheduler_delivery.py`` calls it from inside a profile tick, so the
    session lookup consults the wrong profile's ``sessions.json``.

Same bug class and same fix as skills_tool (f8723c478), skill_manager_tool (c6a3d412d) and
skills_sync (issue #65828), and as agent/auxiliary_client (loops
auxiliary-client-auth-json-module-scope-snapshot-20260920). Both modules keep their module
constants because existing tests patch them; the accessors honour an explicit patch and
otherwise re-resolve, exactly as skills_sync does.

loops ``module-scope-hermes-home-snapshots-survey-20260920``.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def test_sticker_cache_writes_into_the_overridden_home(tmp_path, monkeypatch):
    """Stubbed writer: a red run must not drop sticker_cache.json in the real home."""
    import gateway.sticker_cache as sc

    recorded: list[Path] = []
    monkeypatch.setattr(sc, "atomic_json_write",
                        lambda path, data: recorded.append(Path(path)))

    token = set_hermes_home_override(tmp_path)
    try:
        sc.cache_sticker_description("uid-1", "a waving cat")
    finally:
        reset_hermes_home_override(token)

    assert recorded and recorded[-1] == tmp_path / "sticker_cache.json", (
        f"sticker cache wrote to {recorded} instead of the overridden home -- one profile's "
        "turn persists sticker descriptions into the launch profile's cache")


def test_sticker_cache_reads_from_the_overridden_home(tmp_path):
    import gateway.sticker_cache as sc

    (tmp_path / "sticker_cache.json").write_text(json.dumps(
        {"uid-1": {"description": "from the override", "emoji": "", "set_name": "",
                   "cached_at": 0}}), encoding="utf-8")

    token = set_hermes_home_override(tmp_path)
    try:
        entry = sc.get_cached_description("uid-1")
    finally:
        reset_hermes_home_override(token)

    assert entry is not None and entry["description"] == "from the override", (
        "sticker cache read the launch profile's file instead of the active profile's")


def test_mirror_session_lookup_uses_the_overridden_home(tmp_path):
    import gateway.mirror as mirror

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "sessions.json").write_text(json.dumps({
        "sess-from-override": {"session_id": "sess-from-override",
                               "origin": {"platform": "telegram", "chat_id": "4242"}},
    }), encoding="utf-8")

    token = set_hermes_home_override(tmp_path)
    try:
        found = mirror._find_session_id("telegram", "4242")
    finally:
        reset_hermes_home_override(token)

    assert found == "sess-from-override", (
        f"mirror resolved {found!r} -- it read the launch profile's sessions.json, so a cron "
        "profile tick mirrors into the wrong profile's transcript")
