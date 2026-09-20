"""``control_center.apply._apply_threshold_adjust`` keeps the ``.env`` round-trip contract.

It rewrites ALL of ``~/.hermes/.env`` to change one threshold knob, so every
line it never touched has to survive byte-for-byte.  Until 2026-09-20 it read
and wrote plain ``encoding="utf-8"`` with no ``errors=`` and no ``newline=``:
a cp1252 byte anywhere in the user's .env raised UnicodeDecodeError out of the
approval path, a Notepad BOM duplicated the first key, and every untouched
line was rewritten CRLF on Windows.  Found by
scripts/check_env_writer_contract.py.
"""

from __future__ import annotations

import pytest

from control_center import apply as apply_mod


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point the module at a temp .env and neutralise the reversal/changelog
    side effects, which otherwise write into the live ~/.hermes."""
    path = tmp_path / ".env"
    monkeypatch.setattr(apply_mod, "HERMES_ENV", path)
    monkeypatch.setattr(apply_mod, "_write_reversal", lambda pid, rec: tmp_path / "rev.json")
    monkeypatch.setattr(apply_mod, "_record_changelog", lambda rec: None)
    return path


def _adjust(value: str = "0.75"):
    return {
        "proposal_id": "p1",
        "specific_change": f"HERMES_JOBFLOW_PROCEED_THRESHOLD = {value}",
    }


def test_non_utf8_env_preserves_unrelated_bytes(env_file):
    # write_bytes fixture: write_text would emit CRLF on Windows and hide the defect.
    env_file.write_bytes(b"NAME=caf\xe9\nHERMES_JOBFLOW_PROCEED_THRESHOLD=0.5\n")

    ok, note, _rev = apply_mod._apply_threshold_adjust(_adjust("0.75"))

    assert ok, note
    assert env_file.read_bytes() == b"NAME=caf\xe9\nHERMES_JOBFLOW_PROCEED_THRESHOLD=0.75\n"


def test_update_leaves_untouched_lines_byte_identical(env_file):
    env_file.write_bytes(b"FIRST=1\nHERMES_JOBFLOW_PROCEED_THRESHOLD=0.5\nLAST=3\n")

    ok, note, _rev = apply_mod._apply_threshold_adjust(_adjust("0.75"))

    assert ok, note
    assert env_file.read_bytes() == b"FIRST=1\nHERMES_JOBFLOW_PROCEED_THRESHOLD=0.75\nLAST=3\n"


def test_lf_is_kept_on_every_platform(env_file):
    env_file.write_bytes(b"FIRST=1\nHERMES_JOBFLOW_PROCEED_THRESHOLD=0.5\n")

    ok, note, _rev = apply_mod._apply_threshold_adjust(_adjust("0.75"))

    assert ok, note
    assert b"\r\n" not in env_file.read_bytes()


def test_bom_does_not_duplicate_the_first_key(env_file):
    env_file.write_bytes(b"\xef\xbb\xbfHERMES_JOBFLOW_PROCEED_THRESHOLD=0.5\nOTHER=2\n")

    ok, note, _rev = apply_mod._apply_threshold_adjust(_adjust("0.75"))

    assert ok, note
    body = env_file.read_bytes()
    assert body.count(b"HERMES_JOBFLOW_PROCEED_THRESHOLD=") == 1
    assert b"HERMES_JOBFLOW_PROCEED_THRESHOLD=0.75" in body
