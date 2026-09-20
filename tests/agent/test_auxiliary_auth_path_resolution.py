"""``agent.auxiliary_client`` must resolve ``auth.json`` at CALL time, not at import.

Why this exists
---------------
``agent/auxiliary_client.py`` opened with a module-scope constant::

    _AUTH_JSON_PATH = get_hermes_home() / "auth.json"

``get_hermes_home()`` resolves a **context-local override** first
(``hermes_constants._HERMES_HOME_OVERRIDE``), then ``$HERMES_HOME``, then the platform
default. Snapshotting it at import therefore breaks the one mechanism it most needs to
follow: ``auxiliary_client.probe_credential_scope()`` is a context manager whose own
docstring says it overrides the home so that "``get_hermes_home()`` (auth store +
credential pool) follows the override". ``_read_nous_auth`` reads the auth store, so
under that context manager it was reading whichever home happened to be current when the
module was FIRST imported — not the profile the probe had just switched to.

The same snapshot also made the module unimportable under a stubbed home. The gateway
protocol harness installs
``MagicMock(get_hermes_home=MagicMock(return_value="/tmp/hermes_test"))`` — a str, not a
Path — so the import raised ``TypeError: unsupported operand type(s) for /: 'str' and
'str'`` and 69 of ``tests/tui_gateway/test_protocol.py``'s 70 tests ERRORed before
running. That was the visible symptom; the override bug above is the reason to fix it in
the product rather than by handing the stub a Path.

loops ``auxiliary-client-auth-json-module-scope-snapshot-20260920``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_auth(home: Path, agent_key: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(json.dumps({
        "active_provider": "nous",
        "providers": {"nous": {"agent_key": agent_key}},
    }), encoding="utf-8")


def test_read_nous_auth_follows_a_context_local_home_override(tmp_path, monkeypatch):
    """The probe's whole purpose: an override set AFTER import must reach the auth store.

    ``_select_pool_entry`` is stubbed pool-absent because ``_read_nous_auth`` consults the
    credential pool first and returns early when it has an entry, never reaching the
    auth.json read under test (same idiom as
    tests/hermes_cli/test_auth_store_windows_encoding.py).
    """
    import agent.auxiliary_client as aux
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    override_home = tmp_path / "profile-home"
    _write_auth(override_home, "from-the-override")
    monkeypatch.setattr(aux, "_select_pool_entry", lambda _provider: (False, None))

    token = set_hermes_home_override(override_home)
    try:
        provider = aux._read_nous_auth()
    finally:
        reset_hermes_home_override(token)

    assert provider is not None, (
        "_read_nous_auth found no Nous credentials under a context-local home override -- "
        "it is still reading the home that was current when the module was imported, so "
        "probe_credential_scope() cannot reach the active profile's auth store")
    assert provider.get("agent_key") == "from-the-override", (
        f"_read_nous_auth read a DIFFERENT store than the override named: {provider!r}")


def test_read_nous_auth_follows_a_later_hermes_home_change(tmp_path, monkeypatch):
    """Same defect through the env var: a home set after import must still be honoured."""
    import agent.auxiliary_client as aux

    later_home = tmp_path / "env-home"
    _write_auth(later_home, "from-the-env")
    monkeypatch.setattr(aux, "_select_pool_entry", lambda _provider: (False, None))
    monkeypatch.setenv("HERMES_HOME", str(later_home))

    provider = aux._read_nous_auth()

    assert provider is not None, (
        "_read_nous_auth ignored a HERMES_HOME set after import -- the auth path is still "
        "a module-scope snapshot")
    assert provider.get("agent_key") == "from-the-env"


def test_the_module_imports_when_the_home_resolves_to_a_str():
    """Import must not touch the home at all.

    Run in a SUBPROCESS: this replicates the gateway protocol harness, which stubs
    ``get_hermes_home`` to return a str before importing. Under the module-scope snapshot
    that import raised TypeError and errored 69 tests in one file.
    """
    code = (
        "import hermes_constants;"
        "hermes_constants.get_hermes_home = lambda: '/tmp/hermes_test';"
        "import agent.auxiliary_client as aux;"
        "print(aux.get_hermes_home() == '/tmp/hermes_test')"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), HERMES_DISABLE_LAZY_INSTALLS="1")
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=300)
    assert proc.returncode == 0, (
        "importing agent.auxiliary_client with a str-returning get_hermes_home failed -- "
        "the module still resolves a path at import time:\n" + proc.stderr[-2000:])
    assert proc.stdout.strip() == "True", (
        "the stub never reached the module, so this run proves nothing: "
        f"{proc.stdout.strip()!r}")
