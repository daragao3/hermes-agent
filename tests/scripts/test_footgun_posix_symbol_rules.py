"""Tests for the eight POSIX-only-symbol rules added to ``check-windows-footguns.py``
on 2026-09-15 (process groups, fchmod, pread, O_NONBLOCK, host introspection,
wait-status macros, tty/pty, signal timers).

Why these rules exist. ``scripts/check-windows-footguns.py`` is the BLOCKING
gate for POSIX-only symbols (``lint.yml --all``, pre-commit on staged files).
An empirical sweep -- AST-walk every tracked ``.py`` for ``os.X`` / ``signal.X``
attribute nodes and test ``hasattr`` on the Windows interpreter, no hardcoded
list -- found 17 absent symbols with no rule at all. The largest was
``os.getpgid`` at 48 sites: the ``os.killpg`` rule never covered it, so the
usual ``os.killpg(os.getpgid(pid), sig)`` idiom was gated only on its second
half.

The defect shape the rules catch, and the reason every message says so: the
call sites that were real bugs were WRAPPED -- ``except OSError``,
``contextlib.suppress(OSError)``, ``suppress(OSError, ValueError, TypeError)``.
None of those catch the ``AttributeError`` a missing attribute raises, so the
usual best-effort idiom still crashes. A test that only checked "is the call
inside a try block" would have called both fixed sites safe.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = REPO_ROOT / "scripts" / "check-windows-footguns.py"

PGID_RULE = "bare os.getpgid / os.getpgrp / os.setpgid"  # windows-footgun: ok -- naming the rule, not calling the symbol
FCHMOD_RULE = "bare os.fchmod"  # windows-footgun: ok -- naming the rule, not calling the symbol
PREAD_RULE = "bare os.pread / os.pwrite"  # windows-footgun: ok -- naming the rule, not calling the symbol
NONBLOCK_RULE = "bare os.O_NONBLOCK"  # windows-footgun: ok -- naming the rule, not calling the symbol
HOST_RULE = "bare os.sysconf / os.getloadavg / os.uname / os.sched_getaffinity"  # windows-footgun: ok -- naming the rule, not calling the symbol
WAIT_RULE = "bare os.WNOHANG / os.WIFEXITED / os.WIFSIGNALED / os.WEXITSTATUS / os.WTERMSIG"  # windows-footgun: ok -- naming the rule, not calling the symbol
TTY_RULE = "bare os.ttyname / os.openpty / os.ptsname / os.login_tty"  # windows-footgun: ok -- naming the rule, not calling the symbol
TIMER_RULE = "bare signal.alarm / signal.setitimer / signal.pause"  # windows-footgun: ok -- naming the rule, not calling the symbol

NEW_RULES = (
    PGID_RULE, FCHMOD_RULE, PREAD_RULE, NONBLOCK_RULE,
    HOST_RULE, WAIT_RULE, TTY_RULE, TIMER_RULE,
)


def _load_linter_module():
    # Register in sys.modules BEFORE exec_module so @dataclass can resolve
    # __module__ -- same shape as the sibling scanner test modules.
    spec = importlib.util.spec_from_file_location("check_windows_footguns", LINTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_windows_footguns"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def linter():
    return _load_linter_module()


def _rule(linter, name):
    for fg in linter.FOOTGUNS:
        if fg.name == name:
            return fg
    raise AssertionError(f"no rule named {name!r}; rules are "
                         f"{[f.name for f in linter.FOOTGUNS]}")


# Every symbol the rules are meant to catch, in the shape it actually appears
# in this repo (the in-tree lines are quoted where one exists). If a rule stops
# matching one of these, that entry goes red -- a silently-narrowed pattern is
# indistinguishable from a clean tree.
CAUGHT = [
    (PGID_RULE, "            pgid = os.getpgid(pid)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (PGID_RULE, '        monkeypatch.setattr("os.getpgid", lambda pid: 999)'),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (PGID_RULE, "        my_pgid = os.getpgrp()"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (PGID_RULE, "    os.setpgid(0, 0)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (FCHMOD_RULE, "        os.fchmod(fd, 0o600)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (PREAD_RULE, "            return os.pread(cached[0], length, 0)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (PREAD_RULE, "    os.pwrite(fd, data, offset)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (NONBLOCK_RULE, "                fd = os.open(cache, os.O_WRONLY | os.O_NONBLOCK)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (HOST_RULE, '        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))'),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (HOST_RULE, "    page = os.sysconf_names['SC_PAGE_SIZE']"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (HOST_RULE, '        ctx["loadavg_1m"] = os.getloadavg()[0]'),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (HOST_RULE, "    machine = os.uname().machine"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (HOST_RULE, "        return max(1, len(os.sched_getaffinity(0)))"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "                    pid, status = os.waitpid(-1, os.WNOHANG)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "        if os.WIFEXITED(raw):"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "            code = os.WEXITSTATUS(raw)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "        if os.WIFSIGNALED(raw):"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, '            return ("signaled", os.WTERMSIG(raw))'),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "    if os.WIFSTOPPED(status): sig = os.WSTOPSIG(status)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "    dumped = os.WCOREDUMP(status)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (WAIT_RULE, "    os.waitpid(pid, os.WUNTRACED)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TTY_RULE, "            name = os.ttyname(fd.fileno())"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TTY_RULE, "    master, slave = os.openpty()"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TTY_RULE, "    path = os.ptsname(master)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TTY_RULE, "    os.login_tty(slave)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TTY_RULE, "    pid, fd = os.forkpty()"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "  start=time.monotonic();signal.alarm(2)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.setitimer(signal.ITIMER_REAL, 0.5)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    old = signal.getitimer(signal.ITIMER_REAL)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.pause()"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.sigwait({signal.SIGINT})"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.pthread_kill(tid, signal.SIGINT)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (TIMER_RULE, "    signal.siginterrupt(signal.SIGINT, False)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
]


@pytest.mark.parametrize(
    "name,line", CAUGHT, ids=[f"{n.split()[1]}:{i}" for i, (n, _) in enumerate(CAUGHT)]
)
def test_rule_matches_every_symbol_it_claims(linter, name, line):
    assert _rule(linter, name).pattern.search(line), (
        f"rule {name!r} no longer matches {line!r}"
    )


def test_every_symbol_named_in_a_rule_title_has_a_sample(linter):
    """The rule's own name is its contract: each ``os.X`` / ``signal.X`` it
    advertises must have a CAUGHT entry, so narrowing a pattern to drop one
    symbol cannot hide behind a title that still promises it."""
    for name in NEW_RULES:
        advertised = re.findall(r"\b(?:os|signal)\.\w+", name)
        assert advertised, name
        sampled = " ".join(line for n, line in CAUGHT if n == name)
        missing = [sym for sym in advertised if sym not in sampled]
        assert not missing, f"rule {name!r} advertises {missing} but CAUGHT has no sample for them"


# Shapes that must NOT match, so a rule cannot be "fixed" by widening it into
# something that flags every identifier containing the substring. The
# psutil / platform / subprocess spellings are the documented remedies, so a
# rule that flagged them would fight its own fix text.
NOT_CAUGHT = [
    (PGID_RULE, "    pgid = proc.pid  # start_new_session made it a leader"),
    (PGID_RULE, "    self.getpgid_calls.append(pid)"),
    (PGID_RULE, "    kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP"),
    (FCHMOD_RULE, "    os.chmod(tmp_name, mode)"),
    (FCHMOD_RULE, "    self.fchmod_called = True"),
    (PREAD_RULE, "    os.read(fd, length)"),
    (PREAD_RULE, "    os.lseek(fd, offset, os.SEEK_SET)"),
    (PREAD_RULE, "    spread = os.path.join(a, b)"),
    (NONBLOCK_RULE, "    sock.setblocking(False)"),
    (NONBLOCK_RULE, "    NONBLOCK = 1"),
    (HOST_RULE, "    info = platform.uname()"),
    (HOST_RULE, "    load = psutil.getloadavg()"),
    (HOST_RULE, "    cpus = os.cpu_count()"),
    (HOST_RULE, "    self.sysconf = {}"),
    (WAIT_RULE, "    rc = proc.wait(timeout=5)"),
    (WAIT_RULE, "    pid, status = os.waitpid(child, 0)"),  # waitpid itself exists on Windows
    (WAIT_RULE, "    WNOHANG = getattr(os, 'WNOHANG', 1)"),  # the getattr spelling is a GUARD_HINTS token, so no marker needed here
    (TTY_RULE, "    if sys.stdin.isatty():"),
    (TTY_RULE, "    self.ttyname = name"),
    (TIMER_RULE, "    timer = threading.Timer(2.0, on_timeout)"),
    (TIMER_RULE, "    signal.signal(signal.SIGINT, handler)"),
    (TIMER_RULE, "    alarm = self.alarms.pop()"),
]


@pytest.mark.parametrize("name,line", NOT_CAUGHT)
def test_rule_does_not_overmatch(linter, name, line):
    assert not _rule(linter, name).pattern.search(line), (
        f"rule {name!r} wrongly matches {line!r}"
    )


def test_errno_handling_does_not_suppress_the_finding(linter, tmp_path):
    """The two real defects found on 2026-09-15, in one file: each call WAS
    wrapped, in the wrong guard.

    ``agent/proxy_sources/iron_proxy.py`` had ``os.fchmod`` under ``except
    OSError``; ``tools/process_registry.py`` had ``os.sysconf`` under
    ``suppress(OSError, ValueError, TypeError)``. Neither catches the
    ``AttributeError`` a missing attribute raises, so the scanner must still
    report both. This is the regression that makes the rules worth having.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os\n"
        "from contextlib import suppress\n"
        "def f(fd, path):\n"
        "    try:\n"
        "        os.fchmod(fd, 0o600)\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    except OSError:\n"
        "        pass\n"
        "    with suppress(OSError, ValueError, TypeError):\n"
        "        n = os.sysconf('SC_PHYS_PAGES')\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    with suppress(OSError):\n"
        "        return os.pread(fd, 16, 0)\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    try:\n"
        "        return os.getpgid(0)\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    except (ProcessLookupError, PermissionError, OSError):\n"
        "        return None\n",
        encoding="utf-8",
    )
    fired = {fg.name for _lineno, _line, fg in linter.scan_file(probe, linter.FOOTGUNS)}
    assert fired == {FCHMOD_RULE, HOST_RULE, PREAD_RULE, PGID_RULE}, (
        f"an errno-only except suppressed a finding; rules that fired: {fired}"
    )


def test_documented_remedies_clear_the_finding(linter, tmp_path):
    """Each rule's ``fix`` text names an attribute guard or a platform branch.
    Those remedies (plus the marker on the guarded line) must actually silence
    the rule, or the fix text trains people to reach for the marker alone."""
    probe = tmp_path / "guarded.py"
    probe.write_text(
        "import os, signal\n"
        "def f(fd, pid):\n"
        "    if hasattr(os, 'fchmod'):\n"
        "        os.fchmod(fd, 0o600)  # windows-footgun: ok -- guarded above\n"
        "    if hasattr(os, 'getpgid'):\n"
        "        os.killpg(os.getpgid(pid), 9)  # windows-footgun: ok -- guarded above\n"
        "    if os.name == 'posix':\n"
        "        pid, st = os.waitpid(-1, os.WNOHANG)  # windows-footgun: ok -- guarded above\n"
        "    alarm = getattr(signal, 'alarm', None)\n"
        "    cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count()\n",
        encoding="utf-8",
    )
    assert linter.scan_file(probe, linter.FOOTGUNS) == [], (
        "a documented remedy (attribute guard / platform branch) did not clear the finding"
    )


def test_marker_is_the_only_suppressor_on_the_marked_lines(linter, tmp_path):
    """Every marker added in the 2026-09-15 sweep was mutation-checked: strip
    it, rescan, require the line red. This pins the mechanism that makes that
    check meaningful -- a reason that quotes a GUARD_HINTS token would be a
    second, independent suppressor and the marker itself would be inert."""
    probe = tmp_path / "marked.py"
    src = (
        "import os\n"
        "def f(pid):\n"
        "    return os.getpgid(pid)  # windows-footgun: ok -- inside the not-Windows gate above\n"
    )
    probe.write_text(src, encoding="utf-8")
    assert linter.scan_file(probe, linter.FOOTGUNS) == []
    stripped = src.replace("  # windows-footgun: ok -- inside the not-Windows gate above", "")
    probe.write_text(stripped, encoding="utf-8")
    fired = [fg.name for _l, _line, fg in linter.scan_file(probe, linter.FOOTGUNS)]
    assert fired == [PGID_RULE], "with the marker stripped the line must go red -- nothing else suppressed it"


def test_prefilter_literals_are_fully_qualified_symbols(linter):
    """The prefilter literal for a rule like ``os\\.(?:pread|pwrite)`` must be
    ``os.pread`` / ``os.pwrite``, not the hoisted common prefix ``os.p`` --
    sre_parse rewrites the alternation as ``os\\.p(?:read|write)``, and a bare
    ``os.p`` admits every ``os.path`` line in the tree (a silent 3-4x slowdown
    of the gate, never a coverage loss). Pins the run+group extension in
    ``_required_literals``."""
    assert linter.PREFILTER, "prefilter fell back to scan-everything"
    assert "os.p" not in linter.PREFILTER
    assert "os.get" not in linter.PREFILTER
    assert "signal." not in linter.PREFILTER
    for sym in ("os.pread", "os.pwrite", "os.getpgid", "os.getpgrp", "os.sysconf",  # windows-footgun: ok -- symbol names the prefilter must admit, not calls
                "os.WNOHANG", "os.ttyname", "signal.alarm", "os.getuid", "signal.SIGHUP"):  # windows-footgun: ok -- symbol names the prefilter must admit, not calls
        assert any(sym.startswith(lit) or lit.startswith(sym) for lit in linter.PREFILTER), (
            f"{sym} is not admitted by any prefilter literal: {linter.PREFILTER}"
        )


@pytest.mark.parametrize(
    "pattern,unsound_literal,sound_literals",
    [
        # The exact case that motivated the extension.
        (r"\bos\.(?:pread|pwrite)\b", "os.p", {"os.pread", "os.pwrite"}),  # windows-footgun: ok -- regex under test, not a call
        # Optional first char inside the group: `os.xpread` matches, so
        # `os.pread` is NOT guaranteed and the extension must stand down.
        (r"\bos\.(?:x?pread|pwrite)\b", "os.pread", None),  # windows-footgun: ok -- regex under test, not a call
        # Nested groups, common prefix hoisted twice.
        (r"\bos\.(?:get(?:pgid|pgrp)|setpgid)\b", "os.get", {"os.getpgid", "os.getpgrp", "os.setpgid"}),  # windows-footgun: ok -- regex under test, not a call
    ],
)
def test_run_plus_group_extension_is_sound(linter, pattern, unsound_literal, sound_literals):
    parsed = linter._re_parser.parse(pattern, 0)
    got = linter._required_literals(parsed)
    assert got is not None
    assert unsound_literal not in got or sound_literals is None, (pattern, got)
    if sound_literals is not None:
        assert got == sound_literals, (pattern, got)
    else:
        # Whatever was chosen must still admit the tricky match.
        assert any(lit in "os.xpread(" for lit in got), (pattern, got)


@pytest.mark.parametrize(
    "rel",
    [
        "agent/proxy_sources/iron_proxy.py",
        "tools/process_registry.py",
        "hermes_state_dbfile.py",
        "hermes_cli/kanban_db_dispatch.py",
        "tui_gateway/_stdin_recovery.py",
    ],
)
def test_production_sites_stay_clean(linter, rel):
    """Pins the production files triaged on 2026-09-15 against a NEW, unmarked
    POSIX-only call appearing in them. It does NOT pin the guards themselves:
    each flagged line carries a marker, so the scan stays clean whether or not
    the guard above it survives. The behavioural tests for the two guards added
    here are ``tests/test_iron_proxy.py::test_open_private_append_survives_missing_fchmod``
    and ``tests/tools/test_process_registry.py::test_worker_memory_limit_survives_missing_sysconf``."""
    assert linter.scan_file(REPO_ROOT / rel, linter.FOOTGUNS) == []
