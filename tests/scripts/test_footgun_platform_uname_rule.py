"""The ``platform.uname()``-family rule in ``scripts/check-windows-footguns.py``.

Added 2026-09-17 after the 0xC000070A hunt: on CPython < 3.13.4 every ``platform.system()`` /
``machine()`` / ``release()`` / ``version()`` / ``node()`` / ``platform()`` on Windows runs two
WMI queries whose helper thread is abandoned after a 100 ms timeout (gh-130727) and later closes
a random live handle of the process. ``hermes_bootstrap`` stubs the query for entry points; the
rule exists because every module in the tree is importable from a bare ``python -c`` child
where the stub was never applied, so a bare call anywhere is a latent crash under host load.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = REPO_ROOT / "scripts" / "check-windows-footguns.py"

RULE = "bare platform.system / platform.uname / platform.machine / platform.release (WMI thread)"  # windows-footgun: ok -- naming the rule, not calling the symbol


def _load_linter_module():
    spec = importlib.util.spec_from_file_location("check_windows_footguns", LINTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_windows_footguns"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def linter():
    return _load_linter_module()


def _rule(linter):
    for fg in linter.FOOTGUNS:
        if fg.name == RULE:
            return fg
    raise AssertionError(f"no rule named {RULE!r}")


# Every uname()-backed read, in the shapes the 2026-09-17 sweep actually found in-tree.
CAUGHT = [
    '    return "uv.exe" if platform.system() == "Windows" else "uv"',  # windows-footgun: ok -- sample line for the rule under test, not a call
    "    system, machine = platform.system(), platform.machine().lower()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "        return platform.release()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "            system=_platform.system(), release=_platform.release(), version=_platform.version(),",  # windows-footgun: ok -- sample line for the rule under test, not a call
    '        "arch": _platform.machine(), "hostname": _platform.node(),',  # windows-footgun: ok -- sample line for the rule under test, not a call
    "    info = platform.uname()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "    label = platform.platform()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "    cpu = platform.processor()",  # windows-footgun: ok -- sample line for the rule under test, not a call
    "    if platform.system () == 'Linux':",  # windows-footgun: ok -- sample line for the rule under test, not a call
]


@pytest.mark.parametrize("line", CAUGHT)
def test_rule_matches_every_uname_backed_read(linter, line):
    assert _rule(linter).pattern.search(line), f"rule no longer matches {line!r}"


# The documented remedies and the reads that never touch uname(): flagging any of these would
# make the rule fight its own fix text.
NOT_CAUGHT = [
    '    if sys.platform == "win32":',
    "    system = host_system()",
    "    arch = host_machine().lower()",
    "    plat = wmi_safe_platform()",
    "    print(plat.release(), plat.machine())",
    "    py = platform.python_version()",
    "    impl = platform.python_implementation()",
    "    mac = platform.mac_ver()[0]",
    "    ver = platform.win32_ver()",
    "    self.platform.system = fake",  # attribute assignment on a test double
    "    system = ctx.platform.system_name()",
]


@pytest.mark.parametrize("line", NOT_CAUGHT)
def test_rule_does_not_overmatch(linter, line):
    assert not _rule(linter).pattern.search(line), f"rule wrongly matches {line!r}"


def test_scan_reports_a_bare_call_and_honours_marker_prose_and_strings(linter, tmp_path):
    """End to end through ``scan_file``: a real call reports; the same spelling inside a
    docstring, a comment, a string literal, or behind the marker does not."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""Mentions platform.system() in prose only."""\n'
        "import platform\n"
        "import sys\n"
        "\n"
        "\n"
        "def a():\n"
        "    # a comment naming platform.machine() is not a call\n"
        "    return platform.system() == 'Windows'\n"  # windows-footgun: ok -- probe source text, executed by no one
        "\n"
        "\n"
        "def b():\n"
        "    return platform.uname()  # windows-footgun: ok -- exercising the stub\n"  # windows-footgun: ok -- probe source text, executed by no one
        "\n"
        "\n"
        "SAMPLE = '    info = platform.uname()'\n"
        "\n"
        "\n"
        "def c():\n"
        "    return sys.platform == 'win32'\n",
        encoding="utf-8",
    )
    findings = linter.scan_file(probe, linter.FOOTGUNS)
    ours = [(ln, fg.name) for ln, _line, fg in findings if fg.name == RULE]
    assert ours == [(8, RULE)], findings


def test_guard_hints_no_longer_whitelist_the_platform_system_spelling(linter):
    """``if platform.system() != "Windows"`` used to be a GUARD_HINTS token (a line carrying it
    was skipped by every rule). It is now a finding itself, so it must not silence the scan."""
    assert not any("platform.system()" in hint for hint in linter.GUARD_HINTS)


def test_no_rule_recommends_the_spelling_this_rule_flags(linter):
    for fg in linter.FOOTGUNS:
        if fg.name == RULE:
            continue
        assert "platform.system()" not in fg.fix and "platform.uname()" not in fg.fix, (
            f"rule {fg.name!r} recommends a spelling the WMI-thread rule flags"
        )
