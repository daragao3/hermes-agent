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
import types
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
        """On an interpreter below the gh-130727 fix the stub must have taken over and no query
        may run. From 3.13.4 the stub is a no-op by design (the abandoned thread can no longer
        touch the caller's handles), so the contract there is the inverse: ``platform`` keeps its
        own ``_wmi_query`` and the real query is allowed."""
        module, expr = probe
        code = self._COUNTER + textwrap.dedent(
            f"""
            import {module} as _m
            _ = eval({expr!r}, vars(_m))
            import platform
            print("WMI_CALLS", len(calls))
            print("WMI_QUERY_OWNER", platform._wmi_query.__module__)
            """
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(REPO_ROOT), env=env,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        if sys.version_info < compat.WMI_STRAY_THREAD_FIXED:
            # Sites answered from sys.platform alone never load the stub; the invariant is
            # the query count, not who owns _wmi_query.
            assert "WMI_CALLS 0" in proc.stdout, proc.stdout
        else:
            assert "WMI_QUERY_OWNER platform" in proc.stdout, proc.stdout


_SHARED_BLOCK_COPIES = (
    "hermes_bootstrap.py",
    "hermes_cli/_subprocess_compat.py",
    "tests/conftest.py",
)
_BLOCK_START = "# --- wmi-stub shared block"
_BLOCK_END = "# --- end wmi-stub shared block ---"


def _shared_block(rel: str) -> str:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert text.count(_BLOCK_START) == 1 and text.count(_BLOCK_END) == 1, rel
    return text[text.index(_BLOCK_START): text.index(_BLOCK_END) + len(_BLOCK_END)]


class TestWmiStubCopies:
    """The stub lives three times over (``hermes_bootstrap`` for entry points, ``_subprocess_compat``
    for library callers that cannot import the bootstrap, ``tests/conftest.py`` inline because
    importing the bootstrap there would reconfigure pytest's stdio). They are one block of source,
    kept byte-identical: a fix to the CPU answer that lands in one copy and not the others is exactly
    the drift this test refuses."""

    @pytest.mark.parametrize("rel", _SHARED_BLOCK_COPIES[1:])
    def test_copies_are_byte_identical(self, rel):
        assert _shared_block(rel) == _shared_block(_SHARED_BLOCK_COPIES[0]), rel

    def test_block_defines_the_whole_stub(self):
        block = _shared_block(_SHARED_BLOCK_COPIES[0])
        for name in ("_PE_MACHINE_TO_WMI_ARCHITECTURE", "def _native_machine_from_iswow64",
                     "def _native_processor_architecture", "def _offline_wmi_query"):
            assert name in block, name
        # The truthful API is consulted before the one that lies under emulation.
        assert block.index("IsWow64Process2") < block.index("GetNativeSystemInfo(")

    def test_pe_machine_table_matches_main_desktop(self):
        """Same IMAGE_FILE_MACHINE_* codes as the desktop integrity gate, mapped onto the WMI
        ``Win32_Processor.Architecture`` codes the stdlib table names."""
        from hermes_cli import main_desktop
        table = compat._PE_MACHINE_TO_WMI_ARCHITECTURE
        assert table[main_desktop._PE_MACHINE_ARM64] == 12
        assert table[main_desktop._PE_MACHINE_AMD64] == 9
        assert table[main_desktop._PE_MACHINE_I386] == 0
        assert table[0x01C4] == 5  # ARMNT: the desktop gate has no 32-bit ARM build to name


class TestHostMachineUnderEmulation:
    """``host_machine()`` on an ARM64 Windows host running the x64 PBS interpreter must say
    ``ARM64`` -- what the real WMI query says there -- not the ``AMD64`` GetNativeSystemInfo
    reports for the emulated process. This host is AMD64: the kernel32 answers are faked."""

    @staticmethod
    def _install_fake_kernel32(monkeypatch, native_pe_machine, native_system_info):
        import ctypes
        try:
            import ctypes.wintypes  # noqa: F401
        except Exception as exc:  # pragma: no cover — ancient non-Windows ctypes
            pytest.skip(f"ctypes.wintypes unavailable: {exc}")
        calls = []

        def GetCurrentProcess():
            return -1

        def IsWow64Process2(handle, p_process, p_native):
            calls.append("IsWow64Process2")
            p_native._obj.value = native_pe_machine
            return 1

        def GetNativeSystemInfo(p_info):
            calls.append("GetNativeSystemInfo")
            p_info._obj.wProcessorArchitecture = native_system_info

        dll = types.SimpleNamespace(
            GetCurrentProcess=GetCurrentProcess, IsWow64Process2=IsWow64Process2,
            GetNativeSystemInfo=GetNativeSystemInfo)
        monkeypatch.setattr(ctypes, "WinDLL", lambda name, *a, **k: dll, raising=False)
        return calls

    def test_stub_answers_arm64_from_an_emulated_x64_process(self, monkeypatch):
        calls = self._install_fake_kernel32(monkeypatch, native_pe_machine=0xAA64, native_system_info=9)
        assert compat._native_processor_architecture() == 12
        assert list(compat._offline_wmi_query("CPU", "Architecture")) == ["12"]
        assert calls == ["IsWow64Process2", "IsWow64Process2"]

    @pytest.mark.windows_only
    def test_host_machine_reports_arm64_from_an_emulated_x64_process(self, monkeypatch):
        """End to end through ``platform.machine()``: the stub feeds the stdlib's own code table."""
        import platform
        if sys.version_info >= (3, 13, 4):
            pytest.skip("interpreter carries the gh-130727 fix; stub is a no-op by design")
        monkeypatch.setattr(platform, "_wmi_query", platform._wmi_query)
        monkeypatch.setitem(sys.modules, "_wmi", sys.modules.get("_wmi", None))
        monkeypatch.setattr(platform, "_uname_cache", None)
        monkeypatch.delenv("PROCESSOR_ARCHITECTURE", raising=False)
        monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
        self._install_fake_kernel32(monkeypatch, native_pe_machine=0xAA64, native_system_info=9)

        assert compat.host_machine() == "ARM64"
