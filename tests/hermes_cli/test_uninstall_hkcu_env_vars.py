"""``hermes uninstall`` must only delete the HKCU env vars that belong to the home it is removing.

``HKCU\\Environment\\HERMES_HOME`` is the desktop app's home anchor for the REAL install. This
box also uninstalls sandbox / upgrade-candidate / temp homes, and the old unconditional
``DeleteValue`` wiped the anchor for whichever home happened to be torn down (loops
``hkcu-hermes-home-wipe-attribution-20260915``). ``HERMES_GIT_BASH_PATH`` follows the same
rule, widened to "points inside this home" because install.ps1 may set it to a portable Git
under the home OR to a system Git.

The registry is a fake injected through the ``_edit_user_environment`` seam -- nothing here
opens the real HKCU.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import uninstall

REAL_HOME = r"C:\Users\diego\.hermes"


class _FakeKey:
    REG_SZ = 1

    def __init__(self, values: dict[str, str]):
        self.values = dict(values)

    def QueryValueEx(self, key, name):
        assert key is self
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):
        assert key is self
        del self.values[name]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):
    """Route ``_edit_user_environment`` at an in-memory HKCU\\Environment; returns a seeder that
    hands back the fake so tests can assert on what survived."""
    holder: dict[str, _FakeKey] = {}

    def fake_edit_user_environment(edit, *, warn_label):
        removed: list[str] = []
        edit(holder["key"], holder["key"], removed)
        return removed

    monkeypatch.setattr(uninstall, "_edit_user_environment", fake_edit_user_environment)

    def seed(**values: str) -> _FakeKey:
        holder["key"] = _FakeKey(values)
        return holder["key"]

    return seed


def test_deletes_hermes_home_when_it_points_at_the_uninstalled_home(registry, capsys):
    key = registry(HERMES_HOME=REAL_HOME)

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == ["HERMES_HOME"]
    assert "HERMES_HOME" not in key.values
    assert "Kept User env var" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "stored",
    [
        r"c:\users\diego\.HERMES",          # case
        "C:/Users/diego/.hermes",           # slash direction
        REAL_HOME + "\\",                   # trailing separator
        r"C:\Users\diego\.hermes\.",        # normpath-only difference
    ],
)
def test_match_is_path_normalized(registry, stored):
    key = registry(HERMES_HOME=stored)

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == ["HERMES_HOME"]
    assert "HERMES_HOME" not in key.values


def test_match_expands_env_vars_in_the_stored_value(registry, monkeypatch):
    """REG_EXPAND_SZ values are stored unexpanded; ``_perform_uninstall`` compares the expanded
    home, so the stored side must expand too."""
    monkeypatch.setenv("USERPROFILE", r"C:\Users\diego")
    key = registry(HERMES_HOME=r"%USERPROFILE%\.hermes")

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == ["HERMES_HOME"]
    assert "HERMES_HOME" not in key.values


@pytest.mark.parametrize(
    "uninstalling",
    [
        r"C:\Users\diego\.hermes\upgrade-candidates\desktop-major-currency-20260913",  # child
        r"C:\Users\diego\AppData\Local\Temp\pytest-of-diego\hermes-sandbox",           # unrelated
        r"C:\Users\diego\.hermes-sandbox",                                             # prefix twin
    ],
)
def test_keeps_hermes_home_when_it_points_at_a_different_home(registry, capsys, uninstalling):
    """The regression: uninstalling a candidate / temp home must leave the real anchor alone."""
    key = registry(HERMES_HOME=REAL_HOME)

    removed = uninstall.remove_hermes_env_vars_windows(Path(uninstalling))

    assert removed == []
    assert key.values["HERMES_HOME"] == REAL_HOME
    out = capsys.readouterr().out
    assert f"Kept User env var HERMES_HOME={REAL_HOME}" in out
    assert uninstalling in out


def test_absent_values_are_a_no_op(registry, capsys):
    key = registry()

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == []
    assert key.values == {}
    assert "Kept User env var" not in capsys.readouterr().out


def test_git_bash_path_goes_with_a_matching_home_even_for_system_git(registry):
    """install.ps1 sets HERMES_GIT_BASH_PATH to a system Git when no portable one exists; it
    still belongs to the install whose HERMES_HOME we just matched."""
    key = registry(HERMES_HOME=REAL_HOME, HERMES_GIT_BASH_PATH=r"C:\Program Files\Git\bin\bash.exe")

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == ["HERMES_HOME", "HERMES_GIT_BASH_PATH"]
    assert key.values == {}


def test_git_bash_path_goes_when_it_points_inside_the_uninstalled_home(registry):
    """Portable Git under a candidate home: that value is the candidate's even though the
    anchor belongs to the real home."""
    candidate = r"C:\Users\diego\.hermes\upgrade-candidates\x"
    key = registry(HERMES_HOME=REAL_HOME, HERMES_GIT_BASH_PATH=candidate + r"\git\bin\bash.exe")

    removed = uninstall.remove_hermes_env_vars_windows(Path(candidate))

    assert removed == ["HERMES_GIT_BASH_PATH"]
    assert key.values == {"HERMES_HOME": REAL_HOME}


def test_git_bash_path_kept_when_neither_anchored_nor_inside(registry, capsys):
    """Anchor already gone (the observed state) + system Git: nothing proves the value is this
    home's, so leave it -- a stale override is harmless, a clobbered one is not."""
    candidate = r"C:\Users\diego\.hermes\upgrade-candidates\x"
    key = registry(HERMES_GIT_BASH_PATH=r"C:\Program Files\Git\bin\bash.exe")

    removed = uninstall.remove_hermes_env_vars_windows(Path(candidate))

    assert removed == []
    assert key.values == {"HERMES_GIT_BASH_PATH": r"C:\Program Files\Git\bin\bash.exe"}
    assert "Kept User env var HERMES_GIT_BASH_PATH=" in capsys.readouterr().out


def test_delete_failure_is_reported_not_raised(registry, capsys):
    key = registry(HERMES_HOME=REAL_HOME)

    def failing_delete(k, name):
        raise OSError("access denied")

    key.DeleteValue = failing_delete

    removed = uninstall.remove_hermes_env_vars_windows(Path(REAL_HOME))

    assert removed == []
    assert "Could not delete HERMES_HOME" in capsys.readouterr().out


def test_perform_uninstall_passes_the_expanded_home(monkeypatch, tmp_path):
    """The step wiring: the guard receives the %VAR%-expanded home (install.ps1 writes literal
    paths), so a HERMES_HOME given as ``%USERPROFILE%\\.hermes`` still matches the stored literal."""
    seen: list[Path] = []
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(uninstall, "_is_windows", lambda: True)
    monkeypatch.setattr(uninstall, "_is_default_hermes_home", lambda home: False)
    monkeypatch.setattr(uninstall, "uninstall_gateway_service", lambda: False)
    monkeypatch.setattr(uninstall, "remove_path_from_shell_configs", lambda: [])
    monkeypatch.setattr(uninstall, "remove_path_from_windows_registry", lambda home, **kw: [])
    monkeypatch.setattr(uninstall, "remove_hermes_env_vars_windows", lambda home: seen.append(home) or [])
    monkeypatch.setattr(uninstall, "remove_wrapper_script", lambda: [])
    monkeypatch.setattr(uninstall, "remove_windows_bin_launchers", lambda: [])
    monkeypatch.setattr(uninstall, "remove_node_symlinks", lambda home: [])
    monkeypatch.setattr(uninstall, "_rmtree_step", lambda p: None)
    monkeypatch.setattr(uninstall, "remove_portable_tooling_windows", lambda home: [])
    import hermes_cli.gui_uninstall as gui_uninstall
    monkeypatch.setattr(gui_uninstall, "uninstall_gui", lambda home: False)

    uninstall._perform_uninstall(
        project_root=tmp_path / "hermes-agent",
        hermes_home=Path(r"%USERPROFILE%\.hermes"),
        full_uninstall=False,
        remove_profiles=False,
        named_profiles=[],
    )

    assert seen == [tmp_path / ".hermes"]
