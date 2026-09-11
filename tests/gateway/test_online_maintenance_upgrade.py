"""Online pruning must wait for startup and avoid exclusive maintenance."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.run_watchers import GatewaySessionWatchersMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_online_prune_is_delayed_opt_in_and_never_vacuums(tmp_path, monkeypatch, enabled):
    db = SimpleNamespace(maybe_auto_prune_and_vacuum=AsyncMock())
    runner = SimpleNamespace(_session_db=db, _running=True, config=SimpleNamespace(sessions_dir=tmp_path))
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            db.maybe_auto_prune_and_vacuum.assert_not_awaited()
        else:
            runner._running = False

    monkeypatch.setattr("gateway.run_watchers.asyncio.sleep", sleep)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"sessions": {"auto_prune": enabled, "prune_batch": 17}})
    await GatewaySessionWatchersMixin._state_db_maintenance_watcher(runner)
    assert sleeps == [120, 21600]
    if enabled:
        db.maybe_auto_prune_and_vacuum.assert_awaited_once()
        kwargs = db.maybe_auto_prune_and_vacuum.call_args.kwargs
        assert kwargs["vacuum"] is False
        assert kwargs["max_batch"] == 17
        assert kwargs["sessions_dir"] == tmp_path
    else:
        db.maybe_auto_prune_and_vacuum.assert_not_awaited()
