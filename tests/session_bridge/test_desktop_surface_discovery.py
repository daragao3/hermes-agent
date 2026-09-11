from __future__ import annotations

from pathlib import Path

import pytest

from session_bridge import desktop_surface_discovery as discovery


class FakeProcess:
    def __init__(self, name: str, cmdline: list[str]):
        self.info = {"name": name, "cmdline": cmdline}


def test_live_root_requires_exactly_one_matching_claude_profile(tmp_path: Path, monkeypatch) -> None:
    a = tmp_path / "Claude"
    b = tmp_path / "Claude-3p"
    monkeypatch.setattr(
        "psutil.process_iter",
        lambda fields: [
            FakeProcess("Claude.exe", ["Claude.exe"]),
            FakeProcess("Claude.exe", ["Claude.exe", f"--user-data-dir={b}"]),
            FakeProcess("chrome.exe", ["chrome.exe", f"--user-data-dir={a}"]),
        ],
    )

    result = discovery.detect_live_user_data_root((a, b))
    assert (result.status, result.root_id) == ("one", discovery._root_id(b))
    assert discovery.live_user_data_root((a, b)) == discovery._root_id(b)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_live_root_distinguishes_zero_from_multiple_profiles(
    tmp_path: Path, monkeypatch, ambiguous: bool
) -> None:
    a = tmp_path / "A"
    b = tmp_path / "B"
    processes = (
        [
            FakeProcess("Claude.exe", ["Claude.exe", f"--user-data-dir={a}"]),
            FakeProcess("Claude.exe", ["Claude.exe", f"--user-data-dir={b}"]),
        ]
        if ambiguous
        else []
    )
    monkeypatch.setattr("psutil.process_iter", lambda fields: processes)

    result = discovery.detect_live_user_data_root((a, b))
    assert (result.status, result.root_id) == (
        "ambiguous" if ambiguous else "none",
        None,
    )
    assert discovery.live_user_data_root((a, b)) is None


def test_unreadable_claude_command_line_is_not_treated_as_app_closed(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "Claude"
    monkeypatch.setattr(
        "psutil.process_iter",
        lambda fields: [FakeProcess("Claude.exe", [])],
    )

    result = discovery.detect_live_user_data_root((root,))

    assert (result.status, result.root_id) == ("unavailable", None)
    with pytest.raises(RuntimeError, match="unavailable"):
        discovery.active_user_data_root_for_writes((root,))


def test_presentation_discovery_uses_root_level_config_and_session_tree(tmp_path: Path) -> None:
    good = tmp_path / "Claude"
    good.mkdir()
    (good / "claude_desktop_config.json").write_text("{}", encoding="utf-8")
    (good / "claude-code-sessions").mkdir()
    incomplete = tmp_path / "Claude-3p"
    incomplete.mkdir()
    (incomplete / "claude_desktop_config.json").write_text("{}", encoding="utf-8")

    roots = discovery.discover_presentation_roots((good, incomplete))

    assert list(roots) == [discovery._root_id(good)]
    assert roots[discovery._root_id(good)][1] == good / "claude-code-sessions"


def test_catalog_maps_back_to_user_data_root() -> None:
    catalog = Path("C:/Users/diego/AppData/Local/Claude-3p/claude-code-sessions/a/w/scheduled-tasks.json")
    assert discovery.user_data_root_for_catalog(catalog) == Path(
        "C:/Users/diego/AppData/Local/Claude-3p"
    )


def test_active_catalog_uses_config_account_with_two_accounts_in_one_root(tmp_path: Path) -> None:
    root = tmp_path / "Claude"
    root.mkdir()
    (root / "config.json").write_text(
        '{"lastKnownAccountUuid":"account-b"}', encoding="utf-8"
    )
    a = root / "claude-code-sessions" / "account-a" / "ws" / "scheduled-tasks.json"
    b = root / "claude-code-sessions" / "account-b" / "ws" / "scheduled-tasks.json"
    catalogs = {discovery._root_id(a.parent): a, discovery._root_id(b.parent): b}

    assert discovery.catalog_root_for_user_data(
        catalogs, discovery._root_id(root)
    ) == discovery._root_id(b.parent)
