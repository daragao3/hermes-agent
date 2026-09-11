import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.whatsapp import adapter as wa


def make_adapter(tmp_path):
    return wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={"session_path": str(tmp_path)}))


@pytest.mark.asyncio
async def test_strict_denial_precedes_telemetry_commands_and_media(tmp_path, monkeypatch):
    from events import bus
    adapter = make_adapter(tmp_path)
    monkeypatch.setattr(wa, "_wenv", lambda name, default="": "123" if name == "WHATSAPP_ALLOWED_USERS" else default)
    observer = Mock(side_effect=AssertionError("unauthorized input reached observer"))
    monkeypatch.setattr(bus, "EventBus", observer)
    command = AsyncMock()
    monkeypatch.setattr(adapter, "_maybe_handle_reply_command", command)
    assert await adapter._build_message_event({"chatId": "999@lid", "senderId": "999@lid", "body": "/approve 42"}) is None
    observer.assert_not_called()
    command.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_suffix_reaches_group_policy_without_mutating_input(tmp_path, monkeypatch):
    adapter = make_adapter(tmp_path)
    monkeypatch.setattr(wa, "_wenv", lambda name, default="": default)
    gate = Mock(return_value=False)
    monkeypatch.setattr(adapter, "_should_process_message", gate)
    data = {"chatId": "group@g.us", "senderId": "123", "body": "hello"}
    assert await adapter._build_message_event(data) is None
    assert gate.call_args.args[0]["isGroup"] is True
    assert "isGroup" not in data


@pytest.mark.asyncio
async def test_lid_reply_command_is_authorized_scoped_and_never_becomes_agent_event(tmp_path, monkeypatch):
    from events import bus
    adapter = make_adapter(tmp_path)
    (tmp_path / "lid-mapping-456_reverse.json").write_text(json.dumps("123"), encoding="utf-8")
    monkeypatch.setenv("HERMES_REPLY_HANDLERS_ENABLED", "1")
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "unrelated-other-profile")
    monkeypatch.setattr(wa, "_wenv", lambda name, default="": "123" if name == "WHATSAPP_ALLOWED_USERS" else default)
    monkeypatch.setattr(adapter, "_should_process_message", lambda data: True)
    monkeypatch.setattr(bus, "EventBus", Mock(return_value=Mock()))
    adapter.send = AsyncMock()
    intent = SimpleNamespace(verb="approve", job_id="42")
    monkeypatch.setattr(wa, "parse_reply_command", lambda text: intent)
    execute = Mock(return_value=SimpleNamespace(message="recorded"))
    monkeypatch.setattr(wa, "execute_reply_command", execute)
    assert await adapter._build_message_event({"chatId": "456@lid", "senderId": "456@lid", "body": "/approve 42"}) is None
    execute.assert_called_once_with(intent, actor="456", source="whatsapp", thread_id="job-42")
    adapter.send.assert_awaited_once_with("456@lid", "recorded")
