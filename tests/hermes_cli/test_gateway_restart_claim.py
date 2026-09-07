"""Restart claims for gateway bounces (hermes_cli.gateway_restart_claim, 2026-09-07).

Three agent sessions bounced the gateway three times in 3h15m on 2026-09-07,
each deploying its own fix, none aware of the others. The loops claim gate
matches on target and the gateway is a shared resource, so nothing surfaced
it. These tests cover the restart claim that ``hermes gateway restart`` and
``hermes gateway run --replace`` now open before stopping the incumbent, the
preflight that refuses to stack on another session's open bounce, and the
flags that carry the reason.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import gateway_restart_claim as grc


def _write_registry(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")


def _rec(claim_id, *, status, age_s, session="ccd:other", title="deploy x"):
    updated = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    return {
        "id": claim_id,
        "keywords": [grc.CLAIM_KEYWORDS],
        "title": title,
        "holders": [{"session": session, "harness": "claude-code", "worktree": "w"}],
        "status": status,
        "findings": "",
        "updated_at": updated,
    }


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    path = tmp_path / "loops" / "claims.json"
    monkeypatch.setenv("HERMES_LOOPS_REGISTRY", str(path))
    monkeypatch.setenv("HERMES_LOOP_SESSION", "ccd:me")
    monkeypatch.delenv(grc.CLAIM_ENV, raising=False)
    return path


class TestPreflight:
    def test_missing_registry_is_empty_not_an_error(self, registry):
        pf = grc.preflight()
        assert pf.blocking is None and pf.recent == [] and pf.error is None
        assert pf.render() == []

    def test_other_sessions_young_open_claim_blocks(self, registry):
        _write_registry(registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=120)])
        pf = grc.preflight()
        assert pf.blocking is not None and pf.blocking["id"] == "gateway-restart-20260907-140000"
        text = "\n".join(pf.render())
        assert "IN PROGRESS" in text and "ccd:other" in text and "deploy x" in text
        assert "--ignore-restart-claim" in text

    def test_my_own_open_claim_does_not_block(self, registry):
        _write_registry(
            registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=60, session="ccd:me")]
        )
        pf = grc.preflight()
        assert pf.blocking is None
        assert [r["id"] for r in pf.recent] == ["gateway-restart-20260907-140000"]

    def test_stale_open_claim_is_reported_not_blocking(self, registry):
        _write_registry(
            registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=grc.OPEN_WINDOW_S + 60)]
        )
        pf = grc.preflight()
        assert pf.blocking is None
        assert [r["id"] for r in pf.recent] == ["gateway-restart-20260907-140000"]

    def test_recent_done_claims_are_reported_and_old_ones_dropped(self, registry):
        _write_registry(registry, [
            _rec("gateway-restart-20260907-100000", status="done", age_s=grc.RECENT_WINDOW_S + 1),
            _rec("gateway-restart-20260907-130000", status="done", age_s=3600),
            _rec("gateway-restart-20260907-145900", status="done", age_s=30),
            _rec("cron-something-else", status="active", age_s=10),
        ])
        pf = grc.preflight()
        assert pf.blocking is None
        assert [r["id"] for r in pf.recent] == ["gateway-restart-20260907-145900", "gateway-restart-20260907-130000"]
        text = "\n".join(pf.render())
        assert "still booting" in text  # the 30s one
        assert "already live" in text  # the 1h one
        assert "cron-something-else" not in text

    def test_unreadable_registry_warns_and_does_not_block(self, registry):
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("{not json", encoding="utf-8")
        pf = grc.preflight()
        assert pf.blocking is None and pf.recent == []
        assert pf.error and "JSONDecodeError" in pf.error
        assert any("unreadable" in line for line in pf.render())

    def test_only_stamp_shaped_ids_are_bounce_records(self, registry):
        """A task claim that merely STARTS with the prefix is not a bounce."""
        _write_registry(registry, [
            _rec("gateway-restart-claim-coordination-20260907", status="active", age_s=60),
            _rec("gateway-restart-runbook-whatsapp-field-20260902", status="active", age_s=60),
            _rec("gateway-restart-20260907-140000", status="done", age_s=60),
        ])
        pf = grc.preflight()
        assert pf.blocking is None
        assert [r["id"] for r in pf.recent] == ["gateway-restart-20260907-140000"]

    def test_youngest_blocking_claim_is_the_one_reported(self, registry):
        _write_registry(registry, [
            _rec("gateway-restart-20260907-140001", status="active", age_s=600, session="ccd:a"),
            _rec("gateway-restart-20260907-140002", status="active", age_s=30, session="ccd:b"),
        ])
        assert grc.preflight().blocking["id"] == "gateway-restart-20260907-140002"


def _loops_available():
    return grc.loops_py_path() is not None


@pytest.mark.skipif(not _loops_available(), reason="~/.hermes/bin/loops.py not on this box")
class TestRestartClaimRoundTrip:
    def test_open_then_close_writes_a_done_record_with_pids(self, registry):
        claim = grc.RestartClaim.open(
            reason="deploy accba55c27", surface="cli:restart", incumbent_pids=[111]
        )
        assert claim.opened, claim.detail
        assert claim.claim_id.startswith(grc.CLAIM_PREFIX)
        assert os.environ.get(grc.CLAIM_ENV) == claim.claim_id
        records, err = grc.load_restart_records()
        assert err is None
        rec = next(r for r in records if r["id"] == claim.claim_id)
        assert rec["status"] == "active"
        assert rec["title"] == "deploy accba55c27"
        assert "IN PROGRESS" in rec["findings"] and "111" in rec["findings"]
        assert rec["holders"][0]["session"] == "ccd:me"
        # While open, a DIFFERENT session's preflight is blocked.
        os.environ["HERMES_LOOP_SESSION"] = "ccd:someone-else"
        assert grc.preflight().blocking["id"] == claim.claim_id
        os.environ["HERMES_LOOP_SESSION"] = "ccd:me"

        claim.close(outcome="DONE", new_pids=[222])
        assert claim.closed
        assert grc.CLAIM_ENV not in os.environ
        records, _ = grc.load_restart_records()
        rec = next(r for r in records if r["id"] == claim.claim_id)
        assert rec["status"] == "done"
        assert "DONE" in rec["findings"] and "111" in rec["findings"] and "222" in rec["findings"]
        # Closed: no longer blocking, but reported as recent for the next session.
        os.environ["HERMES_LOOP_SESSION"] = "ccd:someone-else"
        pf = grc.preflight()
        assert pf.blocking is None and pf.recent[0]["id"] == claim.claim_id
        # Idempotent close.
        claim.close(outcome="DONE", new_pids=[333])

    def test_missing_reason_is_recorded_as_such(self, registry):
        claim = grc.RestartClaim.open(reason="   ", surface="cli:restart", incumbent_pids=[])
        assert claim.opened, claim.detail
        rec = next(r for r in grc.load_restart_records()[0] if r["id"] == claim.claim_id)
        assert "no reason given" in rec["title"]
        claim.close(outcome="DONE", new_pids=[])


class TestDegradation:
    def test_open_without_loops_py_is_inert_and_close_is_a_noop(self, registry, monkeypatch):
        monkeypatch.setenv("HERMES_LOOPS_PY", str(registry.parent / "nope.py"))
        claim = grc.RestartClaim.open(reason="x", surface="cli:restart", incumbent_pids=[1])
        assert claim.opened is False
        assert "loops.py not found" in claim.detail
        assert grc.CLAIM_ENV not in os.environ
        claim.close(outcome="DONE", new_pids=[2])  # must not raise
        assert not registry.exists()

    def test_guard_and_open_refuses_over_a_blocking_claim(self, registry, monkeypatch):
        _write_registry(registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=60)])
        out = []
        with pytest.raises(SystemExit) as exc:
            grc.guard_and_open(
                reason="x", surface="cli:restart", incumbent_pids=[1], printer=out.append
            )
        assert exc.value.code == 2
        assert any("IN PROGRESS" in line for line in out)
        # Nothing was opened.
        records, _ = grc.load_restart_records()
        assert [r["id"] for r in records] == ["gateway-restart-20260907-140000"]

    def test_guard_and_open_override_proceeds(self, registry, monkeypatch):
        _write_registry(registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=60)])
        monkeypatch.setenv("HERMES_LOOPS_PY", str(registry.parent / "nope.py"))  # inert write
        out = []
        claim = grc.guard_and_open(
            reason="x", surface="cli:restart", incumbent_pids=[1],
            ignore_blocking=True, printer=out.append,
        )
        assert claim.opened is False
        assert any("--ignore-restart-claim given" in line for line in out)
        assert any("Could not record a restart claim" in line for line in out)

    def test_child_of_a_claiming_parent_opens_nothing(self, registry, monkeypatch):
        monkeypatch.setenv(grc.CLAIM_ENV, "gateway-restart-20260907-140003")
        _write_registry(registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=60)])
        out = []
        claim = grc.guard_and_open(
            reason="x", surface="cli:run --replace", incumbent_pids=[1], printer=out.append
        )
        assert claim.claim_id == "gateway-restart-20260907-140003" and claim.opened is False
        assert out == []  # no preflight either: the parent is the one bouncing


@pytest.mark.skipif(not _loops_available(), reason="~/.hermes/bin/loops.py not on this box")
class TestRestartCommandIntegration:
    """``hermes gateway restart`` on the Windows path opens and closes the claim."""

    def _drive(self, monkeypatch, *, restart_impl, pids_after, args=None):
        from hermes_cli import gateway, gateway_windows

        monkeypatch.setattr(gateway, "is_windows", lambda: True)
        monkeypatch.setattr(gateway, "is_macos", lambda: False)
        monkeypatch.setattr(gateway, "supports_systemd_services", lambda: False)
        monkeypatch.setattr(gateway, "_dispatch_via_service_manager_if_s6", lambda _a: False)
        monkeypatch.setattr(gateway, "_dispatch_all_via_service_manager_if_s6", lambda _a: False)
        monkeypatch.setattr(gateway_windows, "is_installed", lambda: False)
        monkeypatch.setattr(gateway_windows, "restart", restart_impl)
        state = {"pids": [111]}
        monkeypatch.setattr(gateway, "find_gateway_pids", lambda: list(state["pids"]))

        def _restart_and_swap():
            restart_impl()
            state["pids"] = pids_after

        monkeypatch.setattr(gateway_windows, "restart", _restart_and_swap)
        monkeypatch.delenv("_HERMES_GATEWAY", raising=False)
        ns = args or SimpleNamespace(
            gateway_command="restart", system=False, all=False,
            reason="deploy accba55c27", ignore_restart_claim=False,
        )
        gateway.gateway_command(ns)

    def test_restart_opens_before_and_closes_after_with_new_pid(self, registry, monkeypatch, capsys):
        seen = {}

        def fake_restart():
            # At the moment the incumbent is being stopped, the claim is open.
            records, _ = grc.load_restart_records()
            seen["during"] = [(r["id"], r["status"]) for r in records]

        self._drive(monkeypatch, restart_impl=fake_restart, pids_after=[222])

        assert len(seen["during"]) == 1 and seen["during"][0][1] == "active"
        records, _ = grc.load_restart_records()
        assert len(records) == 1
        rec = records[0]
        assert rec["status"] == "done"
        assert rec["title"] == "deploy accba55c27"
        assert "DONE" in rec["findings"] and "111" in rec["findings"] and "222" in rec["findings"]
        assert grc.CLAIM_ENV not in os.environ
        out = capsys.readouterr().out
        assert "Restart claim gateway-restart-" in out

    def test_restart_refuses_over_another_sessions_open_claim(self, registry, monkeypatch, capsys):
        _write_registry(registry, [_rec("gateway-restart-20260907-140000", status="active", age_s=90)])
        called = []
        with pytest.raises(SystemExit) as exc:
            self._drive(monkeypatch, restart_impl=lambda: called.append(1), pids_after=[222])
        assert exc.value.code == 2
        assert called == []  # the incumbent was never touched
        out = capsys.readouterr().out
        assert "IN PROGRESS" in out and "ccd:other" in out

    def test_restart_closes_the_claim_even_when_the_body_exits(self, registry, monkeypatch, capsys):
        def exploding_restart():
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            self._drive(monkeypatch, restart_impl=exploding_restart, pids_after=[])
        records, _ = grc.load_restart_records()
        assert records and records[0]["status"] == "done"
        assert "EXIT 1" in records[0]["findings"]


def test_parser_accepts_reason_and_ignore_flag_on_restart_and_run():
    import argparse

    from hermes_cli.subcommands.gateway import build_gateway_parser

    parser = argparse.ArgumentParser(prog="hermes")
    build_gateway_parser(
        parser.add_subparsers(dest="command"),
        cmd_gateway=lambda _a: None,
        cmd_proxy=lambda _a: None,
        cmd_gateway_enroll=lambda _a: None,
    )
    ns = parser.parse_args(["gateway", "restart", "--reason", "deploy abc", "--ignore-restart-claim"])
    assert ns.reason == "deploy abc" and ns.ignore_restart_claim is True
    ns = parser.parse_args(["gateway", "restart"])
    assert ns.reason is None and ns.ignore_restart_claim is False
    ns = parser.parse_args(["gateway", "run", "--replace", "--reason", "deploy abc"])
    assert ns.replace is True and ns.reason == "deploy abc" and ns.ignore_restart_claim is False
