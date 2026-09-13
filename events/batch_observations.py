"""Occurrence-ordered observation context for delayed notifications."""

from datetime import datetime, timezone

from events.schema import EventType


def instant(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def observation(event):
    payload = event.payload
    cron_states = {EventType.CRON_STARTED: "running", EventType.CRON_STALE: "overdue_running",
                   EventType.CRON_COMPLETED: "completed", EventType.CRON_FAILED: "failed"}
    if event.event_type in cron_states and payload.get("job_id") and payload.get("execution_id"):
        return f"cron:{payload['job_id']}:{payload['execution_id']}", cron_states[event.event_type]
    if event.event_type == EventType.WATCHDOG_PROBE_TRANSITION and payload.get("probe"):
        return f"probe:{event.source}:{payload['probe']}", str(payload.get("after") or "unknown")
    if event.event_type in {EventType.WATCHDOG_SILENCE_ALERT, EventType.WATCHDOG_RECOVERED}:
        source = payload.get("source") or payload.get("agent")
        if source:
            state = "reporting" if event.event_type == EventType.WATCHDOG_RECOVERED else "silent"
            return f"silence:{source}", state
    return "", "unknown"


def remember_observation(latest, event):
    key, state = observation(event)
    occurred = instant(event.timestamp)
    if not key or occurred is None:
        return False
    prior = latest.get(key, {})
    prior_time = instant(prior.get("timestamp"))
    if prior_time is not None and prior_time >= occurred:
        return False
    latest.pop(key, None)
    latest[key] = {**prior, "state": state, "timestamp": event.timestamp}
    while len(latest) > 512:
        latest.pop(next(iter(latest)))
    return True


def repeated_cron_stale(latest, event):
    """Coalesce detector/deadline observations of one execution for 30 minutes."""
    if event.event_type != EventType.CRON_STALE:
        return False
    key, _ = observation(event)
    if not key or key not in latest:
        return False
    record = latest[key]
    if record["state"] in {"completed", "failed"}:
        return True
    now = datetime.now(timezone.utc)
    notified = instant(record.get("notified_at"))
    if notified and (now - notified).total_seconds() < 1800:
        return True
    record["notified_at"] = now.isoformat()
    return False


def queued_message(message, event):
    key, _ = observation(event)
    return {"message": message, "event_id": event.event_id, "timestamp": event.timestamp,
            "queued_at": datetime.now(timezone.utc).isoformat(), "incident_key": key,
            "observed_at": event.payload.get("observed_at") or event.payload.get("checked_at")}


def render_batch(messages, latest, started_at):
    now = datetime.now(timezone.utc)
    rendered = []
    ids = []
    queued_times = []
    for item in messages:
        if isinstance(item, str):
            queued_times.append(instant(started_at))
            rendered.append(f"Historical event (occurrence/current state unavailable):\n{item}")
            continue
        stamp = item.get("timestamp")
        queued_times.append(instant(item.get("queued_at")))
        occurred = instant(stamp)
        age = f"{max(0, int((now - occurred).total_seconds()))}s" if occurred else "unknown"
        observed = instant(item.get("observed_at"))
        observation_age = f"{max(0, int((now - observed).total_seconds()))}s" if observed else "unknown"
        current = latest.get(item.get("incident_key"), {})
        context = (f"Current observed state: {current['state']} (reported at {current['timestamp']})."
                   if current else "Current observed state: unknown.")
        rendered.append(f"Historical observation. Occurrence: {stamp}; event age: {age}; "
                        f"probe observation age: {observation_age}.\n"
                        f"{context}\n{item['message']}")
        if item.get("event_id"):
            ids.append(item["event_id"])
    known_times = [stamp for stamp in queued_times if stamp is not None]
    start = min(known_times) if known_times and len(known_times) == len(messages) else None
    queue_age = max(0, int((now - start).total_seconds() * 1000)) if start else None
    heading = f"Batched ({len(messages)} events):\nDelivery: {now.isoformat()}; oldest queue age: "
    heading += f"{queue_age // 1000}s" if queue_age is not None else "unknown"
    return heading + "\n\n" + "\n---\n".join(rendered), {
        "queue_age_ms": queue_age, "original_event_ids": ids,
        "delivery_attempted_at": now.isoformat(),
    }
