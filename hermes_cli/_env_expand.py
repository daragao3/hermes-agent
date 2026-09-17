"""``${VAR}`` expansion for config dicts, split out of ``hermes_cli.config``.

Why its own module
------------------
The function is eight lines of ``re`` + ``os.environ`` and has no config
dependencies at all, but it lived in ``hermes_cli/config.py`` -- a 7,000-line
module that costs **126 modules** to import. ``hermes send`` needs exactly this
function (plus ``get_hermes_home``, which ``hermes_cli.config`` only re-exports
from ``hermes_constants``) to bridge ``~/.hermes/config.yaml`` into the
environment, and nothing else from that module.

This module carries the FULL expander -- ``${VAR}``, Cursor-style ``${env:VAR}``,
non-env SecretRefs left verbatim with a warning, and profile secret scopes via
``agent.secret_scope`` (imported lazily, only when a ref is actually expanded) --
so the fast path and ``load_config()`` cannot drift apart again (the 0.21.1
integration briefly left the ``${env:VAR}`` version in ``config.py`` only).

``hermes_cli.config`` imports ``expand_env_vars`` back under its historical
private name, so every existing ``from hermes_cli.config import
_expand_env_vars`` -- cli.py, cron/jobs.py, cron/scheduler.py, gateway/run.py,
hermes_cli/managed_scope.py, and tests/hermes_cli/test_config_env_expansion.py
-- keeps resolving to this same function object.

Regression test: ``tests/hermes_cli/test_send_import_cost.py``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


_ENV_REF_RE = re.compile(r"\${([^}]+)}")


def _env_ref_lookup(name: str) -> Optional[str]:
    """Resolve the env var behind a ``${VAR}`` / ``${env:VAR}`` ref — plain ``os.environ`` outside
    a profile secret scope (legacy behavior for the default profile).

    Inside a scope (a multiplexed gateway turn, a secondary profile's config load, a cron job) the read goes
    through ``agent.secret_scope.get_secret`` so the ref resolves against *that* profile's ``.env``: under
    multiplexing a miss is a miss, never another profile's ``os.environ`` value (#84079 — every profile
    "had" the default profile's ``${MATRIX_ACCESS_TOKEN}`` and fanned out). Same policy as
    ``gateway.config._getenv`` and ``get_env_value``.
    """
    try:
        from agent.secret_scope import current_secret_scope, get_secret as _get_secret
    except Exception:
        return os.environ.get(name)
    if current_secret_scope() is None:
        return os.environ.get(name)
    return _get_secret(name)


def _env_expand_match(m: re.Match) -> str:
    """Expand one ``${VAR}`` (legacy bare name) or ``${env:VAR}`` (Cursor-style SecretRef).
    Other SecretRef sources (``file:``, ``bitwarden:``, ``vault:``...) are NOT resolved here:
    external backends inject their values into the environment at startup (the ``secrets:``
    block), so a config ref only ever needs the env shape. Unresolved refs stay verbatim so
    callers can detect them."""
    raw = m.group(0)
    inner = m.group(1).strip()
    name = _env_ref_var_name(inner)
    if name is None:
        if not inner.startswith("env:") and _is_non_env_secret_ref(inner):
            logger.warning(
                "Config ref %r uses source %r which is not resolvable in "
                "config.yaml — external secret sources inject env vars at "
                "startup, so reference the variable as ${env:NAME} instead",
                raw, inner.split(":", 1)[0])
        return raw  # non-env source, or empty ``${env:}``
    val = _env_ref_lookup(name)
    if val is not None:
        return val
    if inner.startswith("env:"):
        logger.warning(
            "Config ref %r: %s is not set (check ~/.hermes/.env); "
            "keeping the literal placeholder", raw, name)
    return raw


def _is_non_env_secret_ref(ref: str) -> bool:
    """True for a SecretRef body with a non-``env`` source (``bitwarden:FOO``, ``vault:...``)."""
    return ":" in ref and re.match(r"^[a-z][a-z0-9_-]*:", ref) is not None


def _env_ref_var_name(ref: str) -> Optional[str]:
    """Env-var name a ``${...}`` body reads, or None for a non-env source / empty ``env:``."""
    ref = ref.strip()
    if ref.startswith("env:"):
        return ref[len("env:"):].strip() or None
    if _is_non_env_secret_ref(ref):
        return None
    return ref


def expand_env_vars(obj):
    """Recursively expand ``${VAR}`` / ``${env:VAR}`` in string values (keys/non-strings untouched)."""
    if isinstance(obj, str):
        return _ENV_REF_RE.sub(_env_expand_match, obj)
    if isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    return obj


__all__ = ["expand_env_vars"]
