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

The static-scan half pins the gap ``--setup-plan`` leaves: a module skipped on
this host is never set up, so its orphan is invisible to the dynamic run
(positive control below: setup-plan alone reports 0 on the demo) and only the
AST visibility scan reports it.  The scanner tests run without the
``pytest --fixtures`` probe (``plugin_fixtures`` passed) so they cost
milliseconds; the model is exercised on the sweep's real false-positive sites
with the allowlist emptied.
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


def test_parser_lists_tests_the_setup_plan_actually_set_up(tmp_path):
    """Only a test that printed ``(fixtures used: ...)`` was set up; the nodeid
    path is relative to pytest's cwd (the repo), param ids collapse, and a
    class path joins with '.' the way the static scan names a method."""
    assert cof.parse_resolved_tests(_SETUP_PLAN_OUTPUT) == {("tests/sub/test_demo.py", "test_bare_ok")}
    output = (
        "        tests/sub/test_demo.py::test_p[1] (fixtures used: here, x)\n"
        "        tests/sub/test_demo.py::test_p[2] (fixtures used: here, x)\n"
        "        tests/sub/test_demo.py::TestCls::test_m (fixtures used: here)\n"
        "        SETUP    F here\n"
        "ss\n"
    )
    assert cof.parse_resolved_tests(output, repo=tmp_path) == {
        ("tests/sub/test_demo.py", "test_p"),
        ("tests/sub/test_demo.py", "TestCls.test_m"),
    }


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


# ── Static visibility scan ──────────────────────────────────────────────────

# A module skipped on THIS host.  The brief's shape is
# ``skipif(sys.platform == "win32", ...)``; the literal is the running
# platform so the positive control (setup-plan misses it) holds on any box,
# and on this one it reads exactly ``"win32"``.
_DEMO_SKIPPED = textwrap.dedent(
    f"""
    import sys

    import pytest

    pytestmark = pytest.mark.skipif(sys.platform == {sys.platform!r}, reason="not on this host")


    @pytest.fixture
    def present():
        return 1


    def test_uses_missing(present, gone_fixture):
        pass


    class TestCls:
        def test_ok(self, present, tmp_path):
            pass
    """
)

# Every request shape the static model must NOT flag.  ``os`` is imported so
# the patch targets are real if anything ever executes this.
_DEMO_NOT_ORPHANS = textwrap.dedent(
    """
    import os
    from unittest.mock import patch

    import pytest

    pytestmark = pytest.mark.parametrize("module_param", [1])
    shape = pytest.mark.parametrize("aliased", [1, 2])


    @pytest.fixture(name="renamed")
    def _renamed_impl():
        return 1


    @pytest.fixture
    def needs_request(request, renamed):
        return request


    def test_request_is_a_real_fixture(request, needs_request):
        pass


    @pytest.mark.parametrize("x, y", [(1, 2)])
    def test_parametrize_string(x, y, module_param):
        pass


    @pytest.mark.parametrize(["a", "b"], [(1, 2)])
    def test_parametrize_list(a, b):
        pass


    @shape
    def test_parametrize_alias(aliased):
        pass


    @patch("os.getcwd")
    @patch.object(os, "sep")
    def test_function_patches_fill_the_first_names(mock_sep, mock_getcwd, renamed):
        pass


    @patch("os.getcwd", new=object())
    def test_patch_with_new_injects_nothing(renamed):
        pass


    @patch.dict(os.environ, {})
    def test_patch_dict_injects_nothing(renamed):
        pass


    @patch("os.getcwd", return_value="/")
    class TestClassPatch:
        def test_class_patch_fills_the_first_name(self, _mock_safe, tmp_path, monkeypatch):
            pass

        @patch("os.sep")
        def test_both_levels(self, own_mock, class_mock, renamed):
            pass

        @pytest.fixture
        def class_fixture(self, renamed):
            return renamed

        def test_class_fixture(self, _mock, class_fixture):
            pass


    @pytest.mark.parametrize("cls_param", [1])
    class TestClassParametrize:
        pytestmark = pytest.mark.usefixtures("renamed")

        def test_uses_class_param(self, cls_param):
            pass


    def test_defaults_are_not_requests(renamed, optional=None, *, kw_only=1):
        pass


    def test_kw_only_without_default_is_a_request(*, renamed):
        pass


    class Helper:
        # Not ``Test*``: pytest never collects it, so nothing here is a request.
        def test_looks_like_a_test(self, urls=None):
            pass

        def test_uncollected(self, not_a_fixture_anywhere):
            pass


    class TestWithInit:
        def __init__(self):
            pass

        def test_not_collected_either(self, not_a_fixture_anywhere):
            pass


    def helper_not_a_test(not_a_fixture_anywhere):
        pass
    """
)


def _write(repo: Path, rel: str, source: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _scanner(repo: Path, **kw):
    """A scanner that never spawns the ``pytest --fixtures`` probe."""
    kw.setdefault("plugin_fixtures", set())
    kw.setdefault("allow", {})
    return cof.StaticScanner(repo, **kw)


def _findings(orphans):
    return sorted((o.path, o.test, o.fixture, o.via) for o in orphans)


@pytest.mark.timeout(scaled(120))
def test_static_scan_finds_the_orphan_in_a_module_setup_plan_skips(tmp_path):
    """(a) the gap this closes: setup-plan alone reports ZERO orphans on a
    module skipped on this host (positive control), the static scan reports
    the one it holds, and the two compose in ``check`` -- without the static
    scan the orphan is invisible, with it the run is red."""
    repo = tmp_path / "repo"
    _write(repo, "tests/sub/test_skipped.py", _DEMO_SKIPPED)
    files = ["tests/sub/test_skipped.py"]

    dynamic = cof.run_directory(sys.executable, repo, "tests/sub", files, budget_seconds=scaled(90))
    assert dynamic.verdict is True, dynamic.detail
    assert dynamic.orphans == [], "setup-plan set the skipped test up?!"
    assert dynamic.resolved == set(), "a skipped test must print no (fixtures used:) line"

    static, unknowable = _scanner(repo).scan(files)
    assert unknowable == []
    assert _findings(static) == [("tests/sub/test_skipped.py", "test_uses_missing", "gone_fixture", "static")]
    def_line = next(i for i, row in enumerate(_DEMO_SKIPPED.splitlines(), 1) if row.startswith("def test_uses_missing"))
    assert static[0].line == def_line
    assert "static scan" in static[0].render() and "gone_fixture" in static[0].render()

    scope = {"tests/sub": files}
    blind = cof.check(repo, scope, sys.executable, scaled(90), static=False)
    assert [r.orphans for r in blind] == [[]]
    assert cof.report(blind, out=_Sink()) == cof.EXIT_CLEAN

    seeing = cof.check(repo, scope, sys.executable, scaled(90), scanner=_scanner(repo))
    assert _findings(o for r in seeing for o in r.orphans) == [
        ("tests/sub/test_skipped.py", "test_uses_missing", "gone_fixture", "static")
    ]
    sink = _Sink()
    assert cof.report(seeing, out=sink) == cof.EXIT_ORPHANS
    assert "1 orphan(s) (1 via static scan)" in sink.text


def test_static_scan_does_not_flag_request_patch_injections_or_parametrize_argnames(tmp_path):
    """(b) every false-positive shape from the 2026-09-17 sweep, plus the
    rest of ``getfuncargnames``, on a file with NO genuine orphan -- then the
    same file with one, so a green here cannot be a scanner that sees nothing."""
    repo = tmp_path / "repo"
    _write(repo, "tests/sub/test_shapes.py", _DEMO_NOT_ORPHANS)
    orphans, unknowable = _scanner(repo).scan(["tests/sub/test_shapes.py"])
    assert (unknowable, _findings(orphans)) == ([], [])

    with_teeth = _DEMO_NOT_ORPHANS + "\n\ndef test_real_orphan(renamed, truly_gone):\n    pass\n"
    _write(repo, "tests/sub/test_shapes.py", with_teeth)
    orphans, _ = _scanner(repo).scan(["tests/sub/test_shapes.py"])
    assert _findings(orphans) == [("tests/sub/test_shapes.py", "test_real_orphan", "truly_gone", "static")]


def test_static_scan_reads_every_getfuncargnames_rule_it_claims(tmp_path):
    """Pin the model one rule at a time: each mutation of the clean file adds
    exactly the finding that rule would otherwise suppress."""
    repo = tmp_path / "repo"
    cases = {
        # a patch WITH new= injects nothing, so its parameter IS a request
        "patch_new": ('@patch("os.getcwd", new=object())\ndef test_patch_with_new_injects_nothing(renamed):',
                      '@patch("os.getcwd", new=object())\ndef test_patch_with_new_injects_nothing(surplus, renamed):',
                      "surplus"),
        # class-level patch fills ONE name; a second unresolved name is a request
        "class_patch": ("def test_class_patch_fills_the_first_name(self, _mock_safe, tmp_path, monkeypatch):",
                        "def test_class_patch_fills_the_first_name(self, _mock_safe, second_mock, tmp_path):",
                        "second_mock"),
        # a parametrize argname is not a request; a name outside it is
        "parametrize": ('@pytest.mark.parametrize("x, y", [(1, 2)])\ndef test_parametrize_string(x, y, module_param):',
                        '@pytest.mark.parametrize("x, y", [(1, 2)])\ndef test_parametrize_string(x, y, z, module_param):',
                        "z"),
        # usefixtures names ARE requests
        "usefixtures": ('pytestmark = pytest.mark.usefixtures("renamed")',
                        'pytestmark = pytest.mark.usefixtures("renamed", "used_but_gone")',
                        "used_but_gone"),
        # a fixture's own parameters are requests
        "fixture_params": ("def needs_request(request, renamed):", "def needs_request(request, renamed, gone_dep):", "gone_dep"),
    }
    for label, (before, after, expected) in cases.items():
        assert before in _DEMO_NOT_ORPHANS, label
        _write(repo, "tests/sub/test_shapes.py", _DEMO_NOT_ORPHANS.replace(before, after))
        orphans, _ = _scanner(repo).scan(["tests/sub/test_shapes.py"])
        assert [o.fixture for o in orphans] == [expected], label


def test_static_visibility_is_the_conftest_chain_pytest_plugins_and_imports(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "conftest.py", "import pytest\n\n@pytest.fixture\ndef root_fx():\n    return 1\n")
    _write(repo, "tests/conftest.py", 'pytest_plugins = ["tests.fixtures.plugged"]\n')
    _write(repo, "tests/fixtures/__init__.py", "")
    _write(repo, "tests/fixtures/plugged.py", "import pytest\n\n@pytest.fixture\ndef plugged_fx():\n    return 1\n")
    _write(repo, "tests/fixtures/shared.py", "import pytest\n\n@pytest.fixture\ndef shared_fx():\n    return 1\n")
    _write(repo, "tests/sub/conftest.py", "from tests.fixtures.shared import shared_fx  # noqa: F401\n")
    _write(repo, "tests/sub/test_in.py", "def test_all(root_fx, plugged_fx, shared_fx, tmp_path):\n    pass\n")
    # A sibling directory sees the root chain but NOT tests/sub/conftest.py.
    _write(repo, "tests/other/test_out.py", "def test_sibling(root_fx, plugged_fx, shared_fx):\n    pass\n")
    # A star import inside the repo resolves; one outside makes the file unjudgeable.
    _write(repo, "tests/star/test_star_in.py", "from tests.fixtures.shared import *  # noqa: F403\n\ndef test_star(shared_fx):\n    pass\n")
    _write(repo, "tests/star/test_star_out.py", "from no_such_package import *  # noqa: F403\n\ndef test_star(whatever):\n    pass\n")

    scanner = _scanner(repo)
    assert scanner.conftest_chain("tests/sub/test_in.py") == ["conftest.py", "tests/conftest.py", "tests/sub/conftest.py"]
    orphans, unknowable = scanner.scan(
        ["tests/sub/test_in.py", "tests/other/test_out.py", "tests/star/test_star_in.py", "tests/star/test_star_out.py"]
    )
    assert _findings(orphans) == [("tests/other/test_out.py", "test_sibling", "shared_fx", "static")]
    assert [rel for rel, _ in unknowable] == ["tests/star/test_star_out.py"]
    assert "no_such_package" in unknowable[0][1]

    # Unjudgeable is informational beside a dynamic run, a missing verdict without one.
    beside = [cof.DirectoryResult("tests/star", ["tests/star/test_star_out.py"])]
    cof.apply_static(beside, _scanner(repo))
    assert beside[0].verdict is True and beside[0].static_unknowable[0][0] == "tests/star/test_star_out.py"
    alone = [cof.DirectoryResult("tests/star", ["tests/star/test_star_out.py"])]
    cof.apply_static(alone, _scanner(repo), static_only=True)
    assert alone[0].verdict is False and "could not judge" in alone[0].detail
    sink = _Sink()
    assert cof.report(alone, out=sink) == cof.EXIT_NO_VERDICT
    assert "NOT CHECKED (static) tests/star/test_star_out.py" in sink.text


def test_static_allowlist_plugin_fixtures_and_lazy_probe(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "tests/test_a.py", "def test_a(unused_tcp_port, listed):\n    pass\n\n\ndef test_b(tmp_path):\n    pass\n")
    files = ["tests/test_a.py"]

    # The probe is never spawned while every name resolves statically.
    clean = _scanner(repo, plugin_fixtures=None)
    clean.python = None
    _write(repo, "tests/test_clean.py", "def test_c(tmp_path, request):\n    pass\n")
    assert clean.scan(["tests/test_clean.py"]) == ([], [])
    assert clean.probed is False

    # Without a probe result both names are findings ...
    lazy = _scanner(repo, plugin_fixtures=None)
    lazy.python = None
    assert [o.fixture for o in lazy.scan(files)[0]] == ["unused_tcp_port", "listed"]
    assert lazy.probed is True  # it tried, once, and had no interpreter
    # ... a plugin-provided name is not, and an allowlisted one is not.
    seeded = _scanner(repo, plugin_fixtures={"unused_tcp_port"}, allow={"tests/test_a.py::listed": "known"})
    assert seeded.scan(files) == ([], [])
    # The allowlist is per PATH.
    elsewhere = _scanner(repo, plugin_fixtures={"unused_tcp_port"}, allow={"tests/test_b.py::listed": "known"})
    assert [o.fixture for o in elsewhere.scan(files)[0]] == ["listed"]


def test_shipped_allowlist_entries_exist_and_the_model_covers_them_unaided():
    """The two sites the sweep flagged are modelled; the allowlist is a belt
    on top of the braces.  Run with the allowlist EMPTY so a model regression
    on the real files shows here rather than being masked by the entry."""
    for key in cof.STATIC_ALLOWLIST:
        path, fixture = key.split("::")
        assert (REPO_ROOT / path).is_file(), key
        assert fixture in (REPO_ROOT / path).read_text(encoding="utf-8"), key
    files = sorted({k.split("::")[0] for k in cof.STATIC_ALLOWLIST})
    orphans, unknowable = _scanner(REPO_ROOT).scan(files)
    assert (unknowable, _findings(orphans)) == ([], [])


@pytest.mark.timeout(scaled(120))
def test_static_finding_on_a_test_the_setup_plan_set_up_is_dropped(tmp_path):
    """The dynamic run is authoritative wherever it reaches: a fixture bound
    at import time is invisible to the AST but real to pytest, so beside a
    setup-plan the static finding is a false positive and goes; alone it stays."""
    repo = tmp_path / "repo"
    _write(
        repo,
        "tests/sub/test_dyn.py",
        "import pytest\n\n\ndef _make():\n    return 1\n\n\n"
        'globals()["dyn_fixture"] = pytest.fixture(name="dyn_fixture")(_make)\n\n\n'
        "def test_dyn(dyn_fixture):\n    assert dyn_fixture == 1\n",
    )
    scope = {"tests/sub": ["tests/sub/test_dyn.py"]}
    alone = cof.check(repo, scope, sys.executable, scaled(90), static_only=True, scanner=_scanner(repo))
    assert _findings(alone[0].orphans) == [("tests/sub/test_dyn.py", "test_dyn", "dyn_fixture", "static")]

    beside = cof.check(repo, scope, sys.executable, scaled(90), scanner=_scanner(repo))
    assert beside[0].verdict is True, beside[0].detail
    assert ("tests/sub/test_dyn.py", "test_dyn") in beside[0].resolved
    assert beside[0].orphans == []


@pytest.mark.timeout(scaled(120))
def test_cli_static_switches(tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "tests/sub/test_skipped.py", _DEMO_SKIPPED)

    def run(*extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo), "--python", sys.executable, *extra, "tests/sub/test_skipped.py"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=scaled(100),
        )

    static_only = run("--static-only")
    assert static_only.returncode == cof.EXIT_ORPHANS, static_only.stdout + static_only.stderr
    assert "(static scan only)" in static_only.stdout
    assert "requests fixture 'gone_fixture' which no visibility rule resolves" in static_only.stdout

    allowed = run("--static-only", "--static-allow", "tests/sub/test_skipped.py::gone_fixture")
    assert allowed.returncode == cof.EXIT_CLEAN, allowed.stdout + allowed.stderr

    malformed = run("--static-only", "--static-allow", "gone_fixture")
    assert malformed.returncode == cof.EXIT_USAGE and "PATH::FIXTURE" in malformed.stderr

    both = run("--static-only", "--no-static")
    assert both.returncode == 2  # argparse: mutually exclusive


class _Sink:
    def __init__(self):
        self.text = ""

    def write(self, chunk):
        self.text += chunk
