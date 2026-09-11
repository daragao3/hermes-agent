"""Rollback must compose with scoped registries and durable plugin attribution."""
import pytest
from tools.registry import ToolRegistry


def entry(name, scope=None):
    return {"name": name, "toolset": "test", "schema": {"name": name},
            "handler": lambda args: "ok", "scope": scope}


def test_transaction_restores_scoped_entries_and_policy_identity():
    reg = ToolRegistry()
    reg.register(**entry("existing", "a"))
    original = reg.get_entry("existing", scope="a")
    policy = reg.register_plugin_override_policy("hermes_plugins.test", False, scope="a")
    generation = reg._generation
    with pytest.raises(RuntimeError):
        with reg.transaction():
            reg.register(**entry("added", "a"))
            reg.deregister("existing", scope="a")
            reg.register_plugin_override_policy("hermes_plugins.test", True, scope="a")
            raise RuntimeError("abort")
    assert reg.get_entry("added", scope="a") is None
    assert reg.get_entry("existing", scope="a") is original
    assert reg.snapshot_plugin_override_policy("hermes_plugins.test", scope="a") is policy
    assert reg._generation == generation


def test_failed_plugin_retains_scope_attribution_without_override_authority(monkeypatch):
    reg = ToolRegistry()
    monkeypatch.setattr(reg, "current_scope_key", lambda: "elsewhere")
    with pytest.raises(RuntimeError):
        with reg.transaction():
            reg.register_plugin_override_policy("hermes_plugins.failed", True, scope="a")
            raise RuntimeError("abort")
    assert reg.plugin_scope_for_module("hermes_plugins.failed.callback") == "a"
    assert not reg._plugin_override_allowed("a", "hermes_plugins.failed")


def test_batch_rejects_scoped_collision_without_partial_registration():
    reg = ToolRegistry()
    reg.register(**entry("occupied", "a"))
    original = reg.get_entry("occupied", scope="a")
    with pytest.raises(ValueError, match="already registered"):
        reg.register_batch_if_absent([entry("new", "a"), entry("occupied", "a")])
    assert reg.get_entry("new", scope="a") is None
    assert reg.get_entry("occupied", scope="a") is original


def test_batch_rolls_back_scoped_success_before_later_error():
    reg = ToolRegistry()
    bad = entry("bad", "b")
    bad["schema"] = None
    with pytest.raises(AttributeError):
        reg.register_batch_if_absent([entry("new", "a"), bad])
    assert reg.get_entry("new", scope="a") is None
    assert reg.get_entry("bad", scope="b") is None


def test_thread_specific_interrupt_observes_only_live_call_cancellation():
    from tools.inflight_call import inflight_call, cancel_inflight_calls
    from tools.interrupt import is_thread_interrupted
    with inflight_call("scoped-test") as frame:
        assert not is_thread_interrupted(frame.thread_id)
        assert cancel_inflight_calls([frame.thread_id], reason="test") == 1
        assert is_thread_interrupted(frame.thread_id)
        assert not is_thread_interrupted(None)
    assert not is_thread_interrupted(frame.thread_id)


def test_batch_does_not_confuse_names_in_another_profile():
    reg = ToolRegistry()
    reg.register(**entry("shared-name", "a"))
    original = reg.get_entry("shared-name", scope="a")
    reg.register_batch_if_absent([entry("shared-name", "b")])
    assert reg.get_entry("shared-name", scope="a") is original
    assert reg.get_entry("shared-name", scope="b") is not original
