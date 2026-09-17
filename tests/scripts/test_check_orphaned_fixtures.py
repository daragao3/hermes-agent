"""Wrappers for scripts/check_orphaned_fixtures.py.

Same pattern as tests/scripts/test_case_collision_check.py: pin the parser on
canned ``pytest --setup-plan`` output, then run the REAL script against a
throwaway repo in both directions -- a demo file with a missing fixture must
be detected, and a clean file must come back clean -- so a green here cannot
be a checker that refuses everything or one that sees nothing.

The defect this guards against is the 2026-09-17 ``bash_syntax_check`` orphan:
an integration merge carried a test that requested a fixture no conftest on
the trunk defined, ``--collect-only`` passed, and the test ERRORed at setup on
every platform.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.timeout_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_orphaned_fixtures.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_orphaned_fixtures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # A @dataclass under `from __future__ import annotations` resolves its
    # module through sys.modules; an unregistered module dies at class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cof = _load()


# ── Parser ──────────────────────────────────────────────────────────────────

# Verbatim shape of pytest 9.1.1 ``--setup-plan -q`` on a file with a missing
# fixture (Windows paths, a class method, a parametrized test) plus one module
# that would not import, ending in the summary line.
_SETUP_PLAN_OUTPUT = textwrap.dedent(
    r"""
    tests/sub/test_demo.py::test_bare_ok
            SETUP    F present
            tests/sub/test_demo.py::test_bare_ok (fixtures used: present)
            TEARDOWN F present
    ==================================== ERRORS ====================================
    _____________________ ERROR at setup of test_bare_missing _____________________
    file C:\repo\tests\sub\test_demo.py, line 10
      def test_bare_missing(gone_fixture):
    E       fixture 'gone_fixture' not found
    >       available fixtures: capfd, monkeypatch, present, tmp_path
    >       use 'pytest --fixtures [testpath]' for help on them.

    C:\repo\tests\sub\test_demo.py:10
    ________________ ERROR at setup of TestCls.test_method_missing ________________
    file C:\repo\tests\sub\test_demo.py, line 14
          def test_method_missing(self, present, other_gone):
    E       fixture 'other_gone' not found
    >       available fixtures: capfd, monkeypatch, present, tmp_path

    C:\repo\tests\sub\test_demo.py:14
    ___________________ ERROR at setup of test_param_missing[1] ___________________
    file C:\repo\tests\sub\test_demo.py, line 17
      @pytest.mark.parametrize("x", [1, 2])
      def test_param_missing(x, gone_fixture):
    E       fixture 'gone_fixture' not found

    C:\repo\tests\sub\test_demo.py:17
    ___________________ ERROR at setup of test_param_missing[2] ___________________
    file C:\repo\tests\sub\test_demo.py, line 17
      @pytest.mark.parametrize("x", [1, 2])
      def test_param_missing(x, gone_fixture):
    E       fixture 'gone_fixture' not found

    C:\repo\tests\sub\test_demo.py:17
    =========================== short test summary info ===========================
    ERROR tests\sub\test_broken_import.py - ModuleNotFoundError: No module named 'nope'
    ERROR tests\sub\test_demo.py::test_bare_missing
    ERROR tests\sub\test_demo.py::TestCls::test_method_missing
    ERROR tests\sub\test_demo.py::test_param_missing[1]
    ERROR tests\sub\test_demo.py::test_param_missing[2]
    5 errors in 0.02s
    """
).lstrip("\n")


def test_parser_reports_each_missing_fixture_once_with_location():
    orphans, collection_errors, finished = cof.parse_setup_plan(_SETUP_PLAN_OUTPUT)

    assert finished is True
    assert [(o.path, o.line, o.test, o.fixture) for o in orphans] == [
        ("C:/repo/tests/sub/test_demo.py", 10, "test_bare_missing", "gone_fixture"),
        ("C:/repo/tests/sub/test_demo.py", 14, "TestCls.test_method_missing", "other_gone"),
        # parametrized: one row, not one per param id
        ("C:/repo/tests/sub/test_demo.py", 17, "test_param_missing[1]", "gone_fixture"),
    ]
    # The module that would not import is reported, but NOT as an orphan.
    assert collection_errors == ["tests/sub/test_broken_import.py"]


def test_parser_relativises_paths_under_repo(tmp_path):
    output = _SETUP_PLAN_OUTPUT.replace("C:\\repo", str(tmp_path))
    orphans, _, _ = cof.parse_setup_plan(output, repo=tmp_path)
    assert {o.path for o in orphans} == {"tests/sub/test_demo.py"}


def test_parser_clean_run_has_verdict_and_nothing_else():
    orphans, collection_errors, finished = cof.parse_setup_plan(
        "tests/x/test_a.py::test_ok\n        SETUP    F tmp_path\n3 skipped in 20.43s\n"
    )
    assert (orphans, collection_errors, finished) == ([], [], True)
    assert cof.parse_setup_plan("no tests ran in 0.01s\n")[2] is True
    assert cof.parse_setup_plan("== 2 passed, 1 skipped in 1.5s ==\n")[2] is True


def test_parser_crash_log_without_summary_line_is_no_verdict():
    crashed = (
        "tests/x/test_a.py::test_ok\n"
        "Windows fatal exception: code 0x8007000e\n"
        "\n"
        "Current thread 0x00001234 (most recent call first):\n"
        '  File "C:\\x\\_pytest\\python.py", line 1, in collect\n'
    )
    orphans, collection_errors, finished = cof.parse_setup_plan(crashed)
    assert finished is False
    assert orphans == [] and collection_errors == []


# ── Scope ───────────────────────────────────────────────────────────────────


def test_build_scope_groups_by_directory_and_expands_changed_conftest(tmp_path):
    for rel in (
        "tests/a/test_one.py",
        "tests/a/test_two.py",
        "tests/a/helper.py",
        "tests/b/test_three.py",
        "tests/b/sub/test_nested.py",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    scope = cof.build_scope(
        [
            "tests/b/test_three.py",
            "tests\\a\\conftest.py",  # backslashes normalised; conftest expands
            "agent/not_a_test.py",  # ignored
            "tests/a/helper.py",  # not a test file
            "tests/b/test_deleted.py",  # no longer on disk: dropped
        ],
        tmp_path,
    )
    assert scope == {
        "tests/a": ["tests/a/test_one.py", "tests/a/test_two.py"],
        "tests/b": ["tests/b/test_three.py"],
    }
    # The conftest expansion is NON-recursive: tests/b/sub is untouched.
    assert "tests/b/sub" not in scope


def test_pytest_argv_is_setup_plan_via_argsfile_with_addopts_cleared():
    argv = cof.pytest_argv("py", "C:/tmp/x.args")
    assert argv[:3] == ["py", "-m", "pytest"]
    assert "--setup-plan" in argv and "--collect-only" not in argv
    assert argv[-1] == "@C:/tmp/x.args"
    assert argv[argv.index("-o") + 1] == "addopts="
    assert "--continue-on-collection-errors" in argv
    assert "-p" in argv and argv[argv.index("-p") + 1] == "no:cacheprovider"


# ── Live fire ───────────────────────────────────────────────────────────────

_DEMO_ORPHAN = textwrap.dedent(
    """
    import pytest


    @pytest.fixture
    def present():
        return 1


    def test_bare_ok(present):
        assert present


    def test_bare_missing(gone_fixture):
        pass


    class TestCls:
        def test_method_missing(self, present, other_gone):
            pass
    """
)

_DEMO_CLEAN = textwrap.dedent(
    """
    def test_fine(tmp_path):
        assert tmp_path
    """
)


def _demo_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests" / "sub").mkdir(parents=True)
    (repo / "tests" / "sub" / "test_demo_orphan.py").write_text(_DEMO_ORPHAN, encoding="utf-8")
    (repo / "tests" / "sub" / "test_fine.py").write_text(_DEMO_CLEAN, encoding="utf-8")
    return repo


@pytest.mark.timeout(scaled(120))
def test_live_setup_plan_detects_bare_test_and_class_method(tmp_path):
    repo = _demo_repo(tmp_path)
    result = cof.run_directory(
        sys.executable,
        repo,
        "tests/sub",
        ["tests/sub/test_demo_orphan.py", "tests/sub/test_fine.py"],
        budget_seconds=scaled(90),
    )
    assert result.verdict is True, result.detail
    assert result.collection_errors == []
    assert [(o.path, o.test, o.fixture) for o in result.orphans] == [
        ("tests/sub/test_demo_orphan.py", "test_bare_missing", "gone_fixture"),
        ("tests/sub/test_demo_orphan.py", "TestCls.test_method_missing", "other_gone"),
    ]


@pytest.mark.timeout(scaled(120))
def test_live_clean_file_is_clean_and_has_a_verdict(tmp_path):
    """Positive control: the checker is not simply flagging everything."""
    repo = _demo_repo(tmp_path)
    result = cof.run_directory(
        sys.executable, repo, "tests/sub", ["tests/sub/test_fine.py"], budget_seconds=scaled(90)
    )
    assert result.verdict is True, result.detail
    assert result.orphans == [] and result.collection_errors == []


@pytest.mark.timeout(scaled(180))
def test_cli_exit_codes_on_demo_repo(tmp_path):
    repo = _demo_repo(tmp_path)

    def run(*files):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo), "--python", sys.executable, *files],
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=scaled(150),
        )

    red = run("tests/sub/test_demo_orphan.py")
    assert red.returncode == cof.EXIT_ORPHANS, red.stdout + red.stderr
    assert "requests fixture 'gone_fixture' which does not exist" in red.stdout
    assert "requests fixture 'other_gone' which does not exist" in red.stdout

    green = run("tests/sub/test_fine.py")
    assert green.returncode == cof.EXIT_CLEAN, green.stdout + green.stderr
    assert "0 orphan(s)" in green.stdout

    empty = run("agent/nothing_to_do_with_tests.py")
    assert empty.returncode == cof.EXIT_CLEAN
    assert "no test file in scope" in empty.stdout


def test_cli_refuses_to_judge_a_scope_over_the_cap(tmp_path):
    repo = _demo_repo(tmp_path)
    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--repo", str(repo), "--python", sys.executable,
            "--max-files", "1", "tests/sub/test_demo_orphan.py", "tests/sub/test_fine.py",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        timeout=scaled(60),
    )
    assert proc.returncode == cof.EXIT_NO_VERDICT, proc.stdout + proc.stderr
    assert "NOT CHECKED" in proc.stdout


def test_no_verdict_when_pytest_times_out(tmp_path):
    def runner(argv, cwd, env, budget):
        raise subprocess.TimeoutExpired(argv, budget)

    result = cof.run_directory("py", tmp_path, "tests/x", ["tests/x/test_a.py"], 7, runner=runner)
    assert result.verdict is False and "7s" in result.detail
    assert cof.report([result], out=_Sink()) == cof.EXIT_NO_VERDICT


def test_orphans_outrank_a_missing_verdict_elsewhere(tmp_path):
    def runner(argv, cwd, env, budget):
        with open(argv[-1][1:], encoding="utf-8") as fh:
            files = fh.read().split()
        if files == ["tests/x/test_a.py"]:
            return 1, _SETUP_PLAN_OUTPUT
        return 1, "Windows fatal exception: code 0x8007000e\n"

    results = cof.check(
        tmp_path,
        {"tests/x": ["tests/x/test_a.py"], "tests/y": ["tests/y/test_b.py"]},
        "py",
        30,
        runner=runner,
    )
    assert [r.verdict for r in results] == [True, False]
    assert cof.report(results, out=_Sink()) == cof.EXIT_ORPHANS


class _Sink:
    def __init__(self):
        self.text = ""

    def write(self, chunk):
        self.text += chunk
