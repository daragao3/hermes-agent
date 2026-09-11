from __future__ import annotations

from pathlib import Path

from session_bridge import desktop_scheduled_handoff_cli as cli


class FakeDB:
    calls: list[bool] = []

    def __init__(self, path: Path, read_only: bool = False):
        self.calls.append(read_only)

    def close(self) -> None:
        pass


class FakeHandoff:
    def __init__(self, store, **kwargs):
        pass

    def plan(self, **kwargs):
        return {"phase": "disable_old_owners", "mutations": [], "plan": object()}

    def apply(self, **kwargs):
        return {"phase": "disable_old_owners", "mutations": [], "status": "applied"}


def _install(monkeypatch):
    FakeDB.calls = []
    monkeypatch.setattr(cli, "SessionDB", FakeDB)
    monkeypatch.setattr(cli, "SessionBridgeStore", lambda db: object())
    monkeypatch.setattr(cli, "discover_scheduled_catalogs", lambda: {"source": Path("s"), "target": Path("t")})
    monkeypatch.setattr(cli, "default_user_data_dirs", lambda: ())
    monkeypatch.setattr(
        cli,
        "detect_live_user_data_root",
        lambda roots: type("Live", (), {"root_id": "ud", "status": "one"})(),
    )
    monkeypatch.setattr(cli, "catalog_root_for_user_data", lambda catalogs, root: "target")
    monkeypatch.setattr(cli, "DesktopScheduledHandoff", FakeHandoff)


def test_default_plan_opens_state_database_read_only(monkeypatch) -> None:
    _install(monkeypatch)

    rc = cli.main(
        [
            "--source-root-id",
            "source",
            "--target-root-id",
            "target",
            "--task-id",
            "watch",
        ]
    )

    assert rc == 0
    assert FakeDB.calls == [True]


def test_apply_opens_state_database_writable(monkeypatch) -> None:
    _install(monkeypatch)

    rc = cli.main(
        [
            "--source-root-id",
            "source",
            "--target-root-id",
            "target",
            "--task-id",
            "watch",
            "--apply",
            "--confirm",
            cli.CONFIRMATION,
        ]
    )

    assert rc == 0
    assert FakeDB.calls == [False]
