"""Finish verification of the existing migrated copy without rebuilding it."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

import pytest


@pytest.mark.timeout(2800)
def test_finish_verified_migration_and_recover():
    root = Path("C:/Users/diego/architecture-map/wave-execution/2026-09-08/candidate-recovery-20260910")
    permit = root / "run-final-verification-once.json"
    if not permit.is_file():
        pytest.skip("final verification requires its one-shot permit")
    permit.rename(root / "final-verification-permit-consumed.json")
    from hermes_state_common import SCHEMA_VERSION
    from hermes_state_conversion import _verify_preserved_rows

    source = root / "source" / "state.db"
    staged = root / ".hermes-conversion-o6k_8s5h" / "state.db"
    candidate = root / "candidate.db"
    assert not candidate.exists() and not staged.is_symlink()
    accepted = json.loads((root / "source-identity-preflight.json").read_text(encoding="utf-8"))
    assert accepted["phase"] == "PASS"
    assert shutil.disk_usage(root).free > staged.stat().st_size + 256 * 1024**2
    progress = root / "recovery-progress.json"
    started = time.monotonic()
    progress.write_text(json.dumps({"phase": "converted_source_identity"}), encoding="utf-8")
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == accepted["source_sha256"]
    progress.write_text(json.dumps({"phase": "final_all_row_preservation"}), encoding="utf-8")
    with closing(sqlite3.connect(staged.as_uri() + "?mode=rw", uri=True)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(SCHEMA_VERSION,)]
        assert conn.execute("SELECT value FROM state_meta WHERE key='schema_conversion_source_domain'").fetchone() == ("hermes-local-34",)
        deadline = time.monotonic() + 1800
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        _verify_preserved_rows(conn, source)
        (root / "final-row-preservation-result.json").write_text(json.dumps({
            "result": "PASS", "source_sha256": accepted["source_sha256"],
            "seconds": round(time.monotonic() - started, 3),
        }), encoding="utf-8")
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    os.link(staged, candidate)
    staged.unlink()
    report = {**accepted["inspection"], "target_version": SCHEMA_VERSION,
              "destination": str(candidate), "conversion_seconds": round(time.monotonic() - started, 3),
              "reused_completed_migration_and_integrity": True}
    (root / "conversion-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    progress.write_text(json.dumps({"phase": "recovery"}), encoding="utf-8")
    # Reuse the already defined disposable write/restore acceptance journey.
    spec = importlib.util.spec_from_file_location("owned_recovery_journey", Path(__file__).with_name("test_upgrade_candidate_recovery.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._verify_candidate_recovery(candidate, report, started, progress)
