"""Windows UTF-8 bootstrap for Hermes entry points (no-op on POSIX).

Windows binds stdio to the console code page (cp1252), so ``print("café")`` raises
``UnicodeEncodeError``, and Python children inherit the same default unless
``PYTHONUTF8``/``PYTHONIOENCODING`` are set. Import this module first in every entry
point (``hermes``, ``hermes-agent``, ``hermes-acp``, ``gateway.run``, ``batch_runner``,
``cron/scheduler``). It does NOT re-exec with ``-X utf8``: ``open()`` in the current
process still needs an explicit ``encoding="utf-8"`` (ruff ``PLW1514``). POSIX is left
alone deliberately — users' ``LANG``/``LC_*`` choices are respected.
"""

from __future__ import annotations

import os
import sys

_IS_WINDOWS = sys.platform == "win32"
_bootstrap_applied = False


def apply_windows_utf8_bootstrap() -> bool:
    """Apply the Windows UTF-8 bootstrap once; True only when it was applied this call."""
    global _bootstrap_applied

    if not _IS_WINDOWS or _bootstrap_applied:
        return False

    # setdefault() so a user can opt out with PYTHONUTF8=0 / PYTHONIOENCODING=...
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # os.environ changes don't rebind streams bound at interpreter startup, so
    # reconfigure them in-process. errors="replace" keeps a non-UTF-8 legacy
    # pipe on stdin from crashing us (U+FFFD instead of an exception).
    # Non-TextIOWrapper streams (BytesIO in tests, embedded hosts) have no
    # reconfigure(): skip — the env-var fix for children is the bigger win.
    for stream_name in ("stdout", "stderr", "stdin"):
        reconfigure = getattr(getattr(sys, stream_name, None), "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass  # closed, or replaced with something non-reconfigurable

    _bootstrap_applied = True
    return True


def suppress_platform_ver_console() -> None:
    """Stub ``platform._syscmd_ver`` on Windows — decode-crash + console-flash guard.

    ``platform.win32_ver()`` (reached via ``platform.platform()``, which the OpenAI SDK
    calls) shells out ``cmd /c ver`` with ``shell=True`` and no ``CREATE_NO_WINDOW``: a
    windowless parent (pythonw gateway, slash/kanban workers) flashes a console per call,
    and Python 3.11.0/3.11.1 (no ``encoding="locale"`` fix) strict-utf-8-decodes the OEM
    code page output under PEP 540 mode and raises (#69413). Returning the inputs makes
    ``win32_ver()`` fall back to ``sys.getwindowsversion()`` — same data, no subprocess.
    Mirrors ``hermes_cli._subprocess_compat.suppress_platform_ver_console`` for callers
    that never import ``hermes_cli.main``; double application is harmless.
    """
    if not _IS_WINDOWS:
        return
    try:
        import platform

        if hasattr(platform, "_syscmd_ver"):
            def _quiet_syscmd_ver(system="", release="", version="",
                                  supported_platforms=("win32", "win16", "dos")):
                return system, release, version

            platform._syscmd_ver = _quiet_syscmd_ver
    except Exception:
        pass  # hardening only — never break an entry point


# --- wmi-stub shared block (byte-identical in hermes_bootstrap.py, hermes_cli/_subprocess_compat.py
# and tests/conftest.py; tests/hermes_cli/test_host_platform_helpers.py::TestWmiStubCopies diffs them) ---
# IsWow64Process2's IMAGE_FILE_MACHINE_* codes -> WMI ``Win32_Processor.Architecture`` codes, the
# space ``platform.uname()`` maps (0 x86, 5 ARM, 9 AMD64, 12 ARM64).
_PE_MACHINE_TO_WMI_ARCHITECTURE = {0xAA64: 12, 0x8664: 9, 0x014C: 0, 0x01C4: 5}


def _native_machine_from_iswow64():
    """The OS-native machine as a WMI architecture code via ``IsWow64Process2``, or ``None`` (API
    absent before Windows 10 1709, call failed, unmapped machine code). It is the one kernel32 API
    that tells the truth from an x64 interpreter emulated on ARM64 Windows, where
    ``GetNativeSystemInfo`` returns the emulated details (AMD64) and the real WMI query would have
    said 12. HANDLE types are bound explicitly: ctypes' default ``c_int`` truncates the
    ``(HANDLE)-1`` pseudo-handle and ``IsWow64Process2`` then fails with ERROR_INVALID_HANDLE on
    Win64 (the residual Windows-on-ARM failure ``main_desktop._windows_native_machine_from_iswow64``
    documents)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    try:
        is_wow64_process2 = kernel32.IsWow64Process2
    except AttributeError:
        return None
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    is_wow64_process2.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
    is_wow64_process2.restype = wintypes.BOOL
    process_machine = wintypes.USHORT(0)
    native_machine = wintypes.USHORT(0)
    if not is_wow64_process2(
            kernel32.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)):
        return None
    return _PE_MACHINE_TO_WMI_ARCHITECTURE.get(native_machine.value)


def _native_processor_architecture() -> int:
    """The host's native CPU architecture in WMI's ``Win32_Processor.Architecture`` code space,
    read from kernel32 -- no thread, no environment. ``IsWow64Process2`` first (truthful under
    x64-on-ARM64 emulation), then ``GetNativeSystemInfo().wProcessorArchitecture`` (same code
    space; emulated details on such a host, exact everywhere else)."""
    import ctypes

    try:
        code = _native_machine_from_iswow64()
    except (OSError, AttributeError, TypeError, ValueError):
        code = None  # DLL load failure or a mistyped binding: fall back, never raise

    if code is not None:
        return code

    class _SYSTEM_INFO(ctypes.Structure):
        _fields_ = [("wProcessorArchitecture", ctypes.c_ushort), ("wReserved", ctypes.c_ushort),
                    ("dwPageSize", ctypes.c_uint32), ("lpMinimumApplicationAddress", ctypes.c_void_p),
                    ("lpMaximumApplicationAddress", ctypes.c_void_p), ("dwActiveProcessorMask", ctypes.c_void_p),
                    ("dwNumberOfProcessors", ctypes.c_uint32), ("dwProcessorType", ctypes.c_uint32),
                    ("dwAllocationGranularity", ctypes.c_uint32), ("wProcessorLevel", ctypes.c_ushort),
                    ("wProcessorRevision", ctypes.c_ushort)]

    info = _SYSTEM_INFO()
    ctypes.WinDLL("kernel32").GetNativeSystemInfo(ctypes.byref(info))
    return int(info.wProcessorArchitecture)


def _offline_wmi_query(table, *keys):
    """Stand-in for ``platform._wmi_query``: answer the CPU-architecture query from kernel32 and
    refuse the rest, so ``platform.machine()`` stays correct in a process whose environment lacks
    ``PROCESSOR_ARCHITECTURE`` (``env -i`` test runners) while ``win32_ver()`` takes its documented
    ``sys.getwindowsversion()`` fallback."""
    if table == "CPU" and tuple(keys) == ("Architecture",):
        return iter([str(_native_processor_architecture())])
    raise OSError("not supported")
# --- end wmi-stub shared block ---


def suppress_platform_wmi_queries() -> None:
    """Keep ``platform.uname()`` off WMI on interpreters that abandon the query thread.

    On Windows, CPython's ``platform.uname()`` (so ``system()``, ``machine()``,
    ``release()``, ``version()``, ``node()``, ``platform()``) runs two WMI queries on
    first use through the ``_wmi`` extension, which does the COM work on a helper
    thread and gives up after 1000 ms (CoInitialize) / 100 ms (ConnectServer). Before
    gh-130727 (fixed in 3.13.4 / 3.14.0b2, never backported to 3.12) the abandoned
    thread kept a pointer to the caller's *stack* struct and later ran
    ``SetEvent``/``WriteFile``/``CloseHandle`` on whatever that memory held by then —
    i.e. on a random live handle of the process. When that handle is one with a
    threadpool wait registered (bcrypt's system-RNG handle, taken on the next
    ``os.urandom``/``random.seed``), ntdll raises STATUS_THREADPOOL_HANDLE_EXCEPTION
    and the process dies with exit code 0xC000070A, no traceback, no WER entry.
    Measured 2026-09-17 on this box under a 2x CPU-oversubscribed load: the WMI
    connect timed out in 14 of 24 queries and 2 of 12 SessionDB children died that
    way; with this stub, 0 of 18.

    Setting ``_wmi`` to ``None`` in ``sys.modules`` makes a not-yet-imported
    ``platform`` take its ``ImportError`` branch; stubbing ``_wmi_query`` covers a
    ``platform`` that was imported before us. ``win32_ver()`` then takes the fallback
    it already takes when WMI times out (``sys.getwindowsversion()``); the CPU
    architecture is answered from kernel32 rather than left to the
    ``PROCESSOR_ARCHITECTURE`` env fallback, which an ``env -i`` runner strips
    (``machine()`` came back '' under scripts/run_tests.sh) — same values, no thread.
    Fixed interpreters are left alone. Mirrors
    ``hermes_cli._subprocess_compat.suppress_platform_wmi_queries``.
    """
    if not _IS_WINDOWS or sys.version_info >= (3, 13, 4):
        return
    try:
        sys.modules["_wmi"] = None  # type: ignore[assignment]
        import platform

        platform._wmi_query = _offline_wmi_query
    except Exception:
        pass  # hardening only — never break an entry point


def harden_import_path(src_root: str | None = None) -> None:
    """Stop a package in the current directory from shadowing Hermes modules.

    Hermes ships top-level modules with common names (``utils``, ``proxy``, ``ui``); a
    project with its own ``utils/`` launched from its directory would win the import.
    The cwd reaches ``sys.path`` as ``""``/``"."`` (script/``-m`` launches) AND as an
    absolute path (venv activation, PYTHONPATH), so both are handled: relative forms are
    dropped and the Hermes root is *relocated* to the front, not merely inserted when
    absent. ``src_root`` defaults to this module's directory (the repo root for every
    shipped entry point), so no spawner env var is required.
    """
    root = src_root or os.environ.get("HERMES_PYTHON_SRC_ROOT") or os.path.dirname(
        os.path.abspath(__file__)
    )

    sys.path[:] = [p for p in sys.path if p not in ("", ".")]

    root_abs = os.path.abspath(root)
    sys.path[:] = [p for p in sys.path if os.path.abspath(p) != root_abs]
    sys.path.insert(0, root)


def activate_durable_lazy_target() -> None:
    """Put the durable lazy-install dir (``HERMES_LAZY_INSTALL_TARGET``) on ``sys.path``.

    Immutable Docker images seal the venv and redirect lazy installs to the data volume;
    packages installed there on a previous run must be importable before any backend
    imports its SDK. Appends to the END of ``sys.path`` so the core venv always wins name
    collisions (see ``tools.lazy_deps``). Never raises; unset target is a no-op.
    """
    if not os.environ.get("HERMES_LAZY_INSTALL_TARGET", "").strip():
        return
    try:
        from tools import lazy_deps
        lazy_deps.activate_durable_lazy_target()
    except Exception:
        pass  # a failed activation just leaves the backend reporting itself unavailable


# Apply on import — entry points only need ``import hermes_bootstrap`` first.
apply_windows_utf8_bootstrap()
suppress_platform_ver_console()
suppress_platform_wmi_queries()
activate_durable_lazy_target()
