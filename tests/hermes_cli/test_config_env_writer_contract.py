"""``hermes_cli.config``'s split ``.env`` writer keeps the round-trip contract.

``_read_env_lines`` / ``_write_env_lines`` are the canonical pair behind
``hermes config set`` and the dashboard's key writes -- they rewrite ALL of
``~/.hermes/.env`` to change one key, so every untouched line has to survive
byte-for-byte.  Until 2026-09-20 the read used ``errors="replace"``, which
does not raise but turns an undecodable byte into U+FFFD and writes the
replacement back, silently corrupting an unrelated credential.  Found by
scripts/check_env_writer_contract.py.
"""

from __future__ import annotations

from hermes_cli.config import _read_env_lines, _write_env_lines


def _round_trip(env_path, key: str, value: str) -> None:
    """The save_env_value shape: read, replace one key, write back."""
    lines = _read_env_lines(env_path)
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            break
    else:
        lines.append(f"{key}={value}\n")
    _write_env_lines(env_path, lines, preserve_mode=True)


def test_non_utf8_env_preserves_unrelated_bytes(tmp_path):
    # write_bytes fixture: write_text would emit CRLF on Windows and hide the defect.
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"NAME=caf\xe9\nANTHROPIC_API_KEY=old\n")

    _round_trip(env_path, "ANTHROPIC_API_KEY", "new")

    assert env_path.read_bytes() == b"NAME=caf\xe9\nANTHROPIC_API_KEY=new\n"


def test_update_leaves_untouched_lines_byte_identical(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"FIRST=1\nANTHROPIC_API_KEY=old\nLAST=3\n")

    _round_trip(env_path, "ANTHROPIC_API_KEY", "new")

    assert env_path.read_bytes() == b"FIRST=1\nANTHROPIC_API_KEY=new\nLAST=3\n"


def test_lf_is_kept_on_every_platform(tmp_path):
    """newline="\\n" on the write: text mode would turn every untouched LF into
    CRLF on Windows, leaving a \\r in every value for a POSIX shell that sources
    the same file."""
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"FIRST=1\nANTHROPIC_API_KEY=old\n")

    _round_trip(env_path, "ANTHROPIC_API_KEY", "new")

    assert b"\r\n" not in env_path.read_bytes()


def test_bom_does_not_duplicate_the_first_key(tmp_path):
    """A Notepad BOM would otherwise hide the first key behind U+FEFF, so the
    key match misses and the writer appends a DUPLICATE line."""
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"\xef\xbb\xbfANTHROPIC_API_KEY=old\nOTHER=2\n")

    _round_trip(env_path, "ANTHROPIC_API_KEY", "new")

    body = env_path.read_bytes()
    assert body.count(b"ANTHROPIC_API_KEY=") == 1
    assert b"ANTHROPIC_API_KEY=new" in body
