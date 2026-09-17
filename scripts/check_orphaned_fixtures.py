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

WHAT IT DOES NOT CHECK
----------------------
* Tests skipped at collection on this platform (``pytest.mark.skipif`` at
  module/class level, ``pytest.importorskip``) are never set up, so their
  fixtures are not resolved.
* A file that fails to IMPORT is reported as NOT CHECKED, not as an orphan --
  collection errors are the job of the merge collection gate
  (``~/.hermes/ops/merge_collect_check.py``) and of CI.  The line is printed;
  read it.  A directory it declined to judge is not a directory it passed.

USAGE
-----
    python scripts/check_orphaned_fixtures.py                     # vs the trunk (see DEFAULT_BASES)
    python scripts/check_orphaned_fixtures.py --base codex/wave2-hermes-accepted
    python scripts/check_orphaned_fixtures.py tests/x/test_a.py tests/y/conftest.py
    python scripts/check_orphaned_fixtures.py --files-from changed.txt

Exit status:
    0 -- every requested fixture in scope resolved (or the scope was empty)
    1 -- at least one ``fixture '<name>' not found``
    2 -- usage error (base ref does not resolve, no interpreter with pytest)
    3 -- no verdict: a directory timed out, crashed without a pytest summary
         line, or the scope exceeded --max-files.  Distinct from 1 so a caller
         can fail open on it deliberately, never by accident.
"""

from __future__ import annotations

import argparse
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


@dataclass(frozen=True)
class Orphan:
    """One test whose setup could not resolve a fixture."""

    path: str
    line: int
    test: str
    fixture: str

    def render(self) -> str:
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


# ── CLI ─────────────────────────────────────────────────────────────────────


def check(
    repo: Path,
    scope: dict[str, list[str]],
    python: str,
    budget_seconds: float,
    runner=None,
) -> list[DirectoryResult]:
    return [
        run_directory(python, repo, directory, files, budget_seconds, runner=runner)
        for directory, files in scope.items()
    ]


def report(results: list[DirectoryResult], out=sys.stdout) -> int:
    orphans = [o for r in results for o in r.orphans]
    no_verdict = [r for r in results if not r.verdict]
    not_collected = [(r.directory, p) for r in results for p in r.collection_errors]
    checked = sum(len(r.files) for r in results if r.verdict)

    for r in results:
        for path in r.collection_errors:
            out.write("NOT CHECKED %s -- did not collect; its fixtures were not resolved\n" % path)
        if not r.verdict:
            out.write("NO VERDICT  %s/ (%d file(s)): %s\n" % (r.directory, len(r.files), r.detail))
    for orphan in orphans:
        out.write("ORPHAN      %s\n" % orphan.render())

    out.write(
        "orphaned-fixture check: %d file(s) in %d dir(s) resolved, %d orphan(s), "
        "%d not collected, %d dir(s) without verdict\n"
        % (checked, len(results), len(orphans), len(not_collected), len(no_verdict))
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

    print("orphaned-fixture check: %d file(s) in %d dir(s) via %s" % (total, len(scope), python))
    results = check(repo, scope, python, args.budget)
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
