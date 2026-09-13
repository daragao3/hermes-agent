"""Runtime regressions for profile-scoped cron plugin tools."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PUBLISHER_TOOL = "matcher_publish_score_batch"
PUBLISHER_TOOLSET = "matcher_score_publisher"
MATCHER_TOOLSETS = [
    "search",
    "file_read",
    PUBLISHER_TOOLSET,
    "no_mcp",
]
EXPECTED_MATCHER_TOOLS = {
    "web_search",
    "read_file",
    "search_files",
    PUBLISHER_TOOL,
}


def _write_plugin(profile_home: Path) -> None:
    plugin_dir = profile_home / "plugins" / "matcher-score-publisher"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                "name: matcher-score-publisher",
                "version: 1.0.0",
                "provides_tools:",
                f"  - {PUBLISHER_TOOL}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def _publish(args, **kwargs):",
                "    return json.dumps({'ok': True})",
                "",
                "def register(ctx):",
                "    ctx.register_tool(",
                f"        name={PUBLISHER_TOOL!r},",
                f"        toolset={PUBLISHER_TOOLSET!r},",
                "        schema={",
                f"            'name': {PUBLISHER_TOOL!r},",
                "            'description': 'Publish one score batch',",
                "            'parameters': {'type': 'object', 'properties': {}},",
                "        },",
                "        handler=_publish,",
                "    )",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_fixture_provider():
    """Deterministic stand-in web backend for the sanitized runtime.

    ``web_search`` carries ``check_fn=check_web_api_key``, so it only appears
    in the tool surface when *some* web backend is available. This fixture's
    HERMES_HOME is a throwaway tempdir with no credentials, and the hermetic
    conftest blanks credential env vars — so on a machine without ambient
    keys (or an undeclared ad-hoc ``ddgs`` install) every real backend probe
    returns False and ``web_search`` is stripped, failing the toolset-filter
    assertion below for reasons that have nothing to do with profile plugin
    loading. Registering one always-available provider gives the production
    resolution path (agent.web_search_registry → check_web_api_key) a
    deterministic True on every machine.
    """
    """Build the fixture provider as a real WebSearchProvider subclass."""
    from agent.web_search_provider import WebSearchProvider

    class _FixtureProvider(WebSearchProvider):
        name = "fixture-always-available"
        display_name = "Fixture always-available"
        supports_search_cap = True
        supports_extract_cap = True

        def supports_search(self) -> bool:
            return True

        def supports_extract(self) -> bool:
            return True

        def is_available(self) -> bool:
            return True

        def search(self, query: str, limit: int = 5, **kwargs):
            raise NotImplementedError("fixture provider never dispatches")

        def extract(self, urls, **kwargs):
            raise NotImplementedError("fixture provider never dispatches")

    return _FixtureProvider()


@pytest.fixture()
def isolated_matcher_runtime(tmp_path, monkeypatch):
    root = tmp_path / "hermes-root"
    main_home = root / "profiles" / "main"
    matcher_home = root / "profiles" / "matcher"
    main_home.mkdir(parents=True)
    matcher_home.mkdir(parents=True)
    (root / "cron").mkdir(parents=True)

    (main_home / "config.yaml").write_text(
        "model: test-model\nplugins:\n  enabled: []\n",
        encoding="utf-8",
    )
    (matcher_home / "config.yaml").write_text(
        "\n".join(
            [
                "model: test-model",
                "plugins:",
                "  enabled:",
                "    - matcher-score-publisher",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_plugin(matcher_home)

    monkeypatch.setenv("HERMES_HOME", str(main_home))
    monkeypatch.setattr("cron.jobs.CRON_DIR", root / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", root / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", root / "cron" / "output")

    import cron.scheduler as sched
    import hermes_cli.plugins as plugins
    from agent import web_search_registry as web_registry
    from tools.registry import invalidate_check_fn_cache, registry

    monkeypatch.setattr(sched, "_hermes_home", None)
    # Exercise real fixture plugin loading without discovering unrelated installed
    # packages or scanning this checkout's bundled platform catalog.
    monkeypatch.setattr(
        plugins.PluginManager, "_collect_directory_manifests",
        lambda manager: manager._scan_directory(manager.home_path / "plugins", source="user"),
    )
    monkeypatch.setattr(plugins.PluginManager, "_scan_entry_points", lambda manager: [])
    previous_manager = plugins._plugin_manager
    monkeypatch.setattr(plugins, "_plugin_managers_by_home", {})
    previous_publisher_entry = registry.get_entry(PUBLISHER_TOOL)
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("hermes_plugins.matcher_score_publisher")
    }
    # Snapshot the live provider table so the fixture's stand-in can be
    # removed without disturbing whatever the surrounding session loaded.
    previous_providers = dict(web_registry._providers)
    web_registry.register_provider(_make_fixture_provider())
    invalidate_check_fn_cache()
    registry.deregister(PUBLISHER_TOOL)
    plugins._plugin_manager = None

    try:
        yield root, main_home, matcher_home
    finally:
        plugins._reset_plugin_managers_for_tests()
        web_registry._providers.clear()
        web_registry._providers.update(previous_providers)
        invalidate_check_fn_cache()
        registry.deregister(PUBLISHER_TOOL)
        if previous_publisher_entry is not None:
            registry.register(
                name=previous_publisher_entry.name,
                toolset=previous_publisher_entry.toolset,
                schema=previous_publisher_entry.schema,
                handler=previous_publisher_entry.handler,
                check_fn=previous_publisher_entry.check_fn,
                requires_env=previous_publisher_entry.requires_env,
                is_async=previous_publisher_entry.is_async,
                description=previous_publisher_entry.description,
                emoji=previous_publisher_entry.emoji,
                max_result_size_chars=previous_publisher_entry.max_result_size_chars,
                dynamic_schema_overrides=previous_publisher_entry.dynamic_schema_overrides,
            )
        plugins._plugin_manager = previous_manager
        for name in list(sys.modules):
            if name.startswith("hermes_plugins.matcher_score_publisher"):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)


def _install_runtime_stubs(monkeypatch, observed: dict, *, assemble_tool_definitions=False) -> None:
    import cron.scheduler as sched
    import cron.scheduler_delivery as sched_delivery

    class FakeAgent:
        def __init__(self, **kwargs):
            from tools.registry import registry

            enabled = kwargs.get("enabled_toolsets")
            disabled = kwargs.get("disabled_toolsets")
            observed["enabled_toolsets"] = enabled
            observed["publisher_registered_before_agent"] = (
                registry.get_entry(PUBLISHER_TOOL) is not None
            )
            # Only the dedicated surface test needs real schema assembly.
            # Lifecycle tests assert registration timing and profile isolation.
            if assemble_tool_definitions:
                import model_tools

                observed["tool_names"] = {
                    item["function"]["name"]
                    for item in model_tools.get_tool_definitions(
                        enabled_toolsets=enabled,
                        disabled_toolsets=disabled,
                        quiet_mode=True,
                        skip_tool_search_assembly=True,
                    )
                }

        def run_conversation(self, *_args, **_kwargs):
            return {"final_response": "done", "messages": []}

        def get_activity_summary(self):
            return {"seconds_since_activity": 0.0}

        def close(self):
            return None

    fake_run_agent = type(sys)("run_agent")
    fake_run_agent.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    from hermes_cli import runtime_provider

    monkeypatch.setattr(
        runtime_provider,
        "resolve_runtime_provider",
        lambda **_kwargs: {
            "provider": "test",
            "api_key": "test-key",
            "base_url": "http://test.local",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(sched, "_build_job_prompt", lambda *_a, **_kw: "score")
    # _resolve_origin moved to cron.scheduler_delivery (Sep 2026 decomposition).
    monkeypatch.setattr(sched_delivery, "_resolve_origin", lambda _job: None)
    monkeypatch.setattr(sched, "_resolve_delivery_target", lambda _job: None)
    monkeypatch.setattr(
        sched,
        "_resolve_cron_enabled_toolsets",
        lambda _job, cfg: sched._merge_mcp_into_per_job_toolsets(
            list(MATCHER_TOOLSETS), cfg
        ),
    )
    monkeypatch.setenv("HERMES_CRON_TIMEOUT", "0")

    import tools.mcp_tool_discovery as mcp_tool

    def record_mcp_discovery():
        observed["mcp_discovery_calls"] = observed.get("mcp_discovery_calls", 0) + 1
        return []

    monkeypatch.setattr(mcp_tool, "discover_mcp_tools", record_mcp_discovery)


def test_profile_cron_additively_loads_enabled_plugin_before_agent_init(
    isolated_matcher_runtime, monkeypatch
):
    import cron.scheduler as sched
    from hermes_cli.plugins import discover_plugins
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.registry import registry

    _root, main_home, matcher_home = isolated_matcher_runtime
    observed: dict = {}
    _install_runtime_stubs(monkeypatch, observed)

    token = set_hermes_home_override(main_home)
    try:
        discover_plugins()
    finally:
        reset_hermes_home_override(token)
    assert registry.get_entry(PUBLISHER_TOOL) is None

    success, _output, _response, error = sched.run_job(
        {
            "id": "matcher-runtime",
            "name": "matcher-runtime",
            "profile": "matcher",
            "enabled_toolsets": list(MATCHER_TOOLSETS),
            "schedule_display": "manual",
        }
    )

    assert success is True, error
    assert observed["publisher_registered_before_agent"] is True
    assert registry.get_entry(PUBLISHER_TOOL) is None
    token = set_hermes_home_override(matcher_home)
    try:
        assert registry.get_entry(PUBLISHER_TOOL) is not None
    finally:
        reset_hermes_home_override(token)


def test_profile_tool_loader_scopes_and_unloads_owned_tools(isolated_matcher_runtime):
    from hermes_cli.plugins import PluginManager
    from hermes_constants import hermes_home_key, reset_hermes_home_override, set_hermes_home_override
    from tools.registry import registry

    _root, _main_home, matcher_home = isolated_matcher_runtime
    manager = PluginManager(scope_key=hermes_home_key(matcher_home))
    try:
        assert manager.load_profile_tools(matcher_home) == [PUBLISHER_TOOL]
        assert registry.get_entry(PUBLISHER_TOOL) is None
        token = set_hermes_home_override(matcher_home)
        try:
            assert registry.get_entry(PUBLISHER_TOOL) is not None
        finally:
            reset_hermes_home_override(token)
        manager.unload()
        token = set_hermes_home_override(matcher_home)
        try:
            assert registry.get_entry(PUBLISHER_TOOL) is None
        finally:
            reset_hermes_home_override(token)
    finally:
        manager.unload()


def test_profile_cron_initializes_mcp_without_explicit_opt_out(isolated_matcher_runtime, monkeypatch):
    import cron.scheduler as sched

    observed = {}
    _install_runtime_stubs(monkeypatch, observed)
    success, _output, _response, error = sched.run_job({
        "id": "matcher-mcp-default", "profile": "matcher",
        "enabled_toolsets": list(MATCHER_TOOLSETS[:-1]), "schedule_display": "manual",
    })
    assert success is True, error
    assert observed["mcp_discovery_calls"] == 1


def test_profile_plugin_load_failure_prevents_agent_initialization(
    isolated_matcher_runtime, monkeypatch
):
    import cron.scheduler as sched
    import hermes_cli.plugins as plugins

    _root, _main_home, _matcher_home = isolated_matcher_runtime
    observed: dict = {}
    _install_runtime_stubs(monkeypatch, observed)

    monkeypatch.setattr(
        plugins.PluginManager,
        "load_profile_tools",
        lambda self, profile_home: (_ for _ in ()).throw(
            ValueError("profile tool contract failed")
        ),
    )

    success, _output, _response, error = sched.run_job(
        {
            "id": "matcher-plugin-failure",
            "name": "matcher-plugin-failure",
            "profile": "matcher",
            "enabled_toolsets": list(MATCHER_TOOLSETS),
            "schedule_display": "manual",
        }
    )

    assert success is False
    assert "profile tool contract failed" in (error or "")
    assert "publisher_registered_before_agent" not in observed


def test_profile_cron_rejects_mismatched_discovered_tools(isolated_matcher_runtime, monkeypatch):
    import cron.scheduler as sched
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.registry import registry

    _root, _main_home, matcher_home = isolated_matcher_runtime
    source = matcher_home / "plugins" / "matcher-score-publisher" / "__init__.py"
    source.write_text(source.read_text(encoding="utf-8").replace(PUBLISHER_TOOL, "wrong_profile_tool"),
                      encoding="utf-8")
    observed = {}
    _install_runtime_stubs(monkeypatch, observed)
    success, _output, _response, error = sched.run_job({
        "id": "invalid-profile-tool", "profile": "matcher",
        "enabled_toolsets": list(MATCHER_TOOLSETS), "schedule_display": "manual",
    })
    assert success is False
    assert "manifest declares" in error
    assert "publisher_registered_before_agent" not in observed
    token = set_hermes_home_override(matcher_home)
    try:
        assert registry.get_entry("wrong_profile_tool") is None
    finally:
        reset_hermes_home_override(token)


@pytest.fixture()
def scoped_profile_manager(isolated_matcher_runtime):
    from hermes_cli.plugins import PluginManager
    from hermes_constants import hermes_home_key

    _root, _main, home = isolated_matcher_runtime
    manager = PluginManager(scope_key=hermes_home_key(home))
    try:
        yield manager, home
    finally:
        manager.unload()


@pytest.mark.parametrize("contribution", [
    "ctx.register_hook('pre_tool_call', lambda **kwargs: None)",
    "ctx.register_browser_provider(object())",
])
def test_profile_cron_rejects_undeclared_surfaces(scoped_profile_manager, monkeypatch, contribution):
    import cron.scheduler as sched
    import hermes_cli.plugins as plugins
    from tools.registry import registry

    manager, home = scoped_profile_manager
    source = home / "plugins" / "matcher-score-publisher" / "__init__.py"
    source.write_text(source.read_text(encoding="utf-8") + f"\n    {contribution}\n", encoding="utf-8")
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)
    observed = {}
    _install_runtime_stubs(monkeypatch, observed)
    success, _output, _response, error = sched.run_job({
        "id": "invalid-profile-surface", "profile": "matcher",
        "enabled_toolsets": list(MATCHER_TOOLSETS), "schedule_display": "manual",
    })
    assert success is False
    assert "tool-only" in error
    assert "publisher_registered_before_agent" not in observed
    assert registry.snapshot_registration(PUBLISHER_TOOL, scope=manager.scope_key) is None
    assert not any(item.active for item in manager._registration_order)
    assert not manager._hooks


def test_profile_tool_loader_safe_mode_never_scans(scoped_profile_manager, monkeypatch):
    manager, home = scoped_profile_manager
    monkeypatch.setenv("HERMES_SAFE_MODE", "1")
    monkeypatch.setattr(manager, "_scan_directory", lambda *args, **kwargs: pytest.fail("safe-mode scan"))
    monkeypatch.setattr(manager, "_load_directory_module", lambda *args, **kwargs: pytest.fail("safe-mode import"))
    assert manager.load_profile_tools(home) == []
    assert not manager._plugins


def test_profile_tool_loader_declared_hook_never_imports(scoped_profile_manager, monkeypatch):
    manager, home = scoped_profile_manager
    manifest = home / "plugins" / "matcher-score-publisher" / "plugin.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "provides_hooks: [pre_tool_call]\n", encoding="utf-8")
    monkeypatch.setattr(manager, "_load_directory_module", lambda *args, **kwargs: pytest.fail("hook plugin imported"))
    with pytest.raises(ValueError, match="tool-only"):
        manager.load_profile_tools(home)
    assert not any(item.active for item in manager._registration_order)


def test_profile_tool_loader_global_fallback_is_not_owned(scoped_profile_manager):
    from tools.registry import registry

    manager, home = scoped_profile_manager
    manager.load_profile_tools(home)
    manager.unload()
    handler = lambda *_args, **_kwargs: "global"
    registry.register(PUBLISHER_TOOL, "global_fixture", {"name": PUBLISHER_TOOL}, handler)
    try:
        with pytest.raises(ValueError, match="already registered"):
            manager.load_profile_tools(home)
        assert registry.get_entry(PUBLISHER_TOOL).handler is handler
        assert registry.snapshot_registration(PUBLISHER_TOOL, scope=manager.scope_key) is None
        assert not any(item.active for item in manager._registration_order)
    finally:
        registry.deregister(PUBLISHER_TOOL)


def test_profile_tool_loader_direct_registration_rolls_back(scoped_profile_manager):
    from tools.registry import registry

    manager, home = scoped_profile_manager
    source = home / "plugins" / "matcher-score-publisher" / "__init__.py"
    source.write_text(
        "from tools.registry import registry\n" + source.read_text(encoding="utf-8")
        + "\n    registry.register('rogue_profile_tool', 'fixture', {'name': 'rogue_profile_tool'}, lambda args: '{}')\n",
        encoding="utf-8",
    )
    registry.register("prior_profile_tool", "fixture", {"name": "prior_profile_tool"}, lambda args: "prior",
                      scope=manager.scope_key)
    prior = registry.snapshot_registration("prior_profile_tool", scope=manager.scope_key)
    try:
        with pytest.raises(ValueError, match="ctx.register_tool"):
            manager.load_profile_tools(home)
        assert registry.snapshot_registration("prior_profile_tool", scope=manager.scope_key) is prior
        for name in (PUBLISHER_TOOL, "rogue_profile_tool"):
            assert registry.snapshot_registration(name, scope=manager.scope_key) is None
        assert not any(item.active for item in manager._registration_order)
    finally:
        registry.deregister("prior_profile_tool", scope=manager.scope_key)


def test_profile_tool_loader_discovery_does_not_repeat_registration(scoped_profile_manager):
    manager, home = scoped_profile_manager
    source = home / "plugins" / "matcher-score-publisher" / "__init__.py"
    counter = home / "register-count.txt"
    source.write_text(
        "from pathlib import Path\n" + source.read_text(encoding="utf-8")
        + f"\n    counter = Path({str(counter)!r})\n"
        + "    count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        + "    counter.write_text(str(count))\n"
        + "    if count > 1:\n        ctx.register_hook('pre_tool_call', lambda **kwargs: None)\n",
        encoding="utf-8",
    )
    manager.load_profile_tools(home)
    manager.discover_and_load()
    manager.load_profile_tools(home)
    assert counter.read_text(encoding="utf-8") == "1"
    assert not manager._hooks


@pytest.mark.parametrize("source", ["project", "entrypoint"])
def test_profile_tool_loader_rejects_conflicting_catalog_winner(scoped_profile_manager, monkeypatch, source):
    from dataclasses import replace
    from unittest.mock import Mock
    from tools.registry import registry

    manager, home = scoped_profile_manager
    manager.load_profile_tools(home)
    loaded = next(iter(manager._plugins.values()))
    previous = registry.snapshot_registration(PUBLISHER_TOOL, scope=manager.scope_key)
    winner = replace(loaded.manifest, source=source, path=str(home / "replacement"))
    monkeypatch.setattr(manager, "_collect_directory_manifests", lambda: [loaded.manifest, winner])
    gate = Mock(side_effect=AssertionError("conflicting winner reached effectful gate"))
    monkeypatch.setattr(manager, "_gate_manifest", gate)
    with pytest.raises(ValueError, match="replace strict profile"):
        manager.discover_and_load()
    gate.assert_not_called()
    assert registry.snapshot_registration(PUBLISHER_TOOL, scope=manager.scope_key) is previous
    assert manager._plugins[loaded.manifest.key] is loaded
    assert not manager._hooks


def test_profile_tool_loader_entrypoint_metadata_is_not_success(scoped_profile_manager, monkeypatch):
    import importlib.metadata
    from types import SimpleNamespace
    from unittest.mock import Mock
    import hermes_cli.plugins as plugins

    manager, home = scoped_profile_manager
    (home / "config.yaml").write_text("plugins:\n  enabled: [external_fixture]\n", encoding="utf-8")
    entry = SimpleNamespace(name="external_fixture", value="nonexistent_fixture_package:plugin", dist=None,
                            load=Mock(side_effect=AssertionError("entrypoint imported during metadata scan")))
    eps = SimpleNamespace(select=lambda *, group: [entry] if group == plugins.ENTRY_POINTS_GROUP else [])
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda: eps)
    monkeypatch.setattr(manager, "_scan_entry_points", plugins.discover_entrypoint_manifests)
    assert manager.load_profile_tools(home) == []
    entry.load.assert_not_called()
    assert "nonexistent_fixture_package" not in sys.modules

    def failed_load(manifest):
        manager._plugins[manifest.name] = plugins.LoadedPlugin(manifest=manifest, enabled=False, error="fixture failure")

    monkeypatch.setattr(manager, "_load_plugin", failed_load)
    manager.discover_and_load()
    with pytest.raises(ValueError, match="external_fixture"):
        manager.load_profile_tools(home)
    entry.load.assert_not_called()


def test_profile_tool_loader_bundled_metadata_waits_for_discovery(scoped_profile_manager, monkeypatch):
    import hermes_cli.plugins as plugins
    from tools.registry import registry

    manager, home = scoped_profile_manager
    bundle = home / "fixture-bundle"
    bundle.mkdir()
    marker = home / "bundle-imported.txt"
    (bundle / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('loaded', encoding='utf-8')\n"
        "def register(ctx):\n"
        "    ctx.register_tool('external_fixture_tool', 'fixture', {'name': 'external_fixture_tool'}, lambda args: '{}')\n",
        encoding="utf-8",
    )
    manifest = plugins.PluginManifest(name="external_fixture", key="external_fixture", source="bundled",
                                      path=str(bundle), provides_tools=["external_fixture_tool"])
    monkeypatch.setattr(manager, "_collect_directory_manifests", lambda: [manifest])
    (home / "config.yaml").write_text("plugins:\n  enabled: [external_fixture]\n", encoding="utf-8")
    assert manager.load_profile_tools(home) == []
    assert not marker.exists()
    manager.discover_and_load()
    assert manager.load_profile_tools(home) == []
    assert marker.read_text(encoding="utf-8") == "loaded"
    assert registry.snapshot_registration("external_fixture_tool", scope=manager.scope_key) is not None


def test_profile_cron_exposes_only_read_search_and_publisher_tools(
    isolated_matcher_runtime, monkeypatch
):
    import cron.scheduler as sched
    from hermes_cli.plugins import discover_plugins
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    _root, main_home, _matcher_home = isolated_matcher_runtime
    observed: dict = {}
    _install_runtime_stubs(monkeypatch, observed, assemble_tool_definitions=True)

    token = set_hermes_home_override(main_home)
    try:
        discover_plugins()
    finally:
        reset_hermes_home_override(token)

    success, _output, _response, error = sched.run_job(
        {
            "id": "matcher-tools",
            "name": "matcher-tools",
            "profile": "matcher",
            "enabled_toolsets": list(MATCHER_TOOLSETS),
            "schedule_display": "manual",
        }
    )

    assert success is True, error
    assert observed["enabled_toolsets"] == MATCHER_TOOLSETS[:-1]
    assert observed["tool_names"] == EXPECTED_MATCHER_TOOLS
    assert observed["tool_names"].isdisjoint(
        {
            "terminal",
            "process",
            "send_message",
            "files",
            "write_file",
            "patch",
            "edit_file",
            "execute_code",
        }
    )
    assert not any(name.startswith("mcp_") for name in observed["tool_names"])
    assert observed.get("mcp_discovery_calls", 0) == 0
