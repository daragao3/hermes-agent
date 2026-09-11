from gateway.platform_registry import PlatformEntry, PlatformRegistry


def test_hints_follow_scope_and_restore_displaced_loader(monkeypatch):
    registry = PlatformRegistry()
    monkeypatch.setattr(registry, "current_scope_key", lambda: "a")
    def old():
        raise AssertionError("metadata must not load")
    def new():
        raise AssertionError("metadata must not load")
    registry.register_deferred("chat", old, scope="a", env_hints=["OLD_"])
    previous = registry.snapshot_registration("chat", scope="a")
    registry.register_deferred("chat", new, scope="a", env_hints=["NEW_"])
    current = registry.snapshot_registration("chat", scope="a")
    registry.register_deferred("chat", old, scope="b", env_hints=["OTHER_"])
    assert registry.deferred_env_hints("chat") == ("NEW_",)
    assert registry.restore_registration("chat", current, previous, scope="a")
    assert registry.deferred_env_hints("chat") == ("OLD_",)
    monkeypatch.setattr(registry, "current_scope_key", lambda: "b")
    assert registry.deferred_env_hints("chat") == ("OTHER_",)


def test_concrete_scoped_entry_hides_global_deferred_hints(monkeypatch):
    registry = PlatformRegistry()
    monkeypatch.setattr(registry, "current_scope_key", lambda: "a")
    def loader():
        raise AssertionError("must not load")
    registry.register_deferred("chat", loader, env_hints=["GLOBAL_"])
    entry = PlatformEntry("chat", "Chat", lambda config: None, lambda: True)
    registry.register(entry, scope="a")
    assert registry.deferred_env_hints("chat") == ()
    assert "chat" not in registry.deferred_names()
    assert registry.loaded_entries() == [entry]
    assert registry.known_names() == ["chat"]


def test_unhashable_loader_falls_back_to_unknown_hints():
    class Loader:
        __hash__ = None
        def __call__(self):
            raise AssertionError("metadata must not load")
    registry = PlatformRegistry()
    registry.register_deferred("chat", Loader(), env_hints=["CHAT_"])
    assert registry.deferred_env_hints("chat") == ()
    assert "chat" in registry.deferred_names()
