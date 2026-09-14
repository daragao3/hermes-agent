"""An unavailable explicit target must never become the launch profile."""
import os
from pathlib import Path

import pytest


def test_explicit_profile_target_never_falls_back(tmp_path, monkeypatch):
    from tui_gateway import server
    from hermes_state import SessionDB

    # The launch profile must be the home this process is ALREADY pinned to, not
    # a fresh tmp_path/".hermes". ``profile=None`` takes the argless registry
    # path, which resolves from ``hermes_state.DEFAULT_DB_PATH`` -- and
    # tests/conftest.py re-pins that to <tmp_path>/hermes_test/state.db, but
    # only when ``hermes_state`` is already in sys.modules when that autouse
    # fixture runs. A sibling file with a top-level ``import tui_gateway.server``
    # (e.g. test_subprocess_encoding.py) pulls hermes_state in at COLLECTION and
    # makes it true; run alone, this file's imports are deferred and it is not.
    # So inventing a second home made the launch-profile assertion pass or fail
    # on which other files happened to be collected alongside it, failing as
    # "assert None = get_session('launch')".
    home = Path(os.environ["HERMES_HOME"])
    worker = home / "profiles" / "worker"
    worker.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(server, "_hermes_home", home)
    # The _get_db() handle is a process-wide singleton; drop it so the
    # launch-profile branch rebuilds against THIS home. monkeypatch restores it.
    monkeypatch.setattr(server, "_db", None)
    for path, marker in ((home, "launch"), (worker, "worker")):
        (path / "config.yaml").write_text(f"terminal:\n  cwd: /{marker}\n")
        with SessionDB(db_path=path / "state.db") as db:
            db.create_session(marker, "tui")
    for name, marker in ((None, "launch"), ("default", "launch"), ("DEFAULT", "launch"), ("worker", "worker")):
        with server._profile_db({"profile": name}) as db:
            assert db.get_session(marker)
        response = server._methods["config.get"](1, {"profile": name, "key": "full"})
        assert response["result"]["config"]["terminal"]["cwd"] == f"/{marker}"
    before = (home / "config.yaml").read_bytes()
    worker.rename(worker.with_name("gone"))
    for name in ("worker", "unknown"):
        with pytest.raises(FileNotFoundError):
            with server._profile_db({"profile": name}):
                pytest.fail("unavailable profile reached a database")
        with pytest.raises(FileNotFoundError):
            server._methods["config.set"](2, {"profile": name, "key": "busy", "value": "steer"})
        assert (home / "config.yaml").read_bytes() == before
    # A real resolution I/O failure must propagate, too (no predicate patch).
    # The probe is a self-referential symlink, so it needs the privilege to
    # create one: on Windows without Developer Mode or an elevated shell that is
    # SeCreateSymbolicLinkPrivilege, and the attempt raises WinError 1314. Skip
    # only this stanza there -- every assertion above has already run.
    profiles = home / "profiles"
    profiles.rename(home / "saved-profiles")
    try:
        profiles.symlink_to("profiles")
    except OSError as exc:  # pragma: no cover - platform/privilege dependent
        pytest.skip(f"symlink creation unavailable on this host: {exc}")
    with pytest.raises((OSError, RuntimeError)):
        server._profile_home("worker")


def test_custom_root_basename_target_fails_closed_when_unavailable(tmp_path, monkeypatch):
    """An explicit profile request matching a custom root basename fails closed."""
    from tui_gateway import server

    custom_home = tmp_path / "customer-data"
    custom_home.mkdir()
    (custom_home / "config.yaml").write_text("terminal:\n  cwd: /custom\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(custom_home))
    monkeypatch.setattr(server, "_hermes_home", custom_home)

    with pytest.raises(FileNotFoundError):
        server._profile_home("customer-data")

    with pytest.raises(FileNotFoundError):
        with server._profile_db({"profile": "customer-data"}):
            pass
