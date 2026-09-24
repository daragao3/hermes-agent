"""The OTLP exporter's retry/abandon logging while Langfuse is down (2026-09-23:
three lines every ~30s for the whole outage) is collapsed by obs.otel_tracing's
_ExportFailureLogThrottle."""
from __future__ import annotations

import logging

from obs.otel_tracing import _EXPORTER_LOGGER, _ExportFailureLogThrottle

_REFUSED = ("HTTPConnectionPool(host='localhost', port=3050): Max retries exceeded "
            "with url: /api/public/otel/v1/traces")


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _logger_with(throttle):
    log = logging.getLogger(_EXPORTER_LOGGER + ".throttle_test")
    log.filters[:] = [throttle]
    log.propagate = False
    captured = []

    class _H(logging.Handler):
        def emit(self, record):
            captured.append((record.levelno, record.getMessage()))

    log.handlers[:] = [_H(level=logging.INFO)]
    log.setLevel(logging.DEBUG)
    return log, captured


def _outage_cycle(log):
    # Exact shapes opentelemetry-exporter-otlp-proto-http 1.44 logs per batch.
    log.warning("Transient error %s encountered while exporting span batch, retrying in %.2fs.",
                _REFUSED, 0.95)
    log.warning("Transient error %s encountered while exporting span batch, retrying in %.2fs.",
                _REFUSED, 2.03)
    log.error("Failed to export span batch due to timeout, max retries or shutdown.")


def test_outage_logs_one_error_per_interval_with_suppressed_count():
    clock = _Clock()
    log, captured = _logger_with(_ExportFailureLogThrottle(interval_s=600, clock=clock))

    for _ in range(20):          # ~10 minutes of a down Langfuse, one batch per 30s
        _outage_cycle(log)
        clock.now += 30
    assert captured == [
        (logging.ERROR, "Failed to export span batch due to timeout, max retries or shutdown.")]

    _outage_cycle(log)           # t=600: the interval has passed
    assert len(captured) == 2
    assert captured[1][0] == logging.ERROR
    assert "(19 more batch(es) dropped since the last report" in captured[1][1]


def test_other_exporter_messages_pass_and_http_failures_share_the_budget():
    log, captured = _logger_with(_ExportFailureLogThrottle(clock=_Clock()))
    log.warning("Exporter already shutdown, ignoring batch")
    log.warning("Exporter already shutdown, ignoring batch")
    log.error("Failed to export span batch code: 401, reason: Unauthorized")
    log.error("Failed to export span batch code: 401, reason: Unauthorized")
    assert captured == [
        (logging.WARNING, "Exporter already shutdown, ignoring batch"),
        (logging.WARNING, "Exporter already shutdown, ignoring batch"),
        (logging.ERROR, "Failed to export span batch code: 401, reason: Unauthorized"),
    ]
