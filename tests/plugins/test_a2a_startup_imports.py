"""A2A's deferred client registration must not import the agent runtime."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_deferred_a2a_registration_does_not_import_agent_runtime(tmp_path):
    code = textwrap.dedent("""
        import importlib.abc
        from pathlib import Path
        import sys

        blocked = []
        runtime_modules = {'gateway.platforms', 'gateway.session', 'agent.auxiliary_client', 'agent.conversation_compression'}
        class RejectRuntime(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in runtime_modules or fullname.startswith('gateway.platforms.'):
                    blocked.append(fullname)
                    raise ImportError('agent runtime must stay deferred: ' + fullname)

        sys.meta_path.insert(0, RejectRuntime())
        from hermes_cli.plugins import PluginManager
        from hermes_cli.plugins_manifest import parse_manifest_file
        from tools.registry import registry

        plugin = Path('plugins/platforms/a2a').resolve()
        manifest = parse_manifest_file(plugin / 'plugin.yaml', plugin, 'bundled', 'platforms')
        assert manifest is not None
        manager = PluginManager()
        manager._register_deferred_platform(manifest)
        assert not blocked, blocked
        for name in ('a2a_discover', 'a2a_call', 'a2a_list', 'a2a_history', 'a2a_orchestrate'):
            entry = registry.get_entry(name, scope=manager.scope_key)
            assert entry is not None, name
            assert callable(entry.handler), name
        call = registry.get_entry('a2a_call', scope=manager.scope_key)
        assert call.schema['parameters']['required'] == ['agent', 'message']
        assert runtime_modules.isdisjoint(sys.modules)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "HERMES_HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
