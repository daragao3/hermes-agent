from agent import secret_scope
from gateway.config import _deferred_platform_may_be_configured
from gateway.platform_registry import PlatformRegistry


def test_deferred_gate_uses_active_scope_without_sibling_env(monkeypatch):
    registry = PlatformRegistry()
    registry.register_deferred("scoped", lambda: None, env_hints=["FIXTURE_SCOPED_TOKEN"])
    registry.register_deferred("sibling", lambda: None, env_hints=["FIXTURE_SIBLING_TOKEN"])
    monkeypatch.delenv("FIXTURE_SCOPED_TOKEN", raising=False)
    monkeypatch.setenv("FIXTURE_SIBLING_TOKEN", "sibling-only")
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", True)
    token = secret_scope.set_secret_scope({"FIXTURE_SCOPED_TOKEN": "scoped-only"})
    try:
        assert _deferred_platform_may_be_configured(registry, "scoped", set())
        assert not _deferred_platform_may_be_configured(registry, "sibling", set())
    finally:
        secret_scope.reset_secret_scope(token)
