"""Tests for the session_bridge ROOT-scope divergence guard.

session_bridge is ROOT-scoped by design: ``launch-session-bridge.ps1`` pins
``HERMES_HOME`` to the Hermes root (``~/.hermes``), NOT to the active profile.
The gateway, by contrast, is pinned to ``~/.hermes/profiles/main`` by
``laptop-start.ps1``.  Two long-lived services, two different homes.

That split is fine while both agree.  It stops being fine when the *sidebar*
config diverges between them, because every reader of ``sidebar.enabled``
lives in ``session_bridge/`` and reads whichever home its own process
resolved.  Measured on 2026-09-01: the root had the lane RETIRED
(``enabled: false``) while ``profiles/main/config.yaml`` still said
``enabled: true`` and pointed at a different, empty state.db.  A process
resolving the profile home therefore reported a retired lane as ACTIVE and
healthy with zero rows -- green but blind, the exact failure class the
``optional_feature_disabled`` work spent that day eliminating everywhere else.

The guard warns; it deliberately does NOT raise and does NOT override the
resolved value.  Raising would brick callers over a config file they may not
own, and silently preferring the root would hide a real misconfiguration.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_config(home: Path, *, enabled: bool | None) -> None:
    """Write a minimal config.yaml carrying (or omitting) sidebar.enabled."""
    home.mkdir(parents=True, exist_ok=True)
    if enabled is None:
        body = "session_bridge:\n  sidebar: {}\n"
    else:
        body = (
            "session_bridge:\n"
            "  sidebar:\n"
            f"    enabled: {'true' if enabled else 'false'}\n"
        )
    (home / "config.yaml").write_text(body, encoding="utf-8")


@pytest.fixture
def guard(monkeypatch, tmp_path):
    """Import the config module fresh and reset the one-shot warn flag."""
    import importlib

    import session_bridge.config as config

    importlib.reload(config)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    config._root_scope_divergence_warned = False
    return config


class TestSidebarRootScopeDivergence:
    def test_root_scoped_process_is_silent(self, guard, tmp_path, capsys):
        """HERMES_HOME unset -> resolved home IS the root, nothing to compare."""
        root = tmp_path / ".hermes"
        _write_config(root, enabled=False)

        guard._warn_sidebar_root_scope_divergence(False)

        assert "sidebar root-scope divergence" not in capsys.readouterr().err

    def test_agreeing_profile_home_is_silent(self, guard, tmp_path, monkeypatch, capsys):
        """Profile home that AGREES with the root must not warn."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        _write_config(root, enabled=False)
        _write_config(profile, enabled=False)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        guard._warn_sidebar_root_scope_divergence(False)

        assert "sidebar root-scope divergence" not in capsys.readouterr().err

    def test_diverging_profile_home_warns_once(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """The measured 2026-09-01 case: profile says true, root says false."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        _write_config(root, enabled=False)
        _write_config(profile, enabled=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        guard._warn_sidebar_root_scope_divergence(True)
        err = capsys.readouterr().err

        assert err.count("sidebar root-scope divergence") == 1
        # The operator needs both values and both paths to act on this.
        assert "enabled=True" in err
        assert "enabled=False" in err
        assert str(root) in err
        # One-shot: a second call stays quiet.
        guard._warn_sidebar_root_scope_divergence(True)
        assert "sidebar root-scope divergence" not in capsys.readouterr().err

    def test_divergence_the_other_way_also_warns(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """Guard is symmetric -- root true / profile false is equally wrong."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        _write_config(root, enabled=True)
        _write_config(profile, enabled=False)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        guard._warn_sidebar_root_scope_divergence(False)

        assert "sidebar root-scope divergence" in capsys.readouterr().err

    def test_root_without_explicit_value_is_silent(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """Absence is not divergence -- an unset root key must not warn."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        _write_config(root, enabled=None)
        _write_config(profile, enabled=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        guard._warn_sidebar_root_scope_divergence(True)

        assert "sidebar root-scope divergence" not in capsys.readouterr().err

    def test_unreadable_root_never_raises(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """A broken root config must not brick a load that would otherwise work."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.yaml").write_text("{[not: valid: yaml", encoding="utf-8")
        _write_config(profile, enabled=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        guard._warn_sidebar_root_scope_divergence(True)

        assert "sidebar root-scope divergence" not in capsys.readouterr().err

    def test_guard_is_actually_wired_into_config_load(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """The guard must fire from BridgeConfig.load, not just when called directly.

        Every other test in this file calls ``_warn_sidebar_root_scope_divergence``
        by hand, which proves the guard works but NOT that anything invokes it.
        Verified by mutation: replacing the call site in ``_load`` with ``pass``
        left all seven of those tests green.  This test is the one that fails.
        """
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "main"
        _write_config(root, enabled=False)
        _write_config(profile, enabled=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        config = guard.BridgeConfig.load()

        # The resolved value is honoured -- the guard warns, it does not override.
        assert config.sidebar.enabled is True
        assert "sidebar root-scope divergence" in capsys.readouterr().err

    def test_home_outside_the_root_is_silent(
        self, guard, tmp_path, monkeypatch, capsys
    ):
        """Docker/custom layout: HERMES_HOME outside ~/.hermes IS its own root."""
        elsewhere = tmp_path / "opt" / "data"
        _write_config(elsewhere, enabled=True)
        _write_config(tmp_path / ".hermes", enabled=False)
        monkeypatch.setenv("HERMES_HOME", str(elsewhere))

        guard._warn_sidebar_root_scope_divergence(True)

        assert "sidebar root-scope divergence" not in capsys.readouterr().err
