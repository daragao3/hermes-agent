"""Explicit one-shot full-size offline recovery acceptance for this candidate."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

import pytest

ROOT = Path("C:/Users/diego/architecture-map/wave-execution/2026-09-08/candidate-recovery-20260910")
PERMIT = ROOT / "run-recovery-once.json"


@pytest.mark.timeout(100)
def test_source_validation_timing_diagnostic():
    """Bound the failing preflight by table; no conversion or source writes."""
    output = ROOT / "source-validation-timing.json"
    if output.exists() or not (ROOT / "source-capture.json").exists():
        pytest.skip("one-shot diagnostic of the retained source")
    rows = []
    source = ROOT / "source" / "state.db"
    for table in ("desktop_registry_values", "desktop_registry_baselines", "sessions", "messages"):
        conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)
        started = time.monotonic()
        conn.set_progress_handler(lambda: int(time.monotonic() - started > 15), 1000)
        item = {"table": table}
        try:
            item["cache_size"] = conn.execute("PRAGMA cache_size").fetchone()[0]
            item["count"] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            item["count_seconds"] = round(time.monotonic() - started, 3)
            item["quick_check"] = conn.execute(f"PRAGMA quick_check('{table}')").fetchall()
        except sqlite3.Error as exc:
            item["error"] = str(exc)
        finally:
            item["seconds"] = round(time.monotonic() - started, 3)
            conn.close()
            rows.append(item)
            output.write_text(json.dumps(rows, indent=2))
    assert len(rows) == 4  # Diagnostic completed; this is not recovery acceptance.


@pytest.mark.timeout(110)
@pytest.mark.parametrize("order", [(2000, 65536), (65536, 2000)])
def test_source_cache_timing_diagnostic(order):
    """Compare the default page cache with a bounded offline-read cache."""
    output = ROOT / ("source-cache-timing.json" if order[0] == 2000 else "source-cache-reverse-timing.json")
    if output.exists() or not (ROOT / "source-capture.json").exists():
        pytest.skip("one-shot cache diagnostic of retained source")
    source = ROOT / "source" / "state.db"
    rows = []
    for cache_kib in order:
        conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)
        conn.execute(f"PRAGMA cache_size=-{cache_kib}")
        started = time.monotonic()
        conn.set_progress_handler(lambda: int(time.monotonic() - started > 40), 1000)
        row = {"cache_kib": cache_kib}
        try:
            row["quick_check"] = conn.execute("PRAGMA quick_check('desktop_registry_baselines')").fetchall()
        except sqlite3.Error as exc:
            row["error"] = str(exc)
        finally:
            row["seconds"] = round(time.monotonic() - started, 3)
            conn.close()
            rows.append(row)
            output.write_text(json.dumps(rows, indent=2))
    assert len(rows) == 2


@pytest.mark.timeout(1500)
def test_source_identity_before_readonly_preflight():
    """Verify the artifact sequentially before its cold random-access checks."""
    output = ROOT / "source-identity-preflight.json"
    if output.exists() or not (ROOT / "source-capture.json").exists():
        pytest.skip("one-shot identity-first source inspection")
    source = ROOT / "source" / "state.db"
    expected = json.loads((ROOT / "source-capture.json").read_text())["snapshot_sha256"]
    started = time.monotonic()
    report = {"phase": "source_sha256", "scope": "read-only source inspection, not conversion/recovery"}
    output.write_text(json.dumps(report, indent=2))
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
    report.update(phase="source_inspection", hash_seconds=round(time.monotonic() - started, 3))
    output.write_text(json.dumps(report, indent=2))
    from hermes_state_conversion import inspect_local_snapshot
    report["inspection"] = inspect_local_snapshot(source, timeout_seconds=1200)
    report.update(phase="PASS", seconds=round(time.monotonic() - started, 3), source_sha256=expected)
    output.write_text(json.dumps(report, indent=2))


@pytest.mark.timeout(1500)
def test_full_size_candidate_conversion_and_recovery():
    if not PERMIT.is_file():
        pytest.skip("full-size offline drill requires its explicit one-shot permit")
    permit = json.loads(PERMIT.read_text())
    PERMIT.rename(ROOT / "recovery-permit-consumed-identity-first.json")
    source = ROOT / "source" / "state.db"
    assert permit["source_sha256"] == "dd1d2228f8ff50a088647448825af46fcf4e1d826a8f1e84d62ac17a6b626bee"
    assert sqlite3.sqlite_version_info >= (3, 53, 1)
    from hermes_state_conversion import convert_local_snapshot

    started = time.monotonic()
    progress = ROOT / "recovery-progress.json"
    progress.write_text(json.dumps({"phase": "source_identity"}))
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == permit["source_sha256"]
    progress.write_text(json.dumps({"phase": "conversion", "identity_seconds": round(time.monotonic() - started, 3)}))
    candidate = ROOT / "candidate.db"
    report = convert_local_snapshot(source, candidate, timeout_seconds=1200)
    # The production converter has already compared all preserved source rows,
    # verified both FTS indexes, and reopened under the ordinary runtime.
    assert report["source_domain"] == "hermes-local-34"
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == permit["source_sha256"]
    report.update(conversion_seconds=round(time.monotonic() - started, 3))
    (ROOT / "conversion-result.json").write_text(json.dumps(report, indent=2))
    progress.write_text(json.dumps({"phase": "recovery", "conversion_seconds": report["conversion_seconds"]}))
    _verify_candidate_recovery(candidate, report, started, progress)


@pytest.mark.timeout(4500)
def test_resume_owned_full_size_conversion_and_recovery():
    permit_path = ROOT / "run-owned-resume-once.json"
    if not permit_path.is_file():
        pytest.skip("owned full-size resume requires its one-shot permit")
    permit = json.loads(permit_path.read_text())
    permit_path.rename(ROOT / "owned-resume-permit-consumed-user-restart.json")
    from hermes_state_conversion import _finish_local_snapshot_conversion

    accepted = json.loads((ROOT / "source-identity-preflight.json").read_text())
    assert accepted["phase"] == "PASS"
    assert permit["source_sha256"] == accepted["source_sha256"]
    assert sqlite3.sqlite_version_info >= (3, 53, 1)
    source = ROOT / "source" / "state.db"
    staged = ROOT / ".hermes-conversion-o6k_8s5h" / "state.db"
    # The user stopped the preceding process. Opening only its owned copy
    # writable lets SQLite recover its hot rollback journal before the guard.
    connection = sqlite3.connect(staged.as_uri() + "?mode=rw", uri=True)
    try:
        assert connection.execute("SELECT version FROM schema_version").fetchall() == [(34,)]
    finally:
        connection.close()
    candidate = ROOT / "candidate.db"
    progress = ROOT / "recovery-progress.json"
    started = time.monotonic()
    progress.write_text(json.dumps({"phase": "resume_source_identity"}))
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == accepted["source_sha256"]
    progress.write_text(json.dumps({"phase": "resume_fts_migration_verification"}))
    report = _finish_local_snapshot_conversion(
        source, candidate, staged, accepted["inspection"], time.monotonic() + 3600,
    )
    report.update(conversion_seconds=round(time.monotonic() - started, 3), resumed_owned_copy=True)
    (ROOT / "conversion-result.json").write_text(json.dumps(report, indent=2))
    with source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == accepted["source_sha256"]
    progress.write_text(json.dumps({"phase": "recovery", "conversion_seconds": report["conversion_seconds"]}))
    _verify_candidate_recovery(candidate, report, started, progress)


def _verify_candidate_recovery(candidate, report, started, progress):
    from hermes_state import SessionDB

    # Exercise writes on an owned working copy; preserve the accepted candidate
    # snapshot as the exact recovery authority.
    working = ROOT / "working.db"
    assert not working.exists()
    assert shutil.disk_usage(ROOT).free > candidate.stat().st_size + 256 * 1024**2
    shutil.copyfile(candidate, working)
    marker = "wave1-recovery-disposable-session"
    with SessionDB(working) as db:
        assert db.get_session(marker) is None
        db.ensure_session(marker, source="cli")
        assert db.get_session(marker) is not None
    # All handles are closed. Replace only this explicitly owned disposable
    # working file, never the source snapshot or a production path.
    for suffix in ("-wal", "-shm", "-journal"):
        assert not Path(str(working) + suffix).exists(), suffix
    shutil.copyfile(candidate, working)
    with SessionDB(working) as db:
        assert db.get_session(marker) is None
        assert db.get_meta("schema_conversion_source_domain") == "hermes-local-34"
        assert db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == report["sessions"]
        assert db._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == report["messages"]
    report.update(recovery="PASS", seconds=round(time.monotonic() - started, 3), source_unchanged=True)
    (ROOT / "recovery-result.json").write_text(json.dumps(report, indent=2))
    progress.write_text(json.dumps({"phase": "PASS", "seconds": report["seconds"]}))
