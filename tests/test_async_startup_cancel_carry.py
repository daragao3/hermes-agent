"""Cancellation must survive the gap between worker loop and task creation."""

import asyncio
import threading

import pytest


def test_cancel_before_worker_task_creation(monkeypatch):
    import model_tools
    from tools.inflight_call import cancel_inflight_calls, inflight_call

    caller = threading.get_ident()
    entering = threading.Event()
    release = threading.Event()
    executed = []
    original_set_loop = asyncio.set_event_loop
    original_add_hook = model_tools._add_abort_hook

    def gated_set_loop(loop):
        if threading.get_ident() != caller:
            entering.set()
            assert release.wait(5), "worker was not released"
        return original_set_loop(loop)

    def cancel_at_startup(hook):
        registered = original_add_hook(hook)
        try:
            assert entering.wait(5), "worker did not reach startup gate"
            assert cancel_inflight_calls({caller}, reason="startup stop") == 1
        finally:
            release.set()
        return registered

    async def handler():
        executed.append(True)
        return "ran after stop"

    async def driver():
        with inflight_call("startup-cancel"):
            with pytest.raises(InterruptedError, match="startup stop"):
                model_tools._run_async(handler())

    monkeypatch.setattr(asyncio, "set_event_loop", gated_set_loop)
    monkeypatch.setattr(model_tools, "_add_abort_hook", cancel_at_startup)
    asyncio.run(driver())
    assert not executed
