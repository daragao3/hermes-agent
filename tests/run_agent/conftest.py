"""Fast-path fixtures shared across tests/run_agent/.

Many tests in this directory exercise the retry/backoff paths in the
agent loop. Production code uses ``jittered_backoff(base_delay=5.0)``
with a ``while time.time() < sleep_end`` loop — a single retry test
spends 5+ seconds of real wall-clock time on backoff waits.

Mocking ``jittered_backoff`` to return 0.0 collapses the while-loop
to a no-op (``time.time() < time.time() + 0`` is false immediately),
which handles the most common case without touching ``time.sleep``.

We deliberately DO NOT mock ``time.sleep`` here — some tests
(test_interrupt_propagation, test_primary_runtime_restore, etc.) use
the real ``time.sleep`` for threading coordination or assert that it
was called with specific values. Tests that want to additionally
fast-path direct ``time.sleep(N)`` calls in production code should
monkeypatch ``run_agent.time.sleep`` locally (see
``test_anthropic_error_handling.py`` for the pattern).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fast_retry_backoff(monkeypatch):
    """Short-circuit retry backoff for all tests in this directory."""
    # The agent.turn_* retry paths import ``jittered_backoff`` lazily from
    # ``agent.retry_utils``; patch it there so rate-limit / invalid-response /
    # server-error retries don't burn real wall-clock seconds.
    from agent import retry_utils as _retry_utils
    monkeypatch.setattr(_retry_utils, "jittered_backoff", lambda *a, **k: 0.0)


@pytest.fixture(autouse=True)
def _no_live_gh_cli_token(monkeypatch):
    """Keep auxiliary-client auto-detect off the real ``gh`` CLI.

    Constructing an ``AIAgent`` runs the auxiliary auto-detect, which reaches
    ``hermes_cli.copilot_auth.resolve_copilot_token`` ->
    ``_try_gh_cli_token`` -> ``subprocess.run(["gh", "auth", "token"])``
    against the developer's real GitHub credential store. That is a live host
    seam in a hermetic unit test, and an expensive one: the probe carries a 5s
    timeout and is retried per candidate ``gh`` path, so a single test that
    builds two agents can spend most of the suite-wide 30s ``--timeout=30``
    budget waiting on it. Because ``--timeout-method=thread`` kills the whole
    pytest process rather than one test, an overrun takes the entire file down
    — observed on tests/run_agent/test_in_place_compaction.py, which passed or
    died depending only on how fast ``gh`` answered that run.

    Returning None is the correct hermetic answer: no gh-CLI token is
    available to a test process. Tests that exercise Copilot auth for real
    stub their own layer (env vars or ``resolve_copilot_token``) above this
    one, so this only removes the accidental dependency, not their coverage.
    """
    try:
        from hermes_cli import copilot_auth
    except ImportError:
        return

    monkeypatch.setattr(copilot_auth, "_try_gh_cli_token", lambda: None)


@pytest.fixture
def session_db(tmp_path):
    """A real ``SessionDB`` whose connection is closed before its dir is reclaimed.

    ``sqlite3.Connection`` keeps its prepared-statement cache in a reference
    cycle, so dropping the last reference does NOT close the file — it waits
    for a cyclic-GC pass. On Windows the surviving handle blocks deletion of
    the directory holding the DB.

    ``tests/conftest.py``'s ``pytest_runtest_teardown`` collects those cycles,
    but only *after* the test body returns. Tests that built the DB inside
    their own ``with tempfile.TemporaryDirectory()`` reclaimed the directory
    while still in the body, so they raised ``PermissionError: [WinError 32]``
    before that hook could ever run. Owning ``close()`` here removes the
    dependency on GC timing entirely — matching the local ``session_db``
    fixtures in ``tests/cli/test_branch_command.py`` and
    ``tests/gateway/test_session_api.py``.
    """
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "session.db")
    try:
        yield db
    finally:
        db.close()
