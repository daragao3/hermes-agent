#!/usr/bin/env python3
"""Guard: every fixture a changed test file requests must still exist.

WHY THIS EXISTS
---------------
An integration merge can bring in a test that CONSUMES a fixture without the
commit that DEFINES it.  ``pytest --collect-only`` is blind to that -- fixture
lookup happens at setup, not at import -- so the module collects clean, and the
test ERRORs at setup with ``fixture 'x' not found`` on every platform until
someone notices.  On 2026-09-17 that was ``test_setup_hermes_script_is_valid_shell``:
the 0.21.1 integration merge carried the consumer hunk of upstream 027680b960
but not that commit's ``conftest.py`` definition of ``bash_syntax_check``.

``pytest --setup-plan`` resolves every fixture of every collected test WITHOUT
executing fixture or test bodies, and reports each miss as a setup ERROR with
the fixture name.  It costs the same as ``--collect-only`` (both are dominated
by importing the test modules; measured 22s vs 26s over 40 files), so running
it over the test files a change touched is cheap and catches this class
outright.  The whole-suite sweep that followed the incident (loops record
``orphaned-fixture-sweep-setup-only-20260917``) is the same command over every
directory; this script is the per-change slice of it.

WHAT IT CHECKS
--------------
Given a set of changed test files (by default ``git diff --name-only
<base>...HEAD -- 'tests/**/test_*.py'``), it groups them by DIRECTORY, runs one
``pytest --setup-plan`` per directory over only those files, and fails on any
``fixture '<name>' not found`` line.  A changed ``conftest.py`` pulls in every
``test_*.py`` directly inside its directory, since it governs fixture
visibility there and can orphan siblings it does not mention.

Per directory, not one process, because 51 duplicate ``test_*.py`` basenames
across un-packaged test dirs import-mismatch in a single pytest process; and
always via a pytest 9 ``@argsfile``, because ``tests/gateway`` (801 files) and
``tests/hermes_cli`` (916) overflow the Windows CreateProcess command line.

THE STATIC SCAN (always on; ``--no-static`` / ``--static-only``)
-----------------------------------------------------------------
``--setup-plan`` never sets up a test that is skipped on this host --
``pytest.mark.skipif`` at module/class/function level is evaluated BEFORE
fixture setup, and ``pytest.importorskip`` skips the whole module at
collection -- so a win32 box cannot see an orphan inside a ``posix only``
module (and vice versa).  The same 2026-09-17 sweep closed that gap with an
AST scan; this script runs that scan over the SAME scope, in-process, in
milliseconds.  For every collected test function / method and every fixture
function in a scope file it takes the names pytest would request
(``getfuncargnames``: positional-or-keyword and keyword-only parameters
without defaults, minus ``self`` on a method, minus the FIRST N parameters
where N is the number of ``@patch`` / ``@patch.object`` decorators without
``new=`` on the function AND on its ``Test*`` class, minus ``parametrize``
argnames at function/class/module level, plus ``usefixtures`` names) and
checks each against the names pytest could resolve there: fixtures and
module-level bindings of the module itself, of every ``conftest.py`` on the
path from the repo root down to the file's directory, of every module those
name in ``pytest_plugins``, pytest's own fixtures (``CORE_FIXTURES`` --
``request`` is there because ``pytest --fixtures`` does not list it), and,
only when a name is still unresolved, the fixtures installed plugins provide
(one ``pytest --fixtures`` probe in an empty directory, ~3s, cached per run).

A static finding on a test that ``--setup-plan`` DID set up in the same run is
by definition a false positive of the static model and is dropped; the
dynamic run is authoritative wherever it reaches.  Anything the model still
gets wrong goes in ``STATIC_ALLOWLIST`` (``path::fixture``) or
``--static-allow``.  A ``from x import *`` whose module is outside the repo
makes a file unknowable; it is reported as NOT CHECKED (static), never as
clean.

WHAT IT DOES NOT CHECK
----------------------
* A file that fails to IMPORT is reported as NOT CHECKED, not as an orphan --
  collection errors are the job of the merge collection gate
  (``~/.hermes/ops/merge_collect_check.py``) and of CI.  The line is printed;
  read it.  A directory it declined to judge is not a directory it passed.
* Fixtures reached only through ``getfixturevalue`` / ``pytest.mark.usefixtures``
  with a non-literal name, ``unittest.TestCase`` methods (pytest injects no
  fixture arguments there), and fixture names bound dynamically at import
  time are outside the static model; the dynamic run still covers them when
  the test is set up on this host.

USAGE
-----
    python scripts/check_orphaned_fixtures.py                     # vs the trunk (see DEFAULT_BASES)
    python scripts/check_orphaned_fixtures.py --base codex/wave2-hermes-accepted
    python scripts/check_orphaned_fixtures.py tests/x/test_a.py tests/y/conftest.py
    python scripts/check_orphaned_fixtures.py --files-from changed.txt
    python scripts/check_orphaned_fixtures.py --static-only tests/x/test_a.py  # no pytest run

Exit status:
    0 -- every requested fixture in scope resolved (or the scope was empty)
    1 -- at least one ``fixture '<name>' not found`` (dynamic) or a fixture
         name no visibility rule can resolve (static)
    2 -- usage error (base ref does not resolve, no interpreter with pytest)
    3 -- no verdict: a directory timed out, crashed without a pytest summary
         line, or the scope exceeded --max-files.  Distinct from 1 so a caller
         can fail open on it deliberately, never by accident.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Same caps as the merge collection gate: 150 files is where a single
# collection stops being cheap on this box.
DEFAULT_MAX_FILES = 150
DEFAULT_BUDGET_SECONDS = 300
# The fork's landing trunk first: `main` here is a PARALLEL integration line
# (measured 2026-09-17: 3,781 test files differ between the two), so diffing
# against it from a trunk-based branch is the whole suite, not the change.
DEFAULT_BASES = ("codex/wave2-hermes-accepted", "main", "origin/main")

EXIT_CLEAN = 0
EXIT_ORPHANS = 1
EXIT_USAGE = 2
EXIT_NO_VERDICT = 3

_TEST_FILE = re.compile(r"(^|/)test_[^/]*\.py$")
_CONFTEST = re.compile(r"(^|/)conftest\.py$")

# --setup-plan output, one section per test whose setup failed:
#   ____ ERROR at setup of TestCls.test_method ____
#   file C:\repo\tests\x\test_y.py, line 14
#     def test_method(self, other_gone):
#   E       fixture 'other_gone' not found
_SETUP_ERROR_HEADER = re.compile(r"^_+ ERROR at setup of (?P<test>.+?) _+$")
_FILE_LINE = re.compile(r"^file (?P<path>.+?), line (?P<line>\d+)$")
_NOT_FOUND = re.compile(r"^E\s+fixture '(?P<fixture>[^']+)' not found")
# Short-summary line for a module that would not import (no ``::`` in it).
_SUMMARY_ERROR = re.compile(r"^ERROR\s+(?P<nodeid>\S+)")
# The final line pytest prints for a run that finished, in any outcome.
_SUMMARY_LINE = re.compile(
    r"^=*\s*(?:no tests ran|\d+ [a-z]+(?:, \d+ [a-z]+)*) in \d+(?:\.\d+)?s"
)
# One line per test that --setup-plan actually set up (a skipped test never
# prints one):
#         tests/sub/test_demo.py::TestCls::test_method[1] (fixtures used: present)
_RESOLVED_LINE = re.compile(r"^\s*(?P<path>[^\s:]+\.py)::(?P<nodeid>\S+) \(fixtures used:")


@dataclass(frozen=True)
class Orphan:
    """One test whose setup could not resolve a fixture."""

    path: str
    line: int
    test: str
    fixture: str
    via: str = "setup-plan"  # or "static"

    def render(self) -> str:
        if self.via == "static":
            return (
                "%s:%d  %s  requests fixture '%s' which no visibility rule resolves "
                "(static scan; the test was not set up on this host)"
                % (self.path, self.line, self.test, self.fixture)
            )
        return "%s:%d  %s  requests fixture '%s' which does not exist" % (
            self.path,
            self.line,
            self.test,
            self.fixture,
        )


@dataclass
class DirectoryResult:
    """Outcome of one per-directory pytest run."""

    directory: str
    files: list[str]
    orphans: list[Orphan] = field(default_factory=list)
    collection_errors: list[str] = field(default_factory=list)
    verdict: bool = True  # False = timed out / crashed / no summary line
    detail: str = ""
    # (path, "Cls.test_name") of every test the setup-plan set up: a static
    # finding on one of these is a false positive of the static model.
    resolved: set[tuple[str, str]] = field(default_factory=set)
    # (file, why) the static scan could not judge: star import outside the
    # repo, unparsable conftest.
    static_unknowable: list[tuple[str, str]] = field(default_factory=list)


# ── Parsing ─────────────────────────────────────────────────────────────────


def normalize_path(path: str, repo: Path | None = None) -> str:
    """Forward slashes, repo-relative when under ``repo``."""
    text = path.strip().replace("\\", "/")
    if repo is not None:
        try:
            rel = Path(text).resolve().relative_to(repo.resolve())
        except (ValueError, OSError):
            return text
        return rel.as_posix()
    return text


def parse_setup_plan(output: str, repo: Path | None = None) -> tuple[list[Orphan], list[str], bool]:
    """Parse one ``pytest --setup-plan`` run.

    Returns ``(orphans, collection_errors, finished)``.  ``finished`` is whether
    pytest printed its final summary line -- a log that ends in a faulthandler
    dump (E_OUTOFMEMORY under host load has been observed) has no verdict and
    must never be read as a pass.
    """
    orphans: list[Orphan] = []
    # One row per (file, line, fixture): a parametrized test errors once per
    # param id and would otherwise repeat the same defect N times.
    seen: set[tuple[str, int, str]] = set()
    collection_errors: list[str] = []
    finished = False
    test = None
    path = None
    line = 0
    for raw in output.splitlines():
        row = raw.rstrip()
        header = _SETUP_ERROR_HEADER.match(row)
        if header:
            test, path, line = header.group("test"), None, 0
            continue
        if test is not None:
            where = _FILE_LINE.match(row)
            if where:
                path, line = normalize_path(where.group("path"), repo), int(where.group("line"))
                continue
            missing = _NOT_FOUND.match(row)
            if missing:
                orphan = Orphan(path or "<unknown>", line, test, missing.group("fixture"))
                key = (orphan.path, orphan.line, orphan.fixture)
                if key not in seen:
                    seen.add(key)
                    orphans.append(orphan)
                test = None
                continue
        summary = _SUMMARY_ERROR.match(row)
        if summary and "::" not in summary.group("nodeid"):
            module = normalize_path(summary.group("nodeid"), repo)
            if module not in collection_errors:
                collection_errors.append(module)
            continue
        if _SUMMARY_LINE.match(row):
            finished = True
    return orphans, collection_errors, finished


def parse_resolved_tests(output: str, repo: Path | None = None) -> set[tuple[str, str]]:
    """``(path, "Cls.test_name")`` of every test the setup-plan set up.

    Parametrize ids are stripped so ``test_p[1]`` and ``test_p[2]`` are one
    entry, matching how the static scan names a function."""
    resolved: set[tuple[str, str]] = set()
    for raw in output.splitlines():
        found = _RESOLVED_LINE.match(raw)
        if not found:
            continue
        nodeid = found.group("nodeid")
        if "[" in nodeid:
            nodeid = nodeid[: nodeid.index("[")]
        # pytest prints the nodeid path relative to ITS cwd, which is the repo.
        path = found.group("path")
        if repo is not None and not os.path.isabs(path):
            path = str(repo / path)
        resolved.add((normalize_path(path, repo), nodeid.replace("::", ".")))
    return resolved


# ── Scope ───────────────────────────────────────────────────────────────────


def is_test_path(path: str) -> bool:
    return path.endswith(".py") and bool(_TEST_FILE.search(path))


def is_conftest(path: str) -> bool:
    return bool(_CONFTEST.search(path))


def build_scope(changed: list[str], repo: Path) -> dict[str, list[str]]:
    """Changed test files grouped by directory; a changed conftest pulls in
    every ``test_*.py`` directly beside it.  Paths are repo-relative posix.
    Files that no longer exist (deleted in the change) are dropped."""
    scope: dict[str, list[str]] = {}
    for raw in changed:
        path = normalize_path(raw)
        if not path:
            continue
        if is_test_path(path):
            candidates = [path]
        elif is_conftest(path):
            directory = repo / os.path.dirname(path)
            candidates = sorted(
                (Path(os.path.dirname(path)) / p.name).as_posix()
                for p in directory.glob("test_*.py")
            ) if directory.is_dir() else []
        else:
            continue
        for candidate in candidates:
            if not (repo / candidate).is_file():
                continue
            bucket = scope.setdefault(os.path.dirname(candidate), [])
            if candidate not in bucket:
                bucket.append(candidate)
    return dict(sorted(scope.items()))


def changed_test_files(repo: Path, base: str) -> list[str]:
    """``git diff --name-only <base>...HEAD -- tests/`` narrowed to test files
    and conftests (filtered here rather than by pathspec: git's ``*`` already
    crosses ``/``, and ``**`` needs ``:(glob)`` magic -- easy to get wrong)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=ACMR", base + "...HEAD", "--", "tests/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError("git diff against %r failed:\n%s" % (base, proc.stderr.strip()))
    return [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip() and (is_test_path(line.strip()) or is_conftest(line.strip()))
    ]


def resolve_base(repo: Path, explicit: str | None) -> str | None:
    """The first candidate ref that resolves to a commit, or None."""
    candidates = (explicit,) if explicit else DEFAULT_BASES
    for ref in candidates:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return ref
    return None


# ── Interpreter ─────────────────────────────────────────────────────────────


def resolve_interpreter(repo: Path, explicit: str | None, env=None) -> str | None:
    """--python, then HERMES_PYTEST_PYTHON, then the repo venv, then this
    interpreter -- whichever first imports pytest."""
    env = os.environ if env is None else env
    candidates = [explicit, env.get("HERMES_PYTEST_PYTHON")]
    for venv in (".venv", "venv"):
        for name in ("Scripts/python.exe", "bin/python", "bin/python3"):
            candidates.append(str(repo / venv / name))
    candidates.append(sys.executable)
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        probe = subprocess.run(
            [candidate, "-c", "import pytest"], capture_output=True, timeout=60
        )
        if probe.returncode == 0:
            return candidate
    return None


# ── Running ─────────────────────────────────────────────────────────────────


def pytest_argv(python: str, argsfile: str) -> list[str]:
    return [
        python,
        "-m",
        "pytest",
        "--setup-plan",
        "-q",
        "-p",
        "no:cacheprovider",
        # Drop the repo's `-m 'not integration and not stress'` so marked tests
        # are resolved too; nothing runs, so the marks buy no protection here.
        "-o",
        "addopts=",
        "--continue-on-collection-errors",
        "@" + argsfile,
    ]


def subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(TZ="UTC", PYTHONHASHSEED="0", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    # Nothing here should spawn a shell, but a conftest that does inherits the
    # Claude Code Bash tool's BASH_ENV and dies in its DEBUG trap (see
    # tests/bash_support.py); drop it so a setup-plan never chases that ghost.
    env.pop("BASH_ENV", None)
    return env


def run_directory(
    python: str,
    repo: Path,
    directory: str,
    files: list[str],
    budget_seconds: float,
    runner=None,
) -> DirectoryResult:
    """One ``pytest --setup-plan`` over ``files`` (all inside ``directory``)."""
    result = DirectoryResult(directory=directory, files=list(files))
    run = runner or _default_runner
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".args", prefix="orphan-fixtures-", delete=False
    ) as fh:
        fh.write("\n".join(files) + "\n")
        argsfile = fh.name
    try:
        argv = pytest_argv(python, argsfile)
        try:
            rc, output = run(argv, repo, subprocess_env(), budget_seconds)
        except subprocess.TimeoutExpired:
            result.verdict = False
            result.detail = "setup-plan exceeded %ss" % budget_seconds
            return result
        except OSError as exc:
            result.verdict = False
            result.detail = "could not start pytest: %s" % exc
            return result
    finally:
        try:
            os.unlink(argsfile)
        except OSError:
            pass
    orphans, collection_errors, finished = parse_setup_plan(output, repo)
    result.orphans = orphans
    result.collection_errors = collection_errors
    result.resolved = parse_resolved_tests(output, repo)
    if not finished:
        result.verdict = False
        result.detail = "pytest exited %s without a summary line (crashed?):\n%s" % (
            rc,
            _tail(output),
        )
    return result


def _default_runner(argv, cwd, env, budget_seconds):
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        timeout=budget_seconds,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _tail(output: str, lines: int = 20) -> str:
    rows = [row for row in output.splitlines() if row.strip()]
    return "\n".join(rows[-lines:])


# ── Static visibility scan ──────────────────────────────────────────────────

# Fixtures pytest itself provides (pytest 9).  ``request`` is a real fixture
# that ``pytest --fixtures`` does not list -- the 2026-09-17 sweep took its
# builtins from that output and flagged ``request`` in 14 files for it.
CORE_FIXTURES = frozenset(
    {
        "cache",
        "capfd",
        "capfdbinary",
        "caplog",
        "capsys",
        "capsysbinary",
        "capteesys",
        "doctest_namespace",
        "monkeypatch",
        "pytestconfig",
        "record_property",
        "record_testsuite_property",
        "record_xml_attribute",
        "recwarn",
        "request",
        "subtests",
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
    }
)

# ``<repo-relative posix path>::<fixture>`` -> why it is not an orphan.  For a
# false positive of the static MODEL only: a name a plugin provides comes from
# the ``--fixtures`` probe, a name pytest provides belongs in CORE_FIXTURES.
# The two sites the 2026-09-17 sweep flagged ARE modelled (class-level @patch
# injection; defaulted parameter on a helper class pytest never collects) and
# are listed as well, so a regression of the model on them still cannot turn
# a merge red; the unit tests exercise the model on copies with the allowlist
# emptied.
STATIC_ALLOWLIST: dict[str, str] = {
    "tests/gateway/test_media_download_retry.py::_mock_safe": (
        "class-level @patch on TestCacheImageFromUrl injects it; pytest strips "
        "the first N argnames for N patchings (num_mock_patch_args)"
    ),
    "tests/integration/test_web_tools.py::urls": (
        "defaulted parameter of a method on WebToolsTester, a helper class "
        "pytest never collects"
    ),
}

# Decorator callee -> index of the positional ``new`` argument.  A patcher
# given ``new`` (positionally or by keyword) injects nothing; ``patch.dict``
# and ``patch.multiple`` never inject a positional mock.
_PATCH_INJECTORS = {"patch": 1, "patch.object": 2}

# ``name [module scope] -- path:line`` rows of ``pytest --fixtures -q``.
_FIXTURES_ROW = re.compile(r"^(?P<name>[A-Za-z_]\w*)(?: \[\w+ scope\])? -- ")


@dataclass
class FixtureRequest:
    """The fixture names one collected function would ask pytest for."""

    path: str
    line: int
    test: str  # "Cls.Inner.test_name", as the setup-plan nodeid reads with '.'
    names: list[str]


@dataclass
class ModuleFacts:
    """What one parsed module contributes to fixture visibility."""

    visible: set[str] = field(default_factory=set)
    plugins: list[str] = field(default_factory=list)  # pytest_plugins entries
    star_imports: list[tuple[str, int]] = field(default_factory=list)  # (module, level)
    requests: list[FixtureRequest] = field(default_factory=list)
    error: str = ""  # unreadable / unparsable: the file cannot be judged


def _dotted(node: ast.AST) -> str:
    """``pytest.mark.parametrize`` for a decorator or callee; '' otherwise."""
    if isinstance(node, ast.Call):
        node = node.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _str_list(node: ast.AST | None) -> list[str] | None:
    """Names from ``"a, b"`` or ``["a", "b"]``; None when not a literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [name.strip() for name in node.value.split(",") if name.strip()]
    if isinstance(node, (ast.List, ast.Tuple)):
        out: list[str] = []
        for elt in node.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                return None
            out.append(elt.value.strip())
        return out
    return None


def _mark_names(node: ast.AST) -> tuple[list[str], list[str]]:
    """``(parametrize argnames, usefixtures names)`` one mark contributes."""
    if not isinstance(node, ast.Call):
        return [], []
    name = _dotted(node)
    if name.endswith(".parametrize"):
        arg = node.args[0] if node.args else None
        if arg is None:
            arg = next((k.value for k in node.keywords if k.arg == "argnames"), None)
        return _str_list(arg) or [], []
    if name.endswith(".usefixtures"):
        return [], [n for a in node.args for n in (_str_list(a) or [])]
    return [], []


def _marks_of(value: ast.AST) -> list[ast.AST]:
    """``pytestmark = mark`` or ``pytestmark = [mark, ...]``."""
    return list(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else [value]


def _patch_injections(dec: ast.AST) -> int:
    """1 if this decorator hands the function a positional mock, else 0."""
    if not isinstance(dec, ast.Call):
        return 0
    name = _dotted(dec)
    for tail, new_index in _PATCH_INJECTORS.items():
        if name == tail or name.endswith("." + tail):
            if len(dec.args) > new_index or any(k.arg == "new" for k in dec.keywords):
                return 0
            return 1
    return 0


def _fixture_name(dec: ast.AST, func_name: str) -> str | None:
    """The fixture name a ``@pytest.fixture`` / ``@fixture(name=...)`` defines."""
    name = _dotted(dec)
    if not (name == "fixture" or name.endswith(".fixture")):
        return None
    if isinstance(dec, ast.Call):
        for kw in dec.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
    return func_name


def _argnames(func: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool, mocks: int) -> list[str]:
    """``_pytest.compat.getfuncargnames``: positional-or-keyword and
    keyword-only parameters without defaults, minus ``self`` on a method,
    minus the first ``mocks`` names (what ``@patch`` decorators fill)."""
    args = func.args
    positional = args.args[: len(args.args) - len(args.defaults)]
    names = [p.arg for p in positional]
    names += [p.arg for p, default in zip(args.kwonlyargs, args.kw_defaults) if default is None]
    if is_method and any(_dotted(d) == "staticmethod" for d in func.decorator_list):
        is_method = False
    if is_method:
        names = names[1:]
    return names[mocks:]


def _bound_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _bound_names(elt)]
    return []


def _is_test_class(node: ast.ClassDef) -> bool:
    """Would pytest collect this class as a test class (default python_classes
    ``Test*``, no ``__init__``)?  ``unittest.TestCase`` subclasses are
    collected too but get no fixture ARGUMENTS, so they are out of scope."""
    if not node.name.startswith("Test"):
        return False
    if any(isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name == "__init__" for b in node.body):
        return False
    return not any(_dotted(base).endswith("TestCase") for base in node.bases)


class _ModuleScanner:
    """One pass over a module's AST into a ModuleFacts."""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.facts = ModuleFacts()
        # ``shape = pytest.mark.parametrize("x", ...)`` applied as ``@shape``.
        self.aliases: dict[str, tuple[list[str], list[str]]] = {}

    def _mark_names(self, dec: ast.AST) -> tuple[list[str], list[str]]:
        alias = self.aliases.get(_dotted(dec)) if isinstance(dec, ast.Name) else None
        return alias if alias is not None else _mark_names(dec)

    def scan(self, tree: ast.Module) -> ModuleFacts:
        params, uses = self._marks_in_body(tree.body, module_level=True)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node, prefix="", is_method=False, class_mocks=0, params=params, uses=uses)
            elif isinstance(node, ast.ClassDef):
                self._class(node, prefix="", params=params, uses=uses)
        return self.facts

    def _marks_in_body(self, body: list[ast.stmt], module_level: bool) -> tuple[list[str], list[str]]:
        """Module/class-body assignments: ``pytestmark``, ``pytest_plugins``,
        star imports, and (at module level) every other bound name, which is
        where an imported or factory-built fixture object lives."""
        params: list[str] = []
        uses: list[str] = []
        for node in body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                for name in (n for t in targets for n in _bound_names(t)):
                    if name == "pytestmark" and value is not None:
                        for mark in _marks_of(value):
                            p, u = _mark_names(mark)
                            params += p
                            uses += u
                    elif name == "pytest_plugins" and value is not None:
                        self.facts.plugins += _str_list(value) or []
                    elif module_level:
                        self.facts.visible.add(name)
                        if value is not None:
                            marks = [_mark_names(mark) for mark in _marks_of(value)]
                            if any(p or u for p, u in marks):
                                self.aliases[name] = (
                                    [n for p, _ in marks for n in p],
                                    [n for _, u in marks for n in u],
                                )
            elif isinstance(node, ast.ImportFrom) and module_level:
                for alias in node.names:
                    if alias.name == "*":
                        self.facts.star_imports.append((node.module or "", node.level))
                    else:
                        self.facts.visible.add(alias.asname or alias.name)
        return params, uses

    def _class(self, node: ast.ClassDef, prefix: str, params: list[str], uses: list[str]) -> None:
        if not _is_test_class(node):
            return
        params = list(params)
        uses = list(uses)
        for dec in node.decorator_list:
            p, u = self._mark_names(dec)
            params += p
            uses += u
        p, u = self._marks_in_body(node.body, module_level=False)
        params += p
        uses += u
        class_mocks = sum(_patch_injections(d) for d in node.decorator_list)
        name = prefix + node.name + "."
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(child, name, True, class_mocks, params, uses)
            elif isinstance(child, ast.ClassDef):
                self._class(child, name, params, uses)

    def _function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str,
        is_method: bool,
        class_mocks: int,
        params: list[str],
        uses: list[str],
    ) -> None:
        fixture = next((f for f in (_fixture_name(d, node.name) for d in node.decorator_list) if f), None)
        own_mocks = sum(_patch_injections(d) for d in node.decorator_list)
        if fixture is not None:
            self.facts.visible.add(fixture)
            names = _argnames(node, is_method, own_mocks)
            if names:
                self.facts.requests.append(FixtureRequest(self.rel, node.lineno, prefix + node.name, names))
            return
        if not node.name.startswith("test"):
            return
        params = list(params)
        uses = list(uses)
        for dec in node.decorator_list:
            p, u = self._mark_names(dec)
            params += p
            uses += u
        # unittest.mock's class decorator patches every ``test*`` method.
        names = _argnames(node, is_method, own_mocks + class_mocks)
        names = [n for n in names if n not in params] + [u for u in uses if u not in params]
        if names:
            self.facts.requests.append(FixtureRequest(self.rel, node.lineno, prefix + node.name, names))


def scan_module(repo: Path, rel: str) -> ModuleFacts:
    try:
        source = (repo / rel).read_bytes()
        tree = ast.parse(source, filename=rel)
    except (OSError, SyntaxError, ValueError) as exc:
        facts = ModuleFacts()
        facts.error = "%s: %s" % (type(exc).__name__, exc)
        return facts
    return _ModuleScanner(rel).scan(tree)


def resolve_module(repo: Path, dotted: str, level: int, from_file: str) -> str | None:
    """Repo-relative path of a module named in ``pytest_plugins`` or a star
    import, or None when it lives outside the repo.  Absolute names are tried
    from the repo root and then from the importing file's directory (pytest's
    ``prepend`` import mode puts the test's basedir on ``sys.path``)."""
    tail = Path(*dotted.split(".")) if dotted else Path()
    bases: list[Path]
    if level:
        base = Path(from_file).parent
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        bases = [Path(), Path(from_file).parent]
    for base in bases:
        stem = base / tail
        for candidate in ((stem.with_suffix(".py") if dotted else None), stem / "__init__.py"):
            if candidate is not None and (repo / candidate).is_file():
                return candidate.as_posix()
    return None


def probe_plugin_fixtures(python: str, timeout: float = 120) -> set[str] | None:
    """Fixture names installed plugins provide, from one ``pytest --fixtures``
    in an empty directory (no conftest, no ini); None if the probe failed."""
    with tempfile.TemporaryDirectory(prefix="orphan-fixtures-probe-", ignore_cleanup_errors=True) as tmp:
        argv = [python, "-m", "pytest", "--fixtures", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--rootdir", tmp, tmp]
        try:
            proc = subprocess.run(
                argv,
                cwd=tmp,
                env=subprocess_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    names = {m.group("name") for m in map(_FIXTURES_ROW.match, proc.stdout.decode("utf-8", "replace").splitlines()) if m}
    return names or None


class StaticScanner:
    """AST fixture-visibility scan over scope files and their conftest chain.

    ``plugin_fixtures`` may be passed to skip the probe (tests do); otherwise
    it is probed lazily, once, and only if some name is still unresolved."""

    def __init__(
        self,
        repo: Path,
        python: str | None = None,
        allow: dict[str, str] | None = None,
        plugin_fixtures: set[str] | None = None,
    ) -> None:
        self.repo = repo
        self.python = python
        self.allow = STATIC_ALLOWLIST if allow is None else allow
        self.plugin_fixtures = plugin_fixtures
        self.probed = plugin_fixtures is not None
        self._facts: dict[str, ModuleFacts] = {}

    def facts(self, rel: str) -> ModuleFacts:
        if rel not in self._facts:
            self._facts[rel] = scan_module(self.repo, rel)
        return self._facts[rel]

    def conftest_chain(self, rel: str) -> list[str]:
        """``conftest.py`` files from the repo root down to the file's dir."""
        chain: list[str] = []
        parts = Path(rel).parent.parts
        for depth in range(len(parts) + 1):
            candidate = Path(*parts[:depth]) / "conftest.py"
            if (self.repo / candidate).is_file():
                chain.append(candidate.as_posix())
        return chain

    def visible(self, rel: str) -> tuple[set[str], list[str]]:
        """Names a request in ``rel`` could resolve to, and the reasons (if
        any) the set is incomplete -- a star import outside the repo, an
        unparsable conftest."""
        names = set(CORE_FIXTURES)
        problems: list[str] = []
        pending = [rel] + self.conftest_chain(rel)
        seen: set[str] = set()
        while pending:
            module = pending.pop()
            if module in seen:
                continue
            seen.add(module)
            facts = self.facts(module)
            if facts.error:
                problems.append("%s: %s" % (module, facts.error))
                continue
            names |= facts.visible
            for dotted in facts.plugins:
                target = resolve_module(self.repo, dotted, 0, module)
                if target is None:
                    problems.append("%s: pytest_plugins %r is outside the repo" % (module, dotted))
                else:
                    pending.append(target)
            for dotted, level in facts.star_imports:
                target = resolve_module(self.repo, dotted, level, module)
                if target is None:
                    problems.append("%s: `from %s%s import *` is outside the repo" % (module, "." * level, dotted))
                else:
                    pending.append(target)
        return names, problems

    def scan(self, files: list[str]) -> tuple[list[Orphan], list[tuple[str, str]]]:
        """``(orphans, [(file, why it could not be judged), ...])``."""
        candidates: list[Orphan] = []
        unknowable: list[tuple[str, str]] = []
        for rel in files:
            facts = self.facts(rel)
            if facts.error:
                unknowable.append((rel, facts.error))
                continue
            visible, problems = self.visible(rel)
            if problems:
                unknowable.append((rel, "; ".join(problems)))
                continue
            for req in facts.requests:
                for name in req.names:
                    if name in visible or "%s::%s" % (rel, name) in self.allow:
                        continue
                    candidates.append(Orphan(rel, req.line, req.test, name, via="static"))
        if candidates and not self.probed:
            self.probed = True
            if self.python:
                self.plugin_fixtures = probe_plugin_fixtures(self.python)
        plugin = self.plugin_fixtures or set()
        orphans: list[Orphan] = []
        seen: set[tuple[str, int, str]] = set()
        for orphan in candidates:
            key = (orphan.path, orphan.line, orphan.fixture)
            if orphan.fixture in plugin or key in seen:
                continue
            seen.add(key)
            orphans.append(orphan)
        return orphans, unknowable


def apply_static(results: list[DirectoryResult], scanner: StaticScanner, static_only: bool = False) -> None:
    """Add static findings to each directory's result.  A finding on a test
    the setup-plan set up is dropped: the dynamic run is authoritative
    wherever it reached.  In static-only mode an unjudgeable file is a
    missing verdict; alongside a dynamic run it is informational."""
    for result in results:
        orphans, unknowable = scanner.scan(result.files)
        dynamic = {(o.path, o.test, o.fixture) for o in result.orphans}
        for orphan in orphans:
            if (orphan.path, orphan.test) in result.resolved:
                continue
            if (orphan.path, orphan.test, orphan.fixture) in dynamic:
                continue
            result.orphans.append(orphan)
        result.static_unknowable = list(unknowable)
        if unknowable and static_only:
            result.verdict = False
            result.detail = "static scan could not judge: " + "; ".join("%s (%s)" % pair for pair in unknowable)


# ── CLI ─────────────────────────────────────────────────────────────────────


def check(
    repo: Path,
    scope: dict[str, list[str]],
    python: str | None,
    budget_seconds: float,
    runner=None,
    static: bool = True,
    static_only: bool = False,
    scanner: StaticScanner | None = None,
) -> list[DirectoryResult]:
    if static_only:
        results = [DirectoryResult(directory=d, files=list(f)) for d, f in scope.items()]
    else:
        results = [
            run_directory(python, repo, directory, files, budget_seconds, runner=runner)
            for directory, files in scope.items()
        ]
    if static or static_only:
        apply_static(results, scanner or StaticScanner(repo, python), static_only=static_only)
    return results


def report(results: list[DirectoryResult], out=sys.stdout) -> int:
    orphans = [o for r in results for o in r.orphans]
    static = [o for o in orphans if o.via == "static"]
    no_verdict = [r for r in results if not r.verdict]
    not_collected = [(r.directory, p) for r in results for p in r.collection_errors]
    checked = sum(len(r.files) for r in results if r.verdict)

    for r in results:
        for path in r.collection_errors:
            out.write("NOT CHECKED %s -- did not collect; its fixtures were not resolved\n" % path)
        for path, why in r.static_unknowable:
            out.write("NOT CHECKED (static) %s -- %s\n" % (path, why))
        if not r.verdict:
            out.write("NO VERDICT  %s/ (%d file(s)): %s\n" % (r.directory, len(r.files), r.detail))
    for orphan in orphans:
        out.write("ORPHAN      %s\n" % orphan.render())

    out.write(
        "orphaned-fixture check: %d file(s) in %d dir(s) resolved, %d orphan(s) (%d via static scan), "
        "%d not collected, %d dir(s) without verdict\n"
        % (checked, len(results), len(orphans), len(static), len(not_collected), len(no_verdict))
    )
    if orphans:
        return EXIT_ORPHANS
    if no_verdict:
        return EXIT_NO_VERDICT
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("files", nargs="*", help="changed test files / conftests (default: git diff vs --base)")
    parser.add_argument("--base", help="ref to diff HEAD against (default: first of %s)" % ", ".join(DEFAULT_BASES))
    parser.add_argument("--files-from", help="read changed paths, one per line")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="repository root (default: this checkout)")
    parser.add_argument("--python", help="interpreter with pytest (default: HERMES_PYTEST_PYTHON, .venv, this one)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_SECONDS, help="seconds per directory")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES, help="refuse to judge a wider scope")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--no-static", action="store_true", help="skip the AST visibility scan (setup-plan only)")
    mode.add_argument("--static-only", action="store_true", help="run only the AST visibility scan (no pytest)")
    parser.add_argument(
        "--static-allow",
        action="append",
        default=[],
        metavar="PATH::FIXTURE",
        help="extra static-scan allowlist entry (repeatable); see STATIC_ALLOWLIST",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    changed: list[str] = list(args.files)
    if args.files_from:
        with open(args.files_from, encoding="utf-8") as fh:
            changed.extend(line.strip() for line in fh if line.strip())
    if not changed:
        base = resolve_base(repo, args.base)
        if base is None:
            wanted = (args.base,) if args.base else DEFAULT_BASES
            print("error: none of %s resolves; pass --base <ref> or explicit files" % (wanted,), file=sys.stderr)
            return EXIT_USAGE
        try:
            changed = changed_test_files(repo, base)
        except RuntimeError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return EXIT_USAGE
        print("scope: test files changed since merge-base with %s" % base)

    scope = build_scope(changed, repo)
    total = sum(len(v) for v in scope.values())
    if total == 0:
        print("orphaned-fixture check: no test file in scope -- nothing to resolve")
        return EXIT_CLEAN
    if total > args.max_files:
        print(
            "NO VERDICT  scope is %d test file(s) in %d dir(s), over the --max-files cap (%d) -- "
            "NOT CHECKED. Raise the cap or pass a narrower file list." % (total, len(scope), args.max_files)
        )
        return EXIT_NO_VERDICT

    python = resolve_interpreter(repo, args.python)
    if python is None:
        print("error: no interpreter with pytest (--python, HERMES_PYTEST_PYTHON, or a repo .venv)", file=sys.stderr)
        return EXIT_USAGE

    allow = dict(STATIC_ALLOWLIST)
    for entry in args.static_allow:
        if "::" not in entry:
            print("error: --static-allow expects PATH::FIXTURE, got %r" % entry, file=sys.stderr)
            return EXIT_USAGE
        allow[normalize_path(entry.split("::", 1)[0]) + "::" + entry.split("::", 1)[1]] = "--static-allow"

    what = "static scan only" if args.static_only else ("setup-plan" if args.no_static else "setup-plan + static scan")
    print("orphaned-fixture check: %d file(s) in %d dir(s) via %s (%s)" % (total, len(scope), python, what))
    results = check(
        repo,
        scope,
        python,
        args.budget,
        static=not args.no_static,
        static_only=args.static_only,
        scanner=StaticScanner(repo, python, allow=allow),
    )
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
