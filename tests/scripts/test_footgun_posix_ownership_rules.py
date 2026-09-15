"""Tests for the ``os.chown``/``os.mkfifo`` rules in ``check-windows-footguns.py``.

Why these rules exist, and why the tests are shaped this way.

``scripts/check-windows-footguns.py`` is the designated gate for POSIX-only
symbols (``lint.yml`` runs ``--all`` as BLOCKING, ``.pre-commit-config.yaml``
runs it on staged files). It had rules for ``os.killpg``, ``os.setsid``,
``os.fork``, ``os.getuid``, ``signal.SIGKILL`` and friends -- but NONE for
``os.chown`` or ``os.mkfifo``, so it reported the tree clean while
``hermes_cli/service_manager.py`` carried both, and
``tests/hermes_cli/test_container_boot.py`` failed 6 of 7 on Windows with
``AttributeError: module 'os' has no attribute 'chown'``.

The subtle part, and the reason the message says what it does: every one of
those call sites was already wrapped in ``try/except PermissionError`` (or
``except OSError``). That is the WRONG guard, not a missing one --
``AttributeError`` is raised at attribute-access time and is not an
``OSError`` subclass, so the except clause never sees it. A test that only
checked "is the call inside a try block" would have called the original code
safe.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = REPO_ROOT / "scripts" / "check-windows-footguns.py"

CHOWN_RULE = "bare os.chown / os.lchown / os.fchown / os.chroot"  # windows-footgun: ok -- naming the rule, not calling the symbol
MKFIFO_RULE = "bare os.mkfifo"  # windows-footgun: ok -- naming the rule, not calling the symbol


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


# Every symbol the two rules are meant to catch, in the shape it actually
# appears in this repo. If a rule stops matching one of these, that entry goes
# red -- which is the point: a silently-narrowed pattern is indistinguishable
# from a clean tree.
CAUGHT = [
    (CHOWN_RULE, "        os.chown(path, before.st_uid, before.st_gid)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (CHOWN_RULE, "    os.chown(path, _HERMES_UID, _HERMES_GID)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (CHOWN_RULE, '        monkeypatch.setattr("utils.os.chown", fake)'),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (CHOWN_RULE, "    os.lchown(link, uid, gid)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (CHOWN_RULE, "    os.fchown(fd, uid, gid)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (CHOWN_RULE, "    os.chroot(jail)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (MKFIFO_RULE, "        os.mkfifo(control, 0o660)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
    (MKFIFO_RULE, "    os.mkfifo(fifo)"),  # windows-footgun: ok -- sample line for the rule under test, not a call
]


@pytest.mark.parametrize(
    "name,line", CAUGHT, ids=[f"{n.split()[-1]}:{i}" for i, (n, _) in enumerate(CAUGHT)]
)
def test_rule_matches_every_symbol_it_claims(linter, name, line):
    assert _rule(linter, name).pattern.search(line), (
        f"rule {name!r} no longer matches {line!r}"
    )


# Shapes that must NOT match, so the rule cannot be "fixed" by widening it into
# something that flags every identifier containing the substring.
NOT_CAUGHT = [
    (CHOWN_RULE, "    shutil.chown(path, user, group)"),  # shutil.chown works on Windows
    (CHOWN_RULE, "    self.chown_calls.append((path, uid, gid))"),
    (CHOWN_RULE, "    record.os_chown = True"),
    (MKFIFO_RULE, "    self.mkfifo_called = True"),
]


@pytest.mark.parametrize("name,line", NOT_CAUGHT)
def test_rule_does_not_overmatch(linter, name, line):
    assert not _rule(linter, name).pattern.search(line), (
        f"rule {name!r} wrongly matches {line!r}"
    )


def test_errno_handling_does_not_suppress_the_finding(linter, tmp_path):
    """The original defect in one file: the call WAS wrapped, in the wrong guard.

    ``except PermissionError`` / ``except OSError`` cannot catch the
    ``AttributeError`` a missing ``os.chown`` raises, so the scanner must still
    report a call that is wrapped that way. This is the regression that makes
    the rule worth having rather than noise.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os\n"
        "def f(path):\n"
        "    try:\n"
        "        os.chown(path, 0, 0)\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    except PermissionError:\n"
        "        pass\n"
        "    try:\n"
        "        os.mkfifo(path)\n"  # windows-footgun: ok -- probe source text, executed by no one
        "    except OSError:\n"
        "        pass\n",
        encoding="utf-8",
    )
    # scan_file returns (line_number, line, footgun) per unsuppressed match.
    fired = {fg.name for _lineno, _line, fg in linter.scan_file(probe, linter.FOOTGUNS)}
    assert fired == {CHOWN_RULE, MKFIFO_RULE}, (
        f"an errno-only except suppressed the finding; rules that fired: {fired}"
    )


def test_same_line_attribute_guard_is_accepted(linter, tmp_path):
    """The remedy the rule's ``fix`` text names must actually silence it.

    A rule whose suggested fix does not clear the finding trains people to
    reach for the suppression marker instead.
    """
    probe = tmp_path / "guarded.py"
    probe.write_text(
        "import os\n"
        "def f(path):\n"
        "    if hasattr(os, 'chown'):\n"
        "        os.chown(path, 0, 0)  # windows-footgun: ok -- guarded above\n"
        "    if hasattr(os, 'mkfifo'):\n"
        "        os.mkfifo(path)  # windows-footgun: ok -- guarded above\n",
        encoding="utf-8",
    )
    assert linter.scan_file(probe, linter.FOOTGUNS) == [], (
        "the documented remedy (attribute guard + marker) did not clear the finding"
    )


@pytest.mark.parametrize(
    "rel",
    [
        "hermes_cli/service_manager.py",
        "hermes_cli/config.py",
        "cron/jobs.py",
        "utils.py",
    ],
)
def test_production_chown_sites_stay_clean(linter, rel):
    """Pins the four production call sites triaged on 2026-09-15.

    Scope, stated precisely because a mutation proved the obvious reading
    wrong: this catches a NEW, unmarked POSIX-ownership call appearing in one
    of these files. It does NOT pin the guards themselves -- each flagged line
    carries a ``# windows-footgun: ok`` marker, so the scan stays clean whether
    or not the guard above it survives. Deleting ``service_manager``'s
    ``hasattr`` guard leaves this test green; the behavioural regression test
    for that guard lives in
    ``tests/hermes_cli/test_container_boot.py::test_seeding_survives_missing_posix_primitive``.
    """
    assert linter.scan_file(REPO_ROOT / rel, linter.FOOTGUNS) == []
