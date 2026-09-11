"""Deterministic Z.AI priority regression; no threads or HTTP calls."""
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest


@pytest.mark.real_provider_auth_probe
@pytest.mark.parametrize("first_outcome", ["success", "miss", "exception"])
def test_completed_probes_consumed_in_reverse_keep_endpoint_priority(monkeypatch, first_outcome):
    import concurrent.futures as futures
    from hermes_cli import auth_zai_kimi as zai

    endpoints = list(zai.ZAI_ENDPOINTS)
    shutdown = MagicMock()

    def probe(key, endpoint, timeout):
        assert key == "synthetic-test-key"
        if endpoint == endpoints[0]:
            if first_outcome == "miss":
                return None
            if first_outcome == "exception":
                raise RuntimeError("synthetic probe failure")
        return {"id": endpoint[0], "base_url": endpoint[1]}

    class CompletedExecutor:
        def __init__(self, max_workers):
            assert max_workers == len(endpoints)

        def submit(self, fn, *args):
            future = Future()
            try:
                future.set_result(fn(*args))
            except Exception as error:
                future.set_exception(error)
            return future

        def shutdown(self, **kwargs):
            shutdown(**kwargs)

    monkeypatch.setattr(zai, "_probe_single_zai_endpoint", probe)
    monkeypatch.setattr(futures, "ThreadPoolExecutor", CompletedExecutor)
    # Every Future is done before iteration starts, but low priority is yielded first.
    monkeypatch.setattr(futures, "as_completed", lambda submitted: iter(reversed(list(submitted))))
    result = zai.detect_zai_endpoint("synthetic-test-key", timeout=1.0)
    expected = endpoints[0 if first_outcome == "success" else 1][0]
    assert result is not None and result["id"] == expected
    shutdown.assert_called_once_with(wait=False)


@pytest.mark.real_provider_auth_probe
def test_highest_priority_success_returns_with_lower_probes_pending(monkeypatch):
    import concurrent.futures as futures
    from hermes_cli import auth_zai_kimi as zai

    submitted = []
    shutdown = MagicMock()

    class PendingExecutor:
        def __init__(self, max_workers):
            pass

        def submit(self, fn, key, endpoint, timeout):
            future = Future()
            if not submitted:
                future.set_result({"id": endpoint[0]})
            submitted.append(future)
            return future

        def shutdown(self, **kwargs):
            shutdown(**kwargs)

    def completions(_):
        yield submitted[0]
        pytest.fail("must return before asking for pending lower-priority probes")

    monkeypatch.setattr(futures, "ThreadPoolExecutor", PendingExecutor)
    monkeypatch.setattr(futures, "as_completed", completions)
    result = zai.detect_zai_endpoint("synthetic-test-key")
    assert result == {"id": zai.ZAI_ENDPOINTS[0][0]}
    assert all(not future.done() for future in submitted[1:])
    shutdown.assert_called_once_with(wait=False)
