#!/usr/bin/env python3
"""
Grep-based checker for Windows cross-platform footguns.

Flags common patterns that break silently on Windows. Run before PRs —
cheap, fast, catches regressions in a codebase that runs on three OSes.

Usage:
    # Scan staged changes (default when run from a git checkout)
    python scripts/check-windows-footguns.py

    # Scan the full tree (full-repo audit)
    python scripts/check-windows-footguns.py --all

    # Scan a specific file or directory
    python scripts/check-windows-footguns.py path/to/file.py path/to/dir/

    # Scan only modified files vs. main
    python scripts/check-windows-footguns.py --diff main

Exit status:
    0 — no Windows footguns found (or all matches suppressed)
    1 — at least one unsuppressed match

Suppress an intentional use (e.g. tests or platform-gated code) with:
    os.kill(pid, 0)  # windows-footgun: ok — only called on POSIX
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

SUPPRESS_MARKER = re.compile(r"#\s*windows-footgun\s*:\s*ok\b", re.IGNORECASE)

# Line-level guard hints. If a line contains any of these tokens, we assume
# the programmer wrote the line in full awareness of the Windows pitfall —
# e.g. `if hasattr(os, 'setsid'): ... os.setsid()`, or the classic
# `getattr(signal, 'SIGKILL', signal.SIGTERM)`, or `shutil.which("wmic")`.
# False negatives are fine here — the inline `# windows-footgun: ok` marker
# is still the authoritative suppression. This is just to reduce the noise
# floor on obviously-guarded lines so the signal-to-noise stays useful.
GUARD_HINTS = (
    "hasattr(os,",
    "hasattr(signal,",
    "getattr(os,",
    "getattr(signal,",
    "shutil.which(",
    "if platform.system() != \"Windows\"",
    "if platform.system() != 'Windows'",
    "if sys.platform == \"win32\"",
    "if sys.platform != \"win32\"",
    "if sys.platform == 'win32'",
    "if sys.platform != 'win32'",
    "IS_WINDOWS",
    "is_windows",
)

# Dirs we never scan.
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
    "website/build",
    "optional-skills",  # external skills
}

# File globs we never scan (beyond the dirs above).
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".png",
    ".jpg",
    ".gif",
    ".ico",
    ".svg",
    ".mp4",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".lock",
    ".min.js",
    ".min.css",
}

# Files we never scan (self-referential — this script mentions the
# patterns it detects — and the CONTRIBUTING docs that list them).
EXCLUDED_FILES = {
    "scripts/check-windows-footguns.py",
    "CONTRIBUTING.md",
}


@dataclass
class Footgun:
    """A Windows cross-platform footgun pattern."""

    name: str
    pattern: re.Pattern
    message: str
    fix: str
    # If set, matches in files/paths containing any of these substrings are
    # silently ignored (e.g. tests that legitimately exercise the footgun
    # behind a platform guard). Prefer `# windows-footgun: ok` inline
    # suppression over this list; only use path_allowlist for whole files
    # that are inherently tests of the footgun itself.
    path_allowlist: tuple[str, ...] = ()
    # Optional post-match predicate. Takes the re.Match and returns True
    # if the match is a REAL footgun (not a false positive). Use this when
    # the regex can't fully distinguish (e.g. open() where mode may contain
    # "b" for binary, or the line may have `encoding=` elsewhere).
    post_filter: "callable | None" = None
    # Opt-in for encoding-rules whose call can span lines. When set, a match
    # whose call does NOT close on the flagged line is re-checked against the
    # call's FULL paren span: it is dropped only if `encoding=` genuinely
    # appears somewhere in that span. A multi-line call with no encoding=
    # anywhere still reports, so this removes false positives WITHOUT buying
    # any false negative. See _encoding_in_call_span and MULTILINE ENCODING.
    multiline_encoding_aware: bool = False


FOOTGUNS: list[Footgun] = [
    Footgun(
        name="open() without encoding= on text mode",
        multiline_encoding_aware=True,
        # Match builtins.open() specifically — NOT os.open(), .open()
        # method calls (Path.open, tarfile.open, zf.open, webbrowser.open,
        # Image.open, wave.open, etc), or `async def open()` method
        # definitions.  The pattern requires a start-of-identifier boundary
        # before `open(` so `os.open`, `.open`, `def open` are all skipped.
        # Note: Path.open() is ALSO affected by the encoding default, but
        # rather than flagging all `.open(` (huge noise), we require an
        # explicit builtins-style open() call.  Path.open() is rare in the
        # codebase compared to open() and can be audited separately.
        pattern=re.compile(
            r"""(?:^|[\s\(,;=])(?<![.\w])open\s*\(\s*[^,)]+\s*(?:,\s*['"](?P<mode>[^'"]*)['"])?"""
        ),
        message=(
            "open() without an explicit encoding= uses the platform default "
            "(UTF-8 on POSIX, cp1252/mbcs on Windows) — files round-tripped "
            "between hosts get mojibake. Always pass encoding='utf-8' for "
            "text files, or use open(path, 'rb')/'wb' for binary."
        ),
        fix=(
            "open(path, 'r', encoding='utf-8')  # or 'utf-8-sig' if the "
            "file may have a BOM"
        ),
        # Filter: only flag if mode is missing-or-text AND the line doesn't
        # already pass encoding=. Skip binary mode (contains "b").
        post_filter=lambda m, line: (
            "b" not in (m.group("mode") or "")
            and "encoding=" not in line
            and "encoding =" not in line
            # Skip `def open(` and `async def open(` (method definitions)
            and not line.lstrip().startswith("def ")
            and not line.lstrip().startswith("async def ")
            # Skip open(path, **kwargs) patterns — encoding may be in the dict.
            # Too expensive to trace; require the author to set encoding in
            # the dict and trust them (or they can add a # windows-footgun: ok).
            and "**" not in line
        ),
    ),
    Footgun(
        name="os.fdopen() without encoding= on text mode",
        # ruff PLW1514 covers builtins.open/Path.read_text/write_text/
        # Path.open but NOT os.fdopen — a bare text-mode fdopen still
        # decodes/encodes with the locale default (cp1252 on Windows).
        # This is the exact hole the July 2026 encoding sweep kept
        # re-fixing by hand (PRs #56033/#56940/#65565), so gate it here.
        pattern=re.compile(
            r"""(?:os\s*\.\s*)?\bfdopen\s*\(\s*[^,)]+\s*(?:,\s*['"](?P<mode>[^'"]*)['"])?"""
        ),
        message=(
            "os.fdopen() without an explicit encoding= uses the platform "
            "default (cp1252/mbcs on Windows) in text mode — the same "
            "mojibake class as bare open(). ruff PLW1514 does not cover "
            "fdopen, so this checker is the only gate."
        ),
        fix=(
            "os.fdopen(fd, 'w', encoding='utf-8')  # or mode 'wb' for binary"
        ),
        post_filter=lambda m, line: (
            "b" not in (m.group("mode") or "")
            and "encoding=" not in line
            and "encoding =" not in line
            and "**" not in line
        ),
    ),
    Footgun(
        name="os.kill(pid, 0)",
        pattern=re.compile(r"\bos\.kill\s*\(\s*[^,]+,\s*0\s*\)"),
        message=(
            "os.kill(pid, 0) is NOT a no-op on Windows — it sends "
            "CTRL_C_EVENT to the target's console process group, "
            "hard-killing the target and potentially unrelated siblings. "
            "See bpo-14484."
        ),
        fix=(
            "Use psutil.pid_exists(pid) (psutil is a core dependency). "
            "Or gateway.status._pid_exists(pid) for the hermes wrapper "
            "with a stdlib fallback."
        ),
    ),
    Footgun(
        name="bare os.setsid",
        pattern=re.compile(r"(?<!hasattr\()\bos\.setsid\b"),
        message=(
            "os.setsid does not exist on Windows and raises "
            "AttributeError. Subprocesses that need detachment on "
            "Windows use creationflags instead."
        ),
        fix=(
            "if platform.system() != 'Windows':\n"
            "    kwargs['preexec_fn'] = os.setsid\n"
            "else:\n"
            "    kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP"
        ),
    ),
    Footgun(
        name="bare os.killpg",
        pattern=re.compile(r"\bos\.killpg\b"),
        message="os.killpg does not exist on Windows.",
        fix=(
            "Use psutil for cross-platform process-tree kill:\n"
            "  p = psutil.Process(pid)\n"
            "  for c in p.children(recursive=True): c.kill()\n"
            "  p.kill()"
        ),
    ),
    Footgun(
        name="bare os.getuid / os.geteuid / os.getgid",
        pattern=re.compile(r"\bos\.(?:getuid|geteuid|getgid|getegid)\b"),
        message=(
            "os.getuid / os.geteuid / os.getgid do not exist on Windows "
            "and raise AttributeError at import time if referenced."
        ),
        fix=(
            "Use getpass.getuser() for the username, or gate with "
            "hasattr(os, 'getuid')."
        ),
    ),
    Footgun(
        name="bare os.fork",
        pattern=re.compile(r"(?<!hasattr\()\bos\.fork\s*\("),
        message="os.fork does not exist on Windows.",
        fix=(
            "Use subprocess.Popen for daemonization, or guard with "
            "hasattr(os, 'fork') and a Windows fallback path."
        ),
    ),
    Footgun(
        name="bare os.chown / os.lchown / os.fchown / os.chroot",
        pattern=re.compile(r"\bos\.(?:chown|lchown|fchown|chroot)\b"),
        message=(
            "os.chown / os.lchown / os.fchown / os.chroot do not exist on "
            "Windows and raise AttributeError at ATTRIBUTE-ACCESS time. "
            "try/except PermissionError -- or even OSError -- does NOT "
            "catch that, since AttributeError is not an OSError subclass, "
            "so the usual best-effort-chown idiom still crashes. "
            "Container-only code counts: its unit tests run on dev/CI hosts."
        ),
        fix=(
            "Guard the attribute, not the errno:\n"
            "    if hasattr(os, 'chown'):\n"
            "        os.chown(path, uid, gid)\n"
            "or return early off POSIX (if os.name != 'posix': return).\n"
            "Adding AttributeError to the except clause also works but "
            "swallows real typos; prefer the explicit guard."
        ),
    ),
    Footgun(
        name="bare os.mkfifo",
        pattern=re.compile(r"\bos\.mkfifo\b"),
        message=(
            "os.mkfifo does not exist on Windows and raises AttributeError. "
            "Windows has no POSIX FIFOs (named pipes are a different API), "
            "so there is no drop-in replacement -- the call site has to be "
            "skipped or branched on Windows."
        ),
        fix=(
            "Gate with hasattr(os, 'mkfifo'), or return early off POSIX. "
            "For a test that inherently needs a FIFO, skip the module on "
            "Windows: pytestmark = pytest.mark.skipif(os.name != 'posix', ...)"
        ),
    ),
    Footgun(
        name="bare os.getpgid / os.getpgrp / os.setpgid",
        pattern=re.compile(r"\bos\.(?:getpgid|getpgrp|setpgid)\b"),
        message=(
            "os.getpgid / os.getpgrp / os.setpgid do not exist on Windows "
            "and raise AttributeError at attribute access. Process groups "
            "are a POSIX concept; the usual os.killpg(os.getpgid(pid), sig) "
            "tree-kill idiom crashes on Windows before killpg is reached."
        ),
        fix=(
            "Gate the whole process-group branch on the platform:\n"
            "    if hasattr(os, 'getpgid'):\n"
            "        os.killpg(os.getpgid(pid), sig)\n"
            "    else:\n"
            "        ...psutil tree kill / CREATE_NEW_PROCESS_GROUP...\n"
            "or return early off POSIX (if os.name != 'posix': return)."
        ),
    ),
    Footgun(
        name="bare os.fchmod",
        pattern=re.compile(r"\bos\.fchmod\b"),
        message=(
            "os.fchmod does not exist on Windows and raises AttributeError "
            "at attribute access; except OSError does not catch it. "
            "os.chmod exists on every platform, so the fd-based form buys "
            "nothing portable."
        ),
        fix=(
            "Use os.chmod(path, mode) on the path (after close, or on the "
            "still-open file's name), or gate with hasattr(os, 'fchmod')."
        ),
    ),
    Footgun(
        name="bare os.pread / os.pwrite",
        pattern=re.compile(r"\b(?:os\.pread|os\.pwrite)\b"),
        message=(
            "os.pread / os.pwrite do not exist on Windows and raise "
            "AttributeError at attribute access."
        ),
        fix=(
            "Use os.lseek(fd, offset, os.SEEK_SET) followed by os.read / "
            "os.write, or gate with hasattr(os, 'pread') and fall back."
        ),
    ),
    Footgun(
        name="bare os.O_NONBLOCK",
        pattern=re.compile(r"\bos\.O_NONBLOCK\b"),
        message=(
            "os.O_NONBLOCK does not exist on Windows (nor does fcntl), "
            "so referencing it raises AttributeError. Non-blocking "
            "reads of a pipe/tty fd have no drop-in Windows equivalent."
        ),
        fix=(
            "Branch on the platform: gate the fcntl/O_NONBLOCK path with "
            "if os.name == 'posix' (or hasattr(os, 'O_NONBLOCK')) and use a "
            "reader thread or msvcrt/overlapped I/O on Windows."
        ),
    ),
    Footgun(
        name="bare os.sysconf / os.getloadavg / os.uname / os.sched_getaffinity",
        pattern=re.compile(
            r"\bos\.(?:sysconf|sysconf_names|getloadavg|uname|sched_getaffinity)\b"
        ),
        message=(
            "os.sysconf / os.getloadavg / os.uname / os.sched_getaffinity do "
            "not exist on Windows and raise AttributeError at attribute "
            "access. Each has a portable stdlib or psutil equivalent."
        ),
        fix=(
            "Guard with hasattr(os, 'X') and fall back: platform.uname() for "
            "uname; psutil.getloadavg() / psutil.cpu_percent() for "
            "getloadavg; os.cpu_count() for sched_getaffinity; "
            "psutil.virtual_memory() / os.cpu_count() for the sysconf "
            "page/cpu keys."
        ),
    ),
    Footgun(
        name="bare os.WNOHANG / os.WIFEXITED / os.WIFSIGNALED / os.WEXITSTATUS / os.WTERMSIG",
        pattern=re.compile(
            r"\bos\.(?:WNOHANG|WIFEXITED|WIFSIGNALED|WEXITSTATUS|WTERMSIG|WIFSTOPPED|WSTOPSIG|WCOREDUMP|WUNTRACED)\b"
        ),
        message=(
            "The wait-status macros (os.WNOHANG, os.WIFEXITED, "
            "os.WEXITSTATUS, ...) do not exist on Windows and raise "
            "AttributeError at attribute access. Windows os.waitpid exists "
            "but returns a different status encoding, so the POSIX "
            "reap-and-decode idiom cannot be ported piecemeal."
        ),
        fix=(
            "Prefer subprocess.Popen.poll()/wait()/returncode (portable "
            "status decoding), or psutil.Process.wait(). If a raw pid must "
            "be reaped, gate the whole block on os.name == 'posix'."
        ),
    ),
    Footgun(
        name="bare os.ttyname / os.openpty / os.ptsname / os.login_tty",
        pattern=re.compile(r"\bos\.(?:ttyname|openpty|ptsname|login_tty|forkpty)\b"),
        message=(
            "os.ttyname / os.openpty / os.ptsname / os.login_tty / "
            "os.forkpty do not exist on Windows and raise AttributeError "
            "at attribute access. Windows has no POSIX tty/pty devices."
        ),
        fix=(
            "Gate with hasattr(os, 'ttyname') / hasattr(os, 'openpty') and "
            "fall back (e.g. no tty identity, or a pipe). For a test that "
            "inherently needs a pty, skip the module on Windows: "
            "pytestmark = pytest.mark.skipif(os.name != 'posix', ...)"
        ),
    ),
    Footgun(
        name="bare signal.SIGKILL",
        pattern=re.compile(r"\bsignal\.SIGKILL\b"),
        message=(
            "signal.SIGKILL does not exist on Windows and raises "
            "AttributeError at import time."
        ),
        fix="Use getattr(signal, 'SIGKILL', signal.SIGTERM).",
    ),
    Footgun(
        name="bare signal.SIGHUP / SIGUSR1 / SIGUSR2 / SIGALRM / SIGCHLD / SIGPIPE / SIGQUIT",
        pattern=re.compile(
            r"\bsignal\.(?:SIGHUP|SIGUSR1|SIGUSR2|SIGALRM|SIGCHLD|SIGPIPE|SIGQUIT)\b"
        ),
        message=(
            "These POSIX signals don't exist on Windows; referencing "
            "them raises AttributeError at import time."
        ),
        fix=(
            "Use getattr(signal, 'SIGXXX', None) and check for None "
            "before using, or gate the whole block behind a platform check."
        ),
    ),
    Footgun(
        name="bare signal.alarm / signal.setitimer / signal.pause",
        pattern=re.compile(
            r"\bsignal\.(?:alarm|setitimer|getitimer|pause|sigwait|pthread_kill|pthread_sigmask|siginterrupt|ITIMER_REAL)\b"
        ),
        message=(
            "signal.alarm / signal.setitimer / signal.pause (and the other "
            "POSIX-only signal helpers) do not exist on Windows and raise "
            "AttributeError at attribute access. SIGALRM itself is also "
            "absent, so a timeout built on alarm has no Windows path."
        ),
        fix=(
            "Use a portable timeout: threading.Timer, subprocess timeout=, "
            "or pytest-timeout (method='thread'). If the alarm path must "
            "stay, gate it with getattr(signal, 'alarm', None) and branch."
        ),
    ),
    Footgun(
        name="subprocess shebang script invocation",
        pattern=re.compile(
            r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\(\s*\[\s*['\"]\./"
        ),
        message=(
            "Running a script via './scriptname' doesn't work on Windows — "
            "shebang lines aren't honored. CreateProcessW can't execute "
            "bash/python scripts without an explicit interpreter."
        ),
        fix="Use [sys.executable, 'scriptname.py', ...] explicitly.",
    ),
    Footgun(
        name="wmic invocation without shutil.which guard",
        # Match wmic appearing as a subprocess argument — NOT the
        # shutil.which("wmic") guard pattern itself. Looks for wmic in a
        # list or as first arg of subprocess.run/Popen.
        pattern=re.compile(
            r"""(?:subprocess\.\w+\s*\(\s*\[\s*['"]wmic['"]|['"]wmic\.exe['"])"""
        ),
        message=(
            "wmic was removed in Windows 10 21H1 and later. Always "
            "gate with shutil.which('wmic') and fall back to "
            "PowerShell (Get-CimInstance Win32_Process)."
        ),
        fix=(
            "if shutil.which('wmic'):\n"
            "    ... wmic path ...\n"
            "else:\n"
            "    subprocess.run(['powershell', '-NoProfile', '-Command',\n"
            "                    'Get-CimInstance Win32_Process | ...'])"
        ),
    ),
    Footgun(
        name="hardcoded ~/Desktop (OneDrive trap)",
        pattern=re.compile(
            r"""['"](?:~|~/|[A-Z]:[/\\]Users[/\\][^/\\'"]+[/\\])Desktop\b"""
        ),
        message=(
            "When OneDrive Backup is enabled on Windows, the real Desktop "
            "is at %USERPROFILE%\\OneDrive\\Desktop, not %USERPROFILE%\\"
            "Desktop (which exists as an empty husk)."
        ),
        fix=(
            "On Windows, resolve via ctypes + SHGetKnownFolderPath, or "
            "read the Shell Folders registry key, or run PowerShell "
            "[Environment]::GetFolderPath('Desktop')."
        ),
    ),
    Footgun(
        name="asyncio add_signal_handler without try/except",
        pattern=re.compile(r"\.add_signal_handler\s*\("),
        message=(
            "loop.add_signal_handler raises NotImplementedError on "
            "Windows — always wrap in try/except or gate with a "
            "platform check."
        ),
        fix=(
            "try:\n"
            "    loop.add_signal_handler(sig, handler, sig)\n"
            "except NotImplementedError:\n"
            "    pass  # Windows asyncio doesn't support signal handlers"
        ),
    ),
    Footgun(
        name="subprocess text=True without explicit encoding=",
        multiline_encoding_aware=True,
        # Match ``text=True`` (or ``text = True``) anywhere on a line. We
        # rely on the post_filter to (a) skip lines that already pass
        # ``encoding=`` on the same line, and (b) skip false positives like
        # ``def text(self, ...)`` or string literals. ``text=True`` is
        # overwhelmingly a subprocess kwarg, so a bare match + filter has a
        # high signal-to-noise ratio and avoids the complexity of parsing
        # multi-line subprocess calls (which the line-based scanner can't
        # reliably attribute to a single line anyway).
        pattern=re.compile(r"\btext\s*=\s*True\b"),
        message=(
            "subprocess text=True without explicit encoding= decodes "
            "child output with locale.getpreferredencoding() — cp936 "
            "(GBK) on Chinese Windows, cp1252 on Western Windows — "
            "which crashes _readerthread with UnicodeDecodeError on "
            "non-default-codepage bytes. Always pass encoding='utf-8' "
            "(and errors='replace' for Windows-native CLIs that emit "
            "non-UTF-8). See issues #47939, #53428, #57238."
        ),
        fix=(
            "subprocess.run(..., text=True, encoding='utf-8', "
            "errors='replace')\n"
            "Both params are required: encoding alone still crashes on "
            "non-UTF-8 bytes from Windows-native CLIs (tasklist, "
            "schtasks)."
        ),
        post_filter=lambda m, line: (
            # Skip if the same line already specifies encoding=.
            "encoding=" not in line
            and "encoding =" not in line
            # Skip method definitions named ``text`` (def text(self, ...)).
            and not line.lstrip().startswith("def ")
            and not line.lstrip().startswith("async def ")
            # Skip ``text=True`` inside string literals (heuristic: the
            # substring appears between matching quotes that aren't part
            # of an f-string expression). This is imperfect but catches
            # the common case of docstrings mentioning text=True.
            and not _looks_like_string_literal(line, m)
            # Skip lines that are obviously not subprocess calls — e.g.
            # DataFrame.rename(text=True) or similar. We can't know for
            # sure without parsing, so we accept some false negatives by
            # only flagging when ``subprocess`` or a known subprocess-
            # shaped call (run/Popen/call/check_output/check_call/
            # check_output) appears on the same line. This keeps the
            # rule focused on the actual footgun.
            and _is_likely_subprocess_call(line)
        ),
    ),
    Footgun(
        name="bare Path.read_text()/write_text() without encoding=",
        multiline_encoding_aware=True,
        # Match ``.read_text(`` / ``.write_text(`` when the same line does
        # not pass ``encoding=``. A call that wraps is re-checked against its
        # full paren span (multiline_encoding_aware) and dropped only when
        # ``encoding=`` is genuinely in there -- the same filter the open()
        # and subprocess rules use. Until 2026-09-15 this rule instead
        # exempted EVERY multi-line call on shape alone; switching it
        # surfaced 600 wrapped read_text/write_text calls in tests/ and
        # evals/ with no encoding= anywhere, swept in the same change, plus
        # two the old shape test hid outright: ``write_text("def broken(\n")``
        # (a ``(`` inside the string made the line look unclosed) and a
        # 23-line ``write_text(<child script>)`` whose script TEXT mentioned
        # encoding= (the old span walk did not track string state).
        pattern=re.compile(r"\.(read_text|write_text)\s*\("),
        message=(
            "Path.read_text()/write_text() without encoding= uses "
            "locale.getpreferredencoding() — cp936/cp1252 on Windows — "
            "so UTF-8 content (config JSON, session state, skills) "
            "crashes with UnicodeDecodeError or writes mojibake. "
            "See issue #37423 and the #71014 / read_text campaign."
        ),
        fix='path.read_text(encoding="utf-8") / path.write_text(data, encoding="utf-8")',
        post_filter=lambda m, line: (
            "encoding=" not in line
            and "encoding =" not in line
            and not _looks_like_string_literal(line, m)
            # Chained forms like ``read_text()[:4000]`` / ``.splitlines()``
            # close on the line and are caught here; a wrapped call goes
            # through _encoding_in_call_span. AST-level enforcement for the
            # gateway/adapters lives in tests/gateway/test_gateway_utf8_encoding.py.
        ),
    ),
]


# ---------------------------------------------------------------------------
# Line prefilter
#
# scan_file's per-line work (the docstring machine aside) is dominated by three
# things: the pure-Python character walk in _find_unquoted_hash, the GUARD_HINTS
# substring sweep, and one regex search per rule. On this repo that is ~2.1M
# lines x 15 rules, and only ~0.2% of lines can match ANY rule -- so ~99.8% of
# that work is spent proving a line is boring.
#
# So: gate all of it behind a cheap literal test. The literals are DERIVED FROM
# THE RULES THEMSELVES rather than hand-maintained, because a hand-written
# trigger table silently stops matching the rule it guards the moment someone
# edits the pattern -- and a prefilter that wrongly rejects a line is a
# coverage reduction that reports itself as a clean scan.
#
# Soundness. _required_literals(node) returns a set L such that every string
# the node matches contains at least one member of L. The union over all rules
# therefore admits every line any rule could match. Two conditions have to hold
# for that to lift from `code` (what the rules see) to `code_for_scan` (what
# the prefilter sees):
#
#   1. `code` is always a PREFIX of `code_for_scan` -- _strip_code only ever
#      truncates. A match inside a prefix sits at the same offsets in the whole
#      string, so it survives.
#   2. No rule may be anchored at the end ($ / \Z) or use a lookahead, since
#      either can match a prefix but fail once more text follows.
#
# _has_unliftable_anchor enforces (2). If any rule trips it -- or the private
# re parser moves, or a rule yields no guaranteed literal -- the prefilter is
# disabled wholesale and every line is scanned. That fallback is slow, which is
# the correct direction to fail: never silent, never lossy.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import shape differs across CPython versions
    import re._constants as _re_constants
    import re._parser as _re_parser
except ImportError:  # pragma: no cover - CPython < 3.11
    import sre_constants as _re_constants  # type: ignore[no-redef]
    import sre_parse as _re_parser  # type: ignore[no-redef]


def _leading_literals(node) -> set[str] | None:
    """Set P where every string `node` matches STARTS WITH some member of P.

    Stricter than _required_literals (starts-with, not contains), which is
    what lets a caller glue it onto the literal run that precedes the node.
    None means no non-empty prefix can be guaranteed.
    """
    acc = ""
    for op, av in node:
        if op is _re_constants.LITERAL:
            acc += chr(av)
            continue
        sub = None
        if op is _re_constants.BRANCH:
            subs = [_leading_literals(b) for b in av[1]]
            if all(s is not None for s in subs):
                sub = set().union(*subs)
        elif op is _re_constants.SUBPATTERN:
            sub = _leading_literals(av[3])
        elif op in (_re_constants.MAX_REPEAT, _re_constants.MIN_REPEAT):
            if av[0] >= 1:
                sub = _leading_literals(av[2])
        elif op is getattr(_re_constants, "ATOMIC_GROUP", None):
            sub = _leading_literals(av)
        # Anything else (IN / ANY / AT / ASSERT / GROUPREF, or a group that
        # guarantees no prefix) ends the guaranteed prefix here.
        if sub:
            return {acc + x for x in sub}
        return {acc} if acc else None
    return {acc} if acc else None


def _required_literals(node) -> set[str] | None:
    """Set L where every string `node` matches contains some member of L.

    None means "nothing can be guaranteed" -- the caller must not filter.
    """
    best = ""  # longest run of adjacent literals at this level
    run = ""
    alts: list[set[str] | None] = []
    for op, av in node:
        if op is _re_constants.LITERAL:
            run += chr(av)
            if len(run) > len(best):
                best = run
            continue
        # A group that DIRECTLY follows a literal run extends it: every match
        # spells the run and then, contiguously, one of the group's leading
        # literals. Without this, `os\.(?:pread|pwrite)` -- which sre_parse
        # rewrites as `os\.p(?:read|write)` -- could only offer "os.p", a
        # literal that admits every os.path line in the tree.
        if run and op in (
            _re_constants.BRANCH,
            _re_constants.SUBPATTERN,
            getattr(_re_constants, "ATOMIC_GROUP", None),
        ):
            lead = _leading_literals([(op, av)])
            if lead:
                alts.append({run + x for x in lead} if all(lead) else None)
        run = ""
        if op is _re_constants.BRANCH:
            subs = [_required_literals(b) for b in av[1]]
            # Every branch must guarantee something, or the branch as a whole
            # guarantees nothing.
            alts.append(None if any(s is None for s in subs) else set().union(*subs))
        elif op is _re_constants.SUBPATTERN:
            alts.append(_required_literals(av[3]))
        elif op in (_re_constants.MAX_REPEAT, _re_constants.MIN_REPEAT):
            if av[0] >= 1:  # min repeat count; 0 guarantees nothing
                alts.append(_required_literals(av[2]))
        elif op is getattr(_re_constants, "ATOMIC_GROUP", None):
            alts.append(_required_literals(av))
        # IN / ANY / AT / ASSERT / ASSERT_NOT / GROUPREF guarantee no literal.

    candidates = [a for a in alts if a]
    if best:
        candidates.append({best})
    if not candidates:
        return None
    # Any ONE guaranteed requirement is enough, so keep the most selective:
    # the candidate whose weakest member is the longest, then the smallest set.
    # Without this, `\.(read_text|write_text)` would pick the literal run "."
    # -- technically sound, and useless as a filter.
    return max(candidates, key=lambda s: (min(len(x) for x in s), -len(s)))


def _has_unliftable_anchor(node) -> bool:
    """True if the pattern can match a prefix but not the whole string.

    End anchors and lookaheads both do that, and would break the
    prefix-to-superstring step the prefilter relies on.
    """
    end_ats = {
        getattr(_re_constants, n)
        for n in ("AT_END", "AT_END_STRING")
        if hasattr(_re_constants, n)
    }
    for op, av in node:
        if op is _re_constants.AT and av in end_ats:
            return True
        if op is _re_constants.ASSERT:  # lookahead (ASSERT_NOT too, below)
            if av[0] > 0 or _has_unliftable_anchor(av[1]):
                return True
        elif op is _re_constants.ASSERT_NOT:
            if av[0] > 0 or _has_unliftable_anchor(av[1]):
                return True
        elif op is _re_constants.BRANCH:
            if any(_has_unliftable_anchor(b) for b in av[1]):
                return True
        elif op is _re_constants.SUBPATTERN:
            if _has_unliftable_anchor(av[3]):
                return True
        elif op in (_re_constants.MAX_REPEAT, _re_constants.MIN_REPEAT):
            if _has_unliftable_anchor(av[2]):
                return True
    return False


def build_prefilter(footguns: "list[Footgun]") -> tuple[str, ...]:
    """Literals such that any line matching any rule contains one of them.

    Returns () when no sound prefilter can be derived, meaning "scan every
    line" -- correct but slow.
    """
    try:
        literals: set[str] = set()
        for fg in footguns:
            if fg.pattern.flags & re.IGNORECASE:
                return ()  # a literal test would have to be case-folded too
            parsed = _re_parser.parse(fg.pattern.pattern, fg.pattern.flags)
            if _has_unliftable_anchor(parsed):
                return ()
            got = _required_literals(parsed)
            if not got:
                return ()
            literals |= got
    except Exception:  # pragma: no cover - private re API moved
        return ()
    # Drop any literal that contains another: a line holding the longer one
    # holds the shorter, so the shorter already admits it. Pure speed, no
    # change to what is admitted.
    return tuple(
        sorted(s for s in literals if not any(o != s and o in s for o in literals))
    )


PREFILTER: tuple[str, ...] = build_prefilter(FOOTGUNS)


def repo_relative(path: Path) -> str | None:
    """POSIX-style path of ``path`` relative to ``REPO_ROOT``, or ``None``
    when it lives outside the repo.

    Paths outside the repo are legitimate CLI input -- the documented
    pre-merge step scans upstream ``.py`` files copied into a temp tree with
    the widened scanner -- and ``Path.relative_to`` raises ``ValueError`` on
    them rather than returning anything.  Only the self-exclusion below and
    the finding printer need the relative form, so callers fall back to the
    absolute path when this returns ``None``.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None


def should_scan_file(path: Path) -> bool:
    """Return True if this file is in scope for the checker."""
    # Skip the excluded dirs
    parts = set(path.parts)
    if parts & EXCLUDED_DIRS:
        return False
    # Skip excluded suffixes
    for suffix in EXCLUDED_SUFFIXES:
        if str(path).endswith(suffix):
            return False
    # Skip self and docs that intentionally mention the patterns.  A path
    # outside the repo can never be one of them, so it stays scannable.
    rel = repo_relative(path)
    if rel is not None and rel in EXCLUDED_FILES:
        return False
    # Only scan text files (rough heuristic — .py, .md, .sh, .ps1, .yaml, etc.)
    if path.suffix in {".py", ".pyw", ".pyi"}:
        return True
    # Other file types are read but only Python-specific patterns would match;
    # that's fine and cheap to skip.
    return False


def iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_file():
            if should_scan_file(p):
                yield p
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                # prune excluded dirs in-place for speed
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
                for fname in files:
                    fpath = Path(root) / fname
                    if should_scan_file(fpath):
                        yield fpath


def _strip_code(line: str) -> str:
    """Return just the code portion of a line — strip trailing comments and
    skip lines that are entirely inside a string literal or comment.

    Heuristic only (we don't parse Python); good enough to avoid flagging
    our own `# ``os.kill(pid, 0)`` is NOT a no-op` docstring-style comments.
    """
    stripped = line.lstrip()
    # Line starts with # — entirely a comment.
    if stripped.startswith("#"):
        return ""
    # Remove trailing "# ..." inline comment. Naive — doesn't handle `#`
    # inside strings — but on balance reduces noise far more than it adds.
    hash_idx = _find_unquoted_hash(line)
    if hash_idx is not None:
        return line[:hash_idx]
    return line


def _find_unquoted_hash(line: str) -> int | None:
    """Index of the first `#` not inside a single/double/triple-quoted string.

    Simple state machine — good enough for the 99% case of "code, then
    optional trailing comment."
    """
    i = 0
    n = len(line)
    in_s = False  # single-quote string
    in_d = False  # double-quote string
    while i < n:
        c = line[i]
        if c == "\\" and (in_s or in_d) and i + 1 < n:
            i += 2
            continue
        if not in_d and c == "'":
            in_s = not in_s
        elif not in_s and c == '"':
            in_d = not in_d
        elif c == "#" and not in_s and not in_d:
            return i
        i += 1
    return None


# Subprocess method names that accept ``text=`` and are affected by the
# encoding-default footgun. Used by ``_is_likely_subprocess_call`` below to
# keep the ``text=True`` rule focused on subprocess calls (and avoid flagging
# unrelated APIs that happen to accept a ``text`` kwarg).
_SUBPROCESS_METHODS = (
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_output",
    "subprocess.check_call",
    "_sp.run",            # common alias
    "_sp.Popen",
    "_sp.check_output",
    "_sp.check_call",
    "_sp.call",
    ".run(",              # bare .run( — usually subprocess.run
    ".Popen(",
    ".check_output(",
    ".check_call(",
    ".call(",
)


def _is_likely_subprocess_call(line: str) -> bool:
    """Heuristic: does this line look like a subprocess invocation?

    The ``text=True`` footgun rule only fires when the matched line also
    contains a subprocess-shaped call site. This avoids false positives on
    unrelated APIs that accept a ``text`` kwarg (e.g. DataFrame.rename,
    custom library calls). Multi-line calls where the ``subprocess.X(``
    prefix is on a previous line won't be flagged — that's an acceptable
    false negative for a line-based scanner.
    """
    return any(token in line for token in _SUBPROCESS_METHODS)


def _call_closes_on_line(line: str, open_paren_end: int) -> bool:
    """True when the call whose ``(`` sits at ``open_paren_end - 1`` closes
    on this same line (naive paren-balance walk -- a ``(`` inside a string
    counts, so ``write_text("def broken(\n")`` reads as unclosed). Used only
    to decide whether a match needs the span walk in
    ``_encoding_in_call_span``; it is NOT a filter on its own. It was one for
    the read_text rule until 2026-09-15, which exempted every wrapped call on
    shape alone and hid a 600-site backlog plus two footguns outright."""
    depth = 1
    for ch in line[open_paren_end:]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return True
    return False


# ---------------------------------------------------------------------------
# MULTILINE ENCODING
#
# The encoding rules are line-based, but `open(...)` / `subprocess.run(...)`
# calls routinely wrap, and a correctly-written call can carry its
# `encoding="utf-8"` on a continuation line. Flagging those is a false
# positive; the repo carried four, all resolved by hand with suppression
# markers.
#
# The tempting fix -- give these rules the `_call_closes_on_line` filter the
# read_text rule then had, i.e. skip every multi-line call -- was
# MEASURED AND REJECTED. A/B of both scanners over the pre-sweep tree
# (9c5250323c, 2996 findings / 6651 files) lost exactly six findings: two
# false positives, and FOUR GENUINE FOOTGUNS -- the very calls the tests/evals
# encoding sweep then had to find and fix. A blanket multi-line skip on a
# blocking gate buys two false positives at the price of four real bugs.
#
# So: only skip a multi-line call when `encoding=` is actually THERE. The walk
# below is bounded and runs only for a match that does not close on its own
# line -- a few dozen sites in the whole tree -- so it costs nothing against
# the per-line prefilter that already rejects ~99.8% of lines.
# ---------------------------------------------------------------------------

# Upper bound on continuation lines inspected for one call. Above the widest
# real call site (the widest in-repo, measured 2026-09-15, is a 76-line
# ``write_text(textwrap.dedent("""<child script>"""), encoding="utf-8")`` in
# tests/tools/test_mcp_discovery_cross_process.py -- the 40-line bound this
# started with reported that correct call); the bound exists so a runaway
# unbalanced-paren walk cannot read to end of file on every match. A call
# wider than this is reported and needs a `# windows-footgun: ok` marker.
_MAX_CALL_SPAN_LINES = 200


def _encoding_in_call_span(
    lines: list[str], start_idx: int, open_paren_end: int
) -> bool:
    """Does ``encoding=`` appear anywhere in this call's full paren span?

    ``lines`` is the file's raw lines, ``start_idx`` the 0-based index of the
    flagged line, and ``open_paren_end`` an offset on that line that sits at
    paren depth 1 inside the call. Walks forward balancing parens until the
    call closes, and reports whether any line of the span passes ``encoding=``.

    The walk tracks string-literal state ACROSS lines (single, double and
    triple quotes, with backslash escapes), so a ``)`` inside a string
    argument cannot close the span early and a ``#`` inside one is not a
    comment. Measured 2026-09-15 on the read_text sweep: three correctly
    written ``write_text(<shell script>, encoding="utf-8")`` calls were
    reported because a ``case ... )`` in the script text closed the walk
    before the kwarg line. Comments are still dropped, so explanatory prose
    that merely mentions ``encoding=`` cannot suppress a real finding, and
    ``encoding=`` INSIDE a string literal does not count either.

    Returns False if the call does not close within ``_MAX_CALL_SPAN_LINES``
    -- an unterminated walk is reported as "no encoding found", which keeps
    the finding rather than silently dropping it.
    """
    depth = 1
    quote = ""  # "", "'", '"', "'''" or '"""' while inside a string literal
    segment = lines[start_idx][open_paren_end:]
    for offset in range(_MAX_CALL_SPAN_LINES):
        idx = start_idx + offset
        if idx >= len(lines):
            return False
        if offset:
            segment = lines[idx]
        code_chars: list[str] = []
        i = 0
        n = len(segment)
        while i < n:
            ch = segment[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if segment.startswith(quote, i):
                    i += len(quote)
                    quote = ""
                    continue
                i += 1
                continue
            if ch in "\"'":
                quote = ch * 3 if segment.startswith(ch * 3, i) else ch
                i += len(quote)
                continue
            if ch == "#":
                break  # trailing comment: rest of the line is prose
            code_chars.append(ch)
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    code = "".join(code_chars)
                    return "encoding=" in code or "encoding =" in code
            i += 1
        code = "".join(code_chars)
        if "encoding=" in code or "encoding =" in code:
            return True
    return False


def _looks_like_string_literal(line: str, match: "re.Match") -> bool:
    """Heuristic: is the ``text=True`` match inside a string literal?

    Catches the common case of docstrings/comments that mention ``text=True``
    as prose. Walks the line tracking single/double quote state and returns
    True if the match start index falls inside a quoted region.
    """
    start = match.start()
    in_s = False
    in_d = False
    i = 0
    while i < start and i < len(line):
        c = line[i]
        if c == "\\" and (in_s or in_d) and i + 1 < len(line):
            i += 2
            continue
        if not in_d and c == "'":
            in_s = not in_s
        elif not in_s and c == '"':
            in_d = not in_d
        i += 1
    return in_s or in_d


def scan_file(path: Path, footguns: list[Footgun]) -> list[tuple[int, str, Footgun]]:
    """Return a list of (line_number, line, footgun) for unsuppressed matches."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    matches: list[tuple[int, str, Footgun]] = []

    # Track whether we're inside a triple-quoted string (docstring/raw block).
    # Simple state machine — handles both ''' and """, toggled by the FIRST
    # triple-quote we see; we don't try to handle nested or f-string cases.
    in_triple: str | None = None  # None, "'''", or '"""'

    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        # Update triple-quote state based on this line's occurrences.
        code_for_scan = line
        if in_triple:
            # We're inside a docstring — skip the whole line's scan.
            # Check if it closes here.
            if in_triple in line:
                # Find the closing delimiter; anything after it is real code.
                after = line.split(in_triple, 1)[1]
                in_triple = None
                code_for_scan = after
            else:
                continue
        # Now check for docstring-open in the (possibly after-triple) portion.
        # Scan for the first unescaped '''/""" in the current code_for_scan.
        for delim in ('"""', "'''"):
            if delim in code_for_scan:
                # Count occurrences — even count means single-line docstring,
                # odd means we've entered a multi-line one.
                count = code_for_scan.count(delim)
                if count % 2 == 1:
                    # Odd — we're now inside the triple-quoted block.
                    # Scan only the part BEFORE the opening delimiter.
                    before = code_for_scan.split(delim, 1)[0]
                    code_for_scan = before
                    in_triple = delim
                    break
                else:
                    # Even — entire docstring fits on one line. Strip it
                    # from the scan text to avoid matching on prose.
                    parts = code_for_scan.split(delim)
                    # Keep the "outside" parts (every other chunk, starting
                    # with index 0) as code, drop the "inside" parts.
                    code_for_scan = "".join(parts[::2])
                    break

        # Cheap literal gate -- see PREFILTER. Everything below this point is
        # per-line work that only matters if some rule could fire, and on a
        # real tree ~99.8% of lines cannot. Placed AFTER the triple-quote
        # state machine so docstring tracking still sees every line, and
        # tested against code_for_scan (not `line`), because the single-line
        # docstring branch above CONCATENATES non-adjacent pieces -- so
        # code_for_scan is not always a substring of the raw line.
        if PREFILTER and not any(s in code_for_scan for s in PREFILTER):
            continue
        if SUPPRESS_MARKER.search(line):
            continue
        # Skip if the line has an obvious guard — e.g. hasattr/getattr/
        # shutil.which or a platform check. False negatives are acceptable;
        # the inline suppression marker is the authoritative override.
        if any(hint in line for hint in GUARD_HINTS):
            continue
        code = _strip_code(code_for_scan)
        if not code.strip():
            continue
        for fg in footguns:
            if fg.path_allowlist and any(s in str(path) for s in fg.path_allowlist):
                continue
            match = fg.pattern.search(code)
            if not match:
                continue
            if fg.post_filter is not None:
                try:
                    if not fg.post_filter(match, line):
                        continue
                except (IndexError, AttributeError):
                    # Post-filter assumed a named group that isn't there — skip.
                    continue
            # A call that wraps may carry its encoding= on a later line. Drop
            # the match only when that kwarg is genuinely in the call's span —
            # never merely because the call is multi-line. See MULTILINE
            # ENCODING above for the measurement that rejected the latter.
            if fg.multiline_encoding_aware and not _call_closes_on_line(
                code, match.end()
            ):
                if _encoding_in_call_span(lines, i - 1, match.end()):
                    continue
            matches.append((i, line.rstrip(), fg))
    return matches


def get_staged_files() -> list[Path]:
    """Return paths staged in the current git index. Empty on non-git trees."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace',
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [REPO_ROOT / f for f in out.splitlines() if f.strip()]


def get_diff_files(ref: str) -> list[Path]:
    """Return paths modified vs. the given git ref."""
    try:
        out = subprocess.check_output(
            ["git", "diff", f"{ref}...HEAD", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace',
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [REPO_ROOT / f for f in out.splitlines() if f.strip()]


# Top-level trees `--all` leaves out. This is a DENYLIST on purpose: the list it
# replaced was an allowlist of eight package names that never grew a
# `tui_gateway/` entry, so a bare `os.kill(pid, 0)` sat in
# tui_gateway/host_supervisor.py indefinitely while CONTRIBUTING.md:696 banned
# the pattern and lint.yml ran this script as a BLOCKING gate. `--all` reported
# "No Windows footguns found" the whole time, and that clean result was not
# evidence of anything: the same checkout, pointed at that one file explicitly,
# exited 1. An allowlist fails toward a false green every time a package is
# added; a denylist fails toward noise, which someone actually notices.
#
# This set is now EMPTY, and keeping it empty is the point. It briefly held
# {"tests", "evals"} to defer a measured backlog -- 2996 findings on
# 2026-09-14 (tests/ 2888, evals/ 108), 2771 of them a bare
# Path.read_text()/write_text() without encoding=. That backlog was worked to
# zero on 2026-09-15: ~2800 mechanical `encoding="utf-8"` insertions, 93
# inline suppression markers (each mutation-checked to be load-bearing), one
# missing platform skip on tests/tools/test_local_setsid_descendant_sweep.py,
# and one real bug -- tests/tools/test_zombie_process_cleanup.py probed
# liveness with `os.kill(pid, 0)` from a module carrying no platform skip, so
# on Windows the probe broadcast Ctrl+C to the target's console process group
# instead of asking a question.
#
# Re-adding an entry here re-opens the same hole the git-derived file list was
# written to close, so tests/scripts/test_windows_footguns_full_repo_scan.py
# pins it empty. `--all` now covers tests/ and evals/, and `--include-tests`
# is retained as a no-op for callers that still pass it.
ALL_SCAN_SKIP_TOP_LEVEL: set[str] = set()


def get_all_scan_files(include_tests: bool = False) -> list[Path]:
    """Return every tracked Python file for `--all`, minus ALL_SCAN_SKIP_TOP_LEVEL.

    Derived from `git ls-files` rather than from a hand-maintained package list,
    so a new first-party package is covered the day it lands instead of whenever
    someone remembers this file exists.

    Using the tracked-file list also preserves the property the old named-root
    walk had by accident: `.claude/worktrees/` (one checkout per agent session)
    and the stale `.venv`s are untracked or ignored, so they are never reached.
    Verified rather than assumed -- `git ls-files` returns zero paths under
    `.claude/worktrees/`, `.venv/` or `site-packages/` on this repo, and
    `.claude/` has no tracked files at all.

    The tradeoff is that a brand-new file that has not been `git add`ed yet is
    invisible to `--all`. That gap is covered by the no-argument default, which
    scans staged files, and by `--diff`.
    """
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "*.py", "*.pyw", "*.pyi"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace',
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # No git (release tarball, CI without .git): fall back to walking the
        # first-party package dirs that exist. Narrower than the git list, but
        # a narrow scan beats no scan -- and it is loud about being narrow.
        print(
            "warning: `git ls-files` unavailable — --all is falling back to a "
            "directory walk and may miss first-party code.",
            file=sys.stderr,
        )
        fallback = [p for p in sorted(REPO_ROOT.iterdir()) if p.is_dir()]
        return [
            p for p in fallback
            if p.name not in EXCLUDED_DIRS
            and not p.name.startswith(".")
            and (include_tests or p.name not in ALL_SCAN_SKIP_TOP_LEVEL)
        ]

    files = []
    for rel in out.split("\0"):
        rel = rel.strip()
        if not rel:
            continue
        if not include_tests and rel.split("/", 1)[0] in ALL_SCAN_SKIP_TOP_LEVEL:
            continue
        files.append(REPO_ROOT / rel)
    return files


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Flag Windows cross-platform footguns in Python code."
    )
    p.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific files/dirs to scan (default: staged changes).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Scan every tracked Python file, tests/ and evals/ included.",
    )
    p.add_argument(
        "--include-tests",
        action="store_true",
        help="No-op since the tests/evals backlog reached zero; --all already "
             "covers them. Kept so existing callers keep working.",
    )
    p.add_argument(
        "--diff",
        metavar="REF",
        help="Scan files changed vs. the given git ref (e.g. --diff main).",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List all known footgun rules and exit.",
    )
    return p.parse_args(argv)


def print_rules() -> None:
    print("Known Windows footguns checked by this script:\n")
    for i, fg in enumerate(FOOTGUNS, start=1):
        print(f"{i:2}. {fg.name}")
        print(f"    {fg.message}")
        print(f"    Fix: {fg.fix}")
        print()


def main(argv: list[str]) -> int:
    # Windows terminals default to cp1252, which can't encode the ✓/✗
    # characters used in the output. Reconfigure streams to UTF-8 so the
    # script works correctly on the very platform it is designed to help.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args(argv)

    if args.list:
        print_rules()
        return 0

    if args.all:
        roots = get_all_scan_files(include_tests=args.include_tests)
    elif args.diff:
        roots = get_diff_files(args.diff)
    elif args.paths:
        roots = [p.resolve() for p in args.paths]
    else:
        # Default: staged changes
        roots = get_staged_files()
        if not roots:
            print(
                "No staged files to scan. Pass --all for a full-repo scan, "
                "--diff <ref> for a range diff, or paths explicitly.",
                file=sys.stderr,
            )
            return 0

    total_matches = 0
    files_scanned = 0
    for path in iter_files(roots):
        files_scanned += 1
        matches = scan_file(path, FOOTGUNS)
        for lineno, line, fg in matches:
            rel = repo_relative(path)
            if rel is None:
                rel = path.as_posix()
            print(f"{rel}:{lineno}: [{fg.name}]")
            print(f"    {line.strip()}")
            print(f"    — {fg.message}")
            print(f"    Fix: {fg.fix.splitlines()[0]}")
            print()
            total_matches += 1

    if total_matches:
        print(
            f"\n✗ {total_matches} Windows footgun(s) found across "
            f"{files_scanned} file(s) scanned.",
            file=sys.stderr,
        )
        print(
            "  If an individual match is a false positive or intentionally "
            "platform-gated, suppress it with `# windows-footgun: ok` on "
            "the same line.\n  Run with --list to see all rules.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✓ No Windows footguns found ({files_scanned} file(s) scanned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
