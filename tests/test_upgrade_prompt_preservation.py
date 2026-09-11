"""Logical prompt preservation for already-deduplicated local snapshots."""
from contextlib import closing
import hashlib
import shutil
import sqlite3

import pytest


@pytest.mark.parametrize("tamper", [False, True])
def test_preservation_of_already_hashed_prompt(tmp_path, tamper):
    from hermes_state_conversion import _verify_preserved_rows

    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    prompt = "preserve this source prompt"
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    with closing(sqlite3.connect(source)) as conn:
        conn.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY, system_prompt TEXT, system_prompt_hash TEXT);"
            "CREATE TABLE system_prompts(hash TEXT PRIMARY KEY, prompt TEXT);"
        )
        conn.execute("INSERT INTO system_prompts VALUES (?,?)", (digest, prompt))
        conn.execute("INSERT INTO sessions VALUES ('session',NULL,?)", (digest,))
        conn.commit()
    before = source.read_bytes()
    shutil.copyfile(source, target)
    with closing(sqlite3.connect(target.as_uri() + "?mode=rw", uri=True)) as conn:
        if tamper:
            conn.execute("UPDATE system_prompts SET prompt='changed prompt'")
            conn.commit()
            with pytest.raises(RuntimeError, match="did not preserve source rows"):
                _verify_preserved_rows(conn, source)
        else:
            _verify_preserved_rows(conn, source)
    assert source.read_bytes() == before
