"""Capture observation on the scheduled-task axis: a SIGNAL, never a gate.

A task fire can finish cleanly, report well, and write nothing durable.
``local_146a4406`` "Applier gemini recheck read 20260824" is the proven
instance: seven tool calls, all Bash/PowerShell, no MemPalace or GBrain write,
archived by the first armed pass. Measured 2026-09-03 over the 25 task records
inside the 14-day scan window: 10 wrote a capture, 15 did not, and 6 of those 15
made zero tool calls at all (timing-gate stand-downs and errored fires, which
have nothing to capture by construction).

So the worker OBSERVES and never gates. Refusing to archive a capture-less
record would strand 15 of 25 forever -- reopening the leak the task axis exists
to close, and hitting hardest the fires that correctly did nothing. Diego's
call, 2026-09-03. The source-side fix is the scheduled-task capture reminder
hook; this counter is that hook's falsifier.
"""
from __future__ import annotations

import json
from pathlib import Path

from session_bridge.mirror_float import (
    CaptureMissRecorder,
    transcript_wrote_capture,
)
from tests.session_bridge.test_idle_chip_archive import (
    NOW,
    _load,
    _worker,
    _write_record,
)
from tests.session_bridge.test_idle_task_session_archive import _write_task_record

HERMES_CWD = "C:\\Users\\diego\\.hermes"
HERMES_SLUG = "C--Users-diego--hermes"


def _write_transcript(root: Path, slug: str, cli_session_id: str, tools) -> Path:
    """A transcript shaped like a real one, roster attachment included."""
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cli_session_id}.jsonl"
    lines = [
        # The MCP tool ROSTER attachment. It names every capture tool verbatim
        # and carries no tool_use block. This is the line that makes a substring
        # search report "captured" for a session that captured nothing.
        json.dumps(
            {
                "type": "attachment",
                "tools": [
                    "mcp__mempalace__mempalace_add_drawer",
                    "mcp__gbrain__put_page",
                ],
            }
        )
    ]
    for name in tools:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "name": name, "input": {}}],
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- detection ---------------------------------------------------------------


def test_detection_ignores_the_tool_roster_attachment(tmp_path) -> None:
    """The measured false positive, pinned.

    Every session on this host carries an attachment listing the full MCP tool
    roster, so ``"mempalace_add_drawer" in transcript_text`` is True for a
    session that never called it -- the proven capture-less session greps as one
    hit. It fails toward "captured, safe to archive", which is the WRONG
    direction, so detection must parse ``tool_use`` blocks and never grep.
    """
    path = _write_transcript(tmp_path, "proj", "cli-x", ["Bash", "PowerShell"])

    assert "mempalace_add_drawer" in path.read_text(encoding="utf-8")
    assert transcript_wrote_capture(path) is False


def test_mempalace_write_counts_and_a_delete_does_not(tmp_path) -> None:
    writer = _write_transcript(
        tmp_path, "p", "cli-w", ["mcp__mempalace__mempalace_add_drawer"]
    )
    deleter = _write_transcript(
        tmp_path, "p", "cli-d", ["mcp__mempalace__mempalace_delete_drawer"]
    )

    assert transcript_wrote_capture(writer) is True
    assert transcript_wrote_capture(deleter) is False


def test_gbrain_writes_count_and_gbrain_reads_do_not(tmp_path) -> None:
    reader = _write_transcript(
        tmp_path, "p", "cli-r", ["mcp__gbrain__get_page", "mcp__gbrain__search"]
    )
    writer = _write_transcript(
        tmp_path, "p", "cli-w", ["mcp__gbrain__add_timeline_entry"]
    )

    assert transcript_wrote_capture(reader) is False
    assert transcript_wrote_capture(writer) is True


def test_unreadable_transcript_is_unknown_not_false(tmp_path) -> None:
    assert transcript_wrote_capture(tmp_path / "nope.jsonl") is None


# --- observation through the worker ------------------------------------------


def test_capture_less_task_session_is_recorded_and_still_archived(tmp_path) -> None:
    projects = tmp_path / "projects"
    _write_transcript(projects, HERMES_SLUG, "cli-task1", ["Bash", "PowerShell"])
    path = _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    log = tmp_path / "logs" / "misses.jsonl"
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(
            log, projects_root=projects, wall_clock=lambda: NOW
        ),
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert result["task_archived_without_capture"] == 1
    assert result["task_archived_capture_unknown"] == 0
    # Archived REGARDLESS: observation never spares a record.
    assert _load(path)["isArchived"] is True
    entry = json.loads(log.read_text(encoding="utf-8").strip())
    assert entry["capture"] == "missing"
    assert entry["sessionId"] == "local_task1"
    assert entry["scheduledTaskId"] == "capone-82a8fdc9-fix1-review-adjudication"
    assert entry["observedAt"] == NOW


def test_a_capturing_task_session_writes_no_line(tmp_path) -> None:
    projects = tmp_path / "projects"
    _write_transcript(
        projects,
        HERMES_SLUG,
        "cli-task1",
        ["Bash", "mcp__mempalace__mempalace_add_drawer"],
    )
    _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    log = tmp_path / "logs" / "misses.jsonl"
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(log, projects_root=projects),
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert result["task_archived_without_capture"] == 0
    assert not log.exists()


def test_missing_transcript_files_as_unknown_not_as_a_miss(tmp_path) -> None:
    """Retention must not manufacture findings.

    A record whose transcript has aged off disk is UNKNOWN, exactly as an
    unreadable claim registry is not "no claims". Filing it as a capture MISS
    would turn transcript rotation into a stream of false findings.
    """
    projects = tmp_path / "projects"
    projects.mkdir()
    _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    log = tmp_path / "logs" / "misses.jsonl"
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(log, projects_root=projects),
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert result["task_archived_capture_unknown"] == 1
    assert result["task_archived_without_capture"] == 0
    assert json.loads(log.read_text(encoding="utf-8").strip())["capture"] == "unknown"


def test_transcript_is_found_by_glob_when_the_cwd_moved(tmp_path) -> None:
    """A session's transcript follows the cwd it STARTED in, and a record's cwd
    can be rewritten afterwards, so the slug lookup needs a fallback."""
    projects = tmp_path / "projects"
    _write_transcript(projects, "some--other--project", "cli-task1", ["Bash"])
    _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    log = tmp_path / "logs" / "misses.jsonl"
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(log, projects_root=projects),
    )

    result = worker.run_once()

    assert result["task_archived_without_capture"] == 1
    assert result["task_archived_capture_unknown"] == 0


def test_observer_never_runs_on_the_chip_axis(tmp_path) -> None:
    """A chip is a foreground request whose answer went to the person who asked
    for it. The obligation being reported on is a scheduled-task obligation."""
    projects = tmp_path / "projects"
    projects.mkdir()
    _write_record(tmp_path / "a", "chip1")
    log = tmp_path / "logs" / "misses.jsonl"
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(log, projects_root=projects),
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert result["task_archived_without_capture"] == 0
    assert not log.exists()


def test_observer_is_not_called_for_a_spared_record(tmp_path) -> None:
    """Observation happens AFTER the write, so it cannot influence the decision.
    A record the error guard spares is never observed at all."""
    calls: list = []
    _write_task_record(tmp_path / "a", "task1", extra={"error": "boom", "errorAt": 1})
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=lambda data: calls.append(data) or False,
    )

    result = worker.run_once()

    assert result["archived"] == 0
    assert calls == []


def test_observer_is_not_called_when_the_write_did_not_happen(
    tmp_path, monkeypatch
) -> None:
    """A record that qualified at scan time but lost the write is NOT observed.

    ``archive_if_still_eligible`` re-checks against the bytes on disk, so Desktop
    rewriting a record mid-pass makes the transform return False with nothing
    archived. Reporting a capture miss there would file a finding against a
    session that is still running. Reachable in production but not from the
    other tests in this file, which is what a mutation run caught: dropping the
    ``changed`` term from the guard left the whole suite green.
    """
    calls: list = []
    path = _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    monkeypatch.setattr(
        "session_bridge.mirror_float._optimistic_transform_record",
        lambda *_args, **_kwargs: False,
    )
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=lambda data: calls.append(data) or False,
    )

    result = worker.run_once()

    assert result["archived"] == 0
    assert result["task_archived_without_capture"] == 0
    assert calls == []
    assert _load(path)["isArchived"] is False


def test_a_raising_observer_never_stops_an_archive(tmp_path) -> None:
    """A reaper that dies because it could not observe is strictly worse than
    the gap it was observing."""

    def explode(_data):
        raise RuntimeError("observer is broken")

    path = _write_task_record(tmp_path / "a", "task1")
    worker = _worker(
        tmp_path / "a", task_idle_seconds=4 * 3600.0, capture_observer=explode
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert _load(path)["isArchived"] is True
    assert result["task_archived_without_capture"] == 0


def test_an_unwritable_log_never_stops_an_archive(tmp_path) -> None:
    """The durable leg is best-effort. Losing a log line must not lose a record.

    The log path is a DIRECTORY here, so every open() for append fails.
    """
    projects = tmp_path / "projects"
    _write_transcript(projects, HERMES_SLUG, "cli-task1", ["Bash"])
    path = _write_task_record(tmp_path / "a", "task1", cwd=HERMES_CWD)
    log = tmp_path / "logs" / "misses.jsonl"
    log.mkdir(parents=True)
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        capture_observer=CaptureMissRecorder(log, projects_root=projects),
    )

    result = worker.run_once()

    assert result["archived"] == 1
    assert result["task_archived_without_capture"] == 1
    assert _load(path)["isArchived"] is True
