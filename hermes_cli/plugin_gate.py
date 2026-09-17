"""The ``plugins.enabled`` / ``plugins.disabled`` opt-in gate, as a leaf.

These two readers used to live in ``hermes_cli.plugins_discovery`` and were
imported through ``hermes_cli.plugins``. ``providers._discover_entry_point_providers``
consults the gate while ``hermes_cli.config`` is itself being imported
(``_inject_profile_env_vars`` runs at module scope), so reaching them through
``hermes_cli.plugins`` cost every ``import hermes_cli.config`` -- and therefore
every ``import hermes_cli.auth`` -- ~55 modules (asyncio, threading, the
registration lifecycle) for a gate that is closed on most installs.
tests/hermes_cli/test_auth_import_cost.py pins the budget.

Both names are re-exported from ``hermes_cli.plugins_discovery`` and
``hermes_cli.plugins`` unchanged, so their existing callers and the tests that
monkeypatch them there keep working.
"""

from __future__ import annotations

from typing import Optional


def _get_disabled_plugins() -> set:
    """Read ``plugins.disabled`` — a deny-list that wins over ``plugins.enabled``."""
    try:
        from hermes_cli.config import cfg_get, load_config
        disabled = cfg_get(load_config(), "plugins", "disabled", default=[])
        return set(disabled) if isinstance(disabled, list) else set()
    except Exception:
        return set()


def _get_enabled_plugins() -> Optional[set]:
    """Read the ``plugins.enabled`` allow-list (plugins are opt-in). ``None`` = key missing/malformed ("nothing
    enabled yet"; the first ``migrate_config`` run grandfathers installed user plugins); ``set()`` = explicitly
    empty; else the allow-list."""
    try:
        from hermes_cli.config import cfg_get, load_config
        enabled = cfg_get(load_config(), "plugins", "enabled")
        return set(enabled) if isinstance(enabled, list) else None
    except Exception:
        return None
