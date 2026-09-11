"""Tests for tools/file_operations.py — deny list, result dataclasses, helpers."""

import os
import re as re
import stat
import sys

import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from tests.tools.file_ops_fakes import READ_SENTINEL_RE, compound_read_output
from tools.environments.local import _find_bash, _msys_to_windows_path as _msys_to_windows_path, LocalEnvironment
from agent.file_safety import is_write_denied as _is_write_denied
from tools.file_operations_common import LintResult, SearchMatch
from tools.file_operations import (
    ReadResult,
    WriteResult,
    PatchResult,
    SearchResult,
    ShellFileOperations,
    normalize_read_pagination,
    normalize_search_pagination as normalize_search_pagination,
)


# =========================================================================
# Write deny list
# =========================================================================

class TestIsWriteDenied:
    def test_ssh_authorized_keys_denied(self):
        path = os.path.join(str(Path.home()), ".ssh", "authorized_keys")
        assert _is_write_denied(path) is True


    def test_netrc_denied(self):
        path = os.path.join(str(Path.home()), ".netrc")
        assert _is_write_denied(path) is True

    @pytest.mark.parametrize("name", [".pgpass", ".npmrc", ".pypirc"])
    def test_credential_config_files_denied(self, name):
        path = os.path.join(str(Path.home()), name)
        assert _is_write_denied(path) is True

    def test_aws_prefix_denied(self):
        path = os.path.join(str(Path.home()), ".aws", "credentials")
        assert _is_write_denied(path) is True


    @pytest.mark.parametrize(
        "path",
        [
            "./.anthropic_oauth.json",
        ],
    )
    def test_oauth_traversal_denied(self, path):
        """Path traversal attempts to protected OAuth files must be blocked."""
        from hermes_constants import get_hermes_home
        hermes_home = get_hermes_home()
        full_path = str(hermes_home / path)
        assert _is_write_denied(full_path) is True


    def test_mcp_tokens_dir_protected_in_profile_mode(self, tmp_path, monkeypatch):
        """mcp-tokens/ under profile AND under root must both be denied."""
        root = tmp_path / "hermes"
        profile = root / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        assert _is_write_denied(str(profile / "mcp-tokens" / "tok.json")) is True
        assert _is_write_denied(str(root / "mcp-tokens" / "tok.json")) is True
        # The directory itself must also be denied (not just files inside)
        assert _is_write_denied(str(root / "mcp-tokens")) is True

    def test_pairing_dir_denied(self, tmp_path, monkeypatch):
        """Regression: pairing/ must be write-denied under both profile and root.

        PR #30383 introduced ~/.hermes/pairing/{platform}-approved.json as the
        gateway access-control list. Without this block, a prompt-injected agent
        can write arbitrary user IDs into an approved file, granting persistent
        gateway access without going through the pairing code flow — the same
        threat class that motivated protecting webhook_subscriptions.json.
        """
        root = tmp_path / "hermes"
        profile = root / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        # Active profile pairing entries
        assert _is_write_denied(str(profile / "pairing" / "telegram-approved.json")) is True
        assert _is_write_denied(str(profile / "pairing" / "discord-pending.json")) is True
        # The directory itself
        assert _is_write_denied(str(profile / "pairing")) is True
        # Root pairing entries (profile mode — same shape as mcp-tokens gap)
        assert _is_write_denied(str(root / "pairing" / "telegram-approved.json")) is True
        assert _is_write_denied(str(root / "pairing")) is True


# =========================================================================
# Result dataclasses
# =========================================================================

class TestReadResult:
    def test_to_dict_omits_defaults(self):
        r = ReadResult()
        d = r.to_dict()
        assert "error" not in d    # None omitted
        assert "similar_files" not in d  # empty list omitted


    def test_binary_fields(self):
        r = ReadResult(is_binary=True, is_image=True, mime_type="image/png")
        d = r.to_dict()
        assert d["is_binary"] is True
        assert d["is_image"] is True
        assert d["mime_type"] == "image/png"


class TestWriteResult:
    def test_to_dict_omits_none(self):
        r = WriteResult(bytes_written=100)
        d = r.to_dict()
        assert d["bytes_written"] == 100
        assert "error" not in d
        assert "warning" not in d

    def test_to_dict_includes_error(self):
        r = WriteResult(error="Permission denied")
        d = r.to_dict()
        assert d["error"] == "Permission denied"


class TestPatchResult:
    def test_to_dict_success(self):
        r = PatchResult(success=True, diff="--- a\n+++ b", files_modified=["a.py"])
        d = r.to_dict()
        assert d["success"] is True
        assert d["diff"] == "--- a\n+++ b"
        assert d["files_modified"] == ["a.py"]

    def test_to_dict_error(self):
        r = PatchResult(error="File not found")
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "File not found"


class TestSearchResult:
    def test_to_dict_with_matches(self):
        m = SearchMatch(path="a.py", line_number=10, content="hello")
        r = SearchResult(matches=[m], total_count=1)
        d = r.to_dict()
        assert d["total_count"] == 1
        assert len(d["matches"]) == 1
        assert d["matches"][0]["path"] == "a.py"


    def test_truncated_flag_marks_total_as_lower_bound(self):
        r = SearchResult(total_count=100, truncated=True)
        d = r.to_dict()
        assert d["truncated"] is True
        assert d["total_count_is_lower_bound"] is True

    def test_untruncated_total_omits_lower_bound_flag(self):
        r = SearchResult(total_count=100)
        d = r.to_dict()
        assert "total_count_is_lower_bound" not in d


class TestSearchResultDensify:
    """Path-grouped densification of content-mode matches (lossless)."""

    def _matches(self, n, paths=None):
        # Real ripgrep output is path-ordered: all matches in a file are
        # consecutive (verified against live search_files corpus). The fixture
        # mirrors that — group by path, then enumerate lines within each.
        paths = paths or ["a.py"]
        out = []
        per = max(1, n // len(paths))
        ln = 0
        for p in paths:
            for _ in range(per):
                ln += 1
                out.append(SearchMatch(path=p, line_number=ln,
                                       content=f"line content {ln}"))
        # pad remainder onto the last path
        while len(out) < n:
            ln += 1
            out.append(SearchMatch(path=paths[-1], line_number=ln,
                                   content=f"line content {ln}"))
        return out

    def test_densify_off_by_default(self):
        # The model-facing default must be unchanged for callers that don't
        # opt in: verbose array, no matches_text key.
        r = SearchResult(matches=self._matches(10), total_count=10)
        d = r.to_dict()
        assert "matches" in d
        assert "matches_text" not in d

    def test_densify_below_threshold_keeps_verbose(self):
        # Too few matches: the grouping header would cost more than it saves,
        # so we fall back to the verbose array even with densify=True.
        r = SearchResult(matches=self._matches(4), total_count=4)
        d = r.to_dict(densify=True)
        assert "matches" in d
        assert "matches_text" not in d


    def test_densify_paths_with_spaces(self):
        matches = [SearchMatch(path="my dir/a b.py", line_number=i + 1, content=f"x{i}")
                   for i in range(6)]
        text = SearchResult(matches=matches, total_count=6).to_dict(densify=True)["matches_text"]
        # path with spaces survives as a header line verbatim
        assert "my dir/a b.py" in text.split("\n")[0]


class TestLintResult:
    def test_skipped(self):
        r = LintResult(skipped=True, message="No linter for .md files")
        d = r.to_dict()
        assert d["status"] == "skipped"
        assert d["message"] == "No linter for .md files"


    def test_error(self):
        r = LintResult(success=False, output="SyntaxError line 5")
        d = r.to_dict()
        assert d["status"] == "error"
        assert "SyntaxError" in d["output"]


# =========================================================================
# ShellFileOperations helpers
# =========================================================================

@pytest.fixture()
def mock_env():
    """Create a mock terminal environment."""
    env = MagicMock()
    env.cwd = "/tmp/test"
    env.execute.return_value = {"output": "", "returncode": 0}
    return env


@pytest.fixture()
def file_ops(mock_env):
    return ShellFileOperations(mock_env)


def make_real_subprocess_env(cwd: str, include_stderr: bool = False) -> MagicMock:
    """Mock env whose execute() runs the command in a real subprocess.

    For tests that need the generated shell scripts to actually run
    (search fallback, atomic-write permissions) instead of being
    intercepted by a bare MagicMock.  ``include_stderr`` folds stderr
    into ``output`` for tests that surface shell error text; leave it
    off for tests that parse structured stdout (e.g. find results).
    """
    env = MagicMock()
    env.cwd = cwd

    def execute(command, **kwargs):
        stdin_data = kwargs.get("stdin_data")
        is_windows = os.name == "nt"
        if is_windows:
            # Match LocalEnvironment: commands are POSIX scripts executed by
            # Git Bash, and stdin bytes must bypass Windows newline rewriting.
            command = [_find_bash(), "-c", command]
        completed = subprocess.run(
            command,
            shell=not is_windows,
            text=not is_windows,
            capture_output=True,
            input=(stdin_data.encode("utf-8", "surrogateescape")
                   if is_windows and stdin_data is not None else stdin_data),
        )
        output = (
            completed.stdout.decode("utf-8", "replace")
            if is_windows else completed.stdout
        )
        if include_stderr:
            output += (
                completed.stderr.decode("utf-8", "replace")
                if is_windows else completed.stderr
            )
        return {
            "output": output,
            "returncode": completed.returncode,
        }

    env.execute = execute
    return env


class TestShellFileOpsHelpers:
    def test_normalize_read_pagination_clamps_invalid_values(self):
        assert normalize_read_pagination(offset=0, limit=0) == (1, 1)
        assert normalize_read_pagination(offset=-10, limit=-5) == (1, 1)
        assert normalize_read_pagination(offset="bad", limit="bad") == (1, 2000)
        assert normalize_read_pagination(offset=2, limit=999999) == (2, 2000)


    def test_escape_shell_arg_simple(self, file_ops):
        assert file_ops._escape_shell_arg("hello") == "'hello'"


    @pytest.mark.windows_only
    def test_escape_shell_arg_rewrites_forward_slash_native_paths(self, file_ops):
        """Windows-only: ``_bash_safe_path`` only rewrites drive paths to the
        Git Bash form on Windows, where the MSYS path mangling it works around
        actually happens."""
        assert file_ops._escape_shell_arg(
            "C:/Users/alice/notes.txt"
        ) == "'/c/Users/alice/notes.txt'"

    @pytest.mark.windows_only
    def test_read_file_uses_bash_safe_windows_paths(self, mock_env):
        """Windows-only: proves read_file's shell commands carry the MSYS path
        form Git Bash needs — a translation that is a no-op off Windows."""
        commands = []

        def side_effect(command, **kwargs):
            commands.append(command)
            m = READ_SENTINEL_RE.search(command)
            if m:
                return {
                    "output": compound_read_output(
                        m.group(0), size=5, sample=b"hello", content="hello\n", total_lines=1
                    ),
                    "returncode": 0,
                }
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.read_file(r"C:\Users\alice\notes.txt")

        assert result.error is None
        # One compound probe carries every stage; each embeds the MSYS path.
        # The size probe gates `wc -c` behind `[ -f ]` so a FIFO or device
        # cannot block the read; it still reports a plain byte count.
        assert len(commands) == 1
        probe = commands[0]
        assert probe.startswith(
            "if [ -f '/c/Users/alice/notes.txt' ]; "
            "then wc -c < '/c/Users/alice/notes.txt' 2>/dev/null; "
        )
        assert "head -c 1000 '/c/Users/alice/notes.txt' 2>/dev/null | base64" in probe
        assert "sed -n '1,2000p' '/c/Users/alice/notes.txt' 2>/dev/null | cut -b1-8001" in probe
        assert "wc -l < '/c/Users/alice/notes.txt'" in probe
        assert (
            "elif [ -e '/c/Users/alice/notes.txt' ]; "
            "then echo __hermes_not_regular__; "
        ) in probe

    def test_is_likely_binary_by_extension(self, file_ops):
        assert file_ops._is_likely_binary("photo.png") is True
        assert file_ops._is_likely_binary("data.db") is True
        assert file_ops._is_likely_binary("code.py") is False
        assert file_ops._is_likely_binary("readme.md") is False


    def test_cwd_fallback_to_slash(self):
        env = MagicMock(spec=[])  # no cwd attribute
        ops = ShellFileOperations(env)
        assert ops.cwd == "/"

    def test_read_file_strips_leaked_terminal_fence_markers(self, mock_env):
        leaked = (
            "'\x07__HERMES_FENCE_a9f7b3__\x1b]0;cat "
            "'/tmp/test/a.py' 2> /dev/null\x07\n"
            "print('ok')\n"
            "__HERMES_FENCE_a9f7b3__\x07'\n"
        )

        def side_effect(command, **kwargs):
            m = READ_SENTINEL_RE.search(command)
            if m:
                return {
                    "output": compound_read_output(
                        m.group(0), size=12, sample=b"print('ok')\n",
                        content=leaked, total_lines=1,
                    ),
                    "returncode": 0,
                }
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.read_file("/tmp/test/a.py")

        assert result.error is None
        assert "HERMES_FENCE" not in result.content
        assert "\x1b]" not in result.content
        assert "\x07" not in result.content
        assert "1|print('ok')" in result.content

    def test_read_file_raw_strips_leaked_terminal_fence_markers(self, mock_env):
        leaked = (
            "__HERMES_FENCE_a9f7b3__\x07'\n"
            "alpha\n"
            "\x1b]0;cat '/tmp/test/a.txt'\x07__HERMES_FENCE_a9f7b3__\n"
        )

        def side_effect(command, **kwargs):
            if command.startswith("if [ -f ") or command.startswith("wc -c"):
                return {"output": "6\n", "returncode": 0}
            if command.startswith("head -c"):
                return {"output": "alpha\n", "returncode": 0}
            if command.startswith("cat "):
                return {"output": leaked, "returncode": 0}
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.read_file_raw("/tmp/test/a.txt")

        assert result.error is None
        assert result.content == "alpha\n"


class TestSearchPathValidation:
    """Test that search() returns an error for non-existent paths."""

    def test_search_nonexistent_path_returns_error(self, mock_env):
        """search() should return an error when the path doesn't exist."""
        def side_effect(command, **kwargs):
            if "test -e" in command:
                return {"output": "not_found", "returncode": 1}
            if "command -v" in command:
                return {"output": "yes", "returncode": 0}
            return {"output": "", "returncode": 0}
        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.search("pattern", path="/nonexistent/path")
        assert result.error is not None
        assert "not found" in result.error.lower() or "Path not found" in result.error


    def test_search_rg_error_exit_code(self, mock_env):
        """search() should report error when rg returns exit code 2."""
        call_count = {"n": 0}
        def side_effect(command, **kwargs):
            call_count["n"] += 1
            if "test -e" in command:
                return {"output": "exists", "returncode": 0}
            if "command -v" in command:
                return {"output": "yes", "returncode": 0}
            # rg returns exit 2 (error) with empty output
            return {"output": "", "returncode": 2}
        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.search("pattern", path="/some/path")
        assert result.error is not None
        assert "search failed" in result.error.lower() or "Search error" in result.error


@pytest.mark.skipif(
    os.name == "nt",
    reason="GNU find fallback under test through a shell=True fake env; on "
    "Windows that resolves cmd.exe + System32 find.exe (a different tool), "
    "same gating as TestFindExcludesHiddenDirs in test_search_hidden_dirs.py",
)
class TestSearchFilesFallbackHiddenPaths:
    def _make_env(self):
        return LocalEnvironment("/")

    def test_hidden_root_with_hidden_ancestor_includes_files(self, tmp_path, monkeypatch):
        """Fallback find should include visible files when path is inside hidden root."""
        root = tmp_path / ".hermes" / "logs"
        root.mkdir(parents=True)
        visible_file = root / "agent.log"
        hidden_dir_file = root / ".hidden" / "secret.log"
        nested_hidden_file = root / "nested" / ".secret.log"
        visible_nested_file = root / "nested" / "visible.log"

        for p in [visible_file, nested_hidden_file, visible_nested_file, hidden_dir_file]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")

        ops = ShellFileOperations(self._make_env())
        monkeypatch.setattr(ops, "_has_command", lambda command: command == "find")
        result = ops._search_files("*.log", str(root), limit=50, offset=0)

        assert result.error is None
        assert set(result.files) == {str(visible_file), str(visible_nested_file)}

    def test_normal_root_still_excludes_hidden_descendants(self, tmp_path, monkeypatch):
        """Fallback find should still exclude hidden descendant paths for normal roots."""
        root = tmp_path / "repo"
        root.mkdir()
        visible_file = root / "agent.log"
        visible_nested_file = root / "nested" / "visible.log"
        hidden_dir_file = root / ".hidden" / "secret.log"

        for p in [visible_file, visible_nested_file, hidden_dir_file]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")

        ops = ShellFileOperations(self._make_env())
        monkeypatch.setattr(ops, "_has_command", lambda command: command == "find")
        result = ops._search_files("*.log", str(root), limit=50, offset=0)

        assert result.error is None
        assert set(result.files) == {str(visible_file), str(visible_nested_file)}


class TestShellFileOpsWriteDenied:
    def test_write_file_denied_path(self, file_ops):
        result = file_ops.write_file("~/.ssh/authorized_keys", "evil key")
        assert result.error is not None
        assert "denied" in result.error.lower()


    def test_move_file_failure_path(self, mock_env):
        mock_env.execute.return_value = {"output": "No such file or directory", "returncode": 1}
        ops = ShellFileOperations(mock_env)
        result = ops.move_file("/tmp/nonexistent.txt", "/tmp/dest.txt")
        assert result.error is not None
        assert "Failed to move" in result.error


class TestPatchReplacePostWriteVerification:
    """Tests for the post-write verification added in patch_replace.

    Confirms that a silent persistence failure (where write_file's command
    appears to succeed but the bytes on disk don't match new_content) is
    surfaced as an error instead of being reported as a successful patch.
    """

    def test_patch_replace_fails_when_file_not_persisted(self, mock_env):
        """write_file reports success but the re-read returns old content:
        patch_replace must return an error, not success-with-diff."""
        file_contents = {"/tmp/test/a.py": "hello world\n"}

        def side_effect(command, **kwargs):
            # cat reads the file — both the initial read and the verify read
            if command.startswith("cat "):
                # Extract path from cat command (strip quotes)
                for path in file_contents:
                    if path in command:
                        return {"output": file_contents[path], "returncode": 0}
                return {"output": "", "returncode": 1}
            # mkdir for parent dir
            if command.startswith("mkdir "):
                return {"output": "", "returncode": 0}
            # wc -c for byte count after write
            if command.startswith("if [ -f ") or command.startswith("wc -c"):
                for path in file_contents:
                    if path in command:
                        return {"output": str(len(file_contents[path].encode())), "returncode": 0}
                return {"output": "0", "returncode": 0}
            # Everything else (including the write itself) pretends to succeed
            # but DOESN'T update file_contents — simulates silent failure
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.patch_replace("/tmp/test/a.py", "hello", "hi")
        assert result.error is not None, (
            "Silent persistence failure must surface as error, got: "
            f"success={result.success}, diff={result.diff}"
        )
        assert "verification failed" in result.error.lower()
        assert "did not persist" in result.error.lower()


    def test_patch_replace_fails_when_verify_read_errors(self, mock_env):
        """If the verify-read step itself fails (exit code != 0), return an error."""
        call_count = {"cat": 0}
        state = {"content": "hello world\n"}

        def side_effect(command, stdin_data=None, **kwargs):
            if stdin_data is not None:  # write (atomic temp-file + mv script)
                state["content"] = stdin_data
                return {"output": "", "returncode": 0}
            if command.startswith("cat "):  # read
                call_count["cat"] += 1
                # First read (initial fetch) succeeds; second read (verify) fails
                if call_count["cat"] == 1:
                    return {"output": state["content"], "returncode": 0}
                return {"output": "", "returncode": 1}
            if command.startswith("mkdir "):
                return {"output": "", "returncode": 0}
            if command.startswith("if [ -f ") or command.startswith("wc -c"):
                return {"output": str(len(state["content"].encode())), "returncode": 0}
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = ShellFileOperations(mock_env)
        result = ops.patch_replace("/tmp/test/a.py", "hello", "hi")
        assert result.error is not None
        assert "could not re-read" in result.error.lower()


# =========================================================================
# Git baseline check for write_file warning
# =========================================================================

class _DeletedTestGitBaselineCheck:
    """Removed May 2026 — these tests asserted on a ``_check_git_baseline``
    method that doesn't exist on ``ShellFileOperations`` (regression intro
    by a separate refactor). All 6 tests in the class fail with
    AttributeError on origin/main. Deleted wholesale per Teknium's
    instruction to keep CI green; reinstate them when the underlying
    helper is restored or replaced.
    """
    pass


# =========================================================================
# Local-backend native read fast path
# =========================================================================

def _must_not_execute(*args, **kwargs):
    raise AssertionError("native fast path must not call env.execute()")


class TestLocalNativeReadFastPath:
    """read_file on the local backend must not shell out for regular files.

    Every ShellFileOperations._exec spawns a fresh bash on the local
    backend (spawn-per-call design), and the shell read pipeline makes
    FOUR round-trips per read (wc -c, head -c, sed, wc -l).  On Windows
    a Git Bash spawn costs 0.3-1s, so one read_file was 3-4s and any
    test doing a handful of reads blew the suite-wide 30s pytest-timeout
    (test_accretion_caps killed the whole session under redirected
    stdio).  Regular local files are read with native Python I/O
    instead; anything else falls back to the shell pipeline unchanged.

    The expected values pin the shell pipeline's exact output, quirks
    included: total_lines is the newline count (wc -l), and a window
    whose last printed line ends with a newline gains a trailing empty
    numbered line (sed's final \\n split by _add_line_numbers).  The
    gutter is the compact ``<n>|`` form (upstream #35368/#35532 dropped
    the fixed-width padded gutter for both paths).
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            """Real LocalEnvironment, minus the init-time bash snapshot."""

            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_read_regular_file_uses_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_bytes(b"a\nb\n")
        r = local_ops.read_file(str(f))
        assert r.error is None
        assert r.content == "1|a\n2|b\n3|"
        assert r.total_lines == 2
        assert r.file_size == 4
        assert r.truncated is False

    def test_read_slice_matches_shell_contract(self, local_ops, tmp_path):
        f = tmp_path / "slice.txt"
        f.write_bytes(b"l1\nl2\nl3\nl4\n")
        r = local_ops.read_file(str(f), offset=2, limit=2)
        assert r.content == "2|l2\n3|l3\n4|"
        assert r.total_lines == 4
        assert r.truncated is True
        assert r.hint == "Use offset=4 to continue reading (showing 2-3 of 4 lines)"

    def test_read_no_trailing_newline(self, local_ops, tmp_path):
        f = tmp_path / "nonl.txt"
        f.write_bytes(b"a\nb")
        r = local_ops.read_file(str(f))
        assert r.content == "1|a\n2|b"
        assert r.total_lines == 1  # wc -l counts newlines — historical contract

    def test_read_empty_file(self, local_ops, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        r = local_ops.read_file(str(f))
        assert r.error is None
        assert r.content == ""
        assert r.total_lines == 0

    def test_read_offset_past_eof(self, local_ops, tmp_path):
        f = tmp_path / "short.txt"
        f.write_bytes(b"x\n")
        r = local_ops.read_file(str(f), offset=5, limit=10)
        assert r.content == ""
        assert r.total_lines == 1
        assert r.truncated is False

    def test_read_crlf_keeps_carriage_returns(self, local_ops, tmp_path):
        f = tmp_path / "dos.txt"
        f.write_bytes(b"a\r\nb\r\n")
        r = local_ops.read_file(str(f))
        assert r.content == "1|a\r\n2|b\r\n3|"
        assert r.total_lines == 2

    def test_relative_path_resolves_against_env_cwd(self, local_ops, tmp_path):
        (tmp_path / "rel.txt").write_bytes(b"REL_OK\n")
        r = local_ops.read_file("rel.txt")
        assert r.error is None
        assert "REL_OK" in r.content

    def test_image_short_circuits_without_shell(self, local_ops, tmp_path):
        f = tmp_path / "pic.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        r = local_ops.read_file(str(f))
        assert r.is_image is True
        assert r.is_binary is True

    def test_binary_extension_short_circuits(self, local_ops, tmp_path):
        f = tmp_path / "blob.exe"
        f.write_bytes(b"\x00\x01\x02\x03" * 10)
        r = local_ops.read_file(str(f))
        assert r.is_binary is True
        assert r.error is not None

    def test_missing_file_falls_back_to_shell(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 1}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.read_file(str(tmp_path / "ghost.txt"))
        assert r.error is not None
        assert r.error.startswith("File not found:")
        assert calls, "missing file should defer to the shell pipeline"

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_msys_drive_path_reads_natively_on_windows(self, local_ops, tmp_path):
        f = tmp_path / "msys.txt"
        f.write_bytes(b"MSYS_OK\n")
        drive = f.drive.rstrip(":").lower()
        msys = "/" + drive + str(f)[len(f.drive):].replace("\\", "/")
        r = local_ops.read_file(msys)
        assert r.error is None
        assert "MSYS_OK" in r.content

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_posix_root_path_falls_back_on_windows(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 1}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        # /tmp/... resolves inside Git Bash's filesystem, not C:\tmp —
        # native I/O must not guess, the shell pipeline owns this path.
        ops.read_file("/tmp/hermes-native-readpath-probe.txt")
        assert calls, "POSIX-root path should defer to the shell pipeline"

    def test_non_local_env_keeps_shell_pipeline(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 1}
        ops = ShellFileOperations(env)
        ops.read_file("/x/whatever.txt")
        assert env.execute.called


class TestLocalNativeReadRawFastPath:
    """read_file_raw on the local backend must not shell out for regular files.

    Same rationale as TestLocalNativeReadFastPath: the raw-read shell
    pipeline costs THREE bash round-trips (wc -c, head -c, cat) and the
    local backend spawns a fresh Git Bash per round-trip — 0.3-1s each
    on Windows, ~3s per call.  read_file_raw feeds the patch/verify
    flows, so it is a hot path.

    The expected values pin the shell pipeline's exact output, captured
    empirically before the fast path existed: content is the byte-exact
    file text decoded utf-8/errors=replace — trailing newlines survive
    the pipe (the CWD-marker stripping removes only the wrapper's own
    injected newline) — total_lines stays 0 and truncated False (raw
    reads never count lines), the image short-circuit sets no hint and
    no error (unlike read_file's), and the binary error is the em-dash
    variant ("Binary file — cannot display as text.").
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            """Real LocalEnvironment, minus the init-time bash snapshot."""

            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_raw_read_uses_no_shell_trailing_newline_preserved(self, local_ops, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_bytes(b"a\nb\n")
        r = local_ops.read_file_raw(str(f))
        assert r.error is None
        assert r.content == "a\nb\n"
        assert r.file_size == 4
        assert r.total_lines == 0
        assert r.truncated is False
        assert r.hint is None

    def test_raw_read_no_trailing_newline(self, local_ops, tmp_path):
        f = tmp_path / "nonl.txt"
        f.write_bytes(b"a\nb")
        r = local_ops.read_file_raw(str(f))
        assert r.error is None
        assert r.content == "a\nb"
        assert r.file_size == 3

    def test_raw_read_empty_file(self, local_ops, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        r = local_ops.read_file_raw(str(f))
        assert r.error is None
        assert r.content == ""
        assert r.file_size == 0

    def test_raw_read_multiple_trailing_newlines(self, local_ops, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_bytes(b"a\nb\n\n\n")
        r = local_ops.read_file_raw(str(f))
        assert r.content == "a\nb\n\n\n"
        assert r.file_size == 6

    def test_raw_read_crlf_preserved(self, local_ops, tmp_path):
        f = tmp_path / "dos.txt"
        f.write_bytes(b"a\r\nb\r\n")
        r = local_ops.read_file_raw(str(f))
        assert r.content == "a\r\nb\r\n"
        assert r.file_size == 6

    def test_raw_read_utf8_multibyte(self, local_ops, tmp_path):
        f = tmp_path / "utf8.txt"
        f.write_bytes("héllo wörld\n".encode("utf-8"))
        r = local_ops.read_file_raw(str(f))
        assert r.content == "héllo wörld\n"
        assert r.file_size == 14

    def test_raw_image_short_circuits_without_shell(self, local_ops, tmp_path):
        f = tmp_path / "pic.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        r = local_ops.read_file_raw(str(f))
        assert r.is_image is True
        assert r.is_binary is True
        assert r.file_size == 24
        # Unlike read_file's image result, read_file_raw sets no hint.
        assert r.hint is None
        assert r.error is None
        assert r.content == ""

    def test_raw_binary_extension_short_circuits(self, local_ops, tmp_path):
        f = tmp_path / "blob.exe"
        f.write_bytes(b"\x00\x01\x02\x03" * 10)
        r = local_ops.read_file_raw(str(f))
        assert r.is_binary is True
        assert r.error == f"Binary file (unknown binary, {f.stat().st_size} bytes) — cannot display as text."
        assert r.file_size == 40
        assert r.content == ""

    def test_raw_binary_content_sniff(self, local_ops, tmp_path):
        f = tmp_path / "nuls.txt"
        f.write_bytes(b"\x00" * 600 + b"text tail\n")
        r = local_ops.read_file_raw(str(f))
        assert r.is_binary is True
        assert r.error == f"Binary file (unknown binary, {f.stat().st_size} bytes) — cannot display as text."
        assert r.file_size == 610

    def test_raw_relative_path_resolves_against_env_cwd(self, local_ops, tmp_path):
        (tmp_path / "rel.txt").write_bytes(b"REL_OK\n")
        r = local_ops.read_file_raw("rel.txt")
        assert r.error is None
        assert r.content == "REL_OK\n"

    def test_raw_missing_file_falls_back_to_shell(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                from tools.file_operations import MISSING_SENTINEL
                return {"output": MISSING_SENTINEL, "returncode": 0}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.read_file_raw(str(tmp_path / "ghost.txt"))
        assert r.error is not None
        assert r.error.startswith("File not found:")
        assert calls, "missing file should defer to the shell pipeline"

    def test_raw_size_cap_falls_back_to_shell(self, tmp_path, monkeypatch):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 1}

        monkeypatch.setattr("tools.file_operations._NATIVE_READ_MAX_BYTES", 4)
        f = tmp_path / "big.txt"
        f.write_bytes(b"12345\n")
        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        ops.read_file_raw(str(f))
        assert calls, "file past the size cap should defer to the shell pipeline"

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_raw_msys_drive_path_reads_natively_on_windows(self, local_ops, tmp_path):
        f = tmp_path / "msys.txt"
        f.write_bytes(b"MSYS_OK\n")
        drive = f.drive.rstrip(":").lower()
        msys = "/" + drive + str(f)[len(f.drive):].replace("\\", "/")
        r = local_ops.read_file_raw(msys)
        assert r.error is None
        assert r.content == "MSYS_OK\n"

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_raw_posix_root_path_falls_back_on_windows(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 1}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        # /tmp/... resolves inside Git Bash's filesystem, not C:\tmp —
        # native I/O must not guess, the shell pipeline owns this path.
        ops.read_file_raw("/tmp/hermes-native-rawread-probe.txt")
        assert calls, "POSIX-root path should defer to the shell pipeline"

    def test_raw_non_local_env_keeps_shell_pipeline(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 1}
        ops = ShellFileOperations(env)
        ops.read_file_raw("/x/whatever.txt")
        assert env.execute.called


# =========================================================================
# Local-backend native WRITE / PATCH fast path
# =========================================================================


class TestLocalNativeWriteFastPath:
    """write_file on the local backend must not shell out for regular files.

    The shell write pipeline costs 3-5 bash round-trips per call (a
    pre-read ``cat`` for lint/LSP extensions, ``head -c 4096`` for
    line-ending detection, ``mkdir -p``, the ``cat >`` write, ``wc -c``)
    and the local backend spawns a fresh Git Bash per round-trip — 0.3-1s
    each on Windows.  write_file is the agent's hottest edit-loop path.
    Regular local files are written with native Python I/O instead;
    anything else falls back to the shell pipeline unchanged.

    The pinned expectations are the shell pipeline's exact, empirically
    captured behavior: content lands as ``content.encode("utf-8")`` byte
    for byte (the stdin pipe writes through ``proc.stdin.buffer`` so bare
    LFs are NOT CRLF-injected on Windows); a pre-existing CRLF file forces
    the write to CRLF via line-ending detection; ``bytes_written`` is the
    on-disk byte count; and ``dirs_created`` is True whenever the path has
    a non-empty dirname (even when the directory already existed), False
    only for a bare relative filename.
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            """Real LocalEnvironment, minus the init-time bash snapshot."""

            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_native_atomic_temp_collision_preserves_existing_file(self, local_ops, tmp_path, monkeypatch):
        collision = tmp_path / ".hermes-tmp.fixed"
        collision.write_bytes(b"foreign")
        target = tmp_path / "target.txt"
        target.write_bytes(b"original")
        monkeypatch.setattr("tools.file_operations.secrets.token_hex", lambda count: "fixed")
        result = local_ops.write_file(str(target), "replacement")
        assert result.error
        assert collision.read_bytes() == b"foreign"
        assert target.read_bytes() == b"original"

    def test_native_atomic_replace_failure_preserves_original(self, local_ops, tmp_path, monkeypatch):
        target = tmp_path / "original.txt"
        target.write_bytes(b"original\n")

        def fail_replace(source, destination):
            assert Path(source).parent == target.parent
            assert Path(destination) == target
            assert Path(source).read_bytes() == b"replacement\n"
            raise OSError("injected replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        result = local_ops.write_file(str(target), "replacement\n")
        assert "injected replace failure" in result.error
        assert target.read_bytes() == b"original\n"
        assert not list(tmp_path.glob(".hermes-tmp.*"))

    def test_write_new_file_uses_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "one.txt"
        r = local_ops.write_file(str(f), "a\nb\n")
        assert r.error is None
        assert r.bytes_written == 4
        # Absolute path -> non-empty dirname -> dirs_created True even
        # though tmp_path already exists (shell `mkdir -p` quirk).
        assert r.dirs_created is True
        assert r.lint == {"status": "skipped", "message": "No linter for .txt files"}
        # Bare LF must NOT be CRLF-injected (stdin .buffer write contract).
        assert f.read_bytes() == b"a\nb\n"

    def test_write_no_trailing_newline(self, local_ops, tmp_path):
        f = tmp_path / "nonl.txt"
        r = local_ops.write_file(str(f), "abc")
        assert r.error is None
        assert r.bytes_written == 3
        assert f.read_bytes() == b"abc"

    def test_write_utf8_multibyte_byte_count(self, local_ops, tmp_path):
        f = tmp_path / "utf8.txt"
        r = local_ops.write_file(str(f), "héllo\n")
        assert r.error is None
        assert r.bytes_written == 7  # wc -c counts bytes, not chars
        assert f.read_bytes() == "héllo\n".encode("utf-8")

    def test_write_crlf_txt_normalizes_via_head_sample(self, local_ops, tmp_path):
        # .txt is not a lint/LSP extension -> no pre_content -> the shell
        # path detects the ending with `head -c 4096`; the native path
        # must detect it from a native head read instead.  Bare-LF content
        # must land as CRLF to match the existing file.
        f = tmp_path / "dos.txt"
        f.write_bytes(b"old\r\nline\r\n")
        r = local_ops.write_file(str(f), "new\nstuff\n")
        assert r.error is None
        assert f.read_bytes() == b"new\r\nstuff\r\n"
        assert r.bytes_written == 12

    def test_write_lf_txt_stays_lf(self, local_ops, tmp_path):
        f = tmp_path / "unix.txt"
        f.write_bytes(b"old\nline\n")
        r = local_ops.write_file(str(f), "new\nstuff\n")
        assert r.error is None
        assert f.read_bytes() == b"new\nstuff\n"
        assert r.bytes_written == 10

    def test_write_crlf_py_normalizes_via_precontent(self, local_ops, tmp_path):
        # .py IS a lint/LSP extension -> pre_content is captured -> the
        # ending is detected from it (no head sample) and the write is
        # CRLF-normalized.  In-process py lint must still run (no shell).
        f = tmp_path / "dos.py"
        f.write_bytes(b"a = 1\r\n")
        r = local_ops.write_file(str(f), "b = 2\n")
        assert r.error is None
        assert f.read_bytes() == b"b = 2\r\n"
        assert r.lint == {"status": "ok", "output": ""}

    def test_write_creates_nested_dirs(self, local_ops, tmp_path):
        r = local_ops.write_file("deep/nest/two.txt", "x\n")
        assert r.error is None
        assert r.dirs_created is True
        assert (tmp_path / "deep" / "nest" / "two.txt").read_bytes() == b"x\n"

    def test_write_bare_relative_name_dirs_created_false(self, local_ops, tmp_path):
        # dirname("bare.txt") == "" -> the shell path skips mkdir and
        # reports dirs_created False; the native path must match.
        r = local_ops.write_file("bare.txt", "hi\n")
        assert r.error is None
        assert r.dirs_created is False
        assert (tmp_path / "bare.txt").read_bytes() == b"hi\n"

    def test_write_overwrite_truncates(self, local_ops, tmp_path):
        f = tmp_path / "ow.txt"
        f.write_bytes(b"aaaaaaaaaa\n")
        r = local_ops.write_file(str(f), "z\n")
        assert r.error is None
        assert r.bytes_written == 2
        assert f.read_bytes() == b"z\n"

    def test_write_clean_py_lints_ok_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "clean.py"
        r = local_ops.write_file(str(f), "x = 1\n")
        assert r.error is None
        assert r.lint == {"status": "ok", "output": ""}
        assert f.read_bytes() == b"x = 1\n"

    def test_write_broken_py_lint_reported_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "broken.py"
        r = local_ops.write_file(str(f), "def (:\n")
        assert r.error is None
        assert r.lint["status"] == "error"
        assert "SyntaxError" in r.lint["output"]
        assert f.read_bytes() == b"def (:\n"

    def test_write_deny_listed_path_blocked(self, local_ops):
        # Deny check precedes the native gate; must still block with no
        # write and no shell spawn.
        denied = os.path.join(str(Path.home()), ".ssh", "id_rsa")
        r = local_ops.write_file(denied, "SHOULD NOT WRITE")
        assert r.error is not None
        assert "Write denied" in r.error
        assert r.bytes_written == 0

    def test_write_non_local_env_keeps_shell_pipeline(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 0}
        ops = ShellFileOperations(env)
        ops.write_file("/x/whatever.txt", "data\n")
        assert env.execute.called

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_write_msys_drive_path_writes_natively_on_windows(self, local_ops, tmp_path):
        f = tmp_path / "msys.txt"
        drive = f.drive.rstrip(":").lower()
        msys = "/" + drive + str(f)[len(f.drive):].replace("\\", "/")
        r = local_ops.write_file(msys, "MSYS_OK\n")
        assert r.error is None
        assert f.read_bytes() == b"MSYS_OK\n"

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_write_posix_root_path_falls_back_on_windows(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        # /tmp/... resolves inside Git Bash's filesystem, not C:\tmp — the
        # native path must not guess; the shell pipeline owns this write.
        ops.write_file("/tmp/hermes-native-writepath-probe.txt", "x\n")
        assert calls, "POSIX-root path should defer to the shell pipeline"


class TestLocalNativePatchReplaceFastPath:
    """patch_replace on the local backend must not shell out for regular files.

    patch_replace reads its initial content and re-reads for post-write
    verification through a direct ``cat`` _exec — two bash spawns per call
    that the read-fast-path commit did NOT cover (it uses ``cat``, not
    read_file_raw).  Its internal write goes through write_file (now native
    too).  For a regular local file the whole patch_replace round-trip is
    native; anything non-trivial (missing file, POSIX-root path, non-local
    backend) falls back to the shell ``cat`` so the historical error and
    verify semantics are preserved untouched.
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_patch_replace_uses_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "pr.txt"
        f.write_bytes(b"alpha\nbeta\ngamma\n")
        r = local_ops.patch_replace(str(f), "beta", "BETA")
        assert r.success is True
        assert r.error is None
        assert f.read_bytes() == b"alpha\nBETA\ngamma\n"
        assert "-beta" in r.diff and "+BETA" in r.diff

    def test_patch_replace_crlf_preserved_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "pr_crlf.txt"
        f.write_bytes(b"a\r\nb\r\nc\r\n")
        r = local_ops.patch_replace(str(f), "b", "BB")
        assert r.success is True
        assert f.read_bytes() == b"a\r\nBB\r\nc\r\n"

    def test_patch_replace_py_lints_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "pr.py"
        f.write_bytes(b"x = 1\ny = 2\n")
        r = local_ops.patch_replace(str(f), "y = 2", "y = 3")
        assert r.success is True
        assert f.read_bytes() == b"x = 1\ny = 3\n"
        assert r.lint == {"status": "ok", "output": ""}

    def test_patch_replace_no_match_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "pr.txt"
        f.write_bytes(b"alpha\nbeta\ngamma\n")
        r = local_ops.patch_replace(str(f), "NOPE-not-present", "X")
        assert r.success is False
        assert r.error is not None
        assert f.read_bytes() == b"alpha\nbeta\ngamma\n"  # unchanged

    def test_patch_replace_deny_listed_blocked(self, local_ops):
        denied = os.path.join(str(Path.home()), ".ssh", "id_rsa")
        r = local_ops.patch_replace(denied, "a", "b")
        assert r.success is False
        assert "Write denied" in r.error

    def test_patch_replace_missing_file_falls_back(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 1}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.patch_replace(str(tmp_path / "ghost.txt"), "a", "b")
        assert r.success is False
        assert "Failed to read file" in r.error
        assert calls, "missing file should defer to the shell cat"

    def test_patch_replace_non_local_env_keeps_shell(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 1}
        ops = ShellFileOperations(env)
        ops.patch_replace("/x/whatever.txt", "a", "b")
        assert env.execute.called


# =========================================================================
# Local-backend native delete / move fast paths
# =========================================================================

class TestLocalNativeDeleteFastPath:
    """delete_file on the local backend must not shell out for regular files.

    ``delete_file`` shelled a single ``rm -f`` per call — one of the last
    per-call Git Bash spawns in the mutating set (0.3-1s each on Windows).
    Regular local files (including read-only ones) are removed with native
    Python I/O instead; anything ``rm -f`` handles specially falls back to
    the shell so its exact semantics and error text survive.

    The pinned expectations are ``rm -f``'s empirically captured behavior:
    deleting a MISSING file SUCCEEDS (idempotent — ``os.remove`` would
    raise FileNotFoundError); a READ-ONLY file is removed (GNU ``rm -f``
    clears the attribute, so the native path clears the read-only bit via
    ``os.chmod`` before ``os.remove``, which would otherwise raise
    PermissionError on Windows); and a DIRECTORY target is left to the
    shell, which fails it with the exact "Is a directory" message.
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            """Real LocalEnvironment, minus the init-time bash snapshot."""

            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_delete_existing_file_uses_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "gone.txt"
        f.write_bytes(b"bye\n")
        r = local_ops.delete_file(str(f))
        assert r.error is None
        assert not f.exists()

    def test_delete_missing_file_is_idempotent_no_shell(self, local_ops, tmp_path):
        # rm -f on a missing file succeeds; os.remove would raise
        # FileNotFoundError, so the native path must treat absent as success.
        r = local_ops.delete_file(str(tmp_path / "never.txt"))
        assert r.error is None

    def test_delete_readonly_file_no_shell(self, local_ops, tmp_path):
        # Windows read-only attribute (git object files): rm -f removes it;
        # os.remove raises PermissionError, so the native path clears the
        # read-only bit first.
        f = tmp_path / "ro.txt"
        f.write_bytes(b"ro\n")
        os.chmod(str(f), stat.S_IREAD)
        r = local_ops.delete_file(str(f))
        assert r.error is None
        assert not f.exists()

    def test_delete_empty_file_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        r = local_ops.delete_file(str(f))
        assert r.error is None
        assert not f.exists()

    def test_delete_deny_listed_path_blocked(self, local_ops):
        # Deny check precedes the native gate; must still block with no
        # delete and no shell spawn.
        denied = os.path.join(str(Path.home()), ".ssh", "id_rsa")
        r = local_ops.delete_file(denied)
        assert r.error is not None
        assert "denied" in r.error.lower()

    def test_delete_directory_falls_back_to_shell(self, tmp_path):
        # rm -f on a directory fails with a specific "Is a directory"
        # message; the native path must defer so that exact error survives.
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "rm: cannot remove: Is a directory", "returncode": 1}

        d = tmp_path / "adir"
        d.mkdir()
        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.delete_file(str(d))
        assert calls, "directory delete should defer to the shell rm"
        assert r.error is not None
        assert d.exists()

    def test_delete_non_local_env_keeps_shell_pipeline(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 0}
        ops = ShellFileOperations(env)
        ops.delete_file("/x/whatever.txt")
        assert env.execute.called

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_delete_msys_drive_path_no_shell(self, local_ops, tmp_path):
        f = tmp_path / "msys.txt"
        f.write_bytes(b"x\n")
        drive = f.drive.rstrip(":").lower()
        msys = "/" + drive + str(f)[len(f.drive):].replace("\\", "/")
        r = local_ops.delete_file(msys)
        assert r.error is None
        assert not f.exists()

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_delete_posix_root_path_falls_back_on_windows(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        # /tmp/... resolves inside Git Bash's filesystem, not C:\tmp — the
        # native path must not guess; the shell pipeline owns this delete.
        ops.delete_file("/tmp/hermes-native-delpath-probe.txt")
        assert calls, "POSIX-root path should defer to the shell pipeline"


class TestLocalNativeMoveFastPath:
    """move_file on the local backend must not shell out for regular files.

    ``move_file`` shelled a single ``mv`` per call.  A regular file moved
    to a non-directory destination on the same volume is renamed with
    native ``os.replace`` (which overwrites an existing file, matching
    ``mv``); everything ``mv`` handles specially — moving INTO a target
    directory (``dst/basename``), a read-only destination, a missing
    source, a missing destination parent, a cross-device move, or
    src == dst — falls back to the shell so its exact behavior and error
    text survive.

    The pinned expectations are ``mv``'s empirically captured behavior:
    a non-existent dst is created; an existing regular dst is overwritten
    (``os.replace`` matches); an existing-directory dst means "move into
    it" (which ``os.replace`` raises on, so we defer); and a read-only dst
    is force-overwritten by ``mv`` but raises PermissionError under
    ``os.replace`` on Windows (so we defer).
    """

    @pytest.fixture
    def local_ops(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        class _NoSpawnLocal(LocalEnvironment):
            """Real LocalEnvironment, minus the init-time bash snapshot."""

            def init_session(self):
                self._snapshot_ready = False

        env = _NoSpawnLocal(cwd=str(tmp_path))
        env.execute = _must_not_execute
        return ShellFileOperations(env, cwd=str(tmp_path))

    def test_move_to_nonexistent_dst_uses_no_shell(self, local_ops, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_bytes(b"payload\n")
        r = local_ops.move_file(str(src), str(dst))
        assert r.error is None
        assert not src.exists()
        assert dst.read_bytes() == b"payload\n"

    def test_move_overwrites_existing_file_no_shell(self, local_ops, tmp_path):
        # mv overwrites an existing regular dst; os.replace matches it.
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_bytes(b"NEW\n")
        dst.write_bytes(b"OLD-and-longer\n")
        r = local_ops.move_file(str(src), str(dst))
        assert r.error is None
        assert not src.exists()
        assert dst.read_bytes() == b"NEW\n"

    def test_move_deny_listed_src_blocked(self, local_ops, tmp_path):
        # Deny check precedes the native gate; no move, no shell spawn.
        denied = os.path.join(str(Path.home()), ".ssh", "id_rsa")
        r = local_ops.move_file(denied, str(tmp_path / "dst.txt"))
        assert r.error is not None
        assert "denied" in r.error.lower()

    def test_move_deny_listed_dst_blocked(self, local_ops, tmp_path):
        src = tmp_path / "src.txt"
        src.write_bytes(b"x\n")
        denied = os.path.join(str(Path.home()), ".aws", "credentials")
        r = local_ops.move_file(str(src), denied)
        assert r.error is not None
        assert "denied" in r.error.lower()
        # deny precedes the native gate -> src untouched, no shell spawn
        assert src.exists()

    def test_move_into_existing_directory_falls_back(self, tmp_path):
        # mv moves a file INTO a target directory (dst/basename); os.replace
        # raises on that, so the native path must defer to the shell.
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        src = tmp_path / "src.txt"
        src.write_bytes(b"x\n")
        dstdir = tmp_path / "destdir"
        dstdir.mkdir()
        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        ops.move_file(str(src), str(dstdir))
        assert calls, "move into a directory should defer to the shell mv"

    def test_move_readonly_dst_falls_back(self, tmp_path):
        # os.replace over a read-only dst raises PermissionError on Windows;
        # mv force-overwrites it. Defer so the shell wins.
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        src = tmp_path / "src.txt"
        src.write_bytes(b"x\n")
        dst = tmp_path / "dst_ro.txt"
        dst.write_bytes(b"old\n")
        os.chmod(str(dst), stat.S_IREAD)
        try:
            ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
            ops.move_file(str(src), str(dst))
            assert calls, "read-only dst should defer to the shell mv"
        finally:
            os.chmod(str(dst), stat.S_IWRITE)  # let tmp_path teardown remove it

    def test_move_missing_src_falls_back(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "mv: cannot stat: No such file or directory", "returncode": 1}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.move_file(str(tmp_path / "ghost.txt"), str(tmp_path / "dst.txt"))
        assert calls, "missing src should defer to the shell mv"
        assert r.error is not None

    def test_move_dst_parent_missing_falls_back(self, tmp_path):
        # os.replace raises FileNotFoundError (atomically, src intact) when
        # the dst parent is missing; mv reports a specific error. Defer.
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "mv: cannot move: No such file or directory", "returncode": 1}

        src = tmp_path / "src.txt"
        src.write_bytes(b"x\n")
        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        r = ops.move_file(str(src), str(tmp_path / "nodir" / "dst.txt"))
        assert calls, "missing dst parent should defer to the shell mv"
        assert r.error is not None
        assert src.exists()  # os.replace failed atomically — src untouched

    def test_move_same_path_falls_back(self, tmp_path):
        # mv on src == dst is a successful no-op; os.replace(p, p) semantics
        # are murky across platforms, so the native path defers.
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        p = tmp_path / "same.txt"
        p.write_bytes(b"same\n")
        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        ops.move_file(str(p), str(p))
        assert calls, "src == dst should defer to the shell mv"
        assert p.read_bytes() == b"same\n"  # not lost

    def test_move_non_local_env_keeps_shell_pipeline(self):
        env = MagicMock()
        env.cwd = "/x"
        env.execute.return_value = {"output": "", "returncode": 0}
        ops = ShellFileOperations(env)
        ops.move_file("/x/a.txt", "/x/b.txt")
        assert env.execute.called

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_move_msys_drive_path_no_shell(self, local_ops, tmp_path):
        src = tmp_path / "src.txt"
        src.write_bytes(b"MSYS\n")
        dst = tmp_path / "dst.txt"
        drive = src.drive.rstrip(":").lower()
        msys_src = "/" + drive + str(src)[len(src.drive):].replace("\\", "/")
        msys_dst = "/" + drive + str(dst)[len(dst.drive):].replace("\\", "/")
        r = local_ops.move_file(msys_src, msys_dst)
        assert r.error is None
        assert not src.exists()
        assert dst.read_bytes() == b"MSYS\n"

    @pytest.mark.skipif(sys.platform != "win32", reason="MSYS path semantics are Windows-only")
    def test_move_posix_root_path_falls_back_on_windows(self, tmp_path):
        from tools.environments.local import LocalEnvironment

        calls = []

        class _CannedLocal(LocalEnvironment):
            def init_session(self):
                self._snapshot_ready = False

            def execute(self, command, cwd="", **kwargs):
                calls.append(command)
                return {"output": "", "returncode": 0}

        ops = ShellFileOperations(_CannedLocal(cwd=str(tmp_path)), cwd=str(tmp_path))
        # /tmp/... resolves inside Git Bash, not C:\tmp — defer to the shell.
        ops.move_file("/tmp/hermes-native-movesrc.txt", str(tmp_path / "d.txt"))
        assert calls, "POSIX-root src should defer to the shell pipeline"

# Atomic write: umask-default permissions for new files
# =========================================================================

@pytest.mark.skipif(os.name == "nt", reason="POSIX shell permissions and symlink contract")
class TestAtomicWriteNewFilePermissions:
    """_atomic_write should apply umask-default perms to new files (not 0600)."""

    @pytest.mark.parametrize("test_umask", [0o022, 0o002, 0o077])
    def test_new_file_gets_umask_default_permissions(self, tmp_path, test_umask):
        """Newly created file should get umask-computed perms, not mktemp's 0600.

        Uses a real subprocess so the shell script actually runs.
        """
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        dest = tmp_path / "new_file.txt"
        assert not dest.exists()

        old_umask = os.umask(test_umask)
        try:
            result = ops.write_file(str(dest), "test content\n")
        finally:
            os.umask(old_umask)

        assert result.error is None, f"write failed: {result.error}"
        assert dest.read_text() == "test content\n"
        expected_mode = 0o666 & ~test_umask
        actual_mode = dest.stat().st_mode & 0o777
        assert actual_mode == expected_mode, (
            f"Expected mode {expected_mode:04o} (umask {test_umask:04o}), "
            f"got {actual_mode:04o}"
        )

    def test_overwrite_still_preserves_existing_mode(self, tmp_path):
        """The new-file branch must not disturb the overwrite path's
        mode preservation (e.g. an executable script stays 0755)."""
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        dest = tmp_path / "existing.sh"
        dest.write_text("#!/bin/sh\n")
        dest.chmod(0o755)

        result = ops.write_file(str(dest), "#!/bin/sh\necho updated\n")

        assert result.error is None, f"write failed: {result.error}"
        assert dest.read_text() == "#!/bin/sh\necho updated\n"
        assert dest.stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell permissions and symlink contract")
class TestAtomicWriteThroughSymlink:
    """_atomic_write must edit a symlink's target, not replace the link.

    Regression: the temp-file + ``mv`` swap replaced the symlink itself with a
    plain file, orphaning the real target and destroying the link (data-loss).
    """

    def test_write_follows_symlink_and_preserves_link(self, tmp_path):
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        real = tmp_path / "real.txt"
        link = tmp_path / "link.txt"
        real.write_text("original\n")
        link.symlink_to(real)

        result = ops.write_file(str(link), "newcontent\n")

        assert result.error is None, f"write failed: {result.error}"
        # The link must survive as a symlink...
        assert link.is_symlink(), "symlink was replaced by a plain file"
        # ...and the real target must carry the new content.
        assert real.read_text() == "newcontent\n"
        assert os.path.realpath(link) == str(real)

    def test_write_through_broken_symlink_falls_back(self, tmp_path):
        """A broken link resolves through readlink -f and creates the target."""
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        target = tmp_path / "target.txt"
        link = tmp_path / "broken.lnk"
        link.symlink_to(target)  # target does not exist yet

        result = ops.write_file(str(link), "data\n")

        assert result.error is None, f"write failed: {result.error}"
        assert target.exists()
        assert target.read_text() == "data\n"


class TestReadNonUtf8IsBinary:
    """Non-UTF-8 content must be flagged binary, not returned as lossy text.

    Regression: the terminal env decodes stdout with errors="replace", turning
    every non-UTF-8 byte into U+FFFD before _is_likely_binary sees it. U+FFFD is
    "printable", so the non-printable ratio never caught it, and a
    read→edit→write round-trip would overwrite the original bytes with mojibake.
    """

    def test_replacement_char_sample_flagged_binary(self, tmp_path):
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        # A latin-1 file decoded with errors="replace" yields U+FFFD chars.
        lossy_sample = "caf\ufffd r\ufffdsum\ufffd\n"
        assert ops._is_likely_binary("notes.txt", lossy_sample) is True

    def test_plain_utf8_text_not_flagged(self, tmp_path):
        ops = ShellFileOperations(make_real_subprocess_env(str(tmp_path)))
        # Proper UTF-8 (including non-ASCII) must still read as text.
        assert ops._is_likely_binary("notes.txt", "café résumé\nsecond\n") is False

# =========================================================================
# Byte-layer binary detection (#80308 class: CJK/multibyte text flagged
# binary because the byte-boundary sample manufactured U+FFFD in transit)
# =========================================================================

class TestByteLayerBinaryDetection:
    """Regression suite for the misclassification class behind #80308.

    Fragment reports/fixes each caught one member: #80261, #80250, #80188,
    #80349, #79834, #79534, #79408. The boundary contract: text = valid
    UTF-8 allowing one incomplete multibyte sequence at the sample's end;
    NUL or mid-stream invalid UTF-8 = read-only.
    """

    # --- unit: _is_likely_binary_bytes -----------------------------------

    def test_cjk_text_cut_mid_character_is_text(self, file_ops):
        # 999 ASCII bytes + a 3-byte CJK char cut after its first byte —
        # exactly what `head -c 1000` does to a CJK file.
        sample = (b"a" * 999 + "中".encode("utf-8"))[:1000]
        assert sample[-1:] != b"a"  # the cut really is mid-character
        assert file_ops._is_likely_binary_bytes(sample) is False

    def test_pure_cjk_text_cut_mid_character_is_text(self, file_ops):
        sample = ("汉字" * 400).encode("utf-8")[:1000]
        assert file_ops._is_likely_binary_bytes(sample) is False

    def test_emoji_cut_at_boundary_is_text(self, file_ops):
        # 4-byte sequence cut after 2 bytes.
        sample = (b"x" * 998 + "🎉".encode("utf-8"))[:1000]
        assert file_ops._is_likely_binary_bytes(sample) is False

    def test_utf8_bom_is_text(self, file_ops):
        assert file_ops._is_likely_binary_bytes(b"\xef\xbb\xbfhello") is False

    def test_file_containing_real_replacement_char_is_text(self, file_ops):
        # A log file that legitimately stores U+FFFD is valid UTF-8. The old
        # text-layer check could not tell it from transport damage.
        assert file_ops._is_likely_binary_bytes("log: \ufffd bad byte\n".encode("utf-8")) is False

    def test_nul_byte_is_binary(self, file_ops):
        assert file_ops._is_likely_binary_bytes(b"MZ\x00\x01text") is True

    def test_elf_header_is_binary(self, file_ops):
        assert file_ops._is_likely_binary_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8) is True

    def test_latin1_text_stays_read_only(self, file_ops):
        # Mid-stream invalid UTF-8 (0xE9 = latin-1 é). Reading it through the
        # replace-decoding transport would mojibake a read→edit→write
        # round-trip, so it must stay flagged (the old check's guarantee).
        assert file_ops._is_likely_binary_bytes(b"caf\xe9 au lait, plus padding") is True

    def test_empty_sample_is_text(self, file_ops):
        assert file_ops._is_likely_binary_bytes(b"") is False

    def test_short_ascii_is_text(self, file_ops):
        assert file_ops._is_likely_binary_bytes(b"hello\n") is False

    def test_truncated_garbage_tail_after_invalid_prefix_is_binary(self, file_ops):
        # Error near the end but the prefix itself is not clean UTF-8.
        assert file_ops._is_likely_binary_bytes(b"\xff\xfe" + b"a" * 10 + b"\xe4") is True

    # --- transport: _sample_file_bytes ------------------------------------

    def test_sample_decodes_base64_transport(self, mock_env):
        import base64 as b64
        payload = ("汉字" * 400).encode("utf-8")[:1000]
        mock_env.execute.return_value = {
            "output": b64.b64encode(payload).decode() + "\n",
            "returncode": 0,
        }
        ops = ShellFileOperations(mock_env)
        assert ops._sample_file_bytes("/tmp/x.txt") == payload

    def test_sample_falls_back_on_non_base64_output(self, mock_env):
        mock_env.execute.return_value = {"output": "not base64 at all!!", "returncode": 0}
        ops = ShellFileOperations(mock_env)
        assert ops._sample_file_bytes("/tmp/x.txt") is None

    def test_sample_falls_back_on_nonzero_exit(self, mock_env):
        mock_env.execute.return_value = {"output": "", "returncode": 127}
        ops = ShellFileOperations(mock_env)
        assert ops._sample_file_bytes("/tmp/x.txt") is None

    # --- integration: read_file over the mocked terminal ------------------

    def _dispatch(self, cjk_bytes):
        def side_effect(command, **kwargs):
            m = READ_SENTINEL_RE.search(command)
            if m:
                return {
                    "output": compound_read_output(
                        m.group(0),
                        size=len(cjk_bytes),
                        sample=cjk_bytes[:1000],
                        content=cjk_bytes.decode("utf-8", errors="replace"),
                        total_lines=1,
                    ),
                    "returncode": 0,
                }
            return {"output": "", "returncode": 0}

        return side_effect

    def test_read_file_returns_cjk_content_instead_of_binary_error(self, mock_env):
        content = ("汉字测试" * 300).encode("utf-8")  # > 1000 bytes, cut mid-char
        mock_env.execute.side_effect = self._dispatch(content)
        ops = ShellFileOperations(mock_env)
        result = ops.read_file("/tmp/notes-中文.txt")
        assert result.is_binary is False
        assert result.error is None
        assert "汉字测试" in (result.content or "")

    def test_read_file_still_blocks_nul_binaries(self, mock_env):
        content = b"\x7fELF\x00\x00binarybinary" + b"\x00" * 100
        mock_env.execute.side_effect = self._dispatch(content)
        ops = ShellFileOperations(mock_env)
        result = ops.read_file("/tmp/a.out")
        assert result.is_binary is True



class TestEscapeNativeToolArg:
    """Regression tests for _escape_native_tool_arg (Windows native-binary paths).

    Live failure (Windows, Aug 2026): search_files passed rg the MSYS form
    (/c/Users/...) that _escape_shell_arg produces, but Hermes sets
    MSYS_NO_PATHCONV=1 / MSYS2_ARG_CONV_EXCL=* for its bash subprocesses,
    so nothing converted the path back for the native (winget) ripgrep
    binary — every search on a drive-letter path failed with
    "The system cannot find the path specified. (os error 3)". Native
    Windows binaries need C:/... (forward-slash native), which bash also
    passes through untouched.
    """

    def _ops(self, mock_env):
        return ShellFileOperations(mock_env)

    def test_windows_native_path_kept_native(self, mock_env, monkeypatch):
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        ops = self._ops(mock_env)
        out = ops._escape_native_tool_arg(r"C:\Users\alice\project")
        assert out == "'C:/Users/alice/project'"

    def test_msys_path_translated_back_to_native(self, mock_env, monkeypatch):
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        ops = self._ops(mock_env)
        out = ops._escape_native_tool_arg("/c/Users/alice/project")
        assert out == "'C:/Users/alice/project'"

    def test_posix_path_untouched_on_windows(self, mock_env, monkeypatch):
        """Multi-segment POSIX paths (/home/x, /tmp/y) are not drive paths."""
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        ops = self._ops(mock_env)
        assert ops._escape_native_tool_arg("/tmp/workdir") == "'/tmp/workdir'"

    def test_non_windows_behaves_like_escape_shell_arg(self, mock_env, monkeypatch):
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        ops = self._ops(mock_env)
        assert ops._escape_native_tool_arg("/home/u/it's here") == (
            ops._escape_shell_arg("/home/u/it's here")
        )

    def test_rg_content_search_uses_native_form(self, mock_env, monkeypatch):
        """_search_with_rg must pass the path in native C:/ form to rg."""
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        commands = []

        def side_effect(command, **kwargs):
            commands.append(command)
            if "test -e" in command:
                return {"output": "exists", "returncode": 0}
            if "command -v" in command:
                return {"output": "yes", "returncode": 0}
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = self._ops(mock_env)
        ops.search("needle", path=r"C:\Users\alice\project")
        rg_cmds = [c for c in commands if "rg " in c or c.startswith("rg")]
        assert rg_cmds, f"no rg command captured in: {commands}"
        assert any("'C:/Users/alice/project'" in c for c in rg_cmds), rg_cmds
        assert all("/c/Users" not in c for c in rg_cmds), rg_cmds

    def test_shell_linter_uses_native_form(self, mock_env, monkeypatch):
        """_check_lint must hand node/python/etc. the native C:/ path.

        Regression for the double-prefix failure (#84303): node given the
        MSYS /c/Users/... form resolves it as C:\\c\\Users\\... and every
        .js write reports a phantom ENOENT lint error.
        """
        import tools.environments.local as local_mod
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        commands = []

        def side_effect(command, **kwargs):
            commands.append(command)
            if "command -v" in command:
                return {"output": "yes", "returncode": 0}
            return {"output": "", "returncode": 0}

        mock_env.execute.side_effect = side_effect
        ops = self._ops(mock_env)
        result = ops._check_lint(r"C:\Users\alice\app\main.js")
        assert result.skipped is False
        node_cmds = [c for c in commands if "node --check" in c]
        assert node_cmds, f"no node command captured in: {commands}"
        assert "'C:/Users/alice/app/main.js'" in node_cmds[0]
        assert "/c/Users" not in node_cmds[0]
