"""Both-halves control for the runtime vacuity prover.

The prover (``scripts/check_testname_assertion_vacuity.py`` +
``scripts/ci/vacuity_plugin.py``) decides whether a presence assertion is
satisfied by its own test's name.  Like every gate it is GREEN BY DEFAULT, so a
suite that only feeds it defects proves nothing: each case below is paired with
a near-identical one that must come out the other way, and the pairs differ in
exactly the one property the prover is supposed to key on.

The end-to-end cases run a REAL child pytest against a committed fixture file, so
they exercise the actual mechanism -- pytest's ``tmp_path`` naming, the
``pytest_assertion_pass`` hook, ``saferepr`` verbosity and the driver's
reporting -- rather than a reimplementation of it.

ARMING.  These were verified to discriminate by mutating the prover itself and
confirming each mutation turns them red; the mutants are named on the tests
they kill.  See the module docstring of the plugin for why each condition
exists.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts" / "check_testname_assertion_vacuity.py"
PLUGIN = REPO_ROOT / "scripts" / "ci" / "vacuity_plugin.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin_mod():
    return _load(PLUGIN, "_vacuity_plugin_under_test")


@pytest.fixture(scope="module")
def driver_mod():
    return _load(DRIVER, "_vacuity_driver_under_test")


# ---------------------------------------------------------------------------
# Unit half: the separator rule, which is what keeps qualnames out.
# ---------------------------------------------------------------------------

#: (explanation fragment, basename, must_flag, why)
SEPARATOR_CASES = [
    (r"'x' in 'c:\\users\\t\\pytest-1\\test_foo_bar0\\out.bin'", "test_foo_bar", True,
     "a windows path component -- the real leak shape"),
    ("'x' in '/tmp/pytest-1/test_foo_bar0/out.bin'", "test_foo_bar", True,
     "a posix path component -- same leak on the other separator"),
    ("True\n +  where True = any(<generator object C.test_foo_bar.<locals>.<genexpr>>)",
     "test_foo_bar", False,
     "a QUALNAME, not a path: preceded by '.'. This is the measured false "
     "positive that a bare substring test produces"),
    ("'x' in 'the test_foo_bar case failed'", "test_foo_bar", False,
     "prose mentioning the test name, preceded by a space"),
    ("'x' in 'see also_test_foo_bar0'", "test_foo_bar", False,
     "an underscore is not a path separator"),
]


@pytest.mark.parametrize(
    "expl,basename,must_flag,why",
    SEPARATOR_CASES,
    ids=[c[3][:40] for c in SEPARATOR_CASES],
)
def test_separator_rule_admits_paths_and_rejects_qualnames(
    plugin_mod, expl, basename, must_flag, why
):
    """Killed by: dropping the separator check (cases 3-5 flip to flagged);
    by requiring '/' only (case 1 flips); by requiring the separator AFTER
    instead of before (case 3 flips, since '.<locals>' follows)."""
    assert plugin_mod._preceded_by_separator(expl, basename) is must_flag, why


def test_separator_rule_scans_past_a_first_non_path_occurrence(plugin_mod):
    """A qualname hit earlier in the string must not mask a real path later.

    Killed by: replacing the scan loop with a single ``str.find``, which stops
    at the qualname and returns False.
    """
    expl = (
        "True\n +  where True = <generator object C.test_foo_bar.<locals>>"
        r" and 'x' in 'c:\\t\\test_foo_bar0\\out.bin'"
    )
    assert plugin_mod._preceded_by_separator(expl, "test_foo_bar") is True


#: (explanation first line, literal, expected recovered value, why)
HAYSTACK_VALUE_CASES = [
    ("'x' in 'plain string'", "x", "plain string",
     "the ordinary case"),
    ("'exclusive' in (('exclusive plugin -- activate via config'))", "exclusive",
     "exclusive plugin -- activate via config",
     "pytest WRAPS a parenthesised source expression -- a first-character quote "
     "test reads this as a non-string and silently loses a real finding"),
    ("'event' in {'event': 'c:\\\\t\\\\test_x0\\\\f'}", "event", None,
     "dict: membership, not substring -- the measured test_weixin false positive"),
    ("'a' in ('a', 'b')", "a", None,
     "tuple: membership. Naive paren-stripping leaves \"'a', 'b'\", which STARTS "
     "with a quote and would be misread as a string"),
    ("'x' in ['x', 'y']", "x", None, "list: membership"),
    ("'x' in <SomeObject path='/tmp/test_x0'>", "x", None,
     "an object repr is not a literal at all"),
    ("True\n +  where True = any(...)", "x", None,
     "no ' in ' comparison on the first line -- unparseable, claim nothing"),
]


@pytest.mark.parametrize(
    "expl,literal,expected,why",
    HAYSTACK_VALUE_CASES,
    ids=[c[3][:45] for c in HAYSTACK_VALUE_CASES],
)
def test_haystack_value_recovers_only_real_strings(
    plugin_mod, expl, literal, expected, why
):
    """Killed by: returning the raw rhs text instead of literal_eval'ing it
    (the paren case then mismatches); by testing the first character for a
    quote (paren case -> None, a false negative; tuple case -> a string, a
    false positive); by dropping the isinstance check (dict/list/tuple all
    come back non-None)."""
    assert plugin_mod.haystack_value(expl, literal) == expected, why


def test_condition_two_ignores_pytest_where_provenance(plugin_mod):
    """The path must be in the OPERAND, not merely somewhere in the explanation.

    Reproduces the measured false positive at
    tests/hermes_cli/test_plugin_scanner_recursion.py:217, where the haystack is
    a plain message and only pytest's ``+ where`` line carries a tmp_path.

    Killed by: searching the whole ``expl`` for the basename instead of the
    recovered operand -- which is what the tool shipped with.
    """
    expl = (
        "'exclusive' in (('exclusive plugin -- activate via config'))\n"
        " +  where 'exclusive plugin -- activate via config' = "
        "LoadedPlugin(path='c:\\\\t\\\\test_exclusive_kind_skipped0\\\\p')"
    )
    basename = "test_exclusive_kind_skipped"
    assert plugin_mod._preceded_by_separator(expl, basename) is True, (
        "precondition: the basename IS in the raw explanation"
    )
    value = plugin_mod.haystack_value(expl, "exclusive")
    assert value == "exclusive plugin -- activate via config"
    assert plugin_mod._preceded_by_separator(value, basename) is False, (
        "but it is NOT in the operand, so the assertion is load-bearing"
    )


def test_truncation_model_matches_the_static_scanner(plugin_mod):
    """The plugin and the scanner must model pytest's naming identically.

    The plugin carries its own copy so pytest can load it as a single file;
    a drift between the two silently changes which sites are provable.
    Killed by: changing either copy's 30-character cut or its regex.
    """
    scanner = _load(
        REPO_ROOT / "scripts" / "check_testname_substring_assertions.py",
        "_scanner_for_model_check",
    )
    for name in [
        "test_patch_replace_funnel_rejects_surrogate_new_string",
        "test_unencodable_surrogate_rejected_before_write",
        "test_a",
        "test_param[a-b]",
    ]:
        assert plugin_mod.tmp_path_basename(name) == scanner.tmp_path_basename(name)


# ---------------------------------------------------------------------------
# End-to-end half: a real child pytest, both outcomes.
# ---------------------------------------------------------------------------

# The fixture input is GENERATED, and where it lives is load-bearing twice
# over.
#
# It must be named ``test_*.py``: pytest only assertion-rewrites modules whose
# filename matches ``python_files``, and an un-rewritten module fires no
# ``pytest_assertion_pass`` at all.  Measured -- the same three cases in a file
# named ``vacuity_sample_cases.py`` collect and pass when passed explicitly, yet
# the prover reports "not executed 2" and exits 0.  A fixture that defeats the
# hook is indistinguishable from a working gate finding nothing.
#
# It must also be INSIDE the repo but OUTSIDE ``testpaths`` (= ["tests"]).
# Inside, because the driver runs its child with ``cwd=REPO`` and that
# combination hangs on an out-of-tree path.  Outside ``tests``, because the file
# deliberately contains a vacuous assertion: collected by the ordinary suite it
# would be a test that exists to be broken, and ``--all`` would report the
# project's own fixture as a finding.  ``.pytest_cache/`` satisfies both and is
# already gitignored.
SAMPLE_DIR = REPO_ROOT / ".pytest_cache" / "vacuity-e2e"
SAMPLE = SAMPLE_DIR / "test_vacuity_sample_cases.py"

SAMPLE_SOURCE = '''\
"""Generated fixture for the vacuity prover's end-to-end control.

All seven tests PASS.  That is the entire point of the defect class: a vacuous
assertion is invisible precisely because it is green.
"""


def test_symlink_refused_vacuous(tmp_path):
    """MUST be proven unfalsifiable: "symlink" reaches the haystack via the
    PATH, with no production message involved at all."""
    msg = f"Refusing to delete {tmp_path}: not permitted"
    assert "symlink" in msg.lower()


def test_symlink_refused_loadbearing(tmp_path):
    """MUST be cleared -- same literal, same name collision, real reason.
    Differs from the case above in exactly one property: the haystack does not
    carry the path.  Anything that flags this one is over-wide."""
    msg = "target is a symlink/junction"
    assert "symlink" in msg.lower()


def test_phrase_is_immune_vacuous(tmp_path):
    """MUST be cleared even though its haystack DOES carry the path.  This is
    the recommended fix shape: a sanitised tmp_path segment cannot contain a
    space, so a multi-word phrase can never be satisfied by the directory
    name."""
    msg = f"Refusing to delete {tmp_path}: is a symlink/junction"
    assert "is a symlink/junction" in msg


def test_dirty_marker_reported(tmp_path):
    """MUST be cleared on CASE, though everything else about it looks vacuous.

    The haystack carries the path AND the scanner offers this as a candidate,
    because its case-folded test reports "dirty" as inside the basename.  But
    this assertion does not fold, and the path segment is lowercase, so "DIRTY"
    can only come from the message.  Load-bearing.  (The parent audit rejected
    a real site of exactly this shape by hand.)
    """
    out = f"scan of {tmp_path} complete: DIRTY"
    assert "DIRTY" in out


def test_provenance_only_path_is_not_in_the_haystack(tmp_path):
    """MUST be cleared: the path is in pytest's ``+ where`` line, not the
    haystack.

    The haystack is a clean message with no path in it. Only the INTERMEDIATE
    object's repr carries tmp_path, and pytest prints that as provenance below
    the comparison. A prover that searches the whole explanation calls this
    vacuous; one that searches the operand does not. Reproduces the real false
    positive on tests/hermes_cli/test_plugin_scanner_recursion.py:217.
    """
    class Holder:
        def __init__(self, p):
            self.p = p
            self.msg = "provenance marker only"

        def __repr__(self):
            return f"Holder(path={self.p})"

    holder = Holder(tmp_path)
    assert "provenance" in holder.msg


def test_capture_dict_membership_is_not_substring(tmp_path):
    """MUST be cleared: ``in`` on a dict is KEY membership, not substring.

    Everything a naive prover looks at says vacuous -- the literal is in the
    test's name, and the tmp_path really is in the explanation, because it sits
    in a VALUE. But the assertion tests a KEY, so the path is irrelevant and the
    assertion is load-bearing. Reproduces the real false positive this tool
    produced on tests/gateway/test_weixin.py:897.
    """
    captured = {}
    captured["capture"] = f"payload written to {tmp_path}/out.bin"
    assert "capture" in captured


def test_long_message_still_carries_the_path(tmp_path):
    """MUST be proven, and only ``-vv`` makes it visible.

    The path sits in the MIDDLE of a haystack padded well past ``saferepr``'s
    default limit.  saferepr keeps the head and the tail and elides the middle,
    so at normal verbosity the leaked directory segment is exactly what
    disappears from the explanation.  This is the shape of the real historical
    defect at test_certifi_repair.py:139.
    """
    msg = ("context " * 40) + f"refusing {tmp_path} " + ("more " * 40)
    assert "long" in msg.lower()
'''


@pytest.fixture(scope="module")
def sample():
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(SAMPLE_SOURCE, encoding="utf-8")
    try:
        yield SAMPLE
    finally:
        shutil.rmtree(SAMPLE_DIR, ignore_errors=True)


def _run_driver(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DRIVER), str(target)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture(scope="module")
def driver_run(sample):
    proc = _run_driver(sample)
    assert proc.returncode in (0, 1), (
        "driver errored instead of reporting:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    return proc


@pytest.mark.timeout(120)
def test_sample_cases_all_pass_as_ordinary_tests(sample):
    """POSITIVE CONTROL for the fixture itself.

    If the sample file did not actually run green, every end-to-end assertion
    below would be measuring a collection error rather than the prover.  A
    vacuous assertion is dangerous precisely BECAUSE it passes.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(sample), "-q", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, f"fixture suite is not green:\n{proc.stdout}"
    assert "7 passed" in proc.stdout


def test_sample_file_is_outside_the_collected_testpaths(sample):
    """The fixture must not leak into the real suite.

    It contains a deliberately vacuous assertion, so if an ordinary run
    collected it, every full-suite run would carry a test that exists to be
    broken -- and ``--all`` would report the project's own fixture as a
    finding.  It is named ``test_*`` (required for assertion rewriting), so
    only its LOCATION keeps it out.
    """
    assert sample.is_file()
    assert REPO_ROOT / "tests" not in sample.parents, (
        "fixture moved under testpaths; the ordinary suite would collect it"
    )


@pytest.mark.timeout(120)
def test_driver_proves_the_vacuous_assertion(driver_run):
    """MUST FLAG. Killed by: dropping condition (2); dropping ``-vv``."""
    assert driver_run.returncode == 1, driver_run.stdout
    assert "test_symlink_refused_vacuous" in driver_run.stdout
    assert "PROVEN UNFALSIFIABLE" in driver_run.stdout


@pytest.mark.timeout(120)
def test_driver_clears_the_loadbearing_assertion(driver_run):
    """MUST NOT FLAG -- same literal, same test-name collision, real reason.

    Killed by: dropping condition (2) entirely (this site then reports as
    proven, and the gate becomes the 85%-false-positive static check).
    """
    out = driver_run.stdout
    proven_block = out.split("PROVEN UNFALSIFIABLE")
    assert "test_symlink_refused_loadbearing" not in "".join(proven_block[1:]), out


@pytest.mark.timeout(120)
def test_driver_clears_the_phrase_fix_shape(driver_run):
    """The recommended fix must actually clear the gate it is the fix for.

    A multi-word phrase cannot survive pytest's sanitisation into a directory
    name, so this site is structurally immune even though its haystack DOES
    carry the path.  Killed by: comparing squashed forms (which drop the
    spaces and make the phrase collide again).
    """
    proven_block = driver_run.stdout.split("PROVEN UNFALSIFIABLE")
    assert "test_phrase_is_immune_vacuous" not in "".join(proven_block[1:]), (
        driver_run.stdout
    )


@pytest.mark.timeout(120)
def test_driver_clears_a_provenance_only_path(driver_run):
    """MUST NOT FLAG: tmp_path appears only in pytest's ``+ where`` provenance.

    This is the END-TO-END pair for the operand-scoping rule, and it exists
    because the unit test alone did NOT discriminate: mutating the hook to
    search the whole explanation again (M11) left the suite fully green until
    this case was added. A unit test of the helper does not cover the wiring
    that uses it.

    Killed by: passing ``expl`` instead of the recovered operand to
    _preceded_by_separator -- which is what the tool shipped with, and what
    produced its false positive on a real site.
    """
    proven_block = driver_run.stdout.split("PROVEN UNFALSIFIABLE")
    assert "test_provenance_only_path_is_not_in_the_haystack" not in "".join(
        proven_block[1:]
    ), driver_run.stdout


@pytest.mark.timeout(120)
def test_driver_clears_a_dict_membership_assertion(driver_run):
    """MUST NOT FLAG: ``in`` on a dict is membership, not substring.

    Killed by: dropping the haystack_is_str check in the plugin, which is what
    the tool shipped with -- it reported this shape as PROVEN on a real site
    (tests/gateway/test_weixin.py:897) that the 2026-09-14 audit had correctly
    rejected by hand.
    """
    proven_block = driver_run.stdout.split("PROVEN UNFALSIFIABLE")
    assert "test_capture_dict_membership_is_not_substring" not in "".join(
        proven_block[1:]
    ), driver_run.stdout


@pytest.mark.timeout(120)
def test_driver_clears_a_case_sensitive_assertion(driver_run):
    """MUST NOT FLAG: the literal's CASE cannot come from the path.

    The scanner offers this site as a candidate because its own check folds
    case, and its haystack really does carry the path -- so everything the
    prover looks at says "vacuous" except the one property that decides it.
    Killed by: dropping the case re-decision of condition (1) in the plugin,
    which is otherwise redundant with the scanner's selection and would look
    safe to delete.
    """
    proven_block = driver_run.stdout.split("PROVEN UNFALSIFIABLE")
    assert "test_dirty_marker_reported" not in "".join(proven_block[1:]), (
        driver_run.stdout
    )


@pytest.mark.timeout(120)
def test_driver_proves_a_leak_hidden_by_saferepr_truncation(driver_run):
    """MUST FLAG even though the path is elided at default verbosity.

    Killed by: dropping ``-vv`` from the driver's child command, which makes
    the gate green by truncation on exactly the long refusal messages that
    embed a path in the first place.
    """
    assert "test_long_message_still_carries_the_path" in driver_run.stdout, (
        driver_run.stdout
    )


@pytest.mark.timeout(120)
def test_driver_reports_exactly_the_two_proven_sites(driver_run):
    """Counts the verdict line, so an over-wide prover fails here even if the
    per-site assertions above happen to pass.

    Killed by: any widening that admits the load-bearing, phrase, or
    case-sensitive cases.
    """
    assert "proven 2," in driver_run.stdout, driver_run.stdout


def test_a_child_run_that_observed_nothing_is_not_reported_as_clean(
    driver_mod, monkeypatch, capsys, sample
):
    """A prover that could not observe anything must exit 2, never 0.

    'Green because it did not run' is the same defect class the prover exists
    to catch, so it must not be the prover's own failure mode.  Exercised at
    ``main()`` with a stubbed ``run_prover``, because the interesting return
    codes (4 usage, 5 nothing collected, 3 internal) cannot be provoked from a
    candidate file -- a file pytest cannot parse yields no candidates and the
    driver correctly exits before ever starting a child.

    Killed by: removing the ``pytest_returncode`` check in ``main()``.
    """
    monkeypatch.setattr(
        driver_mod,
        "run_prover",
        lambda candidates, extra: {
            "proven": [],
            "cleared": [],
            "pytest_returncode": 4,
            "pytest_tail": "ERROR: file or directory not found",
        },
    )
    rc = driver_mod.main([str(sample)])
    assert rc == 2, "a child run that observed nothing must not read as clean"
    assert "exited 4" in capsys.readouterr().err


def test_a_run_that_observed_no_candidate_is_not_reported_as_clean(
    driver_mod, monkeypatch, capsys, sample
):
    """Candidates in scope but ZERO verdicts means the hook never reached them.

    This is the prover's own vacuity failure, and it is not hypothetical: it
    happened twice while building this tool (relative candidate paths, and a
    stale rewritten .pyc left by a preceding ordinary pytest run). Both times
    every site reported "did not execute" and the run exited 0.

    Killed by: removing the ``not proven and not cleared`` guard in ``main()``.
    """
    monkeypatch.setattr(
        driver_mod,
        "run_prover",
        lambda candidates, extra: {
            "proven": [],
            "cleared": [],
            "pytest_returncode": 0,
            "pytest_tail": "3 passed",
        },
    )
    assert driver_mod.main([str(sample)]) == 2
    assert "observed NONE" in capsys.readouterr().err


def test_a_normal_child_run_still_reports(driver_mod, monkeypatch, capsys, sample):
    """PAIR for both guards above: a run that DID observe its candidates must
    report normally, and pytest's exit 1 means a failing test, not a broken run.

    Without this pair both guards could be satisfied by rejecting everything,
    which would make the prover unable to report a clean tree at all.
    """
    observed = [
        {"file": str(sample).replace("\\", "/").lower(), "line": 12},
    ]
    monkeypatch.setattr(
        driver_mod,
        "run_prover",
        lambda candidates, extra: {
            "proven": [],
            "cleared": observed,
            "pytest_returncode": 1,
            "pytest_tail": "",
        },
    )
    assert driver_mod.main([str(sample)]) == 0
    assert "no assertion in scope" in capsys.readouterr().out
