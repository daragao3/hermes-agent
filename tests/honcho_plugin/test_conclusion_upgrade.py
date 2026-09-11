"""Custom conclusion targets retain registration across the session split."""
from unittest.mock import MagicMock
import pytest
from plugins.memory.honcho import session as session_module
from plugins.memory.honcho.session import HonchoSession, HonchoSessionManager

@pytest.mark.parametrize("peer,register", [("hermes-events", True), ("user", False), ("ai", False)])
def test_conclusion_registers_custom_peer_before_create(monkeypatch, peer, register):
    client = MagicMock()
    monkeypatch.setattr(session_module, "get_honcho_client", lambda *a, **k: client)
    manager = HonchoSessionManager(honcho=client)
    session = HonchoSession("test", "user-id", "assistant-id", "session-id")
    manager._cache[session.key] = session
    target = {"user": "user-id", "ai": "assistant-id"}.get(peer, peer)
    events = []
    resolved_peer = MagicMock()
    manager._get_or_create_peer = MagicMock(return_value=resolved_peer)
    client.session.return_value.add_peers.side_effect = lambda peers: events.append("registered")
    resolved_peer.conclusions_of.return_value.create.side_effect = lambda payload: events.append("created")
    assert manager.create_conclusion("test", " durable fact ", peer=peer)
    assert events == (["registered", "created"] if register else ["created"])
    if register:
        client.session.assert_called_once_with("session-id")
        client.session.return_value.add_peers.assert_called_once_with([resolved_peer])
    else:
        client.session.return_value.add_peers.assert_not_called()
    resolved_peer.conclusions_of.assert_called_once_with(target)
    resolved_peer.conclusions_of.return_value.create.assert_called_once_with(
        [{"content": "durable fact", "session_id": "session-id"}])
