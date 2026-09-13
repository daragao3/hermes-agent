"""Windows native and legacy production roots are both test-isolation boundaries."""
import os
import sys
from pathlib import Path

import pytest

import hermes_state


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows legacy-root fallback")


@pytest.mark.parametrize("relative", ["state.db", "profiles/work/state.db"])
def test_legacy_root_is_refused_without_opening_a_database(tmp_path, monkeypatch, relative):
    home = tmp_path / "user"
    monkeypatch.setattr(os.path, "expanduser", lambda value: str(home) if value == "~" else value)
    monkeypatch.setattr(hermes_state, "_real_platform_state_root", lambda: home / "native")
    monkeypatch.setattr(hermes_state, "_in_test_context", lambda: True)
    monkeypatch.setattr(hermes_state, "_STATE_DB_GUARD_BYPASS", False)
    monkeypatch.delenv(hermes_state._STATE_DB_GUARD_BYPASS_ENV, raising=False)
    with pytest.raises(RuntimeError, match="live-system guard"):
        hermes_state._ensure_test_isolation(home / ".hermes" / relative)
    assert not home.exists()


def test_legacy_root_does_not_block_explicit_scratch_home(tmp_path, monkeypatch):
    home = tmp_path / "user"
    scratch = home / ".hermes" / "scratch" / "test-home"
    monkeypatch.setattr(os.path, "expanduser", lambda value: str(home) if value == "~" else value)
    monkeypatch.setattr(hermes_state, "_real_platform_state_root", lambda: home / "native")
    monkeypatch.setattr(hermes_state, "_in_test_context", lambda: True)
    monkeypatch.setenv("HERMES_HOME", str(scratch))
    hermes_state._ensure_test_isolation(scratch / "state.db")
    assert not home.exists()


def test_real_windows_default_resolution_is_guarded(tmp_path, monkeypatch):
    from hermes_constants import _get_platform_default_hermes_home

    home = tmp_path / "user"
    legacy = home / ".hermes"
    legacy.mkdir(parents=True)
    (legacy / "config.yaml").write_text("", encoding="utf-8")
    native_base = home / "AppData" / "Local"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(os.path, "expanduser", lambda value: str(home) if value == "~" else value)
    monkeypatch.setenv("LOCALAPPDATA", str(native_base))
    monkeypatch.setattr(hermes_state, "_in_test_context", lambda: True)
    resolved = _get_platform_default_hermes_home()
    assert resolved == legacy
    for root in (resolved, native_base / "hermes"):
        with pytest.raises(RuntimeError, match="live-system guard"):
            hermes_state._ensure_test_isolation(root / "state.db")
    assert not (legacy / "state.db").exists()
