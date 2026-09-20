"""``hermes_cli.plugin_gate``'s two readers must not pay ``load_config``'s deepcopy.

Why this exists
---------------
``providers._discover_entry_point_providers`` consults this gate, and discovery is
now first-caller-pays: the OPTIONAL_ENV_VARS catalog stopped running
``providers.list_providers()`` at ``hermes_cli.config`` import time (loops
``hermes-cli-config-import-optional-env-vars-lazy-20260919``), so whoever touches
providers first in a process pays discovery -- and the gate's two ``load_config()``
calls with it.

In a terminal session that first caller is ``check_all_command_guards``, whose entire
point is to be cheap per command: ``tools/environments/local_env_policy`` builds its
blocklist at module scope, which imports ``hermes_cli.auth``, which calls
``list_providers()`` at ITS module scope. That is how two deepcopying loads landed
inside a guard pass and reddened
``tests/tools/test_approval_config_readonly.py::test_guard_never_calls_deepcopy_variant``.

Both readers here take one scalar read and copy it into a ``set``; neither mutates the
config it was handed, so they belong on ``load_config_readonly`` like the other sites
audited in that test's own change. Pinning them here as well keeps the guard test from
being the only thing standing between this path and the deepcopy.
"""

import pytest

import hermes_cli.config as hc
from hermes_cli.plugin_gate import _get_disabled_plugins, _get_enabled_plugins


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  default: test-model\n"
        "plugins:\n  enabled: [alpha]\n  disabled: [beta]\n",
        encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    hc._LOAD_CONFIG_CACHE.clear()
    yield home
    hc._LOAD_CONFIG_CACHE.clear()


def _patched_loaders(monkeypatch):
    """Pass-through counters for both loader variants.

    Counting rather than booming: every call site wraps the load in try/except and
    would swallow an exception, so a raising stub would read as a silent pass.
    """
    calls = {"readonly": 0, "legacy": 0}
    real_ro, real_legacy = hc.load_config_readonly, hc.load_config

    def counting_ro():
        calls["readonly"] += 1
        return real_ro()

    def counting_legacy():
        calls["legacy"] += 1
        return real_legacy()

    monkeypatch.setattr(hc, "load_config_readonly", counting_ro)
    monkeypatch.setattr(hc, "load_config", counting_legacy)
    return calls


def test_the_gate_readers_never_call_the_deepcopy_variant(config_home, monkeypatch):
    calls = _patched_loaders(monkeypatch)
    assert _get_enabled_plugins() == {"alpha"}
    assert _get_disabled_plugins() == {"beta"}
    assert calls["legacy"] == 0, (
        f"the plugin gate called deepcopying load_config {calls['legacy']}x -- every "
        "provider discovery, including the first terminal command guard of a session, "
        "pays that deepcopy")
    assert calls["readonly"] == 2, (
        f"expected one readonly load per reader, got {calls['readonly']}")


def test_the_gate_does_not_mutate_the_config_it_reads(config_home):
    """``load_config_readonly`` hands back the live cache, so a reader that wrote to it
    would corrupt every later caller in the process."""
    before = hc.load_config_readonly()
    snapshot = {"enabled": list(before["plugins"]["enabled"]),
                "disabled": list(before["plugins"]["disabled"])}
    _get_enabled_plugins()
    _get_disabled_plugins()
    after = hc.load_config_readonly()
    assert after["plugins"]["enabled"] == snapshot["enabled"]
    assert after["plugins"]["disabled"] == snapshot["disabled"]
