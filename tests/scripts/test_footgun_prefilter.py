"""Tests for the line prefilter in ``scripts/check-windows-footguns.py``.

The prefilter exists because the full-repo scan took ~113s -- past the 60s
timeout in ``test_windows_footguns_full_repo_scan.py``, so the gate could not
report the five real footguns it had found. It now runs in ~5.6s.

A prefilter is a dangerous kind of optimisation: one that wrongly REJECTS a
line removes a rule's coverage and reports the result as a clean scan. So the
tests here are weighted toward the silent direction:

* the literals must be derived (an empty ``PREFILTER`` means the conservative
  fallback fired -- still correct, but back to ~113s and silently so);
* every rule must contribute a literal, and every rule's own positive example
  must survive the filter;
* the filter must actually reject ordinary lines, or the tests above would
  pass just as happily against a filter that admits everything;
* scanning with the filter forced OFF must produce identical findings;
* and a rule shaped in a way the filter cannot soundly lift -- end-anchored,
  lookahead, IGNORECASE -- must disable the filter wholesale rather than
  quietly dropping that rule's matches.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = REPO_ROOT / "scripts" / "check-windows-footguns.py"


def _load_linter_module():
    # Same shape as tests/scripts/test_footgun_subprocess_encoding.py: register
    # in sys.modules BEFORE exec_module so @dataclass can resolve __module__.
    spec = importlib.util.spec_from_file_location("check_windows_footguns", LINTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_windows_footguns"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def linter():
    return _load_linter_module()


# One positive line per rule. Most are real lines taken from this repo's own
# scan output, not invented ones; the rest are rules with no current in-tree
# hit, written from the rule's pattern.
EXAMPLES = {
    "open() without encoding= on text mode": "    with open(f) as fh:",
    "os.fdopen() without encoding= on text mode": '    with os.fdopen(fd, "w") as f:',
    "os.kill(pid, 0)": "    os.kill(pid, 0)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.setsid": "        preexec_fn=os.setsid,",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.killpg": '    patch("os.killpg") as killpg,',  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.getuid / os.geteuid / os.getgid": "    if os.geteuid() == 0:",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.fork": "    pid = os.fork()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.chown / os.lchown / os.fchown / os.chroot": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        "    os.chown(path, _HERMES_UID, _HERMES_GID)"  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare os.mkfifo": "        os.mkfifo(control, 0o660)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.getpgid / os.getpgrp / os.setpgid": "            pgid = os.getpgid(pid)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.fchmod": "        os.fchmod(fd, 0o600)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.pread / os.pwrite": "            return os.pread(cached[0], length, 0)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.O_NONBLOCK": "                fd = os.open(cache, os.O_WRONLY | os.O_NONBLOCK)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare os.sysconf / os.getloadavg / os.uname / os.sched_getaffinity": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        '        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))'  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare platform.system / platform.uname / platform.machine / platform.release (WMI thread)": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        '        return "uv.exe" if platform.system() == "Windows" else "uv"'  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare os.WNOHANG / os.WIFEXITED / os.WIFSIGNALED / os.WEXITSTATUS / os.WTERMSIG": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        "                    pid, status = os.waitpid(-1, os.WNOHANG)"  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare os.ttyname / os.openpty / os.ptsname / os.login_tty": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        "            name = os.ttyname(fd.fileno())"  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare signal.SIGKILL": "    if sig == signal.SIGKILL:",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "bare signal.SIGHUP / SIGUSR1 / SIGUSR2 / SIGALRM / SIGCHLD / SIGPIPE / SIGQUIT": (  # windows-footgun: ok -- sample line for the rule under test, not a call
        "    assert sent == [(67890, signal.SIGHUP)]"  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "bare signal.alarm / signal.setitimer / signal.pause": "  start=time.monotonic();signal.alarm(2)",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "subprocess shebang script invocation": '    subprocess.run(["./script.sh"])',  # windows-footgun: ok -- sample line for the rule under test, not a call
    "wmic invocation without shutil.which guard": (
        '    subprocess.run(["wmic", "process", "list"])'  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "hardcoded ~/Desktop (OneDrive trap)": (
        r'    assert argv == ["export", r"C:\Users\me\Desktop\out.jsonl"]'  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "asyncio add_signal_handler without try/except": (
        "    loop.add_signal_handler(signal.SIGINT, handler)"  # windows-footgun: ok -- sample line for the rule under test, not a call
    ),
    "subprocess text=True without explicit encoding=": (
        "    result = subprocess.run(argv, capture_output=True, text=True)"
    ),
    "bare Path.read_text()/write_text() without encoding=": "    body = p.read_text()",
}

# Ordinary code carrying none of the prefilter literals.
BORING = [
    "import json",
    "def compute(value, factor):",
    "    return self.value + 1",
    "    items = [1, 2, 3]",
    "    logger.info('done')",
    "class Widget:",
    "    if not path.exists():",
    "        # a comment about nothing in particular",
]


def _rule(linter, name):
    for fg in linter.FOOTGUNS:
        if fg.name == name:
            return fg
    pytest.fail(f"Footgun rule {name!r} not found in FOOTGUNS")


def _admits(linter, line: str) -> bool:
    return any(s in line for s in linter.PREFILTER)


def test_prefilter_was_actually_derived(linter):
    """An empty PREFILTER is the conservative fallback: correct, but it puts
    the scan back over the test's timeout, and nothing else here would fail."""
    assert linter.PREFILTER, (
        "PREFILTER is empty -- build_prefilter fell back to scanning every "
        "line. The scan is still correct but ~20x slower, which is what broke "
        "test_windows_footguns_full_repo_scan in the first place."
    )


def test_every_rule_contributes_a_literal(linter):
    for fg in linter.FOOTGUNS:
        parsed = linter._re_parser.parse(fg.pattern.pattern, fg.pattern.flags)
        assert linter._required_literals(parsed), (
            f"rule {fg.name!r} guarantees no literal, which disables the "
            "prefilter for every rule"
        )


def test_every_rule_has_an_example_here(linter):
    """Keeps the table above honest: a rule added without an example would
    otherwise be silently untested by the admission test."""
    assert sorted(EXAMPLES) == sorted(fg.name for fg in linter.FOOTGUNS)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_prefilter_admits_every_rules_own_positive_example(linter, name):
    line = EXAMPLES[name]
    # Positive control first. Without it, an example that stopped matching its
    # rule would make the admission assertion below vacuous.
    assert _rule(linter, name).pattern.search(line), (
        f"example for {name!r} no longer matches its own rule: {line!r}"
    )
    assert _admits(linter, line), (
        f"prefilter REJECTS a line that rule {name!r} matches: {line!r} -- "
        "this rule's findings would silently disappear"
    )


@pytest.mark.parametrize("line", BORING)
def test_prefilter_rejects_ordinary_lines(linter, line):
    """The must-reject direction. A filter that admitted everything would pass
    every admission test above while saving nothing."""
    assert not _admits(linter, line)


def test_prefilter_does_not_change_findings(tmp_path, linter):
    """Equivalence pin: same file, filter ON vs forced OFF, same findings.

    Proved separately over the whole repo (6,640 files / 2,991 findings,
    identical both ways); this keeps it enforced per-commit on a file that
    exercises every rule at once.
    """
    sample = tmp_path / "sample.py"
    body = "\n".join(EXAMPLES[name] for name in sorted(EXAMPLES))
    sample.write_text(body + "\n", encoding="utf-8")

    with_filter = linter.scan_file(sample, linter.FOOTGUNS)
    saved = linter.PREFILTER
    try:
        linter.PREFILTER = ()
        without_filter = linter.scan_file(sample, linter.FOOTGUNS)
    finally:
        linter.PREFILTER = saved

    # Positive control: a file this dense must produce findings, or "identical"
    # would just mean "both empty".
    assert without_filter, "sample produced no findings at all"
    assert with_filter == without_filter


def _synthetic_rule(linter, pattern: str, flags: int = 0):
    return linter.Footgun(
        name="synthetic",
        pattern=re.compile(pattern, flags),
        message="synthetic",
        fix="synthetic",
    )


@pytest.mark.parametrize(
    "pattern,flags,why",
    [
        (r"\bos\.sync\b$", 0, "end anchor"),
        (r"\bos\.sync\b\Z", 0, "end-of-string anchor"),
        (r"\bos\.sync\b(?=\s*\()", 0, "lookahead"),
        (r"\bos\.sync\b", re.IGNORECASE, "IGNORECASE"),
    ],
)
def test_unliftable_rule_disables_the_prefilter(linter, pattern, flags, why):
    """A rule the filter cannot soundly lift must turn the filter OFF for
    everyone -- slow and complete -- rather than drop its own matches.

    The prefilter tests ``code_for_scan`` while the rules test ``code``, a
    PREFIX of it. That step is only valid for patterns that cannot match a
    prefix and then fail on the longer string; an end anchor or a lookahead
    can do exactly that.
    """
    # Positive control: the real rule set does derive a filter, so a () result
    # below is attributable to the synthetic rule and not to a broken builder.
    assert linter.build_prefilter(linter.FOOTGUNS) != ()
    assert (
        linter.build_prefilter(
            list(linter.FOOTGUNS) + [_synthetic_rule(linter, pattern, flags)]
        )
        == ()
    ), f"{why} did not disable the prefilter"


def test_shorter_literal_absorbs_longer_ones(linter):
    """Minimisation is a speed step only: it may drop a literal only when a
    SHORTER one already admits every line the longer one would."""
    for lit in linter.PREFILTER:
        others = [o for o in linter.PREFILTER if o != lit]
        assert not any(o in lit for o in others), (
            f"{lit!r} contains another prefilter literal and should have been "
            "minimised away"
        )
