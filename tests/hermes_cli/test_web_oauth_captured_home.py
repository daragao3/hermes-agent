"""OAuth workers keep the home captured when their request started."""

import pytest


def test_session_captures_home(tmp_path, monkeypatch):
    from hermes_cli.web_routers import oauth
    from hermes_cli import web_server_oauth as state

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    sid, session = oauth._new_oauth_session("nous", "device_code")
    try:
        assert session["hermes_home"] == str(tmp_path.resolve())
        assert state._oauth_session_home(sid) == str(tmp_path.resolve())
    finally:
        with state._oauth_sessions_lock:
            state._oauth_sessions.pop(sid, None)


@pytest.mark.parametrize("profile", [None, "current", "work"])
def test_captured_scope_restores_home_and_named_profile_wins(tmp_path, monkeypatch, profile):
    from hermes_cli import web_server_profiles as profiles
    from hermes_constants import get_hermes_home

    live, captured, named = (tmp_path / name for name in ("live", "captured", "named"))
    monkeypatch.setenv("HERMES_HOME", str(live))
    monkeypatch.setattr(profiles, "_resolve_profile_dir", lambda name: named)
    with profiles._config_profile_scope(profile, hermes_home=str(captured)):
        assert get_hermes_home() == (named if profile == "work" else captured)
    assert get_hermes_home() == live


def test_nous_poller_saves_under_captured_home(tmp_path, monkeypatch):
    import time
    from hermes_cli.web_routers import oauth
    from hermes_cli import web_server_oauth as state, auth
    from hermes_constants import get_hermes_home

    original, later = tmp_path / "original", tmp_path / "later"
    monkeypatch.setenv("HERMES_HOME", str(original))
    sid, session = oauth._new_oauth_session("nous", "device_code")
    session.update(portal_base_url="https://portal.invalid", client_id="test", device_code="test",
                   interval=1, expires_at=time.time() + 600)
    monkeypatch.setattr(auth, "_poll_for_token", lambda **kw: {"access_token": "test", "expires_in": 60})
    monkeypatch.setattr(auth, "refresh_nous_oauth_from_state", lambda value, **kw: value)
    saved = []
    monkeypatch.setattr(auth, "persist_nous_credentials", lambda value: saved.append(get_hermes_home()))
    monkeypatch.setenv("HERMES_HOME", str(later))
    try:
        state._nous_poller(sid)
        assert session["status"] == "approved", session.get("error_message")
        assert saved == [original]
        assert get_hermes_home() == later
    finally:
        with state._oauth_sessions_lock:
            state._oauth_sessions.pop(sid, None)
