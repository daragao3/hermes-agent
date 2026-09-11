"""Reasoning replay and primary-route admission contracts after decomposition."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import agent_runtime_helpers as helpers


@pytest.mark.parametrize('value', [MagicMock(), 42, {'unexpected': 'payload'}])
def test_arbitrary_reasoning_objects_do_not_enter_transcript(value):
    message = SimpleNamespace(reasoning=value, reasoning_content='real reasoning',
                              reasoning_details=[], content=None)
    assert helpers.extract_reasoning(None, message) == 'real reasoning'


def test_typed_reasoning_text_is_preserved_and_deduplicated():
    message = SimpleNamespace(reasoning=[{'type': 'text', 'text': 'reason'}],
                              reasoning_content='reason', reasoning_details=[], content=None)
    assert helpers.extract_reasoning(None, message) == 'reason'


def test_active_override_prevents_return_to_rate_limited_primary(monkeypatch):
    from events import model_override

    agent = SimpleNamespace(_fallback_activated=True, _rate_limited_until=0,
                            _primary_runtime={'provider': 'example', 'model': 'primary'})
    monkeypatch.setattr(helpers, '_revert_stale_init_override', lambda _: False)
    monkeypatch.setattr(model_override, 'get_override', lambda *args: {'model': 'replacement'})
    gate = MagicMock(side_effect=AssertionError('must not reach credential restore'))
    monkeypatch.setattr(helpers, '_primary_reset_gate_blocks', gate)
    assert helpers.restore_primary_runtime(agent) is False
    gate.assert_not_called()


def test_expired_init_override_ignores_replacement_cooldown_but_keeps_pool_gate(monkeypatch):
    from events import model_override

    agent = SimpleNamespace(_fallback_activated=False, _rate_limited_until=float('inf'),
                            _primary_runtime={'provider': 'example', 'model': 'configured'})
    monkeypatch.setattr(helpers, '_revert_stale_init_override', lambda _: True)
    monkeypatch.setattr(model_override, 'get_override', lambda *args: None)
    gate = MagicMock(return_value=(True, None, False))
    monkeypatch.setattr(helpers, '_primary_reset_gate_blocks', gate)
    assert helpers.restore_primary_runtime(agent) is False
    gate.assert_called_once()
