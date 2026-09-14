"""Runtime coverage for gateway filesystem-checkpoint configuration."""

from tests.gateway._agent_stack_warm import warm_agent_stack

# Warm the agent stack HERE, at collection. The tests below import ``run_agent``
# from inside a helper/test body, where the per-test ``--timeout`` applies and a
# ~7s (idle) to ~25s (loaded) import can blow it. See the module docstring.
warm_agent_stack()


def test_gateway_checkpoint_config_reaches_real_agent(tmp_path, monkeypatch):
    """Raw gateway YAML must configure the real agent checkpoint manager."""
    from gateway import run as gateway_run
    from run_agent import AIAgent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    (tmp_path / "config.yaml").write_text(
        """checkpoints:
  enabled: true
  max_snapshots: 11
  max_total_size_mb: 345
  max_file_size_mb: 6
""",
        encoding="utf-8",
    )

    config = gateway_run._load_gateway_config()
    agent = AIAgent(
        model="anthropic/claude-sonnet-4",
        api_key="test",
        base_url="https://openrouter.ai/api/v1",
        provider="openrouter",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=[],
        **gateway_run._checkpoint_agent_kwargs(config),
    )
    try:
        manager = agent._checkpoint_mgr
        assert manager.enabled is True
        assert manager.max_snapshots == 11
        assert manager.max_total_size_mb == 345
        assert manager.max_file_size_mb == 6
    finally:
        agent.close()


