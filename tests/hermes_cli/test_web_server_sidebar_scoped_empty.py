"""The sidebar aggregate must let a client tell a scoped-but-EMPTY profile
apart from a broken one.

A scope that MATCHES a real profile, on a request that SUCCEEDS, can still
return zero rows -- the recents slice excludes cron/subagent/tool/messaging by
design, and a profile can legitimately hold nothing else. Measured on this box
2026-09-07: ~/.hermes/profiles/main holds 1,132 sessions that are 100% excluded
sources, so scoping the sidebar to it returns total 0, profile_matched True and
no errors, and the desktop rendered a confident empty sidebar over a machine
with 8,309 showable chats in the default profile.

`profile_totals` cannot answer that on its own: under a concrete scope it
carries ONLY that profile's key, so the comparison number is absent by
construction. `all_profile_totals` carries every profile regardless of scope.
The two stay SEPARATE because the desktop ITERATES `profile_totals` to decide
which profile catalogs to hydrate -- widening it would make a scoped sidebar
re-fetch every profile.
"""
import pytest


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch, _isolate_hermes_home):
    from hermes_constants import get_hermes_home
    from hermes_cli import profiles

    default_home = get_hermes_home()
    profiles_root = default_home / "profiles"
    worker_home = profiles_root / "worker_beta"
    for home in (default_home, worker_home):
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(profiles, "_get_default_hermes_home", lambda: default_home)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: profiles_root)
    return {"default": default_home, "worker_beta": worker_home}


@pytest.fixture
def client(monkeypatch, isolated_profiles):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from hermes_constants import get_hermes_home
    from fastapi import FastAPI
    from hermes_cli.web_routers import profiles as profile_routes
    app = FastAPI()
    app.include_router(profile_routes.sessions_router)
    monkeypatch.setattr(profile_routes, "_SIDEBAR_CACHE_TTL_SECONDS", 0)
    profile_routes._sidebar_profile_cache_clear()

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
    c = TestClient(app)
    return c


def _seed(home, rows):
    """Create sessions with one message each in that profile's state.db."""
    from hermes_state import SessionDB

    db = SessionDB(db_path=home / "state.db")
    try:
        for sid, src in rows:
            db.create_session(session_id=sid, source=src)
            db.append_message(session_id=sid, role="user", content="hi")
    finally:
        db.close()


def _sidebar(client, scope):
    resp = client.get(
        "/api/profiles/sessions/sidebar"
        f"?recents_profile={scope}&recents_limit=20&recents_exclude=cron,subagent,tool,telegram"
    )
    assert resp.status_code == 200
    return resp.json()


class TestSidebarScopedEmpty:
    def test_all_profile_totals_names_the_other_profile_under_a_concrete_scope(
        self, client, isolated_profiles
    ):
        """THE CASE THIS EXISTS FOR. worker_beta is real, matched, populated --
        and holds only excluded sources, so it shows nothing. The response must
        still carry default's count, or the client cannot say where the chats
        are."""
        _seed(isolated_profiles["default"], [("d-1", "desktop"), ("d-2", "desktop")])
        _seed(isolated_profiles["worker_beta"], [("w-cron", "cron"), ("w-sub", "subagent")])

        recents = _sidebar(client, "worker_beta")["recents"]

        # Everything says "healthy": matched scope, no errors, zero rows.
        assert recents["profile"] == "worker_beta"
        assert recents["profile_matched"] is True
        assert recents["sessions"] == []
        assert recents["total"] == 0

        # profile_totals alone CANNOT distinguish this from a broken load.
        assert recents["profile_totals"] == {"worker_beta": 0}

        # all_profile_totals can: it names where the chats actually are.
        assert recents["all_profile_totals"]["worker_beta"] == 0
        assert recents["all_profile_totals"]["default"] == 2

    def test_profile_totals_stays_scoped(self, client, isolated_profiles):
        """Load-bearing separation. The desktop iterates profile_totals to pick
        catalogs to hydrate; if this ever becomes a superset, a scoped sidebar
        starts re-fetching every profile on every refresh."""
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        _seed(isolated_profiles["worker_beta"], [("w-1", "desktop")])

        scoped = _sidebar(client, "worker_beta")["recents"]

        assert set(scoped["profile_totals"]) == {"worker_beta"}
        assert set(scoped["all_profile_totals"]) >= {"worker_beta", "default"}

    def test_scope_all_keeps_both_maps_agreeing(self, client, isolated_profiles):
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        _seed(isolated_profiles["worker_beta"], [("w-1", "desktop")])

        recents = _sidebar(client, "all")["recents"]

        assert recents["profile_totals"] == recents["all_profile_totals"]
        assert recents["total"] == 2

    def test_total_does_not_absorb_out_of_scope_counts(self, client, isolated_profiles):
        """`total` drives "Load more" for the rows actually shown. Summing
        out-of-scope profiles into it would keep that footer permanently on."""
        _seed(isolated_profiles["default"], [("d-1", "desktop"), ("d-2", "desktop")])
        _seed(isolated_profiles["worker_beta"], [("w-1", "desktop")])

        recents = _sidebar(client, "worker_beta")["recents"]

        assert recents["total"] == 1
        assert len(recents["sessions"]) == 1
