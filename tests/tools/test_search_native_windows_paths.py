"""Regression tests: search must hand NATIVE paths to a native ``rg.exe``,
must quote patterns literally, and must never report a failed search as an
empty one.

The defect
----------
``search_files`` returned ``{"total_count": 0}`` for *every* absolute Windows
path.  Three things stacked up:

1. ``_escape_shell_arg`` runs its input through ``_bash_safe_path``, which
   rewrites ``C:/Users/x`` to the MSYS form ``/c/Users/x``.  That is correct
   for the MSYS coreutils this class shells out to (``cat``, ``sed``,
   ``find``, ``grep``) and wrong for a native Windows binary.
2. ``_apply_windows_msys_bash_env_defaults`` sets ``MSYS_NO_PATHCONV=1``, so
   MSYS does not convert ``/c/...`` back on the way into a native argv.
3. ``rg`` on Windows is a native binary (WinGet/scoop/choco all ship the MSVC
   build).  It cannot resolve ``/c/...`` and fails with ``os error 3``.

``_search_files_rg`` then appended ``2>/dev/null``, so the error was discarded
and the caller saw an empty result set.  That is the part that made it cost a
week: the *content* search surfaced the identical failure as a visible error
because it does not redirect stderr, while the *file* search reported
emptiness.  A search that cannot run must not be indistinguishable from a
search that found nothing.

A fourth, same-family bug rode along: a search *pattern* and a *glob* are not
paths, but they went through the same path translator, so ``\\d+`` reached rg
as ``/d+`` and ``foo\\.py`` as ``foo/.py``.

Every test here fails on the pre-fix code and passes after.  The
faked-Windows tests run on any host; the live ones are Windows+rg only.
"""

import os
import platform
import shutil

import pytest

from tools.environments import local as local_mod
from tools.environments.local import (
    LocalEnvironment,
    _bash_safe_path,
    _native_exec_path,
)
from tools.file_operations import (
    ExecuteResult,
    ShellFileOperations,
    _split_rg_files_output,
)


IS_WINDOWS = platform.system() == "Windows"
HAS_RG = shutil.which("rg") is not None

windows_live = pytest.mark.skipif(
    not (IS_WINDOWS and HAS_RG),
    reason="live Windows + ripgrep only",
)


@pytest.fixture
def fake_windows(monkeypatch):
    """Make the path translators behave as they do on Windows, on any host."""
    monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)


def _ops(root):
    return ShellFileOperations(LocalEnvironment(cwd=str(root)), cwd=str(root))


class _CapturingOps(ShellFileOperations):
    """A ShellFileOperations whose ``_exec`` records commands and replays
    canned results, so command construction can be asserted without a shell."""

    def __init__(self, results=None):
        # Deliberately skip __init__: these tests only exercise pure command
        # construction and result parsing, never the terminal backend.
        self.commands: list[str] = []
        self._results = list(results or [])
        self._command_cache = {"rg": True, "find": True, "grep": True}

    def _exec(self, command, cwd=None, timeout=None, stdin_data=None):
        self.commands.append(command)
        if self._results:
            return self._results.pop(0)
        return ExecuteResult(stdout="", exit_code=1)


# ---------------------------------------------------------------------------
# _native_exec_path — pure function
# ---------------------------------------------------------------------------

class TestNativeExecPath:
    def test_noop_off_windows(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        # POSIX paths are real paths off Windows; never rewrite them.
        assert _native_exec_path("/c/Users/x") == "/c/Users/x"
        assert _native_exec_path("/home/diego/src") == "/home/diego/src"

    def test_msys_form_becomes_native(self, fake_windows):
        assert _native_exec_path("/c/Users/diego/.hermes") == r"C:\Users\diego\.hermes"
        assert _native_exec_path("/d/Projects/foo bar") == r"D:\Projects\foo bar"

    def test_cygwin_and_wsl_spellings(self, fake_windows):
        assert _native_exec_path("/cygdrive/c/Users/x") == r"C:\Users\x"
        assert _native_exec_path("/mnt/c/Users/x") == r"C:\Users\x"

    def test_forward_slash_drive_path_is_normalized(self, fake_windows):
        assert _native_exec_path("C:/Users/diego/.hermes") == r"C:\Users\diego\.hermes"

    def test_native_path_is_unchanged_and_idempotent(self, fake_windows):
        native = r"C:\Users\diego\.hermes"
        assert _native_exec_path(native) == native
        assert _native_exec_path(_native_exec_path("/c/Users/diego/.hermes")) == native

    def test_drive_root(self, fake_windows):
        assert _native_exec_path("/c") == "C:\\"
        assert _native_exec_path("C:/") == "C:\\"

    def test_lowercase_drive_letter_is_upper_cased(self, fake_windows):
        assert _native_exec_path("c:/users/x") == r"C:\users\x"

    def test_non_drive_paths_pass_through(self, fake_windows):
        # There is no correct drive-letter answer for these, and a relative
        # path already resolves against the shell's cwd.
        assert _native_exec_path("tools/environments") == "tools/environments"
        assert _native_exec_path("/tmp/scratch") == "/tmp/scratch"
        assert _native_exec_path("") == ""

    def test_is_the_inverse_of_bash_safe_path(self, fake_windows):
        # The two translations are deliberate opposites: _bash_safe_path for
        # MSYS coreutils, _native_exec_path for a native .exe.
        native = r"C:\Users\diego\.hermes"
        assert _bash_safe_path(native) == "/c/Users/diego/.hermes"
        assert _native_exec_path(_bash_safe_path(native)) == native


# ---------------------------------------------------------------------------
# The escapers
# ---------------------------------------------------------------------------

class TestEscapers:
    def test_literal_escaper_preserves_backslashes(self, fake_windows):
        ops = _CapturingOps()
        # A regex, not a path: the backslash must survive verbatim.
        assert ops._escape_shell_literal(r"\d+") == r"'\d+'"
        assert ops._escape_shell_literal(r"foo\.py") == r"'foo\.py'"

    def test_path_escaper_would_have_mangled_the_same_pattern(self, fake_windows):
        # Documents the bug the literal escaper exists to avoid.
        ops = _CapturingOps()
        assert ops._escape_shell_arg(r"\d+") == "'/d+'"

    def test_literal_escaper_still_escapes_single_quotes(self, fake_windows):
        ops = _CapturingOps()
        assert ops._escape_shell_literal("it's") == "'it'\"'\"'s'"

    def test_native_path_arg_keeps_the_drive(self, fake_windows):
        ops = _CapturingOps()
        assert ops._escape_native_path_arg("C:/Users/x") == r"'C:\Users\x'"
        assert ops._escape_native_path_arg("/c/Users/x") == r"'C:\Users\x'"

    def test_native_path_arg_is_a_noop_off_windows(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        ops = _CapturingOps()
        assert ops._escape_native_path_arg("/home/diego/src") == "'/home/diego/src'"


# ---------------------------------------------------------------------------
# Command construction — the direction-sensitive core of the regression
# ---------------------------------------------------------------------------

class TestSearchFilesCommand:
    def test_absolute_drive_path_reaches_rg_in_native_form(self, fake_windows):
        ops = _CapturingOps()
        ops._search_files_rg("*.json", "C:/Users/diego/.hermes/mailbox/matcher/inbox", 50, 0)

        cmd = ops.commands[0]
        assert r"'C:\Users\diego\.hermes\mailbox\matcher\inbox'" in cmd
        # The MSYS form is what a native rg.exe cannot resolve.
        assert "/c/Users" not in cmd

    def test_stderr_is_not_discarded(self, fake_windows):
        ops = _CapturingOps()
        ops._search_files_rg("*.json", "C:/Users/diego/inbox", 50, 0)
        for cmd in ops.commands:
            assert "2>/dev/null" not in cmd

    def test_pipefail_is_set_so_the_error_guard_can_fire(self, fake_windows):
        ops = _CapturingOps()
        ops._search_files_rg("*.json", "C:/Users/diego/inbox", 50, 0)
        # Without pipefail the pipeline reports head's 0 and rg's 2 is lost.
        assert ops.commands[0].startswith("set -o pipefail; ")

    def test_glob_is_quoted_literally(self, fake_windows):
        ops = _CapturingOps()
        ops._search_files_rg(r"foo\.py", "C:/Users/diego", 50, 0)
        assert r"-g '*foo\.py'" in ops.commands[0]

    def test_relative_path_is_left_alone(self, fake_windows):
        ops = _CapturingOps()
        ops._search_files_rg("*.py", "tools", 50, 0)
        assert "'tools'" in ops.commands[0]


class TestSearchContentCommand:
    def test_absolute_drive_path_reaches_rg_in_native_form(self, fake_windows):
        ops = _CapturingOps()
        ops._search_with_rg("needle", "C:/Users/diego/src", None, 50, 0, "content", 0)

        cmd = ops.commands[0]
        assert r"'C:\Users\diego\src'" in cmd
        assert "/c/Users" not in cmd

    def test_regex_backslashes_survive(self, fake_windows):
        ops = _CapturingOps()
        ops._search_with_rg(r"\bdef\s+\w+", "C:/Users/diego/src", None, 50, 0, "content", 0)
        assert r"'\bdef\s+\w+'" in ops.commands[0]

    def test_file_glob_backslashes_survive(self, fake_windows):
        ops = _CapturingOps()
        ops._search_with_rg("needle", "C:/Users/diego/src", r"foo\.py", 50, 0, "content", 0)
        assert r"--glob 'foo\.py'" in ops.commands[0]

    def test_grep_fallback_keeps_msys_paths_but_literal_patterns(self, fake_windows):
        # grep here is a Git Bash binary: it understands /c/... and must keep
        # getting it. Only the pattern changes.
        ops = _CapturingOps()
        ops._search_with_grep(r"\bdef\b", "C:/Users/diego/src", None, 50, 0, "content", 0)

        cmd = ops.commands[0]
        assert r"'\bdef\b'" in cmd
        assert "'/c/Users/diego/src'" in cmd


# ---------------------------------------------------------------------------
# A failed search must not look like an empty one
# ---------------------------------------------------------------------------

_RG_PATH_ERROR = (
    "rg: /c/Users/diego/inbox: IO error for operation on /c/Users/diego/inbox: "
    "The system cannot find the path specified. (os error 3)"
)


class TestFailedSearchIsNotEmpty:
    def test_hard_error_is_surfaced(self, fake_windows):
        ops = _CapturingOps(results=[
            ExecuteResult(stdout=_RG_PATH_ERROR, exit_code=2),  # --sortr attempt
            ExecuteResult(stdout=_RG_PATH_ERROR, exit_code=2),  # plain retry
        ])
        result = ops._search_files_rg("*.json", "C:/Users/diego/inbox", 50, 0)

        assert result.error, "a search that could not run must report an error"
        assert "os error 3" in result.error
        assert result.total_count == 0
        # The error text must never be parsed back as a file.
        assert not result.files

    def test_no_matches_is_still_an_honest_empty_result(self, fake_windows):
        # rg exits 1 when nothing matched. That is not an error.
        ops = _CapturingOps(results=[
            ExecuteResult(stdout="", exit_code=1),
            ExecuteResult(stdout="", exit_code=1),
        ])
        result = ops._search_files_rg("*.nope", "C:/Users/diego/inbox", 50, 0)

        assert result.error is None
        assert result.total_count == 0

    def test_partial_failure_keeps_the_real_results(self, fake_windows):
        # rg exits 2 for a single unreadable directory in a tree that
        # otherwise listed fine. Those paths are real; do not throw them away.
        stdout = "\n".join([
            r"C:\Users\diego\inbox\a.json",
            r"C:\Users\diego\inbox\b.json",
            r"rg: C:\Users\diego\inbox\locked: Access is denied. (os error 5)",
        ])
        ops = _CapturingOps(results=[ExecuteResult(stdout=stdout, exit_code=2)])
        result = ops._search_files_rg("*.json", "C:/Users/diego/inbox", 50, 0)

        assert result.error is None
        assert result.total_count == 2
        assert all(f.endswith(".json") for f in result.files)

    def test_sortr_fallback_still_runs_before_erroring(self, fake_windows):
        # An old rg rejects --sortr with exit 2. The unsorted retry must still
        # happen, and its success must win.
        ops = _CapturingOps(results=[
            ExecuteResult(
                stdout="rg: error parsing flag --sortr: choice 'modified' is unrecognized",
                exit_code=2,
            ),
            ExecuteResult(stdout=r"C:\Users\diego\inbox\a.json", exit_code=0),
        ])
        result = ops._search_files_rg("*.json", "C:/Users/diego/inbox", 50, 0)

        assert len(ops.commands) == 2
        assert "--sortr" in ops.commands[0]
        assert "--sortr" not in ops.commands[1]
        assert result.error is None
        assert result.total_count == 1


class TestSplitRgFilesOutput:
    def test_diagnostics_split_off(self):
        diags, paths = _split_rg_files_output(
            "a.json\nrg: boom: (os error 3)\nb.json\n"
        )
        assert diags == "rg: boom: (os error 3)"
        assert paths == ["a.json", "b.json"]

    def test_a_path_containing_a_space_is_kept(self):
        # The shape-based classifier used for content search discards this
        # one; the prefix-based split for --files must not.
        diags, paths = _split_rg_files_output(r"C:\Users\diego\My Documents\x.json")
        assert diags == ""
        assert paths == [r"C:\Users\diego\My Documents\x.json"]

    def test_blank_lines_dropped(self):
        assert _split_rg_files_output("\n\na.json\n\n") == ("", ["a.json"])


# ---------------------------------------------------------------------------
# Live end-to-end — the falsifier that actually caught this
# ---------------------------------------------------------------------------

@windows_live
class TestLiveWindowsAbsolutePaths:
    @pytest.fixture
    def tree(self, tmp_path):
        # The search root is a SUBDIRECTORY of the ops cwd: the test
        # environment materializes a whole ``hermes_test`` HERMES_HOME in its
        # cwd, and a bare-glob search would otherwise count it.
        root = tmp_path / "tree"
        root.mkdir()
        (root / "SCORE_REQUEST_one.json").write_text('{"needle": 1}\n')
        (root / "SCORE_REQUEST_two.json").write_text('{"needle": 2}\n')
        sub = root / "nested"
        sub.mkdir()
        (sub / "SCORE_REQUEST_three.json").write_text('{"needle": 3}\n')
        return root

    def test_file_search_by_absolute_drive_path(self, tree):
        # tmp_path is already an absolute drive-letter path on Windows -- the
        # exact input that returned total_count 0 for every caller.
        result = _ops(tree)._search_files_rg("SCORE_REQUEST_*.json", str(tree), 50, 0)

        assert result.error is None, result.error
        assert result.total_count == 3, result.files

    def test_file_search_with_forward_slashes(self, tree):
        result = _ops(tree)._search_files_rg(
            "SCORE_REQUEST_*.json", str(tree).replace("\\", "/"), 50, 0
        )
        assert result.total_count == 3, result.files

    def test_results_come_back_as_native_paths(self, tree):
        result = _ops(tree)._search_files_rg("SCORE_REQUEST_*.json", str(tree), 50, 0)

        # Assert the count first: without it this test passes vacuously on the
        # pre-fix code, where the loop iterates an empty list.
        assert len(result.files) == 3, result.files
        for f in result.files:
            assert os.path.isfile(f), f

    def test_missing_root_reports_an_error_not_emptiness(self, tree):
        missing = str(tree / "does_not_exist")
        result = _ops(tree)._search_files_rg("*", missing, 50, 0)

        assert result.error, "a missing root must not read as an empty directory"
        assert result.total_count == 0

    def test_content_search_by_absolute_drive_path_stays_green(self, tree):
        result = _ops(tree)._search_with_rg("needle", str(tree), None, 50, 0, "content", 0)

        assert result.error is None, result.error
        assert result.total_count == 3, result.matches

    def test_content_search_with_a_backslash_regex(self, tree):
        # \d is destroyed by the path translator; it must reach rg intact.
        result = _ops(tree)._search_with_rg(
            r'"needle": \d', str(tree), None, 50, 0, "content", 0
        )
        assert result.error is None, result.error
        assert result.total_count == 3, result.matches


@windows_live
class TestLiveWindowsPublicSearchApi:
    """The same defect through the public entry point — this is the surface
    the ``jobflow-matcher`` cron calls, and the one that reported
    ``{"total_count": 0}`` against a 194-file inbox for a week."""

    @pytest.fixture
    def inbox(self, tmp_path):
        # A subdirectory, not tmp_path itself — see TestLiveWindowsAbsolutePaths.
        root = tmp_path / "inbox"
        root.mkdir()
        for i in range(3):
            (root / f"20260906T14040{i}_SCORE_REQUEST_tracker_{i}.json").write_text(
                '{"kind": "SCORE_REQUEST"}\n'
            )
        return root

    def test_file_search_finds_the_envelopes(self, inbox):
        result = _ops(inbox).search("SCORE_REQUEST_*.json", str(inbox), target="files")

        assert result.error is None, result.error
        assert result.total_count == 3, result.files

    def test_bare_star_lists_the_directory(self, inbox):
        result = _ops(inbox).search("*", str(inbox), target="files")

        assert result.error is None, result.error
        assert result.total_count == 3, result.files

    def test_content_search_finds_the_envelopes(self, inbox):
        result = _ops(inbox).search("SCORE_REQUEST", str(inbox), target="content")

        assert result.error is None, result.error
        assert result.total_count == 3, result.matches
