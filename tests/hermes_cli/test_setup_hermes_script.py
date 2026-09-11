from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup-hermes.sh"


def test_setup_hermes_script_is_valid_shell(bash_syntax_check):
    # Fed on stdin rather than as a path argument: passing a Windows path to
    # `bash -n` makes the verdict depend on which `bash` is first on PATH.
    # See `bash_syntax_check` in conftest.py.
    result = bash_syntax_check(SETUP_SCRIPT.read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_setup_hermes_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux]" in content
    assert "constraints-termux.txt" in content
    assert "$PREFIX/bin" in content
