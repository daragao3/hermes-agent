"""One complete mocked-provider turn through the local observability carries."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.mark.parametrize("observer_fails", [False, True])
def test_complete_turn_records_usage_source_activity_and_recovery(session_db, monkeypatch, observer_fails):
    from run_agent import AIAgent

    recorder = SimpleNamespace(record_response=Mock(side_effect=RuntimeError("fixture") if observer_fails else None))
    clear = Mock(side_effect=RuntimeError("fixture") if observer_fails else None)
    monkeypatch.setattr("events.rate_limit_signal.clear", clear)
    queued = Mock(wraps=session_db.queue_token_counts)
    monkeypatch.setattr(session_db, "queue_token_counts", queued)
    with patch("model_tools.get_tool_definitions", return_value=[]), patch("model_tools.check_toolset_requirements", return_value={}):
        agent = AIAgent(
            api_key="fixture-key", base_url="https://openrouter.ai/api/v1", provider="openrouter",
            model="fixture/model", quiet_mode=True, skip_context_files=True, skip_memory=True,
            session_db=session_db, session_id="loop-carry", platform="cron", activity_recorder=recorder,
            save_trajectories=False,
        )
    response = SimpleNamespace(
        id="fixture-response", model="fixture/model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Completed fixture turn.", tool_calls=None), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3, total_tokens=14),
    )
    agent.client = Mock(spec=["chat", "close", "base_url", "api_key"])
    agent.client.base_url = "https://openrouter.ai/api/v1"
    agent.client.api_key = "fixture-key"
    agent.client.chat.completions.create.return_value = response
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    try:
        result = agent.run_conversation("Complete the fixture task.")
        assert result["final_response"] == "Completed fixture turn."
        assert result["api_calls"] == 1
        clear.assert_called_once_with(provider="openrouter", model="fixture/model")
        recorder.record_response.assert_called_once()
        assert recorder.record_response.call_args.kwargs["model"] == "fixture/model"
        queued.assert_called_once()
        assert queued.call_args.kwargs["source"] == "cron"
        assert queued.call_args.kwargs["model_config"] == agent._session_init_model_config
        row = session_db.get_session("loop-carry")
        assert row["input_tokens"] == 11 and row["output_tokens"] == 3
        assert row["source"] == "cron"
    finally:
        agent.close()


@pytest.mark.parametrize("filename,is_local", [
    ("C:/fixture/site-packages/openai/_response.py", False),
    ("C:/fixture/hermes/agent/openai_codex_compat.py", True),
])
def test_sdk_contract_error_is_not_classified_as_local_programming_bug(filename, is_local):
    from agent.turn_api_error import _is_local_validation_error

    try:
        exec(compile("raise TypeError('unexpected provider shape')", filename, "exec"))
    except TypeError as error:
        assert _is_local_validation_error(error) is is_local
