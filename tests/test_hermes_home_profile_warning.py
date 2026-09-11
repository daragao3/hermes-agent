"""Tests for get_hermes_home() profile-mode fallback warning.

Regression test for https://github.com/NousResearch/hermes-agent/issues/18594.

When HERMES_HOME is unset but an active_profile file indicates a non-default
profile is active, get_hermes_home() should:
  1. STILL return ~/.hermes (raising would brick 30+ module-level callers)
  2. Emit a loud one-shot warning to stderr so operators can diagnose
     cross-profile data contamination after the fact.

The warning goes to stderr directly (not through logging) because this
function is called at module-import time from 30+ sites, often before the
logging subsystem has been configured.
"""

from pathlib import Path

import pytest


@pytest.fixture
def fresh_constants(monkeypatch, tmp_path):
    r"""Import hermes_constants fresh and reset the one-shot warn flag.

    The platform-native default is pinned to ``tmp_path/.hermes`` so these
    tests state the same intent on every platform.  Patching ``Path.home``
    alone is not enough: on Windows the native default is
    ``%LOCALAPPDATA%\hermes``, and whether the legacy ``~/.hermes`` is
    preferred instead depends on whether the *host's* real AppData directory
    happens to carry a root marker.  That made five of the tests below pass by
    coincidence and the sixth (no ``~/.hermes`` at all, so neither candidate is
    initialized) fail outright.  Platform-default selection is deliberate
    production behaviour and is covered on its own in
    :class:`TestPlatformDefaultHermesHome`.
    """
    import importlib
    import hermes_constants
    importlib.reload(hermes_constants)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        hermes_constants,
        "_get_platform_default_hermes_home",
        lambda: tmp_path / ".hermes",
    )
    monkeypatch.delenv("HERMES_HOME", raising=False)
    return hermes_constants


class TestGetHermesHomeProfileWarning:
    def test_classic_mode_no_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """Classic mode: no active_profile file → silent, returns the default home."""
        result = fresh_constants.get_hermes_home()
        assert result == tmp_path / ".hermes"
        assert "HERMES_HOME fallback" not in capsys.readouterr().err


    def test_named_profile_unset_home_warns_once(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile=coder + HERMES_HOME unset → warn loudly, still return fallback."""
        hermes_dir = tmp_path / ".hermes"
        hermes_dir.mkdir()
        (hermes_dir / "active_profile").write_text("coder\n")

        result = fresh_constants.get_hermes_home()

        # 1. Still returns the fallback — no import-time crash
        assert result == tmp_path / ".hermes"
        # 2. Stderr got the warning exactly once
        err = capsys.readouterr().err
        assert err.count("HERMES_HOME fallback") == 1
        assert "'coder'" in err
        assert "#18594" in err

        # 3. One-shot: second and third calls don't re-warn
        fresh_constants.get_hermes_home()
        fresh_constants.get_hermes_home()
        err2 = capsys.readouterr().err
        assert "HERMES_HOME fallback" not in err2

    def test_hermes_home_set_suppresses_warning(
        self, fresh_constants, tmp_path, capsys, monkeypatch
    ):
        """Even if active_profile is 'coder', setting HERMES_HOME suppresses warning."""
        profile_dir = tmp_path / ".hermes" / "profiles" / "coder"
        profile_dir.mkdir(parents=True)
        (tmp_path / ".hermes" / "active_profile").write_text("coder\n")
        monkeypatch.setenv("HERMES_HOME", str(profile_dir))

        result = fresh_constants.get_hermes_home()

        assert result == profile_dir
        assert "HERMES_HOME fallback" not in capsys.readouterr().err

    def test_unreadable_active_profile_no_crash(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile that can't be decoded → fall through silently."""
        hermes_dir = tmp_path / ".hermes"
        hermes_dir.mkdir()
        # Write bytes that aren't valid utf-8
        (hermes_dir / "active_profile").write_bytes(b"\xff\xfe\x00\x00")

        result = fresh_constants.get_hermes_home()

        assert result == tmp_path / ".hermes"
        # Shouldn't crash; shouldn't warn either (can't tell what profile was intended)
        assert "HERMES_HOME fallback" not in capsys.readouterr().err



class TestPlatformDefaultHermesHome:
    r"""Cover _get_platform_default_hermes_home() directly, on both platforms.

    The tests above used to exercise this branch by accident — they read the
    real ``%LOCALAPPDATA%\hermes`` on this host, so their result depended on
    whether that directory happened to carry a root marker.  These tests isolate
    ``LOCALAPPDATA`` and ``Path.home`` and exercise each platform on its
    native test runner.
    """

    @staticmethod
    def _constants(monkeypatch, tmp_path, local_appdata=None):
        import importlib
        import hermes_constants
        importlib.reload(hermes_constants)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        if local_appdata is None:
            monkeypatch.delenv("LOCALAPPDATA", raising=False)
        else:
            monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
        return hermes_constants

    @pytest.mark.linux_only
    def test_posix_default_is_dot_hermes_under_home(self, monkeypatch, tmp_path):
        constants = self._constants(monkeypatch, tmp_path)
        assert constants._get_platform_default_hermes_home() == tmp_path / ".hermes"

    @pytest.mark.windows_only
    def test_windows_prefers_localappdata_when_neither_is_initialized(
        self, monkeypatch, tmp_path
    ):
        """The case that broke test_classic_mode_no_active_profile_no_warning."""
        appdata = tmp_path / "AppData" / "Local"
        constants = self._constants(monkeypatch, tmp_path, appdata)
        assert constants._get_platform_default_hermes_home() == appdata / "hermes"

    @pytest.mark.windows_only
    def test_windows_prefers_initialized_legacy_over_bare_localappdata(
        self, monkeypatch, tmp_path
    ):
        appdata = tmp_path / "AppData" / "Local"
        (appdata / "hermes").mkdir(parents=True)  # exists, but no root marker
        legacy = tmp_path / ".hermes"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("")
        constants = self._constants(monkeypatch, tmp_path, appdata)
        assert constants._get_platform_default_hermes_home() == legacy

    @pytest.mark.windows_only
    def test_windows_keeps_localappdata_when_it_is_initialized(
        self, monkeypatch, tmp_path
    ):
        appdata = tmp_path / "AppData" / "Local"
        native = appdata / "hermes"
        native.mkdir(parents=True)
        (native / "active_profile").write_text("default\n")
        legacy = tmp_path / ".hermes"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("")
        constants = self._constants(monkeypatch, tmp_path, appdata)
        assert constants._get_platform_default_hermes_home() == native

    @pytest.mark.windows_only
    def test_windows_falls_back_to_home_appdata_when_env_unset(
        self, monkeypatch, tmp_path
    ):
        constants = self._constants(monkeypatch, tmp_path, local_appdata=None)
        assert (
            constants._get_platform_default_hermes_home()
            == tmp_path / "AppData" / "Local" / "hermes"
        )
