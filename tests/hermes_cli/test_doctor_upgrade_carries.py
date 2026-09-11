"""Bounded doctor checks and explicit opt-in behavior in isolation."""
from argparse import Namespace
from unittest.mock import Mock
import pytest
from hermes_cli import doctor, doctor_state, doctor_tools
from hermes_cli.doctor_report import Finding
from hermes_state import SessionDB, StateDbProbeTimeout
from hermes_state_repair import _db_opens_cleanly


def test_real_database_probe_is_bounded_and_leaves_no_rows(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.close()
    assert _db_opens_cleanly(path, timeout_seconds=5) is None
    db = SessionDB(path)
    try:
        assert db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        db.close()


def test_probe_timeout_never_repairs_database(tmp_path, monkeypatch, capsys):
    path = tmp_path / "state.db"
    path.touch()
    monkeypatch.setattr(doctor_state, "_session_count", lambda p: 0)
    monkeypatch.setattr("hermes_state_repair._db_opens_cleanly", Mock(side_effect=StateDbProbeTimeout("budget", 5)))
    repair = Mock()
    monkeypatch.setattr(doctor_state, "_repair_state_db", repair)
    findings = Finding()
    doctor_state._state_db_health(findings, True, path, str(tmp_path))
    repair.assert_not_called()
    assert findings.fixed == 0 and findings.issues == []
    assert "did not finish in budget" in capsys.readouterr().out


def test_default_audit_never_launches_npm(monkeypatch, capsys):
    monkeypatch.setattr(doctor_tools, "_safe_which", lambda name: "npm")
    audit = Mock()
    monkeypatch.setattr(doctor_tools, "_audit_npm_target", audit)
    doctor_tools._check_npm_audit(False)
    audit.assert_not_called()
    assert "--audit" in capsys.readouterr().out


def test_run_doctor_forwards_explicit_options_only_to_owners(monkeypatch):
    state, audit = Mock(return_value=Finding()), Mock(return_value=Finding())
    monkeypatch.setattr(doctor, "_check_state_db", state)
    monkeypatch.setattr(doctor, "_check_npm_audit", audit)
    monkeypatch.setattr(doctor, "DOCTOR_CHECKS", ((None, state), (None, audit)))
    monkeypatch.setattr("hermes_cli.doctor_live.maybe_run_live_checks", lambda *a: None)
    doctor.run_doctor(Namespace(fix=False, deep=True, audit=True))
    state.assert_called_once_with(False, deep=True)
    audit.assert_called_once_with(False, on_demand=True)



def test_actual_sqlite_interruption_is_unknown_not_corruption(tmp_path, monkeypatch):
    import sqlite3
    class SlowIntegrity(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA integrity_check":
                return super().execute("WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n")
            return super().execute(sql, *args, **kwargs)
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.close()
    conn = sqlite3.connect(path, factory=SlowIntegrity)
    monkeypatch.setattr("hermes_state_repair._connect_repair_durable", lambda p: conn)
    with pytest.raises(StateDbProbeTimeout):
        _db_opens_cleanly(path, timeout_seconds=0.05)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_deep_timeout_never_reports_healthy_or_rebuilds(tmp_path, monkeypatch, capsys):
    path = tmp_path / "state.db"
    path.touch()
    monkeypatch.setattr(doctor_state, "_session_count", lambda p: 0)
    monkeypatch.setattr("hermes_state_repair._db_opens_cleanly", lambda *a, **k: None)
    monkeypatch.setattr("hermes_state_local_fts.check_state_db_fts_integrity", Mock(side_effect=StateDbProbeTimeout("fts", 1)))
    rebuild = Mock()
    monkeypatch.setattr(SessionDB, "rebuild_fts", rebuild)
    findings = Finding()
    doctor_state._state_db_health(findings, True, path, str(tmp_path), deep=True)
    rebuild.assert_not_called()
    output = capsys.readouterr().out
    assert "full-text index check did not finish" in output
    assert "verifies against its content" not in output
    assert findings.fixed == 0 and findings.issues == []


def test_explicit_audit_dispatches_with_on_demand_budget(tmp_path, monkeypatch):
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(doctor_tools, "_safe_which", lambda name: "npm")
    monkeypatch.setattr("gateway.platforms.whatsapp_common.resolve_whatsapp_bridge_dir", lambda: tmp_path)
    audit = Mock()
    monkeypatch.setattr(doctor_tools, "_audit_npm_target", audit)
    doctor_tools._check_npm_audit(False, on_demand=True)
    assert audit.call_count == 4
    assert all(call.kwargs == {"on_demand": True} for call in audit.call_args_list)
