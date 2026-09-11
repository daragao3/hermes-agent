"""Profile catalogs must not initialize another schema owner's database."""

import sqlite3

import pytest
from hermes_cli.web_routers import profiles


@pytest.mark.parametrize("delegation_schema", [False, True])
def test_catalog_skips_non_session_db_without_mutation(tmp_path, delegation_schema):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as conn:
        if delegation_schema:
            conn.execute("CREATE TABLE async_delegations (id TEXT)")
    before = path.read_bytes()
    errors, reads = [], []
    result = profiles._read_profile_db("work", tmp_path, errors, lambda db: reads.append(True))
    assert result is None
    assert reads == []
    assert errors == []
    assert path.read_bytes() == before


def test_catalog_reports_unreadable_store(tmp_path):
    path = tmp_path / "state.db"
    path.write_bytes(b"not a SQLite database")
    errors = []
    assert profiles._read_profile_db("work", tmp_path, errors, lambda db: None) is None
    assert len(errors) == 1
    assert errors[0]["profile"] == "work"
    assert path.read_bytes() == b"not a SQLite database"


def test_concrete_catalog_can_page_past_cross_profile_cap(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    path = tmp_path / "state.db"
    db = SessionDB(db_path=path)
    try:
        for index in range(505):
            db.create_session(session_id=f"session-{index:04d}", source="cli")
        db._execute_write(lambda conn: conn.executemany(
            "UPDATE sessions SET started_at=? WHERE id=?",
            [(float(index + 1), f"session-{index:04d}") for index in range(505)]))
    finally:
        db.close()
    monkeypatch.setattr(profiles, "_cron_profile_home", lambda profile: (profile, tmp_path))
    result = profiles.get_profiles_sessions(profile="work", limit=3, offset=501, order="created")
    assert result["errors"] == []
    assert result["total"] == 505
    assert [row["id"] for row in result["sessions"]] == ["session-0003", "session-0002", "session-0001"]
