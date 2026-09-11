"""Regression tests: `hermes dashboard` validates HERMES_WEB_DIST before serving.

A custom HERMES_WEB_DIST without --skip-build previously skipped BOTH the
build and any validation, so the server started and served 404s with no
obvious cause (same failure mode as issue #23817, reached via the env-var
path instead of --skip-build). The env-var branch must now fail fast when
the dist has no index.html, and proceed when it does.

Design credit: PR #17845 (@Caelier).
"""

from pathlib import Path
import sys
import types

import pytest

# Fork's cmd_dashboard also does `from hermes_cli.web_server import WEB_DIST`
# (main.py, 2026-04-17 already-built check) before it ever reaches the
# HERMES_WEB_DIST validation these tests pin, so the stub module must expose
# it. Value is irrelevant to these tests (a nonexistent path just makes the
# already-built short-circuit evaluate False, same as production on a clean
# checkout) -- only its presence (avoiding ImportError) matters.
_STUB_WEB_DIST = Path("nonexistent-hermes-web-dist-stub")


@pytest.fixture()
def main_mod(monkeypatch, tmp_path):
    import hermes_cli.main as main
    from hermes_cli import main_web_build
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    def unexpected_build(*a, **k):
        raise AssertionError("A dashboard unit test attempted a real web build")
    monkeypatch.setattr(main, "_build_web_ui", unexpected_build)
    monkeypatch.setattr(main_web_build, "_build_web_ui", lambda *a, **k: main._build_web_ui(*a, **k))
    return main


def _args(**over):
    base = {
        "host": "127.0.0.1",
        "port": 0,
        "no_open": True,
        "open_profile": None,
        "skip_build": False,
        "headless_backend": False,
        "tui": False,
    }
    base.update(over)
    return types.SimpleNamespace(**base)


def _wire_common(main_mod, monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: "default"
    )
    monkeypatch.setattr(main_mod, "_sync_bundled_skills_quietly", lambda: None)
    monkeypatch.setitem(sys.modules, "fastapi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "hermes_logging",
        types.SimpleNamespace(setup_logging=lambda **_k: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )
    monkeypatch.setattr(
        "hermes_cli.mcp_startup.start_background_mcp_discovery",
        lambda **_k: None,
    )


def test_env_dist_without_index_exits(main_mod, monkeypatch, tmp_path, capsys):
    """HERMES_WEB_DIST pointing at a dist with no index.html must exit 1,
    not start a server that 404s."""
    _wire_common(main_mod, monkeypatch)
    empty_dist = tmp_path / "empty_dist"
    empty_dist.mkdir()
    monkeypatch.setenv("HERMES_WEB_DIST", str(empty_dist))

    started = []
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.web_server",
        types.SimpleNamespace(
            start_server=lambda **k: started.append(k), WEB_DIST=_STUB_WEB_DIST
        ),
    )
    builds = []
    monkeypatch.setattr(
        "hermes_cli.main_web_build._build_web_ui", lambda *a, **k: builds.append(a) or True
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_dashboard(_args())

    assert exc.value.code == 1
    assert started == []
    assert builds == []  # env var set -> build skipped, validation is the gate
    out = capsys.readouterr().out
    assert "HERMES_WEB_DIST" in out and str(empty_dist) in out




# ---------------------------------------------------------------------------
# --skip-build recovery (issue #59288): a missing dist under --skip-build
# should warn and attempt ONE recovery build via _build_web_ui before the
# fatal exit, instead of hard-failing immediately.
# ---------------------------------------------------------------------------


def test_skip_build_missing_dist_attempts_one_recovery_build(
    main_mod, monkeypatch, tmp_path, capsys
):
    """--skip-build + missing index.html triggers exactly one recovery build;
    when the build produces a dist, the server starts."""
    _wire_common(main_mod, monkeypatch)
    monkeypatch.delenv("HERMES_WEB_DIST", raising=False)
    project_root = tmp_path / "proj"
    dist = project_root / "hermes_cli" / "web_dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", project_root)

    started = []
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.web_server",
        types.SimpleNamespace(
            start_server=lambda **k: started.append(k), WEB_DIST=_STUB_WEB_DIST
        ),
    )

    builds = []

    def fake_build(web_dir, *, fatal=False):
        builds.append((web_dir, fatal))
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        return True

    monkeypatch.setattr("hermes_cli.main_web_build._build_web_ui", fake_build)

    main_mod.cmd_dashboard(_args(skip_build=True))

    assert len(builds) == 1  # exactly ONE recovery build
    assert builds[0][0] == project_root / "web"
    assert len(started) == 1
    out = capsys.readouterr().out
    assert "recovery build" in out.lower()




# ---------------------------------------------------------------------------
# Desktop-inherited env isolation (issue #52945 / supersedes #52948, #67402)
# ---------------------------------------------------------------------------







def test_env_dist_tilde_expanded_for_web_server(main_mod, monkeypatch, tmp_path):
    """A '~/...' HERMES_WEB_DIST must be written back expanded so
    web_server's raw os.environ read serves the validated path."""
    _wire_common(main_mod, monkeypatch)
    home = tmp_path / "home"
    dist = home / "mydist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    # ntpath.expanduser() checks USERPROFILE before HOME (posixpath only
    # checks HOME, so this is a no-op there) -- without it, Path("~/mydist")
    # .expanduser() resolves against the real Windows user profile instead
    # of the fixture's fake home, and this test's tilde-expansion assertion
    # observes the developer's real HOME dir path instead of tmp_path.
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HERMES_WEB_DIST", "~/mydist")

    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.web_server",
        types.SimpleNamespace(start_server=lambda **k: None, WEB_DIST=_STUB_WEB_DIST),
    )


    main_mod.cmd_dashboard(_args())
    import os
    assert os.environ["HERMES_WEB_DIST"] == str(dist)


def test_already_built_dist_without_env_starts_server(
    main_mod, monkeypatch, tmp_path
):
    """Regression (2026-07-22 boot, upstream v2026.7.20 merge): default dist
    already built + NO HERMES_WEB_DIST + no --skip-build fell into the env-var
    validation branch and KeyError'd on os.environ["HERMES_WEB_DIST"], killing
    every dashboard relaunch (laptop-monitor's :9119 restart breaker tripped).
    This path must start the server using the built dist, no build, no crash."""
    _wire_common(main_mod, monkeypatch)
    monkeypatch.delenv("HERMES_WEB_DIST", raising=False)

    built = tmp_path / "hermes_cli" / "web_dist"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<html></html>", encoding="utf-8")
    (built / "assets" / "app.js").write_text("//", encoding="utf-8")

    started = []
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.web_server",
        types.SimpleNamespace(
            start_server=lambda **k: started.append(k), WEB_DIST=built
        ),
    )
    builds = []
    monkeypatch.setattr(
        main_mod, "_build_web_ui", lambda *a, **k: builds.append(a) or True
    )

    main_mod.cmd_dashboard(_args())

    assert len(started) == 1
    assert builds == []  # already built -> no rebuild, and crucially no KeyError
