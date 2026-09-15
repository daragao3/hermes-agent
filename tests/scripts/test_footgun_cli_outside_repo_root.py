"""``check-windows-footguns.py`` must accept a path OUTSIDE ``REPO_ROOT``.

Why this exists. The documented pre-merge step is "copy every ``.py`` that
landed upstream since your base into a temp tree and scan it with your
widened scanner".  Until 2026-09-15 the CLI could not do that:
``should_scan_file`` called ``path.relative_to(REPO_ROOT)`` unconditionally,
which raises ``ValueError`` for any path not under the repo, so the scan died
with a traceback before reading a byte -- exit 1 with ZERO findings, which is
indistinguishable from "one footgun found" to a caller that only checks the
exit code.  The 2026-09-15 session worked around it by importing the module
and calling ``scan_file`` directly (loops record
``footgun-posix-symbol-rules-20260915``, its STILL OPEN item).

The only consumer of the relative path in ``should_scan_file`` is the
``EXCLUDED_FILES`` self-exclusion, which by construction can never match a
path outside the repo.  So the fix treats such a path as scannable and the
finding printer falls back to the absolute path.  These tests drive
``main()`` in-process -- the same entry the CLI uses -- rather than
``scan_file``, because ``scan_file`` was never the broken layer.

Every sample line below that spells a POSIX symbol carries its own
``# windows-footgun: ok`` marker: suppression is per-line, and the scanner's
own ``--all`` gate reads this file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = REPO_ROOT / "scripts" / "check-windows-footguns.py"

# A one-line footgun the chown rule flags; the guard-hint prose is kept OUT
# of the planted line so nothing but the rule decides the verdict.
PLANTED_LINE = 'os.chown("x", 0, 0)\n'  # windows-footgun: ok -- probe text, not a call


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


@pytest.fixture
def outside_dir(tmp_path):
    """A directory that is provably NOT under REPO_ROOT.

    ``tmp_path`` lives under the system temp dir on every platform this runs
    on, but the whole point of the test is the "outside" property, so assert
    it rather than assume it -- a pytest ``--basetemp`` inside the repo would
    otherwise turn every test here into a vacuous green.
    """
    assert not tmp_path.resolve().is_relative_to(REPO_ROOT), (
        f"{tmp_path} is under REPO_ROOT; this test needs an outside path"
    )
    return tmp_path


def test_should_scan_file_accepts_a_path_outside_repo_root(linter, outside_dir):
    probe = outside_dir / "probe.py"
    probe.write_text("x = 1\n", encoding="utf-8")
    # Before the fix this raised ValueError from Path.relative_to.
    assert linter.should_scan_file(probe.resolve()) is True


def test_cli_scans_an_outside_file_and_reports_the_planted_footgun(
    linter, outside_dir, capsys
):
    probe = outside_dir / "planted.py"
    probe.write_text("import os\n" + PLANTED_LINE, encoding="utf-8")

    rc = linter.main([str(probe)])

    captured = capsys.readouterr()
    assert rc == 1
    # Exactly ONE finding, on line 2 -- not "exit 1 because the scan died".
    assert "1 Windows footgun(s) found across 1 file(s) scanned" in captured.err
    assert ":2: [bare os.chown" in captured.out  # windows-footgun: ok -- rule name in an assertion
    assert "Traceback" not in captured.err
    # Outside the repo there is no relative form; the printer names the
    # absolute path so the finding is still locatable.
    assert probe.resolve().as_posix() in captured.out


def test_cli_scans_a_clean_outside_file_as_one_file_with_zero_findings(
    linter, outside_dir, capsys
):
    probe = outside_dir / "clean.py"
    probe.write_text("import os\nprint(os.getcwd())\n", encoding="utf-8")

    rc = linter.main([str(probe)])

    captured = capsys.readouterr()
    assert rc == 0
    # "1 file(s) scanned", not 0: the file was actually read, not skipped.
    assert "No Windows footguns found (1 file(s) scanned)" in captured.out


def test_in_repo_self_exclusion_still_holds(linter, capsys):
    """CONTROL: the scanner still refuses to scan itself when named explicitly.

    The self-exclusion is the ONLY reason ``should_scan_file`` needs the
    relative path, so the guard must not have loosened it: the scanner
    mentions every pattern it detects, and scanning it yields findings on
    nearly every rule line.
    """
    assert linter.should_scan_file(LINTER_PATH) is False

    rc = linter.main([str(LINTER_PATH)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "No Windows footguns found (0 file(s) scanned)" in captured.out


def test_repo_relative_returns_none_outside_and_posix_string_inside(linter, outside_dir):
    assert linter.repo_relative(outside_dir / "x.py") is None
    assert linter.repo_relative(LINTER_PATH) == "scripts/check-windows-footguns.py"
