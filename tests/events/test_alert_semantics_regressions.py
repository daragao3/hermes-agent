from events.bus import EventBus
from events.failure_eligibility import failure_cluster_eligible
from events.schema import Event, EventType
from events.producers import ruff_gate_probe as ruff
from events.producers.code_drift_monitor import CodeDriftMonitor, DriftSample
import json
from datetime import datetime, timedelta, timezone
import pytest

# Match the neighboring producer suites: cold shared-fixture imports and
# temporary SQLite initialization can exceed 30s on a saturated Windows host.
pytestmark = pytest.mark.timeout(300)


def test_lint_improvement_and_recovery_survive_restart(tmp_path, monkeypatch):
    bus = EventBus(db_path=tmp_path / "bus.db")
    state = tmp_path / "ruff.json"
    monkeypatch.setattr(ruff, "operation_in_progress", lambda _: False)
    monkeypatch.setattr(ruff, "describe_checkout", lambda _: {"branch": "work", "commit": "abc"})
    sample = ruff.RuffSample(ok=True, red=True, violations=1291, codes={"F401": 1291})
    monkeypatch.setattr(ruff, "run_ruff", lambda *a, **kw: sample)
    def tick(now):
        return ruff.RuffGateProbe(bus, tmp_path, state).check(now)
    assert tick(1000)
    sample.violations = 1290
    sample.codes = {"F401": 1290}
    assert tick(1900) is None
    sample.red = False
    sample.violations = 0
    sample.codes = {}
    assert tick(2800)
    assert tick(3700) is None
    recovered = bus.query(event_type=EventType.DEVFLOW_BUILD_SUCCEEDED)
    assert len(recovered) == 1
    from events.routing_policy import classify, Attention
    assert classify(recovered[0]).attention is Attention.INFO
    assert classify(recovered[0]).topic_key == classify(bus.query(event_type=EventType.DEVFLOW_BUILD_FAILED)[0]).topic_key


def test_commit_counts_do_not_start_new_drift_incidents(tmp_path):
    bus = EventBus(db_path=tmp_path / "bus.db")
    sample = DriftSample(state="ahead", head="a", trunk="b", ahead_count=3)
    monitor = CodeDriftMonitor(bus, state_path=tmp_path / "drift.json")
    assert monitor.evaluate(sample, 1000)
    sample = DriftSample(state="ahead", head="c", trunk="b", ahead_count=4)
    assert monitor.evaluate(sample, 1900) is None


def test_detector_findings_are_not_detector_execution_failures():
    observations = [
        Event.create(EventType.MODEL_RATE_LIMITED, "usage-poller", {"provider": provider, "outcome": "chain_exhausted"})
        for provider in ("anthropic", "anthropic2", "deepseek")
    ] + [
        Event.create(EventType.SECRET_DETECTED, "secret-scanner", {"finding_hash": "redacted"}),
        Event.create(EventType.DEVFLOW_BUILD_FAILED, "ruff-gate-probe", {"gate": "ruff", "violations": 1290}),
    ]
    assert not any(failure_cluster_eligible(event) for event in observations)
    assert failure_cluster_eligible(Event.create(EventType.AGENT_ERROR, "secret-scanner", {"error": "scanner crashed"}))


def test_delayed_recovery_remains_historical_after_new_failure(tmp_path):
    from events.subscribers.telegram_notifier import TelegramNotifier
    bus = EventBus(db_path=tmp_path / "bus.db")
    topics = tmp_path / "topics.json"
    topics.write_text(json.dumps({"group_chat_id": "-1", "topics": {"watchdog_alerts": {"thread_id": 100}}}))
    sent = []
    def notifier():
        return TelegramNotifier(bus, topics_path=topics, verbosity_path=tmp_path / "verbosity.json",
                                send_fn=lambda chat, thread, message: sent.append(message))
    now = datetime.now(timezone.utc)
    failure = Event.create(EventType.WATCHDOG_PROBE_TRANSITION, "watchdog", {"probe": "db", "before": "healthy", "after": "down", "tier": "critical"})
    failure.timestamp = now.isoformat()
    recovered = Event.create(EventType.WATCHDOG_PROBE_TRANSITION, "watchdog", {"probe": "db", "before": "down", "after": "healthy", "tier": "critical"})
    recovered.timestamp = (now - timedelta(minutes=20)).isoformat()
    first = notifier()
    first.handle(failure)
    first.handle(recovered)
    # Model residence in the durable queue without sleeping. This must be
    # reported separately from the milliseconds spent sending to Telegram.
    for records in first._batch_metadata.values():
        for metadata in records:
            metadata["queued_at"] = (now - timedelta(minutes=3)).isoformat()
    first._persist_batch_buffer()
    restarted = notifier()
    restarted._flush_stale_batches(max_age=0)
    batch = next(message for message in sent if "Batched (" in message)
    assert "Current observed state: down" in batch
    assert "historical" in batch.lower()
    assert "Occurrence:" in batch and "Delivery:" in batch and "queue age" in batch
    assert "probe observation age: unknown" in batch
    receipt = next(e for e in bus.query(event_type=EventType.NOTIFICATION_DELIVERED) if e.payload.get("batch_count"))
    assert receipt.payload["queue_age_ms"] >= 180000
    assert receipt.payload["queue_age_ms"] > receipt.payload["latency_ms"]
    assert recovered.event_id in receipt.payload["original_event_ids"]


def test_cron_terminal_identity_does_not_close_a_newer_execution(tmp_path):
    from events.producers.cron_emitter import CronEventEmitter
    from events.subscribers.cron_stale_monitor import CronStaleMonitor
    bus = EventBus(db_path=tmp_path / "bus.db")
    emitter = CronEventEmitter(bus)
    monitor = CronStaleMonitor(bus, default_threshold_seconds=0)
    emitter.on_job_started("job", "worker", "hourly", execution_id="new")
    monitor.handle(bus.query(event_type=EventType.CRON_STARTED)[0])
    emitter.on_job_completed("job", "worker", True, 1.0, execution_id="old")
    monitor.handle(bus.query(event_type=EventType.CRON_COMPLETED)[0])
    monitor._check_stale()
    stale = bus.query(event_type=EventType.CRON_STALE)
    assert len(stale) == 1 and stale[0].payload["execution_id"] == "new"
    emitter.on_job_completed("job", "worker", False, 2.0, execution_id="new")
    terminal = bus.query(event_type=EventType.CRON_FAILED)[0]
    assert terminal.payload["execution_id"] == "new"
    monitor.handle(terminal)
    assert "job" not in monitor._open_jobs


def test_soft_deadline_is_pending_and_same_execution_alerts_coalesce(tmp_path):
    from events.outcomes import OutcomeState, evaluate_outcome
    from events.subscribers.telegram_notifier import TelegramNotifier
    bus = EventBus(db_path=tmp_path / "bus.db")
    topics = tmp_path / "topics.json"
    topics.write_text(json.dumps({"group_chat_id": "-1", "topics": {"watchdog_alerts": {"thread_id": 100}}}))
    sent = []
    notifier = TelegramNotifier(bus, topics_path=topics, verbosity_path=tmp_path / "verbosity.json",
                                send_fn=lambda chat, thread, message: sent.append(message))
    payload = {"job_id": "job", "job_name": "worker", "execution_id": "run", "state": "overdue_running", "reason": "soft_deadline", "age_seconds": 1200, "threshold_seconds": 1200}
    overdue = Event.create(EventType.CRON_STALE, "worker", payload)
    assert evaluate_outcome(overdue).state is OutcomeState.PENDING
    notifier.handle(overdue)
    notifier.handle(Event.create(EventType.CRON_STALE, "cron-stale-monitor", {**payload, "state": "stale", "reason": "stale", "age_seconds": 1400}))
    assert len(sent) == 1
    assert "still running" in sent[0].lower()
    notifier.handle(Event.create(EventType.CRON_STALE, "worker", {**payload, "execution_id": "next-run"}))
    assert len(sent) == 2  # A new execution is a new incident, even with identical prose.
