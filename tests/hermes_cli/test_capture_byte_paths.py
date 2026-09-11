"""Machine-readable Git path bytes must survive bounded file capture."""
import sys

from hermes_cli._subprocess_compat import run_text_capture


def test_binary_capture_preserves_nul_crlf_and_non_utf8_bytes():
    result = run_text_capture(
        [sys.executable, "-c", "import os; os.write(1, b' leading\\x00raw-\\xff\\r\\nname\\x00'); os.write(2, b'bad-\\xff')"],
        timeout=5, text=False,
    )
    assert result.returncode == 0
    assert result.stdout == b" leading\x00raw-\xff\r\nname\x00"
    assert result.stderr == b"bad-\xff"


def test_text_capture_keeps_existing_decode_and_newline_contract():
    result = run_text_capture(
        [sys.executable, "-c", "import os; os.write(1, b'bad-\\xff\\r\\n')"], timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout == "bad-\ufffd\n"
