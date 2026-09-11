"""Local daemon/rotation contracts through the upstream queue and profile router."""
import logging
import os
from pathlib import Path

import pytest

import hermes_logging as hl


def test_gateway_upgrade_keeps_forensics_and_profile_routing(tmp_path, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    monkeypatch.delenv("HERMES_GATEWAY_LOG_FILE", raising=False)
    home = Path(os.environ["HERMES_HOME"])
    other = tmp_path / "other-profile"
    other.mkdir()
    hl.setup_logging(hermes_home=home, mode="cli", force=True)
    hl.setup_logging(hermes_home=home, mode="gateway")
    hl.setup_logging(hermes_home=home, mode="gateway")
    paths = [Path(h.baseFilename) for h in hl.rotating_file_handlers()]
    assert len(paths) == len(set(paths))
    assert {"agent-gateway.log", "errors-gateway.log", "gateway-forensics.log"} <= {p.name for p in paths}
    assert hl.enable_profile_log_routing([home, other])
    logging.getLogger("events.carry-test").info("default-profile-event")
    token = set_hermes_home_override(other)
    try:
        logging.getLogger("gateway.carry-test").info("gateway-component-event")
        logging.getLogger("events.carry-test").info("owned-profile-event")
    finally:
        reset_hermes_home_override(token)
    hl.flush_log_queue()
    for name in ("agent-gateway.log", "gateway-forensics.log"):
        assert "owned-profile-event" in (other / "logs" / name).read_text(encoding="utf-8")
        assert "owned-profile-event" not in (home / "logs" / name).read_text(encoding="utf-8")
        assert "default-profile-event" not in (other / "logs" / name).read_text(encoding="utf-8")
    assert "owned-profile-event" not in (other / "logs" / "gateway.log").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="real Windows rename lock")
def test_locked_rotation_preserves_history_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, "_ROLLOVER_RETRY_DELAY_SEC", 0)
    base = tmp_path / "daemon.log"
    handler = hl._ManagedRotatingFileHandler(str(base), maxBytes=200, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    backup = tmp_path / "daemon.log.1"
    backup.write_text("historical-record", encoding="utf-8")
    try:
        handler.emit(logging.makeLogRecord({"msg": "live-record"}))
        with base.open("a", encoding="utf-8"):
            handler.doRollover()
            assert backup.read_text(encoding="utf-8") == "historical-record"
            assert handler._rollover_blocked_until > 0
            handler.emit(logging.makeLogRecord({"msg": "record-during-lock"}))
        handler._rollover_blocked_until = 0
        handler.doRollover()
        assert "record-during-lock" in backup.read_text(encoding="utf-8")
        assert "live-record" in backup.read_text(encoding="utf-8")
        assert (tmp_path / "daemon.log.2").read_text(encoding="utf-8") == "historical-record"
    finally:
        handler.close()


@pytest.mark.parametrize("argv,role,mode", [
    (["hermes", "-p", "default", "dashboard"], "dashboard", "gui"),
    (["hermes", "-v", "gateway", "run"], "gateway", "cli"),
    (["hermes", "logs", "gateway"], None, "cli"),
])
def test_role_and_mode_preserve_launch_contract(argv, role, mode):
    assert hl.infer_daemon_role(argv) == role
    assert hl.infer_log_mode(argv) == mode
