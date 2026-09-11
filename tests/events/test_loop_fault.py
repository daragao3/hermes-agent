from events.schema import EventType, Priority


class _FakeBus:
    def __init__(self):
        self.emitted = []

    def emit(self, **kwargs):
        self.emitted.append(kwargs)
        return "evt-id"


def _make_exc(message="'NoneType' object is not iterable"):
    try:
        raise TypeError(message)
    except TypeError as exc:
        return exc


def test_emit_agent_loop_fault_emits_sanitized_correlated_event():
    from events.loop_fault import emit_agent_loop_fault

    bus = _FakeBus()
    emitted = emit_agent_loop_fault(
        _make_exc("OPENAI_API_KEY=dummy"),
        source_hint="jobflow-scout",
        phase="stream_accumulation",
        provider="openai-codex",
        model="gpt-5.5",
        status_code=500,
        correlation_id="task-471",
        bus=bus,
    )

    assert emitted is True
    assert len(bus.emitted) == 1
    event = bus.emitted[0]
    assert event["event_type"] is EventType.AGENT_LOOP_FAULT
    assert event["priority"] is Priority.HIGH
    assert event["source"] == "scout"
    assert event["correlation_id"] == "task-471"
    payload = event["payload"]
    assert payload["exception_type"] == "TypeError"
    assert payload["error_class"] == "TypeError"
    assert payload["phase"] == "stream_accumulation"
    assert payload["backend"] == {
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "status_code": 500,
    }
    assert payload["correlation_id"] == "task-471"
    assert "dummy" not in payload["message"]
    assert "dummy" not in payload["traceback_tail"]
    assert payload["message"] == "OPENAI_API_KEY=***"
    assert payload["traceback_tail"]


def test_emit_agent_loop_fault_emits_once_for_every_invocation():
    from events.loop_fault import emit_agent_loop_fault

    bus = _FakeBus()
    for _ in range(10):
        assert emit_agent_loop_fault(
            _make_exc(), source_hint="jobflow-scout", bus=bus
        ) is True

    assert len(bus.emitted) == 10


def test_redacts_complete_traceback_before_taking_tail():
    from events.loop_fault import emit_agent_loop_fault

    bus = _FakeBus()
    assert emit_agent_loop_fault(
        _make_exc("OPENAI_API_KEY=" + ("A" * 2100)),
        source_hint="main",
        bus=bus,
    ) is True

    tail = bus.emitted[0]["payload"]["traceback_tail"]
    assert "A" * 100 not in tail
    assert len(tail) <= 2000


def test_sanitizes_untrusted_error_class_source_and_status_code(monkeypatch):
    from events.loop_fault import emit_agent_loop_fault

    monkeypatch.setenv("HERMES_AGENT_SOURCE", "OPENAI_API_KEY=dummy")
    dynamic_error = type("OPENAI_API_KEY=dummy", (Exception,), {})
    bus = _FakeBus()
    assert emit_agent_loop_fault(
        dynamic_error("boom"), status_code=True, bus=bus
    ) is True

    event = bus.emitted[0]
    assert "dummy" not in event["source"]
    assert "dummy" not in event["payload"]["error_class"]
    assert event["payload"]["status_code"] is None


def test_emit_never_raises_even_if_bus_explodes():
    from events.loop_fault import emit_agent_loop_fault

    class _Boom:
        def emit(self, **kw):
            raise RuntimeError("bus down")

    assert emit_agent_loop_fault(
        _make_exc(), source_hint="x", phase="y", bus=_Boom()
    ) is False
