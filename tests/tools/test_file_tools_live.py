"""Live integration tests for file operations and terminal tools.

These tests run REAL commands through the LocalEnvironment -- no mocks.
They verify that shell noise is properly filtered, commands actually work,
and the tool outputs are EXACTLY what the agent would see.

Every test with output validates against a known-good value AND
asserts zero contamination from shell noise via _assert_clean().
"""

import pytest




import os
import sys
import uuid
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


# ── Shared noise detection ───────────────────────────────────────────────
# Known shell noise patterns that should never appear in command output.

_ALL_NOISE_PATTERNS = [
    "bash: cannot set terminal process group",
    "bash: no job control in this shell",
    "no job control in this shell",
    "cannot set terminal process group",
    "tcsetattr: Inappropriate ioctl for device",
    "bash: ",
    "Inappropriate ioctl",
    "Auto-suggestions:",
]


def _assert_clean(text: str, context: str = "output"):
    """Assert text contains zero shell noise contamination."""
    if not text:
        return
    for noise in _ALL_NOISE_PATTERNS:
        assert noise not in text, (
            f"Shell noise leaked into {context}: found {noise!r} in:\n"
            f"{text[:500]}"
        )


# ── Fixtures ─────────────────────────────────────────────────────────────

# Deterministic file content used across tests. Every byte is known,
# so any unexpected text in results is immediately caught.
SIMPLE_CONTENT = "alpha\nbravo\ncharlie\n"
NUMBERED_CONTENT = "\n".join(f"LINE_{i:04d}" for i in range(1, 51)) + "\n"
SPECIAL_CONTENT = "single 'quotes' and \"doubles\" and $VARS and `backticks` and \\backslash\n"
MULTIFILE_A = "def func_alpha():\n    return 42\n"
MULTIFILE_B = "def func_bravo():\n    return 99\n"
MULTIFILE_C = "nothing relevant here\n"


@pytest.fixture
def env(tmp_path):
    """A real LocalEnvironment rooted in a temp directory."""
    return LocalEnvironment(cwd=str(tmp_path), timeout=15)


@pytest.fixture
def ops(env, tmp_path):
    """ShellFileOperations wired to the real local environment."""
    return ShellFileOperations(env, cwd=str(tmp_path))


@pytest.fixture
def populated_dir(tmp_path):
    """A temp directory with known files for search/read tests."""
    (tmp_path / "alpha.py").write_text(MULTIFILE_A)
    (tmp_path / "bravo.py").write_text(MULTIFILE_B)
    (tmp_path / "notes.txt").write_text(MULTIFILE_C)
    (tmp_path / "data.csv").write_text("col1,col2\n1,2\n3,4\n")
    return tmp_path


# ── LocalEnvironment.execute() ───────────────────────────────────────────

class TestLocalEnvironmentExecute:
    def test_echo_exact_output(self, env):
        result = env.execute("echo DETERMINISTIC_OUTPUT_12345")
        assert result["returncode"] == 0
        assert result["output"].strip() == "DETERMINISTIC_OUTPUT_12345"
        _assert_clean(result["output"])

    def test_printf_no_trailing_newline(self, env):
        result = env.execute("printf 'exact'")
        assert result["returncode"] == 0
        assert result["output"] == "exact"
        _assert_clean(result["output"])


    @pytest.mark.skipif(
        os.name == "nt",
        reason="Git Bash pwd reports MSYS mount forms (/c/Users/..., or /tmp "
        "for %TEMP% via the usertemp fstab mount), never the native C:\\ form",
    )
    def test_cwd_respected(self, env, tmp_path):
        subdir = tmp_path / "subdir_test"
        subdir.mkdir()
        result = env.execute("pwd", cwd=str(subdir))
        assert result["returncode"] == 0
        assert result["output"].strip() == str(subdir)
        _assert_clean(result["output"])


    @pytest.mark.skipif(
        os.name == "nt",
        reason="$HOME inside Git Bash is the MSYS form /c/Users/<user>; it "
        "can never equal Path.home()'s native C:\\ form",
    )
    def test_env_var_home(self, env):
        result = env.execute("echo $HOME")
        assert result["returncode"] == 0
        home = result["output"].strip()
        assert home == str(Path.home())
        _assert_clean(result["output"])


    def test_cat_deterministic_content(self, env, tmp_path):
        f = tmp_path / "det.txt"
        # newline="" keeps the bytes LF-exact on Windows (default write_text
        # maps \n -> os.linesep); as_posix() because bash strips backslashes
        # from unquoted words, mangling C:\-style paths.  Both are byte-level
        # no-ops on POSIX.
        f.write_text(SIMPLE_CONTENT, newline="")
        result = env.execute(f"cat {f.as_posix()}")
        assert result["returncode"] == 0
        assert result["output"] == SIMPLE_CONTENT
        _assert_clean(result["output"])


# ── _has_command ─────────────────────────────────────────────────────────

class TestHasCommand:
    def test_finds_echo(self, ops):
        assert ops._has_command("echo") is True


    def test_missing_command(self, ops):
        assert ops._has_command("nonexistent_tool_xyz_abc_999") is False

    def test_rg_or_grep_available(self, ops):
        assert ops._has_command("rg") or ops._has_command("grep"), \
            "Neither rg nor grep found -- search_files will break"


# ── read_file ────────────────────────────────────────────────────────────

class TestReadFile:
    def test_exact_content(self, ops, tmp_path):
        f = tmp_path / "exact.txt"
        f.write_text(SIMPLE_CONTENT)
        result = ops.read_file(str(f))
        assert result.error is None
        # Content has line numbers prepended, check the actual text is there
        assert "alpha" in result.content
        assert "bravo" in result.content
        assert "charlie" in result.content
        assert result.total_lines == 3
        _assert_clean(result.content)


    def test_tilde_expansion(self, ops):
        # Must live under the real $HOME: ShellFileOperations does NOT expand
        # "~" in Python. tools/file_operations.py::_expand_path shells out --
        # `self._exec("echo $HOME")` -- so the value comes from the Git Bash
        # process LocalEnvironment drives, whose environment is fixed when
        # that shell spawns.
        #
        # tests/_home_isolation.redirect_home does NOT work here, and this
        # comment exists because it was tried: it repoints $HOME/%USERPROFILE%/
        # Path.home() inside the *Python* process, the shell keeps the real
        # one, and the test fails with
        # "File not found: /c/Users/diego/.hermes_test_tilde_...".
        #
        # So this is a KNOWN, ACCEPTED write into the real home -- an audit
        # hook over the suite will report it and that report is correct. It is
        # bounded: the name is unique per process/run so two concurrent pytest
        # invocations of this file don't race on a shared fixed path (one
        # unlinking in its finally while the other is mid-read), and the
        # finally-unlink removes it.
        name = f".hermes_test_tilde_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        test_path = Path.home() / name
        try:
            test_path.write_text("TILDE_EXPANSION_OK\n")
            result = ops.read_file(f"~/{name}")
            assert result.error is None
            assert "TILDE_EXPANSION_OK" in result.content
            _assert_clean(result.content)
        finally:
            test_path.unlink(missing_ok=True)


    def test_no_noise_in_content(self, ops, tmp_path):
        f = tmp_path / "noise_check.txt"
        f.write_text("ONLY_THIS_CONTENT\n")
        result = ops.read_file(str(f))
        assert result.error is None
        _assert_clean(result.content)


# ── write_file ───────────────────────────────────────────────────────────

class TestWriteFile:
    def test_write_and_verify(self, ops, tmp_path):
        path = str(tmp_path / "written.txt")
        result = ops.write_file(path, SIMPLE_CONTENT)
        assert result.error is None
        assert result.bytes_written == len(SIMPLE_CONTENT.encode())
        assert Path(path).read_text() == SIMPLE_CONTENT


    def test_roundtrip_read_write(self, ops, tmp_path):
        """Write -> read back -> verify exact match."""
        path = str(tmp_path / "roundtrip.txt")
        ops.write_file(path, SIMPLE_CONTENT)
        result = ops.read_file(path)
        assert result.error is None
        assert "alpha" in result.content
        assert "charlie" in result.content
        _assert_clean(result.content)


# ── patch_replace ────────────────────────────────────────────────────────

class TestPatchReplace:
    def test_exact_replacement(self, ops, tmp_path):
        path = str(tmp_path / "patch.txt")
        Path(path).write_text("hello world\n")
        result = ops.patch_replace(path, "world", "earth")
        assert result.error is None
        assert Path(path).read_text() == "hello earth\n"


    def test_multiline_patch(self, ops, tmp_path):
        path = str(tmp_path / "multi.txt")
        Path(path).write_text("line1\nline2\nline3\n")
        result = ops.patch_replace(path, "line2", "REPLACED")
        assert result.error is None
        assert Path(path).read_text() == "line1\nREPLACED\nline3\n"

    def test_identical_replacement_explains_no_change(self, ops, tmp_path):
        path = str(tmp_path / "unchanged.txt")
        Path(path).write_text("hello world\n")

        result = ops.patch_replace(path, "world", "world")

        assert result.success is False
        assert result.error is not None
        assert "No edit was applied" in result.error
        assert "existing text to replace in old_string" in result.error
        assert "replacement text in new_string" in result.error
        assert Path(path).read_text() == "hello world\n"


# ── search ───────────────────────────────────────────────────────────────

class TestSearch:
    def test_content_search_finds_exact_match(self, ops, populated_dir):
        result = ops.search("func_alpha", str(populated_dir), target="content")
        assert result.error is None
        assert result.total_count >= 1
        assert any("func_alpha" in m.content for m in result.matches)
        for m in result.matches:
            _assert_clean(m.content)
            _assert_clean(m.path)


    def test_search_output_has_zero_noise(self, ops, populated_dir):
        """Dedicated noise check: search must return only real content."""
        result = ops.search("func", str(populated_dir), target="content")
        assert result.error is None
        for m in result.matches:
            _assert_clean(m.content)
            _assert_clean(m.path)


# ── _expand_path ─────────────────────────────────────────────────────────

class TestExpandPath:
    @pytest.mark.skipif(
        os.name == "nt",
        reason="_expand_path resolves ~ by asking the shell for $HOME; Git "
        "Bash answers in MSYS form (/c/Users/<user>), not Path.home()'s "
        "native form",
    )
    def test_tilde_exact(self, ops):
        result = ops._expand_path("~/test.txt")
        expected = f"{Path.home()}/test.txt"
        assert result == expected
        _assert_clean(result)


    @pytest.mark.skipif(
        os.name == "nt",
        reason="_expand_path resolves ~ by asking the shell for $HOME; Git "
        "Bash answers in MSYS form (/c/Users/<user>), not Path.home()'s "
        "native form",
    )
    def test_bare_tilde(self, ops):
        result = ops._expand_path("~")
        assert result == str(Path.home())
        _assert_clean(result)

    def test_tilde_injection_blocked(self, ops):
        """Paths like ~; rm -rf / must NOT execute shell commands."""
        malicious = "~; echo PWNED > /tmp/_hermes_injection_test"
        result = ops._expand_path(malicious)
        # The invalid username (contains ";") should prevent shell expansion.
        # The path should be returned as-is (no expansion).
        assert result == malicious
        # Verify the injected command did NOT execute
        assert not os.path.exists("/tmp/_hermes_injection_test")

    def test_tilde_username_with_subpath(self, ops):
        """~root/file.txt should attempt expansion (valid username)."""
        result = ops._expand_path("~root/file.txt")
        # On most systems ~root expands to /root
        if result != "~root/file.txt":
            assert result.endswith("/file.txt")
            assert "~" not in result


# ── Terminal output cleanliness ──────────────────────────────────────────

class TestTerminalOutputCleanliness:
    """Every command the agent might run must produce noise-free output."""

    def test_echo(self, env):
        result = env.execute("echo CLEAN_TEST")
        assert result["output"].strip() == "CLEAN_TEST"
        _assert_clean(result["output"])

    def test_cat(self, env, tmp_path):
        f = tmp_path / "cat_test.txt"
        # newline="" + as_posix(): LF-exact bytes and a backslash-free path
        # so the assertion holds under Git Bash on Windows too (no-ops on
        # POSIX) — see test_cat_deterministic_content.
        f.write_text("CAT_CONTENT_EXACT\n", newline="")
        result = env.execute(f"cat {f.as_posix()}")
        assert result["output"] == "CAT_CONTENT_EXACT\n"
        _assert_clean(result["output"])


    def test_head(self, env, tmp_path):
        f = tmp_path / "head_test.txt"
        f.write_text(NUMBERED_CONTENT, newline="")
        result = env.execute(f"head -n 3 {f.as_posix()}")
        expected = "LINE_0001\nLINE_0002\nLINE_0003\n"
        assert result["output"] == expected
        _assert_clean(result["output"])

    @pytest.mark.skipif(
        os.name == "nt",
        reason="$HOME inside Git Bash is the MSYS form /c/Users/<user>; it "
        "can never equal Path.home()'s native C:\\ form",
    )
    def test_env_var_expansion(self, env):
        result = env.execute("echo $HOME")
        assert result["output"].strip() == str(Path.home())
        _assert_clean(result["output"])


    def test_command_v_detection(self, env):
        """This is how _has_command works -- must return clean 'yes'."""
        result = env.execute("command -v cat >/dev/null 2>&1 && echo 'yes'")
        assert result["output"].strip() == "yes"
        _assert_clean(result["output"])
