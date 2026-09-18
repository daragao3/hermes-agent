"""``hermes_cli._subprocess_compat.host_system`` / ``host_machine`` / ``wmi_safe_platform``.

Why they exist. ``hermes_bootstrap.suppress_platform_wmi_queries`` keeps ``platform.uname()``
off the WMI helper thread CPython < 3.13.4 abandons (gh-130727; the stray thread closes a random
live handle and the process exits 0xC000070A under load) -- but only in processes that import
``hermes_bootstrap`` or ``hermes_cli.main``. A probe on 2026-09-17 imported each of the 35
modules that still called ``platform.system()``/``machine()``/``release()`` from a bare
``python -c`` and found ``platform._wmi_query`` live in every one of them: the protection is a
property of the entry point, not of the module. Real non-bootstrapped spawners exist (the
desktop app's ``python -m hermes_cli.windows_ssh_runtime``, ``hermes-session-bridge``,
``~/.hermes/scripts/stale_venv_sweep.py`` importing ``managed_uv``, skill scripts run by the
terminal tool, every ``python -c`` child the tests spawn). ``host_system()`` answers the OS-name
question from ``sys.platform`` with no ``uname()`` at all; the two others apply the stub before
the read. ``scripts/check-windows-footguns.py`` now flags the bare spellings.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hermes_cli import _subprocess_compat as compat

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestHostSystem:
    @pytest.mark.parametrize("sys_platform,expected", [
        ("win32", "Windows"), ("darwin", "Darwin"), ("linux", "Linux"), ("linux2", "Linux"),
    ])
    def test_answers_from_sys_platform_without_uname(self, monkeypatch, sys_platform, expected):
        import platform

        monkeypatch.setattr(sys, "platform", sys_platform)

        def _never(*a, **k):  # pragma: no cover - the assertion is that this is not reached
            raise AssertionError("host_system() must not call platform.uname()")

        monkeypatch.setattr(platform, "uname", _never)
        monkeypatch.setattr(platform, "system", _never)
        assert compat.host_system() == expected

    def test_matches_platform_system_on_this_host(self):
        """The spellings are ``platform.system()``'s own, so dict keys keyed on it keep working."""
        import platform

        if sys.platform == "win32":
            # conftest already stubbed the query in this process; the comparison is still the
            # point (same string), the read is just not the falsifier here.
            assert compat.host_system() == platform.system()  # windows-footgun: ok — stubbed by conftest
        else:
            assert compat.host_system() == platform.system()  # windows-footgun: ok — no WMI outside win32

    def test_unknown_platform_falls_through_to_platform_system(self, monkeypatch):
        import platform

        monkeypatch.setattr(sys, "platform", "freebsd14")
        monkeypatch.setattr(platform, "system", lambda: "FreeBSD")
        assert compat.host_system() == "FreeBSD"


class TestWmiSafePlatform:
    def test_applies_the_stub_before_returning_the_module(self, monkeypatch):
        import platform

        monkeypatch.setattr(compat, "IS_WINDOWS", True)
        monkeypatch.setattr(sys, "version_info", (3, 12, 13, "final", 0))
        monkeypatch.setattr(platform, "_wmi_query", platform._wmi_query)
        monkeypatch.setitem(sys.modules, "_wmi", sys.modules.get("_wmi", None))

        plat = compat.wmi_safe_platform()

        assert plat is platform
        assert sys.modules["_wmi"] is None
        assert platform._wmi_query is compat._offline_wmi_query

    def test_host_machine_reads_through_the_stubbed_module(self, monkeypatch):
        import platform

        monkeypatch.setattr(compat, "IS_WINDOWS", True)
        monkeypatch.setattr(sys, "version_info", (3, 12, 13, "final", 0))
        monkeypatch.setattr(platform, "_wmi_query", platform._wmi_query)
        monkeypatch.setitem(sys.modules, "_wmi", sys.modules.get("_wmi", None))
        monkeypatch.setattr(platform, "machine", lambda: "ARM64")

        assert compat.host_machine() == "ARM64"
        assert platform._wmi_query is compat._offline_wmi_query


@pytest.mark.windows_only
class TestBareChildNeverQueriesWmi:
    """The falsifier from the 2026-09-17 record, in miniature: a bare ``python -c`` child (no
    hermes_bootstrap, no conftest) that exercises a converted site must make **zero**
    ``_wmi.exec_query`` calls. ``-X importtime`` is not used; the child counts the calls itself by
    wrapping the extension before anything touches ``platform``."""

    _COUNTER = textwrap.dedent(
        """
        import sys
        calls = []
        try:
            import _wmi as _real
            _orig = _real.exec_query
            def _counting(*a, **k):
                calls.append(a)
                return _orig(*a, **k)
            _real.exec_query = _counting
        except ImportError:
            pass
        """
    )

    @pytest.mark.parametrize("probe", [
        # (module, expression) -- each is a converted site reached from a bare child.
        ("hermes_cli.managed_uv", "managed_uv_path()"),
        ("hermes_cli.windows_ssh_runtime", "_probe()['arch']"),
        ("agent.secret_sources.bitwarden", "_platform_asset_name()"),
        ("hermes_cli.browser_connect", "chromium_executable('chrome')"),
        ("tools.tirith_security", "is_platform_supported()"),
        ("hermes_cli._subprocess_compat", "host_system() + host_machine()"),
    ])
    def test_converted_site_makes_no_wmi_query(self, probe):
        module, expr = probe
        code = self._COUNTER + textwrap.dedent(
            f"""
            import {module} as _m
            _ = eval({expr!r}, vars(_m))
            print("WMI_CALLS", len(calls))
            """
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(REPO_ROOT), env=env,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "WMI_CALLS 0" in proc.stdout, proc.stdout
