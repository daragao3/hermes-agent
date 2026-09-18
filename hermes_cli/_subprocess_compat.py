"""Windows subprocess compatibility helpers.

* ``["npm", ...]`` — on Windows ``npm`` is ``npm.cmd``, a batch shim; ``Popen`` fails with
  WinError 193 because CreateProcessW can't run a ``.cmd`` without ``shell=True``/PATHEXT.
* ``start_new_session=True`` — POSIX ``os.setsid()`` detach; silently ignored on Windows, whose
  equivalent is the ``CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`` creationflags bundle.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import tempfile
import subprocess
import sys
from typing import IO, Iterable, Mapping, NamedTuple, Optional, Sequence

# Stdlib-only module, so importing it keeps this one import-light; the same constant gates the
# managed-runtime repair (``managed_uv``) and ``hermes doctor``.
from hermes_cli.sqlite_runtime import WMI_STRAY_THREAD_FIXED

__all__ = [
    "IS_WINDOWS",
    "resolve_node_command",
    "split_command_line",
    "suppress_platform_ver_console",
    "suppress_platform_wmi_queries",
    "host_system",
    "host_machine",
    "wmi_safe_platform",
    "windows_detach_flags",
    "windows_detach_flags_without_breakaway",
    "windows_hide_flags",
    "windows_detach_popen_kwargs",
    "bounded_git_probe",
    "bounded_git_probe_outcome",
    "bounded_probe_run",
    "noninteractive_git_env",
    "NO_DRIVER_DIFF_FLAGS",
    "pid_is_hermes",
]

# Flags that neutralize *attribute-scoped* diff drivers on any diff-rendering git command. A
# malicious repo can name a driver in ``.gitattributes`` (``* diff=evil``) and point it at an
# arbitrary program via ``[diff "evil"] command=/textconv=`` in ``.git/config``; because the
# attacker chooses the name, ``GIT_CONFIG_KEY`` overrides in ``noninteractive_git_env`` cannot
# enumerate it — only these flags do. ``--no-ext-diff`` kills ``command=``; ``--no-textconv`` kills
# ``textconv=``; each alone leaves the other live. Smudge/clean filters are neutralized by the env
# layer's ``core.hooksPath`` + running against the index without checkout.
NO_DRIVER_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv")

# Only these subcommands accept ``NO_DRIVER_DIFF_FLAGS`` — ``status`` and friends reject them
# (``unknown option``), so the helper gates on this set rather than blanket-prepending.
_DIFF_RENDERING_SUBCOMMANDS = frozenset({"diff", "show", "log", "blame"})

# Options that consume the FOLLOWING token, so that value is never mistaken for the subcommand
# (``-C diff`` is a path; ``-c diff=x`` is a config pair).
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def harden_git_argv(args: Sequence[str]) -> list[str]:
    """Copy of subcommand-first git *args* (no leading ``"git"``) with :data:`NO_DRIVER_DIFF_FLAGS`
    inserted right after a diff-rendering subcommand; other subcommands are returned unchanged.

    Pair with :func:`noninteractive_git_env`: the env layer disables fsmonitor/hooks/pager/editor/
    credential sinks, this closes the one class (attacker-named attribute drivers) env cannot reach.
    """
    out = list(args)
    i = 0
    while i < len(out):
        tok = out[i]
        if tok in _GIT_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if tok in _DIFF_RENDERING_SUBCOMMANDS:
            return out[: i + 1] + list(NO_DRIVER_DIFF_FLAGS) + out[i + 1 :]
        return out  # first non-option token is a non-diff subcommand
    return out


IS_WINDOWS = sys.platform == "win32"

# Private launcher-to-child metadata. This is diagnostic state, not user config.
_WINDOWS_GATEWAY_BREAKAWAY_ENV = "_HERMES_GATEWAY_BREAKAWAY"


def split_command_line(line: str) -> list[str]:
    """Split a user-supplied command line into tokens, Windows-safely.

    ``shlex.split`` (posix=True) treats every backslash as an escape, mangling Windows paths. On
    Windows use ``posix=False`` and strip one layer of matching quotes per token; on POSIX this is
    exactly ``shlex.split``. Raises ValueError on unbalanced quotes.

    ``shlex.split(line)`` (posix=True) treats every backslash as an escape character, so Windows paths are
    silently mangled: ``C:\\Users\\me\\out.txt`` becomes ``C:Usersmeout.txt`` — no error, just a wrong path
    that then "succeeds" against a mangled relative filename (#83934) or makes a valid hook script report
    "not executable" (#78293).
    """
    import shlex

    if not IS_WINDOWS:
        return shlex.split(line)
    out: list[str] = []
    for tok in shlex.split(line, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
            tok = tok[1:-1]
        out.append(tok)
    return out


def resolve_node_command(name: str, argv: Sequence[str]) -> list[str]:
    """Resolve a Node-ecosystem command name (``npm``, ``npx``, ``yarn``…) to an absolute-path argv.

    On Windows these ship as ``.cmd`` batch shims that CreateProcessW won't execute by bare name;
    ``shutil.which`` resolves via PATHEXT to a fully-qualified path whose extension routes it
    through ``cmd.exe /c``.
    """
    resolved = shutil.which(name)
    return [resolved or name, *argv]


# Win32 CreationFlags — defined here because CREATE_NO_WINDOW / DETACHED_PROCESS aren't guaranteed
# to exist on stdlib subprocess for older Pythons or non-Windows builds.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
# DETACHED_PROCESS (0x00000008) is intentionally NOT part of any flag bundle — do not re-add it
# (the recurring console-flash bug #54220 / #56747): (1) MSDN: CREATE_NO_WINDOW "is ignored if used with either
# CREATE_NEW_CONSOLE or DETACHED_PROCESS"; (2) a DETACHED_PROCESS child has NO console, so every
# console-subsystem descendant (git, gh, cmd, node, powershell, …) allocates its own — a visible
# flash per spawn, including inside third-party libraries no per-site sweep can reach. A
# CREATE_NO_WINDOW child instead OWNS a hidden console all descendants inherit (A/B verified on
# Windows 11 by the desktop backend fix, commit aa2ae36c3f: with per-site hide flags neutered,
# naive git/gh/cmd spawns don't flash under a hidden-console parent and do under a console-less one).
# 1. Combining them means DETACHED_PROCESS governs and the no-window bit is dead. 2. See #54220, #56747.
_CREATE_NO_WINDOW = 0x08000000
# Escape any Win32 job object the parent belongs to. Without this a detached child inherits the
# parent's job, and when that parent (Electron, Tauri, Windows Terminal, the Desktop bootstrap
# installer) dies the OS tears down the whole job — taking the "detached" child with it. Critical
# for the post-update gateway watcher spawned from inside Electron's job.
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def windows_detach_flags() -> int:
    """Win32 creationflags detaching a child from the parent console/group; 0 elsewhere.

    Pair with the default ``start_new_session=False`` (POSIX uses ``start_new_session=True``).
    CREATE_NEW_PROCESS_GROUP stops Ctrl+C propagating; CREATE_NO_WINDOW gives the child a hidden
    console descendants (git, gh, cmd, node, …) inherit so they don't flash — deliberately replacing
    the old DETACHED_PROCESS approach, which re-created the per-descendant console-flash bug
    (#54220/#56747) at every spawn; CREATE_BREAKAWAY_FROM_JOB escapes Electron/Tauri job objects. A
    job that forbids breakaway yields PermissionError from Popen — callers catch OSError and fall
    back to :func:`windows_detach_flags_without_breakaway`.

    Rationale: This both detaches it from the parent's console lifetime (closing the launching terminal
    doesn't CTRL_CLOSE it) AND gives every console-subsystem descendant (git, gh, cmd, node, …) a console to
    inherit, so they don't allocate visible flashing ones. This deliberately replaces the old
    ``DETACHED_PROCESS`` approach: MSDN specifies CREATE_NO_WINDOW is *ignored* when combined with
    DETACHED_PROCESS, and a truly console-less daemon re-creates the per-descendant console-flash bug
    (#54220/#56747) at every spawn — see the note on ``_DETACHED_PROCESS`` above. Electron (Desktop app) and
    Tauri (bootstrap installer) wrap their children in job objects; without breakaway, those children die
    when the parent process exits even though they have their own console. This was the missing flag that
    made the post-update gateway respawn watcher silently die alongside the Tauri updater after the Electron
    Desktop's update flow finished.
    """
    if not IS_WINDOWS:
        return 0
    return _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW | _CREATE_BREAKAWAY_FROM_JOB


def windows_detach_flags_without_breakaway() -> int:
    """:func:`windows_detach_flags` minus ``CREATE_BREAKAWAY_FROM_JOB``; 0 on non-Windows."""
    if not IS_WINDOWS:
        return 0
    return _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW


def windows_hide_flags() -> int:
    """Win32 creationflags hiding the child's console without detaching it; 0 elsewhere.

    For short-lived synchronous helpers (``taskkill``, ``where``, version probes): no flash, but the
    child stays in the parent's process group and job so Ctrl+C and job teardown still propagate.
    Stdio is inherited, so ``capture_output=True`` works.
    """
    return _CREATE_NO_WINDOW if IS_WINDOWS else 0


def suppress_platform_ver_console() -> None:
    """Stub ``platform._syscmd_ver`` on Windows so it never flashes a console. No-op elsewhere.

    ``platform.win32_ver()`` shells out ``cmd /c ver`` without CREATE_NO_WINDOW, so a windowless
    parent (pythonw gateway, kanban workers) flashes a cmd window whenever a dependency touches
    ``platform.uname()`` at import. With the stub, ``win32_ver()`` takes its documented fallback to
    ``sys.getwindowsversion()`` — same data, in-process. Call before heavy imports.
    """
    if not IS_WINDOWS:
        return
    try:
        import platform

        if hasattr(platform, "_syscmd_ver"):
            def _quiet_syscmd_ver(system="", release="", version="",
                                  supported_platforms=("win32", "win16", "dos")):
                return system, release, version

            platform._syscmd_ver = _quiet_syscmd_ver
    except Exception:
        pass  # Purely cosmetic hardening — never let it break startup.


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
    """Keep ``platform.uname()`` off WMI where CPython abandons the query thread. No-op elsewhere.

    ``platform.uname()`` on Windows runs two WMI queries on first use via ``_wmi``, whose
    helper thread is given up on after 100 ms (ConnectServer). On CPython < 3.13.4 the
    abandoned thread (gh-130727) still points at the caller's dead stack struct and ends by
    ``CloseHandle``-ing whatever value sits there — a random live handle. If that is one with
    a threadpool wait on it (bcrypt's system-RNG handle, opened by the next ``os.urandom``),
    ntdll raises STATUS_THREADPOOL_HANDLE_EXCEPTION and the process exits 0xC000070A with no
    traceback. Under load on this box that killed SessionDB children at a 2-in-12 rate
    (2026-09-17). ``win32_ver()`` then takes the fallback it takes when WMI times out
    (``sys.getwindowsversion()``); the CPU architecture comes from kernel32, not the
    ``PROCESSOR_ARCHITECTURE`` env fallback an ``env -i`` runner strips: same values, no thread.
    Mirrors ``hermes_bootstrap.suppress_platform_wmi_queries``; double application is harmless.
    """
    if not IS_WINDOWS or sys.version_info >= WMI_STRAY_THREAD_FIXED:
        return
    try:
        sys.modules["_wmi"] = None  # type: ignore[assignment]
        import platform

        platform._wmi_query = _offline_wmi_query
    except Exception:
        pass  # Hardening only — never let it break startup.


_HOST_SYSTEM_BY_SYS_PLATFORM = {"win32": "Windows", "darwin": "Darwin", "linux": "Linux"}


def host_system() -> str:
    """``platform.system()``'s answer without ``platform.uname()``: ``"Windows"``, ``"Darwin"``
    or ``"Linux"`` from ``sys.platform``, ``platform.system()`` itself on anything else.

    The point is what it does NOT do on Windows: ``platform.system()`` goes through
    ``uname()``, whose WMI query thread CPython < 3.13.4 abandons after 100 ms and which then
    closes a random live handle of the process (exit 0xC000070A under load; see
    ``suppress_platform_wmi_queries``). The stub only covers processes that applied it —
    entry points via ``hermes_bootstrap`` — while every module in this tree is importable
    from a bare ``python -c``/``-m`` child (desktop ``-m hermes_cli.windows_ssh_runtime``,
    ``hermes-session-bridge``, ops scripts, skill scripts run by the terminal tool). An OS
    name test never needs the thread. Same spellings as ``platform.system()``, so dict keys
    and comparisons written against it keep working; tests patch this name, not ``platform``.
    """
    name = _HOST_SYSTEM_BY_SYS_PLATFORM.get(sys.platform)
    if name is None and sys.platform.startswith("linux"):
        name = "Linux"
    if name is not None:
        return name
    import platform

    return platform.system()  # windows-footgun: ok — unreachable on win32 (mapped above)


def wmi_safe_platform():
    """The ``platform`` module with the WMI stub applied first (idempotent; no-op elsewhere).

    For the reads that genuinely need ``uname()`` data on Windows — ``machine()``,
    ``release()``, ``version()``, ``node()``, ``platform()`` — in code a non-bootstrapped
    process can reach. Use ``host_system()`` for an OS-name test instead."""
    suppress_platform_wmi_queries()
    import platform

    return platform


def host_machine() -> str:
    """``platform.machine()`` with the WMI stub applied first; see ``wmi_safe_platform``."""
    return wmi_safe_platform().machine()


def windows_detach_popen_kwargs() -> dict:
    """Popen kwargs detaching a child on Windows, or ``start_new_session=True`` on POSIX.

    Bare ``start_new_session=True`` is accepted but has no effect on Windows: the child stays
    attached to the parent console and dies when it closes.
    """
    if IS_WINDOWS:
        return {"creationflags": windows_detach_flags()}
    return {"start_new_session": True}


# GIT_CONFIG_KEY_n/VALUE_n overrides for internal git children: no credential/askpass prompts, no
# repo-configured fsmonitor/hooks/pager/editor/external-diff programs.
_GIT_CONFIG_INJECT_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
_GIT_CONFIG_OVERRIDES = {
    "credential.helper": "",
    "core.askPass": "",
    "core.fsmonitor": "false",
    "core.untrackedCache": "false",
    "core.hooksPath": os.devnull,
    "core.pager": "cat",
    "core.editor": "true",
    "sequence.editor": "true",
    "diff.external": "",
    # ssh itself bypasses stdin=DEVNULL/GIT_TERMINAL_PROMPT and opens /dev/tty directly — an
    # unknown host key (or password auth) prompts there and steals the caller's terminal (#104591).
    # BatchMode makes ssh fail instead of prompting; a working ssh-agent still succeeds. Injected
    # at the config layer so an explicit user GIT_SSH_COMMAND (env) still takes precedence.
    "core.sshCommand": "ssh -o BatchMode=yes",
}


def noninteractive_git_env(base: "Mapping[str, str] | None" = None) -> dict[str, str]:
    """Environment for *internal* git invocations that must never prompt.

    Copy of ``base`` (default ``os.environ``) with ``GIT_TERMINAL_PROMPT=0`` (fail instead of
    prompting), ``GCM_INTERACTIVE=Never`` (no Git Credential Manager dialog), and isolated git
    config: inherited ``GIT_CONFIG_*`` injection, global/system config, pagers, editors, fsmonitor,
    external diff and hooks are all disabled so a user's repo/global config cannot hang or mutate
    Hermes's plumbing calls. ``core.sshCommand`` is pinned to ``ssh -o BatchMode=yes`` so the ssh
    child of a fetch/ls-remote fails instead of prompting — ssh bypasses ``stdin=DEVNULL`` and
    opens ``/dev/tty`` directly (#104591); an agent-authenticated ssh still succeeds, and an
    explicit user ``GIT_SSH_COMMAND`` env var still takes precedence over this config-layer pin.
    ``GIT_ASKPASS``/``SSH_ASKPASS`` env vars are left alone, but OpenSSH BatchMode disables
    passphrase/password prompts, including SSH askpass. Usable keys and ssh-agent authentication
    still work; Git's own working askpass helper is unaffected. Pair with
    ``stdin=subprocess.DEVNULL``. Internal plumbing only — the agent-facing terminal tool has its
    own policy layer and visible PTY.

    Hermes shells out to git from many non-interactive contexts — MCP catalog installs, plugin
    install/update, profile distribution staging, worktree base fetches, desktop review-pane fetch/push.
    When the remote is private, misconfigured, or requires auth, git's default behavior is to prompt on the
    inherited terminal (or via an askpass helper), which silently hangs the operation until its timeout — or
    forever at call sites without one. Ported from openai/codex#34540 / #34612 ("detach non-interactive
    subprocesses from stdin"): a background tool invocation must fail fast with a readable error, not wait
    for input nobody can type.
    """
    env = dict(base if base is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    # Drop caller-supplied config injection; the GIT_CONFIG_COUNT block is rebuilt below so
    # ambient -c values cannot re-enable pagers, hooks, fsmonitor, editors or credential prompts.
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key, None)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    env["GIT_EDITOR"] = "true"
    env["GIT_CONFIG_COUNT"] = str(len(_GIT_CONFIG_OVERRIDES))
    for idx, (key, value) in enumerate(_GIT_CONFIG_OVERRIDES.items()):
        env[f"GIT_CONFIG_KEY_{idx}"] = key
        env[f"GIT_CONFIG_VALUE_{idx}"] = value
    return env


def _process_start_time(pid: int) -> int | None:
    """The repository's stable process-start fingerprint, if available."""
    try:
        from gateway.status import get_process_start_time

        return get_process_start_time(pid)
    except Exception:
        return None


def _text_names_hermes(text: str) -> bool:
    r"""True when *text* names Hermes at a path-segment / token boundary.

    A bare ``"hermes" in text`` substring test would also match unrelated processes whose paths
    merely contain the letters (``...\shermesa\...``) — the false-positive class this prevents.
    """
    return any(token.startswith(("hermes", ".hermes"))
               for token in re.split(r"[\\/\s=,;\"']+", text.lower()))


def _process_command_is_hermes(pid: int) -> bool:
    """Best-effort check that *pid* currently runs Hermes code."""
    try:
        import psutil

        process = psutil.Process(pid)
        command = " ".join(process.cmdline() or [])
        executable = process.exe() or ""
        return _text_names_hermes(f"{command} {executable}")
    except Exception:
        return False


def pid_is_hermes(pid: int, *, expected_start_time: int | None = None) -> bool:
    """Whether it is safe to use ``taskkill`` for *pid*.

    The PID must be valid, currently exist, and identify a Hermes process. When the caller captured
    a start-time fingerprint before the destructive action, the live process must still have the
    same ``(pid, start_time)`` identity. Any ambiguity fails closed.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if not IS_WINDOWS:
        if expected_start_time is None:
            return True
        try:
            return _process_start_time(pid) == expected_start_time
        except Exception:
            return False
    try:
        current_start_time = _process_start_time(pid)
    except Exception:
        return False
    if current_start_time is None:
        return False
    if expected_start_time is not None and current_start_time != expected_start_time:
        return False
    try:
        return _process_command_is_hermes(pid)
    except Exception:
        return False


def kill_process_tree(proc: "subprocess.Popen") -> None:
    """Best-effort terminate *proc* and its descendants on both platforms; never raises.

    ``proc.kill()`` alone only terminates the direct child. This is cleanup on an already-failing
    path whose contract is to fail open, so every failure (access denied, already reaped) is
    swallowed rather than escaping the caller's ``except``.

    On Windows a suspended descendant (e.g. ``git.exe``) can survive holding duplicates of the captured pipe
    handles, which keeps the pipes from reaching EOF and leaks two reader threads + the process per fired
    timeout — the creation-time-guarded tree kill (never ``taskkill /T``; see the block comment above
    :class:`ProcessRecord`) takes the provable tree down so the bounded drain that follows can actually
    reach EOF. On POSIX the same class exists: killing the launcher leaves descendants (credential helpers,
    ``git-remote-https``, hook children) running and holding the pipe write ends. Callers spawn the child in
    its own process group (``process_group=0``, Python ≥3.11), so when — and only when — the child leads its
    own group (``pgid == pid``), the entire group is signalled with ``os.killpg``. The ownership check means
    a fallback spawn that shares our group can never cause us to kill unrelated processes. Ported from
    openai/codex#36793 ("Terminate timed-out Git process trees"); generalized for the shell-hook runner via
    openai/codex#37527 ("Terminate timed-out hook process trees").
    """
    try:
        from agent.deadline import kill_process_tree as _deadline_kill_tree

        _deadline_kill_tree(proc.pid)
    except Exception:
        _legacy_kill_process_tree(proc)
        return
    # Ensure Popen's own bookkeeping sees the exit so communicate()/wait() cannot hang.
    try:
        proc.kill()
    except OSError:
        pass


def _legacy_kill_process_tree(proc: "subprocess.Popen") -> None:
    """Local tree-kill fallback when agent.deadline is unavailable (partial install, cycle)."""
    if not IS_WINDOWS:
        # Verify the child leads its own process group before signalling, never a shared group.
        try:
            import signal as _signal

            pgid = os.getpgid(proc.pid)  # windows-footgun: ok -- inside the not-Windows gate two lines up
            if pgid == proc.pid:
                os.killpg(pgid, _signal.SIGKILL)  # windows-footgun: ok — inside `if not IS_WINDOWS` gate
        except Exception:
            pass
    if IS_WINDOWS:
        # The root needs no ``pid_is_hermes`` probe: *proc* is our own retained Popen handle, so its
        # PID cannot be recycled while we hold it. Its DESCENDANTS' ParentProcessId edges can still
        # point at strangers (an orphan whose dead parent's pid was recycled onto our child), which
        # is why the walk is creation-time guarded and runs while the root is alive -- see the block
        # comment above :class:`ProcessRecord`.
        try:
            windows_kill_popen_tree(proc)
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def bounded_probe_run(
    argv: Sequence[str], *, timeout: float, errors: str = "replace",
    env: "Mapping[str, str] | None" = None,
) -> "subprocess.CompletedProcess[str] | None":
    """Deadlock-safe ``subprocess.run(argv, capture_output=True, timeout=…)`` for fail-open probes.

    Returns a ``CompletedProcess`` when the child finished within *timeout* (any exit code), or
    ``None`` on spawn failure or timeout.

    Why not ``subprocess.run``: on Windows, ``run()``'s post-timeout cleanup calls an *unbounded*
    ``communicate()`` after killing the direct child. Killing it can leave a descendant (``git.exe`` under a
    launcher shim, ``conhost.exe`` under wmic/powershell) holding duplicates of the captured stdout/stderr
    handles, so the pipes never reach EOF and the reader-thread join blocks forever. The wmic /
    ``Get-CimInstance Win32_Process`` gateway scan hit exactly this during ``hermes update`` on slow-WMI
    machines (#87134); the git probes hit it first (#68609 / #66037).
    """
    return _bounded_probe_run_outcome(argv, timeout=timeout, errors=errors, env=env)[0]


def _bounded_probe_run_outcome(
    argv: Sequence[str], *, timeout: float, errors: str = "replace",
    env: "Mapping[str, str] | None" = None,
) -> "tuple[subprocess.CompletedProcess[str] | None, bool]":
    """:func:`bounded_probe_run` plus a ``stalled`` flag: ``(result, False)`` when the child answered or
    never spawned, ``(None, True)`` when it was killed for overrunning *timeout* (or for a torn pipe mid-
    read). Callers that cache a ``None`` need the distinction — a stall is a fact about the box's load,
    not about the target — while keeping the public ``None`` contract untouched."""
    # Windows: CREATE_SUSPENDED (when thawable) so the probe joins its job before its first
    # instruction; the timeout kill is then by job membership, never by pid (see ``ProcessRecord``).
    suspended_flag = windows_suspended_spawn_flag() if IS_WINDOWS else 0
    _popen_kwargs: dict = (
        {"creationflags": windows_hide_flags() | suspended_flag} if IS_WINDOWS else {"process_group": 0})
    try:
        proc = subprocess.Popen(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors=errors,
            env=dict(env) if env is not None else None, **_popen_kwargs)
    except Exception:
        return None, False
    tree = windows_tree_capture(proc, suspended=bool(suspended_flag)) if IS_WINDOWS else None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except Exception:
        # Timeout OR any other communicate() failure (torn-down pipe, decode error): tree-kill and
        # drain bounded — leaving it running would leak the suspended-descendant class this guards.
        if tree is not None and tree.job is not None:
            _tree_kill(proc, tree)
        else:
            kill_process_tree(proc)
        try:
            proc.communicate(timeout=1)
        except Exception:
            pass
        return None, True
    finally:
        windows_job_close(tree.job if tree is not None else None)
    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr), False


def bounded_git_probe(argv: Sequence[str], *, timeout: float) -> str:
    """Run a short ``git`` probe and return stripped stdout, or ``""`` on ANY failure.

    On Windows ``run()``'s post-timeout cleanup calls an unbounded ``communicate()``; a suspended
    descendant git.exe holding the pipe handles then blocks forever. Here: bounded ``communicate``,
    tree-kill plus a 1s drain, then abandon the pipes; on POSIX the probe gets its own process
    group so cleanup also takes down credential/remote helpers.

    Security (GHSA-7x36-8jrh-v4pw): these probes run automatically against whatever directory the
    session sits in, before any tool call or trust prompt, and an index refresh executes the
    repo-configured ``core.fsmonitor`` program. Every probe therefore runs under
    :func:`noninteractive_git_env`; diff-rendering callers additionally pass
    :data:`NO_DRIVER_DIFF_FLAGS` (attribute-scoped drivers can't be disabled via env).

    Killing the PATH-resolved launcher can leave a suspended descendant ``git.exe`` holding duplicates of
    the captured stdout/stderr handles, so the pipes never reach EOF and the reader-thread join blocks
    forever. On the Desktop agent-build path (``_start_agent_build → _session_info → branch() → run_git``)
    that turned an optional branch label into ``agent initialization timed out`` (issues #68609 / #66037).
    The normal-path spawn contract mirrors the previous ``run`` call byte-for-byte: PIPE/PIPE/DEVNULL,
    ``text`` with UTF-8 ``errors="replace"`` decoding, and the hidden-window ``creationflags`` on Windows
    only. On POSIX the probe is additionally placed in its own process group (``process_group=0``, Python
    ≥3.11) so timeout cleanup can take down descendants — credential helpers, ``git-remote-https``, hook
    children — with the launcher instead of orphaning them (see :func:`kill_process_tree`; port of
    openai/codex#36793). ``process_group`` only changes which group the child belongs to; it does not detach
    the terminal or alter the fast path.
    """
    return bounded_git_probe_outcome(argv, timeout=timeout)[0]


def bounded_git_probe_outcome(argv: Sequence[str], *, timeout: float) -> "tuple[str, bool]":
    """:func:`bounded_git_probe` that also reports whether the probe STALLED: ``(stdout, False)`` on an
    answer, ``("", False)`` when git answered rc!=0 or could not be spawned (a fact about the target,
    safe to remember), ``("", True)`` when it was killed at *timeout* (a fact about the box's load —
    ``git_probe._RootCache`` remembers that only briefly, else one saturated spawn reads as "not a
    repo" for its whole negative TTL)."""
    result, stalled = _bounded_probe_run_outcome(argv, timeout=timeout, env=noninteractive_git_env())
    if result is None or result.returncode != 0:
        return "", stalled
    return (result.stdout or "").strip(), False



if IS_WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PeekNamedPipe = _kernel32.PeekNamedPipe
    _PeekNamedPipe.argtypes = [
        wintypes.HANDLE,                 # hNamedPipe
        ctypes.c_void_p,                 # lpBuffer (NULL — we only want the count)
        wintypes.DWORD,                  # nBufferSize
        ctypes.POINTER(wintypes.DWORD),  # lpBytesRead
        ctypes.POINTER(wintypes.DWORD),  # lpTotalBytesAvail
        ctypes.POINTER(wintypes.DWORD),  # lpBytesLeftThisMessage
    ]
    _PeekNamedPipe.restype = wintypes.BOOL


def resolve_windows_git_bash() -> Optional[str]:
    """Locate a bash.exe on Windows that can execute ``C:\\`` paths.

    On a box with WSL installed, PATH order usually puts the WSL launcher
    (``System32\\bash.exe``) or its Microsoft Store stub
    (``WindowsApps\\bash.exe``) ahead of Git Bash — when Git Bash is on
    PATH at all (a default Git for Windows install only adds ``Git\\cmd``,
    which ships no bash).  WSL bash runs commands inside the Linux VM,
    where ``C:\\...``-style paths do not resolve: scripts and snapshot
    files "vanish" and bash exits 126/127 with a mangled-path "No such
    file or directory".

    Preference order:

    1. ``HERMES_GIT_BASH_PATH`` — explicit user override.
    2. Hermes' own portable Git (``%LOCALAPPDATA%\\hermes\\git``) —
       dropped by install.ps1 when the user had no working system Git;
       checked before system installs so a broken or partially
       uninstalled system Git can't hijack the lookup.  Both PortableGit
       (``bin\\bash.exe``) and MinGit (``usr\\bin\\bash.exe``) layouts
       are probed.
    3. Known Git for Windows install locations (machine-wide and
       per-user).
    4. ``shutil.which("bash")`` — last resort, REFUSING System32 /
       WindowsApps results (the WSL launcher and its Store stub).

    Returns ``None`` when nothing usable exists.  Windows-only by
    intent: callers branch on platform before calling (the POSIX answer
    is just ``shutil.which("bash")``).
    """
    custom = os.environ.get("HERMES_GIT_BASH_PATH")
    if custom and os.path.isfile(custom):
        return custom

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        hermes_git = os.path.join(local_appdata, "hermes", "git")
        for candidate in (
            os.path.join(hermes_git, "bin", "bash.exe"),         # PortableGit
            os.path.join(hermes_git, "usr", "bin", "bash.exe"),  # MinGit
        ):
            if os.path.isfile(candidate):
                return candidate

    for base_var, rel in (
        ("ProgramFiles", os.path.join("Git", "bin", "bash.exe")),
        ("ProgramFiles", os.path.join("Git", "usr", "bin", "bash.exe")),
        ("ProgramFiles(x86)", os.path.join("Git", "bin", "bash.exe")),
        ("LOCALAPPDATA", os.path.join("Programs", "Git", "bin", "bash.exe")),
    ):
        base = os.environ.get(base_var)
        if base:
            candidate = os.path.join(base, rel)
            if os.path.isfile(candidate):
                return candidate

    found = shutil.which("bash")
    if found and is_wsl_bash_launcher(found):
        return None  # WSL launcher / Store stub — cannot see C:\ paths
    return found


def is_wsl_bash_launcher(path: str) -> bool:
    """True for the WSL launcher (``System32\\bash.exe``) or its Microsoft Store stub
    (``WindowsApps\\bash.exe``) — the two ``bash`` spellings ``shutil.which`` returns on a
    WSL-enabled box that must never be run as a shell: they boot the Linux VM and cannot
    see ``C:\\`` paths.  Case-insensitive (``which`` reports ``bash.EXE``).  Every Windows
    bash discovery must consult this before trusting a PATH hit -- ``_find_bash`` in
    ``tools.environments.local`` lost the check in a refactor and probed the launcher
    (booting Ubuntu from inside the test-suite) until 2026-09-16."""
    lowered = path.lower()
    return "\\system32\\" in lowered or "\\windowsapps\\" in lowered


def windows_pipe_readable_bytes(fd: int) -> Optional[int]:
    """Return the bytes readable *right now* on a pipe fd, or ``None`` when the
    pipe is broken / the fd is unusable (the EOF equivalent).

    ``select.select()`` only works on sockets on Windows, so non-blocking pipe
    drains poll this instead: ``os.read(fd, n)`` is guaranteed not to block
    whenever this reports > 0 available bytes.

    Built on ``PeekNamedPipe``, which works on anonymous pipes too — both
    ``subprocess.PIPE`` and ``os.pipe()`` create them.  Pipe fds only; on a
    non-pipe fd the underlying call fails and this reports ``None``.

    Failure mapping: once every write handle is closed AND the buffer is
    drained, ``PeekNamedPipe`` fails with ``ERROR_BROKEN_PIPE`` — exactly the
    moment a POSIX ``read()`` would return ``b""``.  While data is still
    buffered the call keeps succeeding, so no tail output is lost.  Any other
    failure (handle closed under us, not a pipe) also returns ``None``: the
    caller should stop reading in every such case.

    Returns ``None`` on non-Windows hosts, keeping this module's "no-op on
    POSIX" guarantee — callers there use ``select.select([fd], [], [], t)``.
    """
    if not IS_WINDOWS:
        return None
    try:
        handle = msvcrt.get_osfhandle(fd)
    except (OSError, ValueError):
        return None  # fd already closed / not a CRT fd
    avail = wintypes.DWORD(0)
    ok = _PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
    if not ok:
        return None  # broken pipe (all writers gone) or invalid handle
    return avail.value


def run_text_capture(
    argv: Sequence[str] | str,
    *,
    timeout: float,
    cwd: str | os.PathLike | None = None,
    env: Mapping[str, str] | None = None,
    stdin: int | IO[bytes] | None = subprocess.DEVNULL,
    input: str | None = None,  # noqa: A002 — mirrors subprocess.run's parameter name
    shell: bool = False,
    executable: str | os.PathLike | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, capture_output=True, text=True, timeout=timeout)``
    that reliably honours ``timeout`` on Windows.

    ``text=False`` returns raw stdout/stderr bytes, including timeout partial
    output. Use it for NUL-delimited filenames: decoding and newline replacement
    would otherwise corrupt valid paths. Existing text callers are unchanged.

    The stdlib hang this works around: when the spawned child itself spawns a
    grandchild that inherits the capture (stdout/stderr) pipe handles, the
    grandchild keeps the pipe's write end open. ``subprocess.run`` kills only
    the *direct* child on timeout, then (on Windows) calls ``communicate()`` a
    second time to drain the pipes — which blocks forever on the reader-thread
    join because the pipe never reaches EOF. A wedged CLI therefore hangs the
    caller indefinitely instead of timing out at ``timeout`` seconds.

    The fix: **capture into temporary files rather than pipes.** A tree-kill
    alone is not enough — measured against a real wedged `npm audit` on
    Windows, a nominal 30s budget still cost 75s: `taskkill /T /F` itself ran
    11.6s and was abandoned at its own cap, the post-kill drain burned its full
    10s because the surviving grandchild still held the pipe, and
    ``Popen.__exit__`` then blocked a further 22.8s merely *closing* a pipe
    whose reader thread was still parked in a blocking read. Every one of
    those costs is a property of the capture pipes and its reader threads, so
    the pipes have to go. With file-backed stdio there are no reader threads,
    nothing to drain, and closing a file handle cannot block — a grandchild
    that outlives its parent just writes into a temp file nobody reads.

    On timeout we still tree-kill (on Windows the job object the child was
    assigned to at spawn, terminated by membership, else a creation-time-
    guarded ParentProcessId walk -- never ``taskkill /T``, see
    :class:`ProcessRecord`; ``killpg`` on POSIX) so as not to leak an
    abandoned process tree. The kill is best effort — correctness no longer
    *depends* on it succeeding, because with file-backed stdio there is
    nothing left to drain and we never wait on the child again — but it IS
    synchronous, and that costs real wall clock.

    **The bound is ``timeout`` plus the cost of the kill, not ``timeout``.**
    On Windows the old ``_tree_kill`` shelled out to ``taskkill`` under its
    own ``timeout=10``, so the worst case was ``timeout + ~10s``; measured on
    a loaded Windows host against a real wedged ``npm install`` with a 5s
    budget, ``taskkill`` alone took 8.47s and 10.48s across two probes, for
    13.91s and 15.58s end to end (2026-08-11), and 11.6s against a wedged
    ``npm audit``. ``TerminateJobObject`` is one syscall and the walk reads
    one creation time per candidate, so that tail is now small -- but it is
    still paid synchronously, and callers sized against the old bound stay
    correct. On POSIX ``killpg`` is a bare syscall, so the tail there is
    negligible.

    Callers may keep sizing their timeouts against ``timeout + 10s`` on Windows —
    ``agent/lsp/install.py`` passing 600s really means "up to ~610s", and
    ``hermes doctor --audit`` pays the tail once per timed-out target (~40s
    across four). This is a bounded, predictable overshoot; what the
    file-backed capture removed was the *unbounded* one, where a kill that
    missed the grandchild added a 10s drain that could never reach EOF plus a
    22.8s blocking pipe close — 75s against a nominal 30s budget.

    Returns a :class:`subprocess.CompletedProcess`; raises
    :class:`subprocess.TimeoutExpired` on timeout (same as ``subprocess.run``)
    so existing ``except (OSError, subprocess.TimeoutExpired)`` handlers keep
    working, with ``.output`` / ``.stderr`` carrying whatever the child wrote
    before the deadline — callers that record timeout diagnostics (the DevFlow
    validator logs how far a wedged ``pytest`` got) keep working unchanged.
    May raise ``OSError`` / ``FileNotFoundError`` at spawn, also like
    ``subprocess.run``.

    ``cwd`` and ``env`` are passed straight through to :class:`subprocess.Popen`
    for callers that must run the command from a particular directory
    (``npm audit`` in ``hermes doctor``, for one) or under a doctored
    environment (the Node-ecosystem callers all prepend Hermes' managed Node to
    ``PATH`` via ``with_hermes_node_path()``).

    ``stdin`` defaults to ``DEVNULL`` rather than inheriting the parent's.
    Inheriting is the second way this call can outlive its timeout: a child that
    prompts (``npm`` asking to install a missing peer, ``bash -i`` reading a
    profile) blocks on a read from a stdin nobody is driving, and in a gateway
    daemon there is no terminal behind it at all. Every caller of this helper
    wants a non-interactive probe, so closing stdin is the right default; pass
    ``stdin=None`` to opt back into inheritance.

    ``input`` mirrors ``subprocess.run(input=…)`` — the text is fed to the child
    on stdin, which then hits EOF, so a child that reads its payload that way
    (the shell hooks and the webhook route scripts both take their JSON on
    stdin) sees exactly what it did before. It is staged in a **temp file**
    rather than a pipe for the same reason stdout/stderr are: feeding a pipe
    requires ``communicate()``'s writer thread, which is one more thread that
    can park forever when a grandchild holds the other end of the capture.
    A regular file needs no thread at all. Mutually exclusive with ``stdin``.

    ``shell=True`` runs ``argv`` (then a command *string*, not a list) through
    the platform shell, and is the case that needs this helper most: with a
    shell the real command is ALWAYS a grandchild — ``cmd.exe`` / ``/bin/sh``
    is the direct child — so the grandchild-holds-the-pipe hang above is not a
    risk but a guarantee, and ``subprocess.run(shell=True, capture_output=True,
    timeout=N)`` has no bound at all on Windows. File-backed capture removes
    the pipe the shell's children would otherwise inherit.

    ``executable`` is passed through to :class:`subprocess.Popen`; with
    ``shell=True`` it selects the shell binary (POSIX only — on Windows Popen
    uses it *instead of* ``cmd.exe``, so a POSIX shell path there fails to
    spawn). Callers wanting bash must gate on :data:`IS_WINDOWS` themselves.
    """
    suspended_flag = 0
    if IS_WINDOWS:
        # CREATE_SUSPENDED (when thawable) so the child joins its job before its
        # first instruction: nothing it spawns can predate the job, and the
        # timeout kill below is by membership rather than by pid.
        suspended_flag = windows_suspended_spawn_flag()
        popen_kwargs: dict = {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW | suspended_flag}
    else:
        # Own session/process group so killpg() on timeout reaches grandchildren.
        popen_kwargs = {"start_new_session": True}

    # Binary temp files + an explicit decode rather than text=True: we own the
    # handles, so the decoding is ours to make deterministic (utf-8 with
    # replacement, \r\n normalized) instead of locale-dependent.
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f, \
            tempfile.TemporaryFile() as in_f:
        if input is not None:
            if stdin != subprocess.DEVNULL:
                raise ValueError("pass either 'input' or 'stdin', not both")
            in_f.write(input.encode("utf-8"))
            in_f.seek(0)
            stdin = in_f
        proc = subprocess.Popen(
            # With shell=True the command is a string Popen hands to the shell
            # verbatim; list() would shred it into one argument per character.
            argv if shell else list(argv),
            stdout=out_f,
            stderr=err_f,
            stdin=stdin,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            shell=shell,
            executable=executable,
            **popen_kwargs,
        )
        tree = windows_tree_capture(proc, suspended=bool(suspended_flag)) if IS_WINDOWS else None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Best effort — we do NOT wait on the child again afterwards, so a
            # kill that fails costs us nothing but a lingering process.
            _tree_kill(proc, tree)
            # Partial output survives the timeout. Reading is safe even when a
            # grandchild outlived the kill and is still writing: these are
            # regular files, so the read returns whatever was flushed and
            # CANNOT block. A pipe-based capture could not do this at all —
            # that drain is the 10s-then-22.8s cost described above — so the
            # file-backed design is what makes timeout diagnostics recoverable.
            raise subprocess.TimeoutExpired(
                proc.args, timeout,
                output=_read_text(out_f, text=text), stderr=_read_text(err_f, text=text),
            )
        finally:
            # Not kill-on-close: releasing the handle leaves a grandchild the
            # command deliberately detached (agent-browser's daemon) running.
            windows_job_close(tree.job if tree is not None else None)
        return subprocess.CompletedProcess(
            proc.args, proc.returncode, _read_text(out_f, text=text), _read_text(err_f, text=text),
        )


def _read_text(handle, *, text: bool = True) -> str | bytes:
    """Rewind capture; preserve binary records or apply the existing text decode."""
    handle.seek(0)
    content = handle.read()
    return content.decode("utf-8", errors="replace").replace("\r\n", "\n") if text else content


def _tree_kill(proc: subprocess.Popen, tree: "WindowsProcessTree | None" = None) -> None:
    """Kill ``proc`` and its entire descendant tree; never raises.

    Windows: the job object captured at spawn (``tree``) is terminated by
    membership; without one, the creation-time-guarded ppid walk runs while
    the root is still alive. Never ``taskkill /T`` -- it adopted strangers on
    recycled pids (see the block comment above :class:`ProcessRecord`). We
    can't use a softer signal: there is no Windows SIGTERM that cascades
    through a process group. POSIX: ``killpg(SIGKILL)`` reaches the
    grandchildren because the child was started in its own session
    (``start_new_session=True``). Either way this is best effort:
    ``run_text_capture`` captures into files, not pipes, so its budget holds
    whether or not the kill lands — the point here is only to avoid leaving
    an abandoned process tree behind.

    Best effort is not free, though. This runs SYNCHRONOUSLY inside
    ``run_text_capture``'s timeout path, so its duration is added to that
    call's bound (see the note there). The old ``taskkill`` on a live ``npm``
    tree was measured at 8.47s, 10.48s and 11.6s on a loaded Windows host;
    ``TerminateJobObject`` is one syscall, and the walk reads a creation time
    per candidate, so the tail is now small -- but callers sized against
    ``timeout + ~10s`` stay correct.
    """
    if IS_WINDOWS:
        try:
            windows_kill_popen_tree(proc, tree)
        except Exception:
            pass
        try:
            proc.kill()  # Popen's bookkeeping sees the exit either way
        except OSError:
            pass
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # windows-footgun: ok — POSIX-only; the Windows branch above returns first
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass

__all__ += ["resolve_windows_git_bash", "is_wsl_bash_launcher", "windows_pipe_readable_bytes", "run_text_capture"]


# ---------------------------------------------------------------------------
# Windows process trees without ``taskkill /T``
# ---------------------------------------------------------------------------
#
# Why no product path runs ``taskkill /F /T /PID`` any more (2026-09-17T21:30:08Z,
# Security 4689): ``/T`` walks every process whose recorded ParentProcessId
# equals the target pid. Windows recycles pids within minutes on a busy box,
# and every long-lived service is an orphan of a shell that exited long ago --
# an orphan keeps its dead parent's pid as ParentProcessId forever. Two such
# calls, issued 3 ms after the pids they were aimed at had exited normally,
# adopted and killed Hermes Canvas :9121, Control Center :9120, three more
# long-lived interpreters and git/docker/cmd in one 80 ms sweep. ``/IM`` is
# worse still (every instance of an image, cross-session).
#
# Two primitives replace it, neither of which can name a process that was
# never ours. They are the port of ``scripts/run_tests_parallel.py``'s
# fce8860303 (itself a port of memory-fabric d913d20 ``Get-ProcessTreeVictims``);
# the runner keeps its own copy on purpose -- it must be able to validate a
# checkout whose ``hermes_cli`` does not import.
#
# 1. A job object per spawned child (the Windows equivalent of the POSIX
#    process group captured at spawn). The child is assigned while it is
#    still alive -- CREATE_SUSPENDED when we can thaw it, so nothing it will
#    ever spawn can predate the job; every descendant inherits membership;
#    ``TerminateJobObject`` kills by membership, not by pid or image name,
#    and is safe after the root has exited. Product jobs are NOT
#    kill-on-close: ``run_text_capture`` runs commands whose detached
#    grandchild is the point (the agent-browser session daemon), and a
#    kill-on-close handle closed at return would reap it. ``BREAKAWAY_OK``
#    keeps ``CREATE_BREAKAWAY_FROM_JOB`` spawns (the detached gateway /
#    watcher idiom) escaping exactly as they do today.
#
# 2. When there is no job (a bare pid, a Popen we did not spawn, ctypes
#    trouble), a ppid walk over one Toolhelp32 snapshot, guarded: a child is
#    adopted only if it was created at or after its claimed parent -- a real
#    child can never predate its parent -- and an unknown creation time is
#    not adopted. The root must still be the process the caller means (its
#    creation time is pinned at spawn or re-read by the caller) and each
#    victim must still be the process the snapshot saw before it is
#    terminated. A root that has already exited leaves nothing provable to
#    stand on, so the walk kills nothing. Creation times are read only along
#    the candidate chain: ``psutil.process_iter`` with ``create_time`` was
#    62 s cold on this box (2026-09-17).


class ProcessRecord(NamedTuple):
    """One row of a process snapshot (the Win32_Process / psutil shape)."""

    pid: int
    ppid: int
    created: float | None  # epoch seconds; None when the host would not say


class WindowsProcessTree:
    """What a kill knows about a Windows child, captured at spawn.

    ``job`` is the job handle the child was assigned to, or None when
    assignment failed. ``root_created`` is the child's creation time (epoch
    seconds) read while it was certainly alive, so a later walk can tell our
    root from a stranger wearing its recycled pid.
    """

    __slots__ = ("job", "root_created")

    def __init__(self, job: int | None = None, root_created: float | None = None) -> None:
        self.job = job
        self.root_created = root_created


# Two records agree on identity when their creation times match to the
# millisecond: psutil computes the float from the same FILETIME both times,
# and no pid can be reused faster than that.
CREATED_TOLERANCE_S = 1e-3


def same_process(created_a: float | None, created_b: float | None) -> bool:
    if created_a is None or created_b is None:
        return False
    return abs(created_a - created_b) <= CREATED_TOLERANCE_S


def is_genuine_child(child: ProcessRecord, parent: ProcessRecord) -> bool:
    """A real child can never predate its parent; an unknown birth is not adopted.

    The recycled-pid orphan claims ``parent.pid`` as its ParentProcessId but
    was born before ``parent`` existed. This is the whole guard.
    """
    if child.created is None or parent.created is None:
        return False
    return child.created >= parent.created


def process_tree_victims(
    root_pid: int,
    snapshot: "Iterable[ProcessRecord]",
    root_created: float | None = None,
) -> list[ProcessRecord]:
    """Pure: the root and every provable descendant, leaves first, root last.

    Empty when the root is not in the snapshot, or when ``root_created`` is
    given and the snapshot's root is a different process (recycled pid).
    """
    rows = list(snapshot)
    by_pid: dict[int, ProcessRecord] = {r.pid: r for r in rows}
    root = by_pid.get(root_pid)
    if root is None:
        return []
    if root_created is not None and not same_process(root.created, root_created):
        return []
    children: dict[int, list[ProcessRecord]] = {}
    for r in rows:
        children.setdefault(r.ppid, []).append(r)
    victims: list[ProcessRecord] = []
    seen = {root_pid}
    queue = [root]
    while queue:
        current = queue.pop(0)
        victims.append(current)
        for child in children.get(current.pid, ()):
            if child.pid in seen or not is_genuine_child(child, current):
                continue
            seen.add(child.pid)
            queue.append(child)
    victims.reverse()
    return victims


def windows_process_created(pid: int) -> float | None:
    """Creation time of ``pid`` right now, or None if it cannot be read."""
    try:
        import psutil
        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def windows_ppid_map() -> dict[int, int] | None:
    """``{pid: recorded ParentProcessId}`` for every process, one Toolhelp32 snapshot.

    One syscall, no creation times: the walk asks for times only along the
    candidate chain. None when no snapshot could be taken.
    """
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x2
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID_HANDLE_VALUE:
            return None
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            out: dict[int, int] = {}
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                out[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
            return out
        finally:
            kernel32.CloseHandle(snap)
    except Exception:
        return None


def windows_tree_snapshot(root_pid: int) -> list[ProcessRecord] | None:
    """Rows for the root and everything that CLAIMS to descend from it.

    The claim closure is deliberately unguarded -- it only decides whom to
    ask for a creation time; :func:`process_tree_victims` applies the guard.
    None when no snapshot could be taken or the root is not in it: the
    caller kills nothing rather than guess.
    """
    edges = windows_ppid_map()
    if edges is None or root_pid not in edges:
        return None
    claimed: dict[int, list[int]] = {}
    for pid, ppid in edges.items():
        claimed.setdefault(ppid, []).append(pid)
    order = [root_pid]
    seen = {root_pid}
    i = 0
    while i < len(order):
        for child in claimed.get(order[i], ()):
            if child not in seen:
                seen.add(child)
                order.append(child)
        i += 1
    return [ProcessRecord(pid, edges[pid], windows_process_created(pid)) for pid in order]


def windows_kill_pid(pid: int, created: float | None) -> bool:
    """TerminateProcess ``pid`` only if it is still the process the snapshot saw.

    Never by image name, never a recycled pid: a creation time that no
    longer matches means someone else now wears this pid, and we leave it.
    """
    try:
        import psutil
        p = psutil.Process(pid)
        if not same_process(p.create_time(), created):
            return False
        p.kill()
        return True
    except Exception:
        return False


def _popen_handle(proc: "subprocess.Popen") -> int | None:
    """The real Windows process handle behind ``proc``, or None for a stub.

    Every ``subprocess.Popen`` created on Windows carries ``_handle``; a test
    double does not. Nothing below may touch a pid that has no handle behind
    it -- the pid of a stub can belong to anyone.
    """
    handle = getattr(proc, "_handle", None)
    if handle is None:
        return None
    try:
        return int(handle)
    except (TypeError, ValueError):
        return None


def windows_job_for(proc: "subprocess.Popen", *, kill_on_close: bool = False) -> int | None:
    """Create a job object and put ``proc`` in it. Handle, or None.

    ``BREAKAWAY_OK`` keeps children spawned with ``CREATE_BREAKAWAY_FROM_JOB``
    (the product's detached gateway / watcher spawns) escaping exactly as
    they do outside the job. ``kill_on_close`` is off by default: see the
    block comment above -- a job closed at the end of a successful capture
    must not reap a grandchild the command deliberately left behind.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER), ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(wintypes.ULONG)), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                *((n, ctypes.c_size_t) for n in (
                    "ProcessMemoryLimit", "JobMemoryLimit", "PeakProcessMemoryUsed", "PeakJobMemoryUsed")),
            ]

        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_BREAKAWAY_OK | (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE if kill_on_close else 0)
        ok = kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
        # Popen's own handle names exactly the process we spawned, whatever
        # its pid means by now. No OpenProcess-by-pid fallback: a Popen with
        # no handle is a test stub, and its pid may be a stranger's.
        handle = _popen_handle(proc)
        if not ok or handle is None or not kernel32.AssignProcessToJobObject(job, handle):
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def windows_job_terminate(job: int) -> bool:
    """Kill every process still in ``job`` (by membership, not by pid)."""
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        return bool(kernel32.TerminateJobObject(job, 1))
    except Exception:
        return False


def windows_job_close(job: int | None) -> None:
    """Release our handle; without kill-on-close the members are untouched."""
    if job is None:
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(job)
    except Exception:
        pass


_CREATE_SUSPENDED = 0x00000004


def windows_can_resume() -> bool:
    """Whether we can thaw a CREATE_SUSPENDED child (psutil's NtResumeProcess)."""
    try:
        import psutil
        return callable(getattr(psutil.Process, "resume", None))
    except Exception:
        return False


def windows_resume(pid: int) -> bool:
    try:
        import psutil
        psutil.Process(pid).resume()
        return True
    except Exception:
        return False


def windows_suspended_spawn_flag() -> int:
    """``CREATE_SUSPENDED`` when the child can be thawed afterwards, else 0.

    OR this into a spawn's ``creationflags`` and hand the Popen to
    :func:`windows_tree_capture` with ``suspended=True`` before touching it.
    A child left frozen would sit out its caller's whole timeout, so the flag
    is only offered when the thaw is known to be available.
    """
    return _CREATE_SUSPENDED if IS_WINDOWS and windows_can_resume() else 0


def windows_tree_capture(proc: "subprocess.Popen", suspended: bool = False) -> WindowsProcessTree:
    """Pin the child's identity and job membership while it is alive.

    With ``suspended`` the child was created frozen: it joins the job and has
    its creation time read before its first instruction, so nothing it will
    ever spawn can predate the job. It is thawed here; if that fails it is
    killed rather than left frozen for the whole timeout.

    A Popen with no process handle behind it (a test double) gets an empty
    tree and is not touched: its pid is nobody we spawned.
    """
    if _popen_handle(proc) is None:
        return WindowsProcessTree()
    tree = WindowsProcessTree(job=windows_job_for(proc), root_created=windows_process_created(proc.pid))
    if suspended and not windows_resume(proc.pid):
        try:
            proc.kill()
        except Exception:
            pass
    return tree


def windows_kill_process_tree(pid: int, *, root_created: float | None = None) -> list[int]:
    """Guarded ppid walk from a bare ``pid``; returns the pids it terminated.

    ``root_created`` pins the root's identity (epoch seconds, as
    :func:`windows_process_created` reads it); a root that no longer matches
    -- or that has exited, or whose creation time cannot be read -- kills
    nothing. Without it the snapshot's own reading of the root is the
    identity every victim is re-checked against, and the CALLER owns the
    question of whether ``pid`` still means what it did.
    """
    snapshot = windows_tree_snapshot(pid)
    if snapshot is None:
        return []
    killed: list[int] = []
    for victim in process_tree_victims(pid, snapshot, root_created=root_created):
        if windows_kill_pid(victim.pid, victim.created):
            killed.append(victim.pid)
    return killed


def windows_kill_popen_tree(proc: "subprocess.Popen", tree: WindowsProcessTree | None = None) -> list[int]:
    """Kill a Popen's tree: by job membership when we have one, else the guarded walk.

    Returns the pids terminated by the walk (the job path reports none: it
    kills by membership and never learns pids). A root that has exited and
    was in no job of ours is the 2026-09-17 shape exactly -- every
    ParentProcessId edge below it is unprovable -- so that kills nothing.
    """
    if tree is not None and tree.job is not None and windows_job_terminate(tree.job):
        return []
    if proc.poll() is not None:
        return []
    root_created = tree.root_created if tree is not None else None
    return windows_kill_process_tree(proc.pid, root_created=root_created)


__all__ += [
    "ProcessRecord", "WindowsProcessTree", "process_tree_victims", "is_genuine_child", "same_process",
    "windows_tree_snapshot", "windows_process_created", "windows_kill_process_tree",
    "windows_kill_popen_tree", "windows_tree_capture", "windows_job_for", "windows_job_terminate",
    "windows_job_close", "windows_suspended_spawn_flag",
]
