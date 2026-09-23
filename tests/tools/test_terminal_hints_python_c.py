"""Recovery hints for the two `python -c` shapes behind half of the cron agents' failed one-liners.

Measured 2026-09-21..23 in profiles/main/state.db: of 10 failed `python -c` calls, 4 typed a
literal backslash-n expecting a newline (SyntaxError: unexpected character after line
continuation character) and 1 chained a `for` after `;`. The other 5 were ordinary logic errors
(wrong import name, wrong column, psutil AccessDenied) that no hint can pre-empt.
"""

from tools import terminal_hints as th
from tools import terminal_tool

CONTINUATION_OUT = (
    'File "<string>", line 1\r\n    import os; p=1;\\nfor e in x:\\n print(e)\r\n'
    "                   ^\r\nSyntaxError: unexpected character after line continuation character"
)
# Exactly what the agent sent: the two characters backslash + n, not a newline.
CONTINUATION_CMD = (
    r"""python -c "import os, json; p=r'C:/x'; entries=[];\nfor e in os.scandir(p):\n entries.append(e.name)\nprint(json.dumps(entries))" """
)
COMPOUND_CMD = (
    "python -c \"import subprocess,json; checks=[1,2]; out=[]; run=lambda a: a;"
    "for rid in checks: out.append(rid) print(json.dumps(out))\""
)
COMPOUND_OUT = 'File "<string>", line 1\r\n    ...\r\n    ^^^\r\nSyntaxError: invalid syntax'


def test_literal_backslash_n_gets_the_continuation_hint():
    hint = th.annotate_failure(CONTINUATION_CMD, 1, CONTINUATION_OUT)
    assert hint and "literal \\n inside `python -c`" in hint and "write_file" in hint


def test_python3_and_exe_spellings_are_recognised():
    for exe in ("python3", "python3.11", "python.exe", r"C:/py/python.exe"):
        cmd = CONTINUATION_CMD.replace("python -c", f"{exe} -c", 1)
        assert th.annotate_failure(cmd, 1, CONTINUATION_OUT), exe


def test_compound_after_semicolon_gets_its_own_hint():
    hint = th.annotate_failure(COMPOUND_CMD, 1, COMPOUND_OUT)
    assert hint and "compound statement" in hint


def test_shell_eaten_backslash_gets_the_quoting_hint():
    """2026-09-23 12:02, tracker: the command held x.replace('\\\\','/') inside a double-quoted
    python -c; the shell halved it and Python saw an unterminated string."""
    cmd = ("C:/Users/diego/.hermes/agent-src/.venv/Scripts/python.exe -c \"import glob,json; fs=[]\n"
           "print(json.dumps([x.replace('\\\\\\\\','/') for x in fs]))\"")
    out = ("File \"<string>\", line 2\r\n    print(json.dumps([x.replace('\\','/') for x in fs]))\r\n"
           "                          ^\r\nSyntaxError: unterminated string literal (detected at line 2)")
    hint = th.annotate_failure(cmd, 1, out)
    assert hint and "shell quoting" in hint and "forward slashes" in hint


def test_no_hint_for_real_newlines_or_other_errors():
    # A heredoc / real newline is fine; the continuation hint must not fire on it.
    real_newlines = CONTINUATION_CMD.replace("\\n", "\n")
    assert th._python_c_continuation_hint(real_newlines, CONTINUATION_OUT) is None
    # Not python -c at all.
    assert th._python_c_continuation_hint("node -e 'a\\nb'", CONTINUATION_OUT) is None
    # A logic error in a python -c one-liner is not these shapes.
    assert th._python_c_compound_hint(
        "python -c \"import resume_quality as r; r.visible_word_count\"",
        "ImportError: cannot import name 'visible_word_count'") is None
    # `python -m pytest -c cfg` is not python -c code.
    assert th._python_c_compound_hint("pytest -c setup.cfg; for x in y", "SyntaxError") is None


def test_description_tells_the_model_before_it_fails():
    line = next(l for l in terminal_tool.TERMINAL_TOOL_DESCRIPTION.split("\n") if l.startswith("Multi-line Python"))
    assert "write_file" in line and "\\n" in line and "`;`" in line
