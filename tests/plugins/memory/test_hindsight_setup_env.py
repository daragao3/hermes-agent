"""The Hindsight setup wizard's ``.env`` writer keeps the round-trip contract every Hermes
``.env`` writer follows: untouched lines stay byte-identical and LF stays LF on every platform
(``hermes_cli.config._write_env_lines``; 890e5ab0f1 for the OpenViking writer)."""

from plugins.memory.hindsight.setup import _write_env


def test_update_leaves_untouched_lines_byte_identical(tmp_path):
    # write_bytes fixture: write_text would emit CRLF on Windows and hide the defect.
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"FIRST=1\nHINDSIGHT_API_KEY=old\nLAST=3\n")

    _write_env(env_path, {"HINDSIGHT_API_KEY": "new"})

    assert env_path.read_bytes() == b"FIRST=1\nHINDSIGHT_API_KEY=new\nLAST=3\n"


def test_append_and_new_file_use_lf(tmp_path):
    env_path = tmp_path / ".env"

    _write_env(env_path, {"HINDSIGHT_API_KEY": "k"})
    assert env_path.read_bytes() == b"HINDSIGHT_API_KEY=k\n"

    _write_env(env_path, {"HINDSIGHT_API_URL": "http://localhost:8888"})
    assert env_path.read_bytes() == b"HINDSIGHT_API_KEY=k\nHINDSIGHT_API_URL=http://localhost:8888\n"


def test_non_utf8_env_preserves_unrelated_bytes(tmp_path):
    # Same contract as the OpenViking writer (38175b8c22): an undecodable byte on an
    # UNRELATED line (a Windows editor saving cp1252) round-trips unchanged instead of
    # raising UnicodeDecodeError in the wizard.
    env_path = tmp_path / ".env"
    env_path.write_bytes(b"NAME=caf\xe9\nHINDSIGHT_API_KEY=old\n")

    _write_env(env_path, {"HINDSIGHT_API_KEY": "new"})

    assert env_path.read_bytes() == b"NAME=caf\xe9\nHINDSIGHT_API_KEY=new\n"
