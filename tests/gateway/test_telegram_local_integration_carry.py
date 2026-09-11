from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.telegram import adapter as tg


@pytest.mark.asyncio
async def test_pipeline_handlers_precede_generic_handler_and_bind_each_verb(monkeypatch):
    adapter = tg.TelegramAdapter(PlatformConfig(enabled=True, token="fake"))
    handler = AsyncMock()
    monkeypatch.setattr(adapter, "_handle_reply_command", handler)
    class Handler:
        def __init__(self, filters, callback):
            self.callback = callback

    class Command(Handler):
        def __init__(self, verb, callback):
            super().__init__(None, callback)
            self.commands = {verb}

    monkeypatch.setattr(tg, "CommandHandler", Command)
    monkeypatch.setattr(tg, "TelegramMessageHandler", Handler)
    app = Mock()
    adapter._register_handlers(app)
    installed = [call.args[0] for call in app.add_handler.call_args_list]
    commands = [item for item in installed if isinstance(item, tg.CommandHandler)]
    assert len(commands) == 3
    generic = next(i for i, item in enumerate(installed)
                   if getattr(item, "callback", None) == adapter._handle_command)
    for item in commands:
        assert installed.index(item) < generic
        verb = next(iter(item.commands))
        await item.callback("update", "context")
        handler.assert_awaited_with("update", "context", verb)
    assert {next(iter(item.commands)) for item in commands} == {"approve", "reject", "archive"}


@pytest.mark.asyncio
async def test_reply_command_keeps_authorization_and_job_lineage(monkeypatch):
    adapter = tg.TelegramAdapter(PlatformConfig(enabled=True, token="fake"))
    monkeypatch.setenv("HERMES_REPLY_HANDLERS_ENABLED", "1")
    execute = Mock(return_value=SimpleNamespace(message="recorded"))
    monkeypatch.setattr(tg, "execute_reply_command", execute)
    intent = SimpleNamespace(verb="approve", job_id="42")
    monkeypatch.setattr(tg, "parse_reply_command", lambda text: intent)
    msg = SimpleNamespace(text="/approve 42", reply_text=AsyncMock())
    update = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=123))
    monkeypatch.setattr(tg, "is_authorized_telegram", lambda user: False)
    await adapter._handle_reply_command(update, None, "approve")
    execute.assert_not_called()
    msg.reply_text.assert_awaited_with("Not authorized.")
    monkeypatch.setattr(tg, "is_authorized_telegram", lambda user: user == 123)
    await adapter._handle_reply_command(update, None, "approve")
    execute.assert_called_once_with(intent, actor="123", source="telegram", thread_id="job-42")
    msg.reply_text.assert_awaited_with("recorded")


def test_inbound_event_preserves_routing_and_closes_bus_on_observer_failure(monkeypatch):
    from events import bus
    from events.schema import EventType
    observer = Mock()
    observer.emit.side_effect = RuntimeError("observer failure")
    monkeypatch.setattr(bus, "EventBus", lambda: observer)
    adapter = tg.TelegramAdapter(PlatformConfig(enabled=True, token="fake"))
    msg = SimpleNamespace(text="hello", from_user=SimpleNamespace(id=123),
                          chat=SimpleNamespace(id=456), message_thread_id=7,
                          message_id=8, reply_to_message=SimpleNamespace(message_id=9))
    adapter._emit_local_inbound_text(msg)
    values = observer.emit.call_args.kwargs
    assert values["event_type"] == EventType.USER_INBOUND_MESSAGE
    assert values["payload"] == {"platform": "telegram", "text": "hello", "user_id": "123",
                                 "chat_id": "456", "thread_id": "7", "message_id": "8", "in_reply_to": "9"}
    observer.close.assert_called_once()


def test_real_ptb_registration_in_fresh_interpreter():
    from pathlib import Path
    from hermes_constants import real_executable
    from hermes_cli._subprocess_compat import run_text_capture
    code = """
import asyncio
from unittest.mock import Mock, AsyncMock
from telegram.ext import CommandHandler
from gateway.config import PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter, TELEGRAM_AVAILABLE
assert TELEGRAM_AVAILABLE
adapter = TelegramAdapter(PlatformConfig(enabled=True, token='fake'))
adapter._handle_reply_command = AsyncMock()
app = Mock()
adapter._register_handlers(app)
installed = [call.args[0] for call in app.add_handler.call_args_list]
commands = [item for item in installed if isinstance(item, CommandHandler)]
assert len(commands) == 3
assert {next(iter(item.commands)) for item in commands} == {'approve', 'reject', 'archive'}
generic = next(i for i, item in enumerate(installed) if item.callback == adapter._handle_command)
for item in commands:
    assert installed.index(item) < generic
    asyncio.run(item.callback('update', 'context'))
    adapter._handle_reply_command.assert_awaited_with('update', 'context', next(iter(item.commands)))
print('real PTB registration PASS')
"""
    result = run_text_capture([real_executable(), "-c", code], timeout=20,
                              cwd=Path(__file__).resolve().parents[2])
    assert result.returncode == 0, result.stderr
    assert "real PTB registration PASS" in result.stdout
