import os
import subprocess
import sys


def test_lifecycle_guard_does_not_import_job_store_or_scheduler(tmp_path):
    code = """
import importlib.abc
import sys
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'cron.jobs', 'cron.scheduler'}:
            raise AssertionError('pure guard imported runtime: ' + fullname)
sys.meta_path.insert(0, RejectRuntime())
from cron.lifecycle_guard import contains_gateway_lifecycle_command
assert contains_gateway_lifecycle_command('launchctl kick"start" -k gui/501/ai.hermes.gateway')
assert 'cron.jobs' not in sys.modules
assert 'cron.scheduler' not in sys.modules
"""
    env = dict(os.environ, HERMES_HOME=str(tmp_path))
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20, env=env)
    assert result.returncode == 0, result.stderr


def test_public_cron_exports_resolve_to_original_owners(monkeypatch):
    import cron
    from types import SimpleNamespace
    calls = []
    def owner(name):
        calls.append(name)
        return SimpleNamespace(**{key: key for key in cron.__all__})
    monkeypatch.setattr(cron.importlib, 'import_module', owner)
    for key in cron.__all__:
        assert getattr(cron, key) == key
        assert calls[-1] == ('cron.scheduler' if key == 'tick' else 'cron.jobs')
    assert {'request_run', 'JobPaused', 'rearm_oneshot'} <= set(cron.__all__)
