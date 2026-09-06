r"""A redirect that names a Windows device must never become a real file.

Regression for the 2026-08-31 stray `profiles/tailor/workspace/NUL`: a tailor
subagent validated a generated package with

    python -m json.tool "<...>/qa-responses.json" > NUL

meaning "discard the pretty-printed copy". Under cmd.exe or PowerShell that is
exactly what happens. But the local backend runs commands under MSYS bash (Git
Bash), which resolves paths itself instead of handing them to Win32 DOS-device
parsing, so `NUL` was an ordinary relative filename: the redirect wrote a real
4377-byte file into the agent's cwd holding the full application package.

The file was then unreachable to every Win32 caller — `del`, `Remove-Item` and
`os.remove` all resolve `NUL` to the null device, so they no-op or fail against
the device while the directory entry survives. It took an extended-length
``\\?\`` path to delete.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tools.environments.base import BaseEnvironment
from tools.environments.local import LocalEnvironment
from tools.terminal_tool import (
    _is_windows_device_word,
    _rewrite_windows_device_redirects,
)


class TestDeviceWordDetection:
    @pytest.mark.parametrize(
        "word",
        ["NUL", "nul", "Nul", "CON", "PRN", "AUX", "COM1", "COM9", "LPT1", "LPT9"],
    )
    def test_reserved_names_detected_case_insensitively(self, word):
        assert _is_windows_device_word(word)

    @pytest.mark.parametrize("word", ["NUL.txt", "nul.log", "COM1.dat"])
    def test_extension_does_not_rescue_a_device_name(self, word):
        # Win32 resolves `NUL.txt` to the device too, so a file MSYS creates
        # under that name is just as unreachable as a bare `NUL`.
        assert _is_windows_device_word(word)

    @pytest.mark.parametrize(
        "word",
        [
            "null",  # POSIX-ish, not a device
            "console.log",
            "communication",
            "lptx",
            "com0",
            "com10",
            "output",
            "",
        ],
    )
    def test_ordinary_filenames_are_left_alone(self, word):
        assert not _is_windows_device_word(word)

    @pytest.mark.parametrize("word", ["'NUL'", '"NUL"', "logs/NUL", "./NUL", "$NUL"])
    def test_quoted_or_path_qualified_targets_are_taken_at_face_value(self, word):
        # Quoting is how a caller says it means a literal filename.
        assert not _is_windows_device_word(word)


class TestRedirectRewrite:
    @pytest.mark.parametrize(
        "command,expected",
        [
            ("cmd > NUL", "cmd > /dev/null"),
            ("cmd >NUL", "cmd >/dev/null"),
            ("cmd >> NUL", "cmd >> /dev/null"),
            ("cmd >>nul", "cmd >>/dev/null"),
            ("cmd 2> NUL", "cmd 2> /dev/null"),
            ("cmd 2>NUL", "cmd 2>/dev/null"),
            ("cmd &> NUL", "cmd &> /dev/null"),
            ("cmd > CON", "cmd > /dev/null"),
            ("cmd > COM1", "cmd > /dev/null"),
        ],
    )
    def test_device_targets_are_repointed(self, command, expected):
        rewritten, count = _rewrite_windows_device_redirects(command)
        assert rewritten == expected
        assert count == 1

    def test_the_exact_2026_08_31_command(self):
        original = (
            'python -m json.tool "C:/Users/diego/.hermes/profiles/tailor/'
            'workspace/applications/4439962516/qa-responses.json" > NUL'
        )
        rewritten, count = _rewrite_windows_device_redirects(original)
        assert count == 1
        assert rewritten.endswith("> /dev/null")
        assert "> NUL" not in rewritten

    @pytest.mark.parametrize(
        "command",
        [
            "cmd >/dev/null",  # already correct
            "cmd > output.txt",
            "cmd > null",
            "cmd > console.log",
            "cmd 2>&1",
            "cmd > 'NUL'",  # quoted: caller means a filename
            'cmd > "NUL"',
            "echo NUL",  # not a redirect target at all
            "grep NUL file.txt",
            "cmd | tee NUL",  # tee's argument is not a redirect
        ],
    )
    def test_commands_without_a_device_redirect_are_untouched(self, command):
        rewritten, count = _rewrite_windows_device_redirects(command)
        assert rewritten == command
        assert count == 0

    def test_multiple_targets_in_one_command(self):
        rewritten, count = _rewrite_windows_device_redirects("a > NUL && b 2> nul")
        assert rewritten == "a > /dev/null && b 2> /dev/null"
        assert count == 2

    def test_heredoc_bodies_are_never_touched(self):
        # Rewriting inside a heredoc would corrupt the document being written —
        # worse than the stray file this guards against.
        command = "cat > notes.md <<'EOF'\nOn Windows use: cmd > NUL\nEOF"
        rewritten, count = _rewrite_windows_device_redirects(command)
        assert rewritten == command
        assert count == 0

    def test_comments_are_not_rewritten(self):
        command = "ls\n# on Windows you would write cmd > NUL\nls"
        rewritten, count = _rewrite_windows_device_redirects(command)
        assert rewritten == command
        assert count == 0

    def test_a_device_named_argument_is_not_a_redirect_target(self):
        # `NUL` reached as a positional argument is the caller's business.
        rewritten, count = _rewrite_windows_device_redirects("python script.py NUL")
        assert rewritten == "python script.py NUL"
        assert count == 0


class TestBackendGating:
    def test_local_backend_opts_in_only_on_windows(self):
        assert LocalEnvironment._msys_windows_device_redirects == (os.name == "nt")

    def test_sandboxed_backends_stay_posix(self):
        # On a Linux container `NUL` is an ordinary filename; rewriting it there
        # would destroy the caller's intent.
        assert BaseEnvironment._msys_windows_device_redirects is False


@pytest.mark.skipif(os.name != "nt", reason="MSYS device-name semantics are Windows-only")
class TestMsysActuallyCreatesTheFile:
    """The premise, live: this is why the rewrite has to exist."""

    @staticmethod
    def _bash():
        from tools.environments.local import _find_bash

        try:
            return _find_bash()
        except Exception:  # pragma: no cover - no Git Bash on this host
            pytest.skip("Git Bash unavailable")

    def _run(self, bash, workdir, command):
        subprocess.run(
            [bash, "--noprofile", "--norc", "-c", command],
            cwd=workdir,
            capture_output=True,
            timeout=60,
        )

    def test_bare_nul_redirect_creates_a_real_file(self):
        bash = self._bash()
        with tempfile.TemporaryDirectory() as workdir:
            self._run(bash, workdir, "echo payload > NUL")
            entries = os.listdir(workdir)
            assert entries == ["NUL"], (
                "MSYS bash is expected to create a real file here — if this "
                "fails the premise changed and the rewrite may be obsolete"
            )
            # Prove the Win32 side cannot clear it, which is what made the
            # original stray file so awkward.
            with pytest.raises(OSError):
                os.remove(str(Path(workdir) / "NUL"))
            # Extended-length path bypasses Win32 name parsing.
            os.remove("\\\\?\\" + str(Path(workdir) / "NUL"))

    def test_rewritten_command_creates_nothing(self):
        bash = self._bash()
        rewritten, count = _rewrite_windows_device_redirects("echo payload > NUL")
        assert count == 1
        with tempfile.TemporaryDirectory() as workdir:
            self._run(bash, workdir, rewritten)
            assert os.listdir(workdir) == [], (
                "the rewritten command must discard, not write"
            )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
