"""A cleared pressure axis must retire cleanup authority immediately."""
from datetime import datetime, timezone

import pytest

from claude_fleet_control.models import FleetPolicy
from claude_fleet_control.planner import evaluate_pressure
from events.bus import EventBus
from events.producers.resource_monitor import ResourcePressureMonitor
from events.noise_guards import is_sustained_resource_repeat
from events.schema import EventType
from tests.events.producers.test_resource_monitor import make_sample


@pytest.mark.parametrize("disk_free_gb", [300.0, 35.0])
def test_clear_retires_authority_even_with_another_axis_open(tmp_path, disk_free_gb):
    bus = EventBus(db_path=tmp_path / "events.db")
    monitor = ResourcePressureMonitor(bus)
    monitor.evaluate(make_sample(commit_pct=95, disk_free_gb=disk_free_gb), now=0)
    monitor.evaluate(make_sample(commit_pct=50, disk_free_gb=disk_free_gb), now=60)
    events = bus.query(event_type=EventType.RESOURCE_PRESSURE)
    latest = events[-1]
    assert latest.payload["change"] == "axes_cleared"
    assert "commit_high" not in latest.payload["axes_latched"]
    pressure = evaluate_pressure([
        {"event_id": e.event_id, "timestamp": e.timestamp, "payload": e.payload}
        for e in events
    ], datetime.now(timezone.utc).timestamp(), FleetPolicy(commit_pct_arm=90))
    assert not pressure.valid
    assert is_sustained_resource_repeat(latest)  # Both delivery lanes suppress it.
    monitor.evaluate(make_sample(commit_pct=50, disk_free_gb=disk_free_gb), now=61)
    assert len(bus.query(event_type=EventType.RESOURCE_PRESSURE)) == len(events)


def test_clear_between_plan_and_action_cancels_executor(tmp_path, monkeypatch):
    from tests.claude_fleet_control.conftest import NOW, USER, iso
    from tests.claude_fleet_control.test_controller import (
        _fleet, _make_controller, _prime_second_strike, _write_config,
    )

    monkeypatch.setenv("USERNAME", USER)
    policy = FleetPolicy(mode="enforce", policy_version="test", fleet_min_roots=3)
    cfg = _write_config(tmp_path, mode="enforce", approved_enforce_digest=policy.digest())
    records = _fleet(4)
    _prime_second_strike(tmp_path, cfg, records, allow_enforce=True)

    def forbidden_executor(**kwargs):
        raise AssertionError("Cleared pressure must not construct an executor")

    controller, _ = _make_controller(
        tmp_path, records, cfg, allow_enforce=True, executor_factory=forbidden_executor,
    )
    query = controller._query_pressure_events
    calls = 0

    def clear_on_revalidation(bus, now):
        nonlocal calls
        calls += 1
        events = query(bus, now)
        if calls == 2:
            events.append({"event_id": "clear", "timestamp": iso(NOW),
                           "payload": {"reasons": [], "axes_latched": [],
                                       "change": "axes_cleared"}})
        return events

    controller._query_pressure_events = clear_on_revalidation
    _, result = controller.run_once()
    assert calls == 2
    assert result.status == "cancelled"
    assert "pressure revalidation failed: disarmed" in result.detail
    assert not result.executor_called
