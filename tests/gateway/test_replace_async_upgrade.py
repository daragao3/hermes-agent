"""Replacement must request Windows drain without blocking the event loop."""
from unittest.mock import AsyncMock, Mock

import pytest
from gateway import run, status


@pytest.mark.asyncio
async def test_windows_replace_uses_marker_and_async_exit_confirmation(monkeypatch):
    monkeypatch.setattr(run, "_IS_WINDOWS", True, raising=False)
    marker, terminate = Mock(), Mock()
    monkeypatch.setattr(status, "write_planned_stop_marker", marker)
    monkeypatch.setattr(status, "terminate_pid", terminate)
    wait = AsyncMock(return_value=True)
    monkeypatch.setattr(run, "_wait_for_pid_exit", wait)
    assert await run._request_incumbent_shutdown(424242, timeout=42.0)
    marker.assert_called_once_with(424242)
    terminate.assert_not_called()
    wait.assert_awaited_once_with(424242, 84, 0.5)


@pytest.mark.asyncio
async def test_young_incumbent_refused_before_any_marker_or_signal(monkeypatch):
    monkeypatch.setattr(run, "_replace_target_belongs_to_other_profile", lambda pid: False)
    monkeypatch.setattr(status, "get_process_age_seconds", lambda pid: 2.0)
    monkeypatch.delenv("HERMES_GATEWAY_REPLACE_MIN_AGE_SECONDS", raising=False)
    takeover, stop, terminate = Mock(), Mock(), Mock()
    monkeypatch.setattr(status, "write_takeover_marker", takeover)
    monkeypatch.setattr(status, "write_planned_stop_marker", stop)
    monkeypatch.setattr(status, "terminate_pid", terminate)
    assert not await run._start_gateway_replace_existing_instance(424242, True)
    takeover.assert_not_called()
    stop.assert_not_called()
    terminate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("exits", [False, True])
async def test_force_replacement_keeps_identity_and_requires_confirmed_exit(monkeypatch, tmp_path, exits):
    monkeypatch.setattr(run, "_replace_target_belongs_to_other_profile", lambda pid: False)
    monkeypatch.setattr(run, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(status, "get_process_age_seconds", lambda pid: 9999.0)
    monkeypatch.setattr(status, "get_process_start_time", lambda pid: 12345)
    monkeypatch.setattr(status, "write_takeover_marker", Mock())
    monkeypatch.setattr(status, "_snapshot_gateway_children", lambda pid: [])
    monkeypatch.setattr(run, "_request_incumbent_shutdown", AsyncMock(return_value=False))
    monkeypatch.setattr(run, "_wait_for_pid_exit", AsyncMock(return_value=exits))
    terminate, remove, release, reap, takeover, planned = [Mock() for _ in range(6)]
    monkeypatch.setattr(status, "terminate_pid", terminate)
    monkeypatch.setattr(status, "remove_pid_file", remove)
    monkeypatch.setattr(status, "release_all_scoped_locks", release)
    monkeypatch.setattr(status, "reap_gateway_children", reap)
    monkeypatch.setattr(status, "clear_takeover_marker", takeover)
    monkeypatch.setattr(status, "clear_planned_stop_marker", planned)
    assert await run._start_gateway_replace_existing_instance(424242, True) is exits
    terminate.assert_called_once_with(424242, force=True, expected_start_time=12345)
    assert remove.call_count == int(exits)
    assert release.call_count == int(exits)
    assert reap.call_count == int(exits)
    if exits:
        release.assert_called_once_with(owner_pid=424242, owner_start_time=12345)
    takeover.assert_called_once()
    planned.assert_called_once()


@pytest.mark.asyncio
async def test_posix_request_propagates_permission_failure(monkeypatch):
    monkeypatch.setattr(run, "_IS_WINDOWS", False)
    monkeypatch.setattr(status, "terminate_pid", Mock(side_effect=PermissionError("denied")))
    wait = AsyncMock()
    monkeypatch.setattr(run, "_wait_for_pid_exit", wait)
    with pytest.raises(PermissionError):
        await run._request_incumbent_shutdown(424242, timeout=1)
    wait.assert_not_awaited()
