"""Config precedence remains observable without logging scalar secrets."""
import logging
import os
from gateway.run import _bridge_config_to_env


def test_masked_scalar_warns_without_exposing_values(monkeypatch, caplog):
    monkeypatch.setenv("UPGRADE_TEST_API_KEY", "environment-secret")
    with caplog.at_level(logging.INFO):
        _bridge_config_to_env({"UPGRADE_TEST_API_KEY": "config-secret"})
    assert os.environ["UPGRADE_TEST_API_KEY"] == "environment-secret"
    assert "UPGRADE_TEST_API_KEY is IGNORED" in caplog.text
    assert "environment-secret" not in caplog.text and "config-secret" not in caplog.text


def test_home_channel_reports_config_fallback(monkeypatch, caplog):
    monkeypatch.delenv("UPGRADE_TEST_HOME_CHANNEL", raising=False)
    with caplog.at_level(logging.INFO):
        _bridge_config_to_env({"UPGRADE_TEST_HOME_CHANNEL": "fixture-channel"})
    assert os.environ["UPGRADE_TEST_HOME_CHANNEL"] == "fixture-channel"
    assert "UPGRADE_TEST_HOME_CHANNEL was bridged from config.yaml" in caplog.text
    monkeypatch.delenv("UPGRADE_TEST_HOME_CHANNEL")
