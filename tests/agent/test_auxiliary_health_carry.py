"""Endpoint quarantine must retain the local cause without contaminating peers."""
import logging

import pytest

from agent import auxiliary_client as aux


@pytest.fixture(autouse=True)
def isolated_health():
    aux._reset_aux_unhealthy_cache()
    yield
    aux._reset_aux_unhealthy_cache()


def test_reason_and_health_stay_with_the_failed_endpoint(caplog):
    first = "https://first.example/v1"
    second = "https://second.example/v1"
    with caplog.at_level(logging.INFO, logger=aux.__name__):
        aux._mark_provider_unhealthy("local/custom", reason="credential expired", base_url=first)
        assert aux._is_provider_unhealthy("local/custom", first)
        assert not aux._is_provider_unhealthy("local/custom", second)
        aux._mark_provider_unhealthy("local/custom", reason="rate limited", base_url=second)
        aux._log_skip_unhealthy("local/custom", "vision", base_url=first)
        aux._log_skip_unhealthy("local/custom", "vision", base_url=second)
    skips = [r.getMessage() for r in caplog.records if "skipping local/custom" in r.getMessage()]
    assert len(skips) == 2
    assert "credential expired" in skips[0]
    assert "rate limited" in skips[1]


def test_same_reason_is_quiet_only_for_the_same_live_endpoint(caplog):
    first = "https://first.example/v1"
    with caplog.at_level(logging.DEBUG, logger=aux.__name__):
        aux._mark_provider_unhealthy("local/custom", reason="credential expired", base_url=first)
        aux._mark_provider_unhealthy("local/custom", reason="credential expired", base_url=first)
        aux._mark_provider_unhealthy("local/custom", reason="rate limited", base_url=first)
        aux._mark_provider_unhealthy("local/custom", reason="rate limited", base_url="https://second.example/v1")
    marks = [r.levelno for r in caplog.records if "marking local/custom unhealthy" in r.getMessage()]
    assert marks == [logging.WARNING, logging.DEBUG, logging.WARNING, logging.WARNING]


def test_expired_reason_is_evicted_and_a_new_window_warns(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(aux.time, "time", lambda: now[0])
    endpoint = "https://first.example/v1"
    aux._mark_provider_unhealthy("local/custom", ttl=10, reason="credential expired", base_url=endpoint)
    now[0] = 1011.0
    assert not aux._is_provider_unhealthy("local/custom", endpoint)
    assert aux._unhealthy_cache_key("local/custom", endpoint) not in aux._aux_unhealthy_reason
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=aux.__name__):
        aux._mark_provider_unhealthy("local/custom", ttl=10, reason="credential expired", base_url=endpoint)
    assert [r.levelno for r in caplog.records if "marking local/custom unhealthy" in r.getMessage()] == [logging.WARNING]
