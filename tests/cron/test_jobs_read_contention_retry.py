"""cron.jobs: a Windows sharing-violation open of jobs.json is retried, bounded.

2026-09-17 02:45:37Z: ``cron.jobs: IOError reading jobs.json: [Errno 13]
Permission denied`` fired once inside the completion path of
tracker-operator-drain, so its ``cron_completed`` was never emitted and the
run read as started-never-finished. The writer (``utils.atomic_replace``)
already retries its rename against a held handle; this is the reader's mirror.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

import cron.jobs as jobs


def _contended(winerror: int) -> OSError:
    exc = PermissionError(13, "Access is denied")
    exc.winerror = winerror  # type: ignore[attr-defined]
    return exc


@pytest.fixture
def jobs_file(tmp_path) -> Path:
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": [{"id": "abc", "name": "j"}]}), encoding="utf-8")
    return path


def _flaky_open(monkeypatch, failures: list[OSError]):
    """Make the first ``len(failures)`` opens of ANY path raise, then pass through."""
    real_open = builtins.open
    calls = {"n": 0}

    def _open(*args, **kwargs):
        if failures:
            calls["n"] += 1
            raise failures.pop(0)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    return calls


def test_transient_sharing_violation_is_retried_and_the_read_succeeds(monkeypatch, jobs_file):
    monkeypatch.setattr(jobs, "_is_contended_windows_read_error", lambda exc: True)
    calls = _flaky_open(monkeypatch, [_contended(32), _contended(5)])
    data, strict = jobs._parse_jobs_file(jobs_file)
    assert data == {"jobs": [{"id": "abc", "name": "j"}]} and strict is False
    assert calls["n"] == 2


def test_a_permanent_denial_is_raised_after_the_budget(monkeypatch, jobs_file):
    monkeypatch.setattr(jobs, "_is_contended_windows_read_error", lambda exc: True)
    calls = _flaky_open(monkeypatch, [_contended(5) for _ in range(jobs._JOBS_READ_RETRY_ATTEMPTS + 5)])
    with pytest.raises(PermissionError):
        jobs._parse_jobs_file(jobs_file)
    assert calls["n"] == jobs._JOBS_READ_RETRY_ATTEMPTS + 1, "the budget is bounded"


def test_a_non_contention_error_is_not_retried(monkeypatch, jobs_file):
    monkeypatch.setattr(jobs, "_is_contended_windows_read_error", lambda exc: False)
    calls = _flaky_open(monkeypatch, [FileNotFoundError(2, "gone")])
    with pytest.raises(FileNotFoundError):
        jobs._parse_jobs_file(jobs_file)
    assert calls["n"] == 1


def test_contention_classifier_is_the_writers(monkeypatch):
    """Same winerror set as utils.atomic_replace, and Windows-only."""
    import utils

    monkeypatch.setattr(utils, "_IS_WINDOWS", True)
    assert jobs._is_contended_windows_read_error(_contended(32)) is True
    assert jobs._is_contended_windows_read_error(_contended(5)) is True
    assert jobs._is_contended_windows_read_error(_contended(2)) is False
    monkeypatch.setattr(utils, "_IS_WINDOWS", False)
    assert jobs._is_contended_windows_read_error(_contended(32)) is False
