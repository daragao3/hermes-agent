"""The ``plugins.enabled`` / ``plugins.disabled`` opt-in gate, as a leaf.

These two readers used to live in ``hermes_cli.plugins_discovery`` and were
imported through ``hermes_cli.plugins``. ``providers._discover_entry_point_providers``
consults the gate, so reaching them through ``hermes_cli.plugins`` cost ~55 modules
(asyncio, threading, the registration lifecycle) for a gate that is closed on most
installs. tests/hermes_cli/test_auth_import_cost.py pins the budget.

Both readers use ``load_config_readonly``: they take one scalar read and copy it into
a set, never writing to the config they are handed. Since the OPTIONAL_ENV_VARS
catalog stopped running provider discovery at ``hermes_cli.config`` import time, the
first caller to touch providers in a process pays discovery -- and in a terminal
session that is a command guard, which must not pay load_config's deepcopy.
tests/hermes_cli/test_plugin_gate_readonly.py and
tests/tools/test_approval_config_readonly.py pin both halves.

Both names are re-exported from ``hermes_cli.plugins_discovery`` and
``hermes_cli.plugins`` unchanged, so their existing callers and the tests that
monkeypatch them there keep working.
"""

from __future__ import annotations

from typing import Optional


def _get_disabled_plugins() -> set:
    """Read ``plugins.disabled`` — a deny-list that wins over ``plugins.enabled``."""
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        disabled = cfg_get(load_config_readonly(), "plugins", "disabled", default=[])
        return set(disabled) if isinstance(disabled, list) else set()
    except Exception:
        return set()


def _get_enabled_plugins() -> Optional[set]:
    """Read the ``plugins.enabled`` allow-list (plugins are opt-in). ``None`` = key missing/malformed ("nothing
    enabled yet"; the first ``migrate_config`` run grandfathers installed user plugins); ``set()`` = explicitly
    empty; else the allow-list."""
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        enabled = cfg_get(load_config_readonly(), "plugins", "enabled")
        return set(enabled) if isinstance(enabled, list) else None
    except Exception:
        return None
