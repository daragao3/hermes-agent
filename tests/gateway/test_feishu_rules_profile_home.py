"""Feishu comment rules and the pairing store must follow the active profile's home.

Why this exists
---------------
``plugins/platforms/feishu/feishu_comment_rules.py`` bound ``RULES_FILE`` and ``PAIRING_FILE``
at module scope AND built two ``_MtimeCache`` instances around those frozen paths, so both the
rules and the approved-pairing list were read from whichever profile the gateway launched
under. A platform adapter runs inside ``gateway/run.py::_profile_runtime_scope``, which scopes
a whole turn to one profile, so profile B's turn consulted profile A's allowlist -- the
security-relevant direction for a pairing store.

The existing tests in tests/gateway/test_feishu_comment_rules.py had to patch BOTH the constant
and the cache instance to get anywhere near these functions; that double patch is a fossil of
the frozen-path design, the same shape as the ``_AUTH_JSON_PATH`` monkeypatch in
tests/hermes_cli/test_auth_store_windows_encoding.py (loops
auxiliary-client-auth-json-module-scope-snapshot-20260920).

Only the READ paths are exercised here on purpose: ``_save_pairing`` writes, and a red run of a
write test would drop ``feishu_comment_pairing.json`` into the developer's real ``$HERMES_HOME``.
It resolves through the same accessor as the read.

loops ``module-scope-hermes-home-snapshots-survey-20260920``.
"""

from __future__ import annotations

import json

from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def test_rules_are_read_from_the_overridden_home(tmp_path):
    import plugins.platforms.feishu.feishu_comment_rules as rules

    (tmp_path / "feishu_comment_rules.json").write_text(json.dumps({
        "enabled": True, "policy": "allowlist", "allow_from": ["ou_from_override"],
    }), encoding="utf-8")

    token = set_hermes_home_override(tmp_path)
    try:
        cfg = rules.load_config()
    finally:
        reset_hermes_home_override(token)

    assert cfg.allow_from == frozenset({"ou_from_override"}), (
        f"feishu read its rules from the launch profile, not the active one: {cfg.allow_from}")


def test_pairing_approvals_are_read_from_the_overridden_home(tmp_path):
    import plugins.platforms.feishu.feishu_comment_rules as rules

    (tmp_path / "feishu_comment_pairing.json").write_text(json.dumps({
        "approved": {"ou_approved_here": {"at": 0}},
    }), encoding="utf-8")

    token = set_hermes_home_override(tmp_path)
    try:
        approved = rules._load_pairing_approved()
    finally:
        reset_hermes_home_override(token)

    assert approved == {"ou_approved_here"}, (
        f"feishu read the approved-pairing list from the wrong profile: {approved} -- one "
        "profile's turn consults another profile's allowlist")


def test_the_cache_does_not_serve_one_profiles_data_to_another(tmp_path):
    """The mtime cache must be keyed by resolved path, not shared across profiles."""
    import plugins.platforms.feishu.feishu_comment_rules as rules

    for name, who in (("a", "ou_profile_a"), ("b", "ou_profile_b")):
        home = tmp_path / name
        home.mkdir()
        (home / "feishu_comment_pairing.json").write_text(
            json.dumps({"approved": {who: {"at": 0}}}), encoding="utf-8")

    seen = []
    for name in ("a", "b", "a"):
        token = set_hermes_home_override(tmp_path / name)
        try:
            seen.append(rules._load_pairing_approved())
        finally:
            reset_hermes_home_override(token)

    assert seen == [{"ou_profile_a"}, {"ou_profile_b"}, {"ou_profile_a"}], (
        f"the mtime cache leaked across profiles: {seen}")
