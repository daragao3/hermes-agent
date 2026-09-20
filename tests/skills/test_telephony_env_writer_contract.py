"""The telephony skill's ``_upsert_env_file`` keeps the ``.env`` round-trip contract.

It rewrites ALL of ``~/.hermes/.env`` to save Twilio credentials, so every
line it never touched has to survive byte-for-byte.  Until 2026-09-20 it read
and wrote plain ``encoding="utf-8"`` with no ``errors=`` and no ``newline=``.
Found by scripts/check_env_writer_contract.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills" / "productivity" / "telephony" / "scripts" / "telephony.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("telephony_skill_env", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_non_utf8_env_preserves_unrelated_bytes(tmp_path):
    # write_bytes fixture: write_text would emit CRLF on Windows and hide the defect.
    mod = load_module()
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"NAME=caf\xe9\nTWILIO_ACCOUNT_SID=old\n")

    mod._upsert_env_file({"TWILIO_ACCOUNT_SID": "new"}, env_path=env_path)

    assert env_path.read_bytes() == b"NAME=caf\xe9\nTWILIO_ACCOUNT_SID=new\n"


def test_update_leaves_untouched_lines_byte_identical(tmp_path):
    mod = load_module()
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"FIRST=1\nTWILIO_ACCOUNT_SID=old\nLAST=3\n")

    mod._upsert_env_file({"TWILIO_ACCOUNT_SID": "new"}, env_path=env_path)

    assert env_path.read_bytes() == b"FIRST=1\nTWILIO_ACCOUNT_SID=new\nLAST=3\n"


def test_lf_is_kept_on_every_platform(tmp_path):
    mod = load_module()
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"FIRST=1\nTWILIO_ACCOUNT_SID=old\n")

    mod._upsert_env_file({"TWILIO_ACCOUNT_SID": "new"}, env_path=env_path)

    assert b"\r\n" not in env_path.read_bytes()


def test_bom_does_not_duplicate_the_first_key(tmp_path):
    """A Notepad BOM would otherwise hide the first key behind U+FEFF, so the
    key match misses and the writer appends a DUPLICATE line."""
    mod = load_module()
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"\xef\xbb\xbfTWILIO_ACCOUNT_SID=old\nOTHER=2\n")

    mod._upsert_env_file({"TWILIO_ACCOUNT_SID": "new"}, env_path=env_path)

    body = env_path.read_bytes()
    assert body.count(b"TWILIO_ACCOUNT_SID=") == 1
    assert b"TWILIO_ACCOUNT_SID=new" in body
