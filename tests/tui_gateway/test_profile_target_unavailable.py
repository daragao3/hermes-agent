"""An unavailable explicit target must never become the launch profile."""
import os
from pathlib import Path

import pytest

from tests.symlink_support import make_dir_link


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
        (path / "config.yaml").write_text(f"terminal:\n  cwd: /{marker}\n", encoding="utf-8")
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
    # A profiles/ directory that is BROKEN rather than absent must also fail
    # closed -- never silently degrade to the launch profile.
    #
    # This replaces a self-referential-symlink probe that claimed to force "a
    # real resolution I/O failure". It could not: _profile_home() calls
    # home.is_dir() BEFORE home.resolve(), and Path.is_dir() routes OSError
    # through pathlib's _ignore_error, which swallows ELOOP (and the Windows
    # reparse equivalents) and returns False. A symlink loop therefore left via
    # the "Profile does not exist" FileNotFoundError -- itself an OSError, so
    # pytest.raises((OSError, RuntimeError)) could not tell the two apart. It
    # asserted the same branch as the ("worker", "unknown") loop above, on every
    # platform, and was merely SKIPPED here for want of
    # SeCreateSymbolicLinkPrivilege. Measured 2026-09-14: is_dir() on an
    # unresolvable reparse path returns False and raises nothing.
    #
    # A dangling JUNCTION is the honest version and needs no privilege
    # (make_dir_link falls back to mklink /J): the path still EXISTS as a link
    # -- os.path.lexists() is True, which a plain missing path would not be --
    # while is_dir() is False, so the state under test is genuinely "broken
    # reparse point", not "absent".
    profiles = home / "profiles"
    profiles.rename(home / "saved-profiles")
    vanishing = tmp_path / "vanishing-profiles-target"
    vanishing.mkdir()
    make_dir_link(profiles, vanishing)
    vanishing.rmdir()
    assert os.path.lexists(profiles), "the link itself must survive its target"
    assert not profiles.is_dir(), "a dangling link must not read as a directory"
    with pytest.raises((OSError, RuntimeError)):
        server._profile_home("worker")


def test_custom_root_basename_target_fails_closed_when_unavailable(tmp_path, monkeypatch):
    """An explicit profile request matching a custom root basename fails closed."""
    from tui_gateway import server

    custom_home = tmp_path / "customer-data"
    custom_home.mkdir()
    (custom_home / "config.yaml").write_text("terminal:\n  cwd: /custom\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(custom_home))
    monkeypatch.setattr(server, "_hermes_home", custom_home)

    with pytest.raises(FileNotFoundError):
        server._profile_home("customer-data")

    with pytest.raises(FileNotFoundError):
        with server._profile_db({"profile": "customer-data"}):
            pass
