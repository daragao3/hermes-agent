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
from typing import IO, Mapping, Optional, Sequence

__all__ = [
    "IS_WINDOWS",
    "resolve_node_command",
    "split_command_line",
    "suppress_platform_ver_console",
    "windows_detach_flags",
    "windows_detach_flags_without_breakaway",
    "windows_hide_flags",
    "windows_detach_popen_kwargs",
    "bounded_git_probe",
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
    timeout — ``taskkill /T /F`` takes the whole tree down so the bounded drain that follows can actually
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

            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:
                os.killpg(pgid, _signal.SIGKILL)  # windows-footgun: ok — inside `if not IS_WINDOWS` gate
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    if IS_WINDOWS:
        # No identity guard on purpose: *proc* is our own retained Popen handle, so the PID cannot
        # be recycled while we hold it. The fail-closed ``pid_is_hermes`` guard is for BARE pids.
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=2, check=False,
                           creationflags=windows_hide_flags())
        except Exception:
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
    _popen_kwargs: dict = {"creationflags": windows_hide_flags()} if IS_WINDOWS else {"process_group": 0}
    try:
        proc = subprocess.Popen(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors=errors,
            env=dict(env) if env is not None else None, **_popen_kwargs)
    except Exception:
        return None
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except Exception:
        # Timeout OR any other communicate() failure (torn-down pipe, decode error): tree-kill and
        # drain bounded — leaving it running would leak the suspended-descendant class this guards.
        kill_process_tree(proc)
        try:
            proc.communicate(timeout=1)
        except Exception:
            pass
        return None
    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr)


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
    result = bounded_probe_run(argv, timeout=timeout, env=noninteractive_git_env())
    if result is None or result.returncode != 0:
        return ""
    return (result.stdout or "").strip()



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
    if found and (
        "\\system32\\" in found.lower() or "\\windowsapps\\" in found.lower()
    ):
        return None  # WSL launcher / Store stub — cannot see C:\ paths
    return found


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

    On timeout we still tree-kill (``taskkill /T /F`` on Windows, ``killpg``
    on POSIX) so as not to leak an abandoned process tree. The kill is best
    effort — correctness no longer *depends* on it succeeding, because with
    file-backed stdio there is nothing left to drain and we never wait on the
    child again — but it IS synchronous, and that costs real wall clock.

    **The bound is ``timeout`` plus the cost of the kill, not ``timeout``.**
    On Windows ``_tree_kill`` shells out to ``taskkill`` under its own
    ``timeout=10``, so the worst case is ``timeout + ~10s`` (a shade over the
    cap: aborting the timed-out ``taskkill`` and reaping the direct child costs
    a little more on top). That tail is paid on EVERY timeout, not just when
    the kill fails. Measured on a loaded Windows host, staged against a real
    wedged ``npm install`` with a 5s budget: ``taskkill`` alone took 8.47s and
    10.48s across two probes, for 13.91s and 15.58s end to end (2026-08-11);
    an earlier probe against a wedged ``npm audit`` tree clocked it at 11.6s.
    On POSIX ``killpg`` is a bare syscall, so the tail there is negligible.

    Callers must size their timeouts against ``timeout + 10s`` on Windows —
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
    if IS_WINDOWS:
        popen_kwargs: dict = {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW}
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
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Best effort — we do NOT wait on the child again afterwards, so a
            # kill that fails costs us nothing but a lingering process.
            _tree_kill(proc)
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
        return subprocess.CompletedProcess(
            proc.args, proc.returncode, _read_text(out_f, text=text), _read_text(err_f, text=text),
        )


def _read_text(handle, *, text: bool = True) -> str | bytes:
    """Rewind capture; preserve binary records or apply the existing text decode."""
    handle.seek(0)
    content = handle.read()
    return content.decode("utf-8", errors="replace").replace("\r\n", "\n") if text else content


def _tree_kill(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and its entire descendant tree; never raises.

    Windows: ``taskkill /PID <pid> /T /F`` — the documented primitive for a
    tree-kill, mirroring ``tools.process_registry._terminate_host_pid``. We
    can't use a softer signal: there is no Windows SIGTERM that cascades
    through a process group, and ``/T`` without ``/F`` won't reach a windowless
    child. POSIX: ``killpg(SIGKILL)`` reaches the grandchildren because the
    child was started in its own session (``start_new_session=True``). Either
    way this is best effort: ``run_text_capture`` captures into files, not
    pipes, so its budget holds whether or not the kill lands — the point here
    is only to avoid leaving an abandoned process tree behind.

    Best effort is not free, though. This runs SYNCHRONOUSLY inside
    ``run_text_capture``'s timeout path, so its duration is added to that
    call's bound (see the note there). ``taskkill`` on a live ``npm`` tree has
    been measured at 8.47s, 10.48s and 11.6s on a loaded Windows host, and
    still ~3.5s on a trivial two-process Python tree — the cost scales with the
    tree but is never zero. That is why it carries its own ``timeout=10`` cap,
    and why the caller's real bound is ``timeout + ~10s``. Making the kill
    fire-and-forget would tighten that, but was rejected: detaching it opens a
    PID-reuse race between spawning ``taskkill`` and this ``Popen`` handle
    being released, and ``taskkill /PID`` would then be free to shoot an
    unrelated process that inherited the pid.
    """
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()  # at least reap the direct child
            except OSError:
                pass
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass

__all__ += ["resolve_windows_git_bash", "windows_pipe_readable_bytes", "run_text_capture"]
