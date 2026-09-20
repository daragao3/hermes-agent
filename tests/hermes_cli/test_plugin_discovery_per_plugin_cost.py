"""Regression: ``discover_plugins()`` must not pay per-plugin syscalls or the auth package for bundled plugins.

Why this exists
---------------
After the dashboard_auth scrypt fix (a3d1e5b4cf) ``discover_plugins()`` still cost 1.4-2.2 s on the
loaded Windows box, and ``-X importtime`` could not say why: the plugin bodies run through
``spec.loader.exec_module`` (``PluginLoaderMixin._load_directory_module``), which the import-time hook
never sees. Timing ``_load_plugin`` per manifest over five runs (medians) put the 29 eager bundled
backends at ~330 ms together, spotify alone at 44-170 ms. The rest was not plugin code at all:

* ``hermes_cli.plugin_compat.disable_reason`` ran for EVERY plugin the loader was about to import and
  did, per call, ``Path(__file__).resolve()`` + ``.exists()`` (``removal_in_effect``) and a
  ``load_config_readonly()`` (``allow_deprecated_imports``) -- 29 x (resolve + stat + config
  cache-signature stats), 0.17-0.49 s per discovery on this box -- before ``_scan_root`` mapped a
  bundled manifest to "nothing to scan" and ``plugin_hits`` returned ``[]`` anyway.
* ``plugins/spotify`` imported ``hermes_cli.auth`` at module scope (``client.py`` for the credential
  resolver and ``AuthError``, ``tools.py`` for ``get_auth_status``): 23 modules -- the whole ``auth_*``
  family, ``agent.credential_persistence``, ``http.server``, ``html``, ``uuid`` -- that only a live
  Spotify call needs, 0.3 s in the cProfile of one discovery. No other plugin brought them in.

Both are fixed at the seam: ``disable_reason`` answers ``None`` for a manifest with no scan root
without consulting the compat manifest or the config, ``manifest_path`` resolves the repo root once
per process, and spotify resolves ``hermes_cli.auth`` on first use (a PEP 562 ``__getattr__`` keeps
``plugins.spotify.client.resolve_spotify_runtime_credentials`` / ``AuthError`` patchable exactly as
before -- tests/tools/test_spotify_client.py stubs the resolver there).

These tests assert the code path, not wall-clock: discovery on this box swings 1.4-2.2 s run to
run from filesystem-filter latency alone, so a budget would be either vacuous or flaky.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import plugin_compat as pc

REPO_ROOT = Path(__file__).resolve().parents[2]


def _child_env(tmp_path: Path) -> dict:
    """Repo on PYTHONPATH, HERMES_HOME at ``tmp_path`` (so no user plugin is discovered), no creds."""
    env = dict(os.environ)
    env["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    env["HERMES_HOME"] = str(tmp_path)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + existing if existing else str(REPO_ROOT)
    for key in list(env):
        upper = key.upper()
        if any(m in upper for m in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            env.pop(key, None)
    return env


def _run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=_child_env(tmp_path),
        capture_output=True, text=True, timeout=900,
    )


def _trap(what: str):
    def _raise(*_a, **_k):
        raise AssertionError(f"{what} must not run for a manifest with nothing to scan")
    return _raise


# --- disable_reason: bundled / pathless manifests short-circuit ---------------------------------

@pytest.mark.parametrize("manifest", [
    pytest.param(SimpleNamespace(name="spotify", path=str(REPO_ROOT / "plugins" / "spotify"), source="bundled"),
                 id="bundled-with-dir"),
    pytest.param(SimpleNamespace(name="ep", path="", source="user"), id="pathless"),
])
def test_disable_reason_skips_manifests_with_no_scan_root_without_touching_manifest_or_config(
    manifest, monkeypatch,
):
    """The loader calls this for every plugin it imports; a bundled one must cost nothing here."""
    monkeypatch.setattr(pc, "removal_in_effect", _trap("removal_in_effect (Path.resolve + exists)"))
    monkeypatch.setattr(pc, "allow_deprecated_imports", _trap("allow_deprecated_imports (load_config_readonly)"))
    monkeypatch.setattr(pc, "load_manifest", _trap("load_manifest"))
    assert pc.disable_reason(manifest) is None


def test_disable_reason_still_consults_the_gates_for_an_external_plugin(tmp_path, monkeypatch):
    """Non-vacuity: a user plugin directory goes through the date/allow gates and the scan as before."""
    manifest = {"tools.web_tools": {"prefers_gateway": "tools.tool_backend_helpers.prefers_gateway"}}
    monkeypatch.setattr(pc, "load_manifest", lambda: manifest)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "__init__.py").write_text("from tools.web_tools import prefers_gateway\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(pc, "removal_in_effect", lambda today=None: calls.append("date") or True)
    monkeypatch.setattr(pc, "allow_deprecated_imports", lambda config=None: calls.append("allow") or False)
    reason = pc.disable_reason(SimpleNamespace(name="bad", path=str(bad), source="user"))
    assert reason and pc.COMPAT_REMOVAL in reason
    assert calls == ["date", "allow"]


def test_manifest_path_resolves_the_repo_root_once():
    """``Path(__file__).resolve()`` is ~3-9 ms on this box; it used to run on every call."""
    pc._repo_root.cache_clear()
    first = pc.manifest_path()
    second = pc.manifest_path()
    assert first == second == REPO_ROOT / pc._MANIFEST_NAME
    assert pc._repo_root.cache_info().hits >= 1, pc._repo_root.cache_info()


# --- the discovery pass as a whole ----------------------------------------------------------------

@pytest.mark.timeout(900)
def test_discover_plugins_runs_no_compat_gate_when_only_bundled_plugins_exist(tmp_path):
    """With an empty HERMES_HOME every discovered plugin is bundled: zero compat-manifest resolves,
    zero config reads from plugin_compat. Subprocess so the count is not polluted by sibling tests."""
    proc = _run(
        "import hermes_cli.plugin_compat as pc\n"
        "counts = {'date': 0, 'allow': 0}\n"
        "real_date, real_allow = pc.removal_in_effect, pc.allow_deprecated_imports\n"
        "def date(today=None):\n"
        "    counts['date'] += 1\n"
        "    return real_date(today)\n"
        "def allow(config=None):\n"
        "    counts['allow'] += 1\n"
        "    return real_allow(config)\n"
        "pc.removal_in_effect, pc.allow_deprecated_imports = date, allow\n"
        "from hermes_cli.plugins import discover_plugins, get_plugin_manager\n"
        "discover_plugins()\n"
        "loaded = sum(1 for p in get_plugin_manager()._plugins.values() if p.enabled and p.module is not None)\n"
        "print(f'LOADED={loaded} DATE={counts[\"date\"]} ALLOW={counts[\"allow\"]}')\n",
        tmp_path,
    )
    assert proc.returncode == 0, f"discover_plugins() failed.\nstdout:\n{proc.stdout}\nstderr tail:\n{proc.stderr[-3000:]}"
    line = next((l for l in proc.stdout.splitlines() if l.startswith("LOADED=")), "")
    assert line, proc.stdout
    fields = dict(kv.split("=") for kv in line.split())
    assert int(fields["LOADED"]) >= 20, f"discovery loaded too few bundled plugins to mean anything: {line}"
    assert fields["DATE"] == "0" and fields["ALLOW"] == "0", (
        f"plugin_compat gates ran during a bundled-only discovery: {line}. disable_reason() must answer "
        "None for a manifest with no scan root BEFORE resolving the compat manifest or reading config."
    )


@pytest.mark.timeout(900)
def test_discover_plugins_does_not_import_the_auth_package(tmp_path):
    """``hermes_cli.auth`` (and what only it pulls: ``http.server``) stays out of a discovery pass.

    Spotify was the only bundled plugin importing it, at module scope, for a credential resolver and a
    status probe that only run on a live call. ``hermes_cli.auth_*`` is listed as a family: the package
    body imports every provider's helper, so one of them in ``sys.modules`` means the package came in.
    """
    proc = _run(
        "import sys\n"
        "from hermes_cli.plugins import discover_plugins\n"
        "discover_plugins()\n"
        "bad = sorted(m for m in sys.modules if m == 'hermes_cli.auth' or m.startswith('hermes_cli.auth_') "
        "or m == 'http.server')\n"
        "print('AUTH_OFFENDERS=[' + ','.join(bad) + ']')\n",
        tmp_path,
    )
    assert proc.returncode == 0, f"discover_plugins() failed.\nstdout:\n{proc.stdout}\nstderr tail:\n{proc.stderr[-3000:]}"
    assert "AUTH_OFFENDERS=[]" in proc.stdout, (
        f"discover_plugins() imported the auth package: {proc.stdout.strip()}\n"
        "A bundled plugin imports hermes_cli.auth at module scope again (spotify was the one with history: "
        "resolve it inside the method and serve the name through the module __getattr__ so patch seams hold)."
    )


# --- spotify: the seam tests/tools/test_spotify_client.py relies on --------------------------------

def test_spotify_client_module_still_exposes_the_auth_names_lazily():
    """``plugins.spotify.client.resolve_spotify_runtime_credentials`` / ``AuthError`` are the same
    objects ``hermes_cli.auth`` binds -- resolved on first attribute access, not at import."""
    import plugins.spotify.client as spotify_mod
    from hermes_cli import auth
    assert spotify_mod.AuthError is auth.AuthError
    assert spotify_mod.resolve_spotify_runtime_credentials is auth.resolve_spotify_runtime_credentials


def test_spotify_client_honours_a_resolver_patched_on_its_module(monkeypatch):
    """The stub tests put on the client module must be what ``SpotifyClient()`` calls."""
    import plugins.spotify.client as spotify_mod
    seen = []
    monkeypatch.setattr(spotify_mod, "resolve_spotify_runtime_credentials",
                        lambda **kw: seen.append(kw) or {"access_token": "t", "base_url": "https://x/"})
    client = spotify_mod.SpotifyClient()
    assert client.base_url == "https://x" and seen == [{"force_refresh": False, "refresh_if_expiring": True}]
