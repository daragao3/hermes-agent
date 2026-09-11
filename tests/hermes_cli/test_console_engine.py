from __future__ import annotations

import io
import sys
from pathlib import Path as Path

import pytest

from hermes_cli.console_engine import (
    ConsoleResult,
    HermesConsoleEngine,
    run_console_repl,
)


def _stub_run_one_job(monkeypatch, body):
    """Install a ``cron.scheduler.run_one_job`` stub that honours its real contract.

    Two things a naive ``def _fake(job)`` gets wrong:

    1. SIGNATURE. ``tools/cronjob_tools._execute_job_now`` calls
       ``run_one_job(job, _dispatch_admission=admission)`` — the kwarg was added
       by 410c57ddc9 (fail-closed quarantine controls) and these stubs were not
       updated, so every console ``cron run`` test raised TypeError inside
       ``_execute_job_now``'s except-handler and reported the job as failed.
    2. THE ADMISSION HANDOFF. ``_execute_job_now`` sets ``handed_off = True``
       before the call and stops tracking the admission — releasing it is
       ``run_one_job``'s job. A stub that accepts the kwarg but drops it leaves
       ``_DISPATCH_DEPTH.admissions`` pinned and the quarantine store's kernel
       lock held for the rest of the process, which is a far quieter failure
       than the TypeError it replaces.

    ``body(job)`` is the per-test behaviour; the release happens either way.
    """

    def _fake_run_one_job(job, *, _dispatch_admission=None, **_kwargs):
        try:
            return body(job)
        finally:
            if _dispatch_admission is not None:
                _dispatch_admission.__exit__(None, None, None)

    monkeypatch.setattr("cron.scheduler.run_one_job", _fake_run_one_job)
    return _fake_run_one_job


EXPECTED_CONSOLE_COMMANDS = {
    ("status",),
    ("doctor",),
    ("logs",),
    ("version",),
    ("dump",),
    ("debug", "share"),
    ("debug", "delete"),
    ("prompt-size",),
    ("insights",),
    ("security", "audit"),
    ("portal", "info"),
    ("portal", "tools"),
    ("backup",),
    ("import",),
    ("send",),
    ("config", "show"),
    ("config", "path"),
    ("config", "env-path"),
    ("config", "check"),
    ("config", "migrate"),
    ("config", "set"),
    ("sessions", "list"),
    ("sessions", "stats"),
    ("sessions", "export"),
    ("sessions", "rename"),
    ("sessions", "optimize"),
    ("sessions", "repair"),
    ("cron", "list"),
    ("cron", "status"),
    ("cron", "create"),
    ("cron", "edit"),
    ("cron", "pause"),
    ("cron", "resume"),
    ("cron", "run"),
    ("cron", "remove"),
    ("cron", "tick"),
    ("profile",),
    ("profile", "list"),
    ("profile", "show"),
    ("profile", "info"),
    ("profile", "create"),
    ("profile", "use"),
    ("profile", "describe"),
    ("profile", "rename"),
    ("profile", "delete"),
    ("profile", "export"),
    ("profile", "import"),
    ("profile", "install"),
    ("profile", "update"),
    ("tools", "list"),
    ("tools", "enable"),
    ("tools", "disable"),
    ("tools", "post-setup"),
    ("plugins", "list"),
    ("plugins", "enable"),
    ("plugins", "disable"),
    ("plugins", "install"),
    ("plugins", "update"),
    ("plugins", "remove"),
    ("skills", "browse"),
    ("skills", "search"),
    ("skills", "inspect"),
    ("skills", "list"),
    ("skills", "check"),
    ("skills", "list-modified"),
    ("skills", "diff"),
    ("skills", "install"),
    ("skills", "update"),
    ("skills", "audit"),
    ("skills", "uninstall"),
    ("skills", "reset"),
    ("skills", "opt-in"),
    ("skills", "opt-out"),
    ("skills", "repair-official"),
    ("skills", "snapshot", "export"),
    ("skills", "snapshot", "import"),
    ("skills", "tap", "list"),
    ("skills", "tap", "add"),
    ("skills", "tap", "remove"),
    ("mcp", "list"),
    ("mcp", "catalog"),
    ("mcp", "test"),
    ("mcp", "add"),
    ("mcp", "remove"),
    ("mcp", "install"),
    ("mcp", "login"),
    ("mcp", "reauth"),
    ("mcp", "configure"),
    ("mcp", "picker"),
    ("memory", "status"),
    ("memory", "off"),
    ("memory", "reset"),
    ("auth", "list"),
    ("auth", "status"),
    ("auth", "reset"),
    ("auth", "add"),
    ("auth", "remove"),
    ("auth", "logout"),
    ("auth", "spotify", "status"),
    ("auth", "spotify", "login"),
    ("auth", "spotify", "logout"),
    ("pairing", "list"),
    ("pairing", "approve"),
    ("pairing", "revoke"),
    ("pairing", "clear-pending"),
    ("webhook", "list"),
    ("webhook", "subscribe"),
    ("webhook", "remove"),
    ("webhook", "test"),
    ("hooks", "list"),
    ("hooks", "test"),
    ("hooks", "doctor"),
    ("hooks", "revoke"),
    ("slack", "manifest"),
    ("project", "list"),
    ("project", "show"),
    ("project", "create"),
    ("project", "add-folder"),
    ("project", "remove-folder"),
    ("project", "rename"),
    ("project", "set-primary"),
    ("project", "use"),
    ("project", "archive"),
    ("project", "restore"),
    ("project", "bind-board"),
    ("kanban", "init"),
    ("kanban", "boards", "list"),
    ("kanban", "boards", "create"),
    ("kanban", "boards", "rm"),
    ("kanban", "boards", "switch"),
    ("kanban", "boards", "current"),
    ("kanban", "boards", "rename"),
    ("kanban", "boards", "set-workdir"),
    ("kanban", "create"),
    ("kanban", "list"),
    ("kanban", "show"),
    ("kanban", "assign"),
    ("kanban", "reclaim"),
    ("kanban", "reassign"),
    ("kanban", "diagnose"),
    ("kanban", "link"),
    ("kanban", "unlink"),
    ("kanban", "claim"),
    ("kanban", "comment"),
    ("kanban", "complete"),
    ("kanban", "edit"),
    ("kanban", "block"),
    ("kanban", "schedule"),
    ("kanban", "unblock"),
    ("kanban", "promote"),
    ("kanban", "archive"),
    ("kanban", "stats"),
    ("kanban", "runs"),
    ("kanban", "heartbeat"),
    ("kanban", "assignments"),
    ("kanban", "context"),
    ("bundles", "list"),
    ("bundles", "show"),
    ("bundles", "create"),
    ("bundles", "delete"),
    ("bundles", "reload"),
    ("checkpoints", "status"),
    ("checkpoints", "list"),
    ("checkpoints", "prune"),
    ("checkpoints", "clear"),
    ("checkpoints", "clear-legacy"),
    ("curator", "status"),
    ("curator", "run"),
    ("curator", "pause"),
    ("curator", "resume"),
    ("curator", "pin"),
    ("curator", "unpin"),
    ("curator", "restore"),
    ("curator", "list-archived"),
    ("curator", "archive"),
    ("curator", "prune"),
    ("curator", "backup"),
    ("curator", "rollback"),
    ("pets", "list"),
    ("pets", "install"),
    ("pets", "select"),
    ("pets", "show"),
    ("pets", "off"),
    ("pets", "scale"),
    ("pets", "remove"),
    ("pets", "doctor"),
}


MUTATING_CONFIRMATION_SMOKE_COMMANDS = [
    "config set console.test true",
    "config migrate",
    "sessions rename abc123 new title",
    "sessions optimize",
    "cron create 'every 1h' 'say hello'",
    "cron remove abc123",
    "profile create tester --no-alias --no-skills",
    "profile delete tester",
    "tools disable web",
    "plugins install owner/repo --no-enable",
    "skills install openai/skills/example",
    "mcp add demo --url https://example.com/sse",
    "mcp configure github",
    "mcp picker",
    "backup --quick -o /tmp/hermes-console-test.zip",
    "import /tmp/hermes-console-test.zip",
    "send --to telegram hello",
    "memory reset --target memory",
    "auth remove openrouter 1",
    "pairing approve abc123",
    "webhook subscribe test --prompt hello",
    "hooks test pre_tool_call",
    "project create demo",
    "kanban create 'demo task'",
    "bundles create demo --skill skill-a",
    "checkpoints prune",
    "curator pause",
    "pets install cat",
]










def test_console_help_table_keeps_long_summaries_compact():
    help_text = HermesConsoleEngine().help_text()

    slack_line = next(
        line for line in help_text.splitlines() if line.strip().startswith("slack manifest")
    )

    assert len(slack_line) <= 112
    assert slack_line.endswith("...")


def test_console_help_for_command_uses_cli_summary():
    help_text = HermesConsoleEngine().help_text("skills list")

    assert help_text == "skills list\nList installed skills"


def test_console_registry_covers_non_admin_cli_surface():
    registered = set(HermesConsoleEngine().commands)

    missing = EXPECTED_CONSOLE_COMMANDS - registered

    assert missing == set()


# Regression: argparse's --help/--version action calls parser.exit() ->
# sys.exit(). The dashboard web console runs each command in a worker thread
# whose SystemExit (a BaseException) sailed past the `except Exception` guard,
# escaped the asyncio Task, and tore down the whole uvicorn process. The console
# must instead return the help text at the prompt. See console_engine
# _ArgumentParser.exit() + HermesConsoleEngine.execute().
CONSOLE_HELP_FLAG_LINES = [
    ("version --help", False),
    ("version -h", False),
    ("skills list --help", False),
    ("mcp add --help", True),  # mutating -> reached only on the confirmed pass
]


@pytest.mark.parametrize("line, confirmed", CONSOLE_HELP_FLAG_LINES)
def test_console_help_flag_returns_help_without_exiting(
    line: str, confirmed: bool, capsys: pytest.CaptureFixture[str]
):
    engine = HermesConsoleEngine()

    result = engine.execute(line, confirmed=confirmed)

    # Reaching this line at all proves no SystemExit escaped execute().
    assert isinstance(result, ConsoleResult)
    assert result.status == "ok"
    assert "usage:" in result.output
    # The help text is surfaced in the result, not dumped to the process
    # stdout/stderr (which the web console never shows the user).
    captured = capsys.readouterr()
    assert "usage:" not in captured.out
    assert "usage:" not in captured.err


def test_console_cron_create_help_does_not_crash_process():
    # Exact repro from the bug report. `cron create` is mutating, so the crash
    # happened on the confirmation pass (confirmed=True), when the handler
    # actually parsed the args and argparse hit --help.
    engine = HermesConsoleEngine()

    pending = engine.execute("cron create --help")
    assert pending.status == "confirm_required"

    result = engine.execute("cron create --help", confirmed=True)

    assert result.status == "ok"
    assert "usage: hermes cron create" in result.output


def _selftest_exit_handler(_engine: HermesConsoleEngine, _args: list[str]) -> str:
    raise SystemExit(7)


def test_console_contains_handler_process_exit():
    # Defense-in-depth: a handler (or a parser we don't control) that calls
    # sys.exit() must not let SystemExit escape execute(); that BaseException
    # would slip past the dashboard worker's `except Exception` and crash the
    # event loop. execute() must always return a ConsoleResult.
    engine = HermesConsoleEngine()
    engine.register(
        ("selftest-exit",),
        "selftest-exit",
        "Raise SystemExit for the containment test.",
        _selftest_exit_handler,
    )

    result = engine.execute("selftest-exit")

    assert isinstance(result, ConsoleResult)
    assert result.status == "error"
    assert "status 7" in result.output


EXPECTED_HOSTED_CONSOLE_COMMANDS = {
    ("status",),
    ("doctor",),
    ("logs",),
    ("version",),
    ("prompt-size",),
    ("insights",),
    ("security", "audit"),
    ("portal", "info"),
    ("portal", "tools"),
    ("send",),
    ("config", "show"),
    ("config", "path"),
    ("config", "env-path"),
    ("config", "check"),
    ("config", "migrate"),
    ("config", "set"),
    ("sessions", "list"),
    ("sessions", "stats"),
    ("sessions", "export"),
    ("sessions", "rename"),
    ("sessions", "optimize"),
    ("sessions", "repair"),
    ("cron", "list"),
    ("cron", "status"),
    ("cron", "create"),
    ("cron", "edit"),
    ("cron", "pause"),
    ("cron", "resume"),
    ("cron", "run"),
    ("cron", "remove"),
    ("cron", "tick"),
    ("profile",),
    ("profile", "list"),
    ("profile", "show"),
    ("profile", "info"),
    ("tools", "list"),
    ("tools", "enable"),
    ("tools", "disable"),
    ("tools", "post-setup"),
    ("skills", "browse"),
    ("skills", "search"),
    ("skills", "inspect"),
    ("skills", "list"),
    ("skills", "check"),
    ("skills", "list-modified"),
    ("skills", "diff"),
    ("skills", "install"),
    ("skills", "update"),
    ("skills", "audit"),
    ("skills", "uninstall"),
    ("skills", "reset"),
    ("skills", "opt-in"),
    ("skills", "opt-out"),
    ("skills", "repair-official"),
    ("skills", "snapshot", "export"),
    ("skills", "tap", "list"),
    ("mcp", "list"),
    ("mcp", "catalog"),
    ("mcp", "test"),
    ("mcp", "add"),
    ("mcp", "remove"),
    ("mcp", "install"),
    ("mcp", "login"),
    ("mcp", "reauth"),
    ("mcp", "configure"),
    ("mcp", "picker"),
    ("memory", "status"),
    ("auth", "list"),
    ("auth", "status"),
    ("auth", "reset"),
    ("auth", "spotify", "status"),
    ("pairing", "list"),
    ("pairing", "approve"),
    ("pairing", "revoke"),
    ("pairing", "clear-pending"),
    ("webhook", "list"),
    ("webhook", "subscribe"),
    ("webhook", "remove"),
    ("webhook", "test"),
}


def test_hosted_console_registry_exposes_only_hosted_safe_surface():
    engine = HermesConsoleEngine(context="hosted")
    hosted = {
        path for path, command in engine.commands.items() if "hosted" in command.contexts
    }

    assert hosted == EXPECTED_HOSTED_CONSOLE_COMMANDS


@pytest.mark.parametrize(
    "line",
    [
        "portal login",
        "auth add nous --type oauth",
        "auth logout nous",
        "profile create tester",
        "profile use default",
        "plugins list",
        "plugins install owner/repo",
        "kanban list",
        "hooks list",
        "checkpoints clear",
        "curator pause",
        "pets install cat",
        "backup --quick",
        "import /tmp/hermes-console-test.zip",
        "mcp serve",
        "model",
        "setup",
        "dashboard",
        "gateway restart",
        "update",
        "uninstall",
    ],
)
def test_hosted_console_rejects_local_only_or_dangerous_commands(line):
    result = HermesConsoleEngine(context="hosted").execute(line)

    assert result.status == "error"
    assert result.output


@pytest.mark.parametrize(
    "line",
    [
        "mcp add demo --url https://example.com/sse",
        "mcp install n8n",
        "mcp configure github",
        "mcp picker",
        "config set display.interface cli",
        "cron create 'every 1h' 'say hello'",
    ],
)
def test_hosted_console_allows_guarded_useful_commands_before_confirmation(line):
    result = HermesConsoleEngine(context="hosted").execute(line)

    assert result.status == "confirm_required"


@pytest.mark.parametrize(
    "line",
    [
        "mcp add local --command npx --args foo",
        "mcp add local --preset unsafe",
        "mcp add local --url file:///tmp/server",
        "config set model.provider openrouter",
        "config set portal.url https://evil.example",
        "cron create 'every 1h' 'say hello' --script scripts/ping.py",
        "cron create 'every 1h' 'say hello' --no-agent",
        "cron edit abc123 --workdir /tmp/project",
    ],
)
def test_hosted_console_blocks_known_footgun_arguments_before_confirmation(line):
    result = HermesConsoleEngine(context="hosted").execute(line)

    assert result.status == "error"
    assert result.output


@pytest.mark.parametrize(
    "line",
    [
        "sessions delete abc123",
        "sessions prune --older-than 1",
        "chat",
        "--cli",
        "--tui",
        "oneshot hello",
        "model",
        "setup",
        "postinstall",
        "fallback add",
        "moa configure",
        "claw migrate",
        "gateway restart",
        "gateway start",
        "gateway stop",
        "dashboard",
        "serve",
        "proxy start",
        "mcp serve",
        "skills config",
        "skills publish ./skill",
        "completion bash",
        "acp",
        "update",
        "uninstall",
        "gui",
        "desktop",
        "login",
        "logout",
        "--tui",
        "logs | cat",
        "config show > out.txt",
    ],
)
def test_console_rejects_destructive_and_shell_like_commands(line):
    result = HermesConsoleEngine().execute(line)

    assert result.status == "error"
    assert result.output


@pytest.mark.parametrize("line", MUTATING_CONFIRMATION_SMOKE_COMMANDS)
def test_mutating_console_commands_require_confirmation(line):
    result = HermesConsoleEngine().execute(line)

    assert result.status == "confirm_required"
    assert result.confirmation_message


def test_help_lists_supported_commands_and_not_full_cli():
    result = HermesConsoleEngine().execute("help")

    assert result.status == "ok"
    assert "sessions list" in result.output
    assert "config set" in result.output
    assert "dashboard" not in result.output
    assert "gateway restart" not in result.output


def test_config_set_requires_confirmation_then_writes(_isolate_hermes_home):
    engine = HermesConsoleEngine()

    # Use a schema-known key path. Since #34067, `config set` refuses unknown
    # top-level keys, so this flow test must target a valid path (telegram is a
    # PlatformConfig-shaped dict that accepts arbitrary child keys).
    pending = engine.execute("config set telegram.test true")
    assert pending.status == "confirm_required"

    from hermes_cli.config import read_raw_config

    assert read_raw_config() == {}

    result = engine.execute("config set telegram.test true", confirmed=True)

    assert result.status == "ok"
    assert "telegram.test" in result.output
    assert read_raw_config()["telegram"]["test"] is True


def test_sessions_list_and_stats_use_isolated_session_store(_isolate_hermes_home):
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("chat-session", source="cli", model="test/model")
        db.create_session("tool-session", source="tool", model="test/model")
    finally:
        db.close()

    engine = HermesConsoleEngine()
    listed = engine.execute("sessions list --limit 10")
    stats = engine.execute("sessions stats")

    assert listed.status == "ok"
    assert "chat-session" in listed.output
    assert "tool-session" not in listed.output
    assert "Total sessions: 2" in stats.output
    assert "Listable sessions: 1" in stats.output


@pytest.fixture()
def _tmp_cron_store(tmp_path, monkeypatch):
    """Redirect cron.jobs' module-pinned storage to a per-test tmp dir.

    ``cron.jobs.CRON_DIR``/``JOBS_FILE``/``OUTPUT_DIR`` are constants resolved
    from ``get_hermes_home()`` at *import* time — which, during collection,
    is the real ``~/.hermes`` (the hermetic ``HERMES_HOME`` env override lands
    after import). Without this, a console cron test creating a named job
    writes it to the live cron store: it pollutes the user's real jobs.json
    and, under xdist, goes ambiguous once a sibling reuses the same name.
    Mirrors ``tests/cron/test_jobs.py::tmp_cron_dir``.
    """
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


def test_sessions_export_rejects_oversized_single_before_touching_output(
    _isolate_hermes_home,
    monkeypatch,
    tmp_path,
):
    import hermes_state
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("too-large", source="cli")
        db.append_messages_batch(
            "too-large",
            [{"role": "user", "content": f"message-{i}"} for i in range(3)],
        )
    finally:
        db.close()

    monkeypatch.setattr(hermes_state, "resolved_max_export_messages", lambda: 2)
    materialized = []
    original_export_session = SessionDB.export_session

    def tracked_export_session(self, session_id):
        materialized.append(session_id)
        return original_export_session(self, session_id)

    monkeypatch.setattr(SessionDB, "export_session", tracked_export_session)
    output = tmp_path / "sessions.jsonl"
    output.write_text("keep me\n", encoding="utf-8")

    result = HermesConsoleEngine().execute(
        f"sessions export {output} --session-id too-large",
        confirmed=True,
    )

    assert result.status == "error"
    assert "too-large" in result.output
    assert "streaming Export" in result.output
    assert "resume" not in result.output.lower()
    assert materialized == []
    assert output.read_text(encoding="utf-8") == "keep me\n"


def test_sessions_export_all_uses_per_session_budget(
    _isolate_hermes_home,
    monkeypatch,
    tmp_path,
):
    """N small sessions export fine; ONE oversized session still rejects.

    The budget is per session, not cumulative across the export set —
    a cumulative budget broke full-DB backups of many small sessions.
    """
    import json

    import hermes_state
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        for name in ("first-safe", "second-safe", "third-safe"):
            db.create_session(name, source="cli")
            db.append_messages_batch(
                name,
                [{"role": "user", "content": f"{name}-{i}"} for i in range(2)],
            )
    finally:
        db.close()

    monkeypatch.setattr(hermes_state, "resolved_max_export_messages", lambda: 3)
    output = tmp_path / "all-sessions.jsonl"

    # 3 sessions x 2 messages = 6 total > 3, but each session is under the
    # per-session limit, so the full-DB export succeeds.
    result = HermesConsoleEngine().execute(
        f"sessions export {output}",
        confirmed=True,
    )
    assert result.status == "ok"
    exported = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert {row["id"] for row in exported} == {
        "first-safe",
        "second-safe",
        "third-safe",
    }


def test_sessions_export_all_rejects_single_oversized_session(
    _isolate_hermes_home,
    monkeypatch,
    tmp_path,
):
    import hermes_state
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("small", source="cli")
        db.append_messages_batch(
            "small",
            [{"role": "user", "content": f"small-{i}"} for i in range(2)],
        )
        db.create_session("runaway", source="cli")
        db.append_messages_batch(
            "runaway",
            [{"role": "user", "content": f"runaway-{i}"} for i in range(4)],
        )
    finally:
        db.close()

    monkeypatch.setattr(hermes_state, "resolved_max_export_messages", lambda: 3)
    export_all_calls = []

    def tracked_export_all(self, source=None):
        export_all_calls.append(source)
        raise AssertionError("export_all must not run before every guard passes")

    monkeypatch.setattr(SessionDB, "export_all", tracked_export_all)
    output = tmp_path / "all-sessions.jsonl"

    result = HermesConsoleEngine().execute(
        f"sessions export {output}",
        confirmed=True,
    )

    assert result.status == "error"
    assert "runaway" in result.output
    assert "more than 3 active" in result.output
    assert "streaming Export" in result.output
    assert "max_export_messages" in result.output
    assert export_all_calls == []
    assert not output.exists()


def test_sessions_export_zero_limit_disables_guard(
    _isolate_hermes_home,
    monkeypatch,
    tmp_path,
):
    import hermes_state
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("huge", source="cli")
        db.append_messages_batch(
            "huge",
            [{"role": "user", "content": f"huge-{i}"} for i in range(5)],
        )
    finally:
        db.close()

    monkeypatch.setattr(hermes_state, "resolved_max_export_messages", lambda: 0)
    output = tmp_path / "huge.jsonl"

    result = HermesConsoleEngine().execute(
        f"sessions export {output} --session-id huge",
        confirmed=True,
    )
    assert result.status == "ok"
    assert output.exists()


def test_cron_pause_resume_and_run_require_confirmation(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    from cron.jobs import create_job, get_job

    # Local `cron run` now executes immediately (CLI/LLM parity); stub the real
    # agent-run boundary so this confirmation-flow test doesn't depend on — or
    # attempt — an actual agent execution.
    def _run(job):
        from cron.jobs import mark_job_run

        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _run)

    job = create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine()

    pending = engine.execute(f"cron pause {job['id']}")
    assert pending.status == "confirm_required"
    stored = get_job(job["id"])
    assert stored is not None
    assert stored["state"] == "scheduled"

    paused = engine.execute(f"cron pause {job['id']}", confirmed=True)
    assert paused.status == "ok"
    stored = get_job(job["id"])
    assert stored is not None
    assert stored["state"] == "paused"

    resumed = engine.execute("cron resume alpha", confirmed=True)
    assert resumed.status == "ok"
    stored = get_job(job["id"])
    assert stored is not None
    assert stored["state"] == "scheduled"

    triggered = engine.execute("cron run alpha", confirmed=True)
    assert triggered.status == "ok"
    assert "Ran job" in triggered.output


def test_cron_run_attributes_trigger_to_console(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """`cron run` must emit CRON_TRIGGERED with an explicit console caller.

    The emit fires on both the local execute-now path and the hosted
    schedule-for-next-tick path; this exercises the default (local) engine.
    """
    from cron.jobs import create_job
    from events.bus import EventBus
    from events.schema import EventType

    # ``_tmp_cron_store`` isolates the module-pinned cron paths (returning the
    # tmp root); point the emit-side bus at a tmp DB in that same root.
    bus = EventBus(db_path=_tmp_cron_store / "events.db")
    monkeypatch.setattr("cron.jobs._get_event_bus", lambda: bus)

    # Local `cron run` executes immediately; stub the agent-run boundary so the
    # attribution assertions don't depend on a real agent execution.
    def _run(job):
        from cron.jobs import mark_job_run

        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _run)

    job = create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine()

    triggered = engine.execute("cron run alpha", confirmed=True)
    assert triggered.status == "ok"

    events = bus.query(event_type=EventType.CRON_TRIGGERED)
    assert len(events) == 1
    assert events[0].payload["caller"] == "tui:console_engine"
    assert events[0].payload["job_id"] == job["id"]


def test_cron_run_executes_immediately_in_local_context(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """Local REPL `cron run` executes the job NOW (CLI/LLM `run` parity), not
    just schedule-for-next-tick — and still emits CRON_TRIGGERED as the console.

    A manual `cron run` in the standalone REPL should actually fire, even when
    no gateway ticker is active (the #41037 case), mirroring `hermes cron run`
    and the cronjob(action='run') tool which both route through _execute_job_now.
    """
    from cron.jobs import create_job
    from events.bus import EventBus
    from events.schema import EventType

    # ``_tmp_cron_store`` isolates the module-pinned cron paths (returning the
    # tmp root); point the emit-side bus at a tmp DB in that same root.
    bus = EventBus(db_path=_tmp_cron_store / "events.db")
    monkeypatch.setattr("cron.jobs._get_event_bus", lambda: bus)

    # Stub the real agent-execution boundary so no actual run happens: record
    # that it fired and mark the job ok so the console reports success.
    ran: dict = {}

    def _run(job):
        from cron.jobs import mark_job_run

        ran["job_id"] = job["id"]
        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _run)

    job = create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine()  # default context == "local"
    assert engine.context == "local"

    result = engine.execute("cron run alpha", confirmed=True)
    assert result.status == "ok"
    assert "Ran job" in result.output
    assert "succeeded" in result.output

    # It actually executed now, rather than deferring to a scheduler tick.
    assert ran.get("job_id") == job["id"]

    # Attribution is preserved on the execute-now path.
    events = bus.query(event_type=EventType.CRON_TRIGGERED)
    assert len(events) == 1
    assert events[0].payload["caller"] == "tui:console_engine"
    assert events[0].payload["job_id"] == job["id"]


def test_cron_run_reports_skip_when_claim_lost_in_local_context(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """If the scheduler already holds the fire claim, local `cron run` reports a
    skip and never double-runs the job (at-most-once safety)."""
    from cron.jobs import create_job

    # Force the at-most-once claim to be lost (another fire owns this job).
    monkeypatch.setattr(
        "tools.cronjob_tools.claim_job_for_fire", lambda job_id, **kwargs: False
    )

    def _must_not_run(job, **_kwargs):
        raise AssertionError("run_one_job must not fire when the claim is lost")

    monkeypatch.setattr("cron.scheduler.run_one_job", _must_not_run)

    create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine()  # local

    result = engine.execute("cron run alpha", confirmed=True)
    assert result.status == "ok"
    assert "Run skipped" in result.output
    assert "already being fired" in result.output


def test_cron_run_executes_in_background_in_hosted_context(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """Hosted (dashboard web-console) `cron run` fires the job NOW, but off the
    console's bounded 4-worker/60s pool: it dispatches `_execute_job_now` on a
    dedicated background executor and returns a "started" ack immediately.

    The run still emits exactly one CRON_TRIGGERED (console caller) and — via
    `run_one_job` -> `on_job_completed` — the completion event the dashboard
    activity feed already consumes; that is how the result is surfaced without
    blocking the console thread or tripping the 60s timeout.
    """
    import concurrent.futures

    from cron.jobs import create_job, get_job
    from events.bus import EventBus
    from events.schema import EventType
    from hermes_cli import console_engine

    bus = EventBus(db_path=_tmp_cron_store / "events.db")
    monkeypatch.setattr("cron.jobs._get_event_bus", lambda: bus)

    # Stub the real agent-execution boundary: record that it fired and mark the
    # job ok. Running on the background thread, it reaches the same store/bus
    # (HERMES_HOME env + monkeypatched globals are process-global).
    ran: dict = {}

    def _run(job):
        from cron.jobs import mark_job_run

        ran["job_id"] = job["id"]
        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _run)

    # The test owns the background executor so it can join deterministically
    # (no sleeps): shutdown(wait=True) blocks until the fire completes.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(
        console_engine, "_get_console_run_executor", lambda: executor
    )

    job = create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine(context="hosted")

    result = engine.execute("cron run alpha", confirmed=True)
    assert result.status == "ok"
    assert "Started" in result.output
    assert "background" in result.output.lower()
    assert job["id"] in result.output

    executor.shutdown(wait=True)  # join the background fire

    # It actually executed NOW in the background (not defer-to-tick).
    assert ran.get("job_id") == job["id"]
    stored = get_job(job["id"])
    assert stored is not None
    assert stored.get("last_status") == "ok"

    # Exactly one CRON_TRIGGERED, attributed to the console caller.
    events = bus.query(event_type=EventType.CRON_TRIGGERED)
    assert len(events) == 1
    assert events[0].payload["caller"] == "tui:console_engine"
    assert events[0].payload["job_id"] == job["id"]


def test_cron_run_hosted_dispatch_is_non_blocking(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """The hosted `cron run` ack returns while the agent run is still in flight.

    A synchronous run would block the console worker (and trip the 60s timeout).
    Here the stubbed run parks on a gate: if `execute()` returned, the console
    thread was NOT blocked on the run. If it *were* blocked, the test would
    deadlock (the gate is released only after `execute()` returns) — a hang is
    the failure signal.
    """
    import concurrent.futures
    import threading

    from cron.jobs import create_job
    from events.bus import EventBus
    from hermes_cli import console_engine

    bus = EventBus(db_path=_tmp_cron_store / "events.db")
    monkeypatch.setattr("cron.jobs._get_event_bus", lambda: bus)

    started = threading.Event()
    gate = threading.Event()

    def _blocking_run(job):
        from cron.jobs import mark_job_run

        started.set()
        if not gate.wait(timeout=5):
            raise AssertionError("gate never released")
        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _blocking_run)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(
        console_engine, "_get_console_run_executor", lambda: executor
    )

    create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine(context="hosted")

    # Returns immediately with the ack even though the run is parked on `gate`.
    result = engine.execute("cron run alpha", confirmed=True)
    assert result.status == "ok"
    assert "background" in result.output.lower()

    # The background fire genuinely started, and it is still blocked — proving
    # `execute()` did not wait for it.
    assert started.wait(timeout=5)
    assert not gate.is_set()

    gate.set()
    executor.shutdown(wait=True)


def test_cron_run_hosted_missing_job_fast_fails_without_dispatch(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """Hosted `cron run <missing>` resolves on the console thread and fast-fails
    with `Job not found` — it must NOT dispatch a background run for a job that
    does not exist."""
    from hermes_cli import console_engine

    class _NoDispatchExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError(
                "must not dispatch a background run for a missing job"
            )

    monkeypatch.setattr(
        console_engine, "_get_console_run_executor", lambda: _NoDispatchExecutor()
    )

    engine = HermesConsoleEngine(context="hosted")
    result = engine.execute("cron run does-not-exist", confirmed=True)
    assert result.status == "error"
    assert "not found" in result.output.lower()


def test_cron_run_hosted_returns_started_ack_even_when_claim_lost(
    _isolate_hermes_home, _tmp_cron_store, monkeypatch: pytest.MonkeyPatch
):
    """The hosted background fire is optimistic (fire-and-forget): if the
    scheduler already holds the fire claim, `_execute_job_now` no-ops on the
    background thread, but the console has already returned the "started" ack.
    At-most-once safety still holds — `run_one_job` is never called — and the
    activity feed shows the scheduler's own trigger/completion. This pins that
    deliberate optimistic-ack decision.
    """
    import concurrent.futures

    from cron.jobs import create_job
    from hermes_cli import console_engine

    # Force the at-most-once claim to be lost (another fire owns this job).
    monkeypatch.setattr(
        "tools.cronjob_tools.claim_job_for_fire", lambda job_id: False
    )

    def _must_not_run(job, **_kwargs):
        raise AssertionError("run_one_job must not fire when the claim is lost")

    monkeypatch.setattr("cron.scheduler.run_one_job", _must_not_run)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(
        console_engine, "_get_console_run_executor", lambda: executor
    )

    create_job(prompt="say hello", schedule="every 1h", name="alpha")
    engine = HermesConsoleEngine(context="hosted")

    result = engine.execute("cron run alpha", confirmed=True)
    assert result.status == "ok"
    assert "Started" in result.output
    assert "background" in result.output.lower()

    executor.shutdown(wait=True)  # join; the fire no-ops on a lost claim


def test_cron_run_hosted_background_fire_inherits_profile_home(
    _isolate_hermes_home,
    _tmp_cron_store,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    """The background fire must resolve the SAME profile store as the console
    thread that dispatched it.

    Hosted `cron run` runs inside `_profile_scope`, which sets a *context-local*
    (ContextVar) HERMES_HOME override for a non-default profile. A
    ThreadPoolExecutor worker does NOT inherit that ContextVar, so the dispatch
    must carry the caller's context (contextvars.copy_context) — otherwise the
    fire would claim/run/record against the WRONG profile's store, regressing
    the per-profile fire correctness cron.jobs' dynamic resolution preserves.
    """
    import concurrent.futures

    from cron.jobs import create_job
    from events.bus import EventBus
    from hermes_cli import console_engine
    from hermes_constants import (
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    bus = EventBus(db_path=_tmp_cron_store / "events.db")
    monkeypatch.setattr("cron.jobs._get_event_bus", lambda: bus)

    # A distinct profile home, different from the hermetic default HERMES_HOME.
    profile_home = tmp_path / "profileX"
    (profile_home / "cron").mkdir(parents=True)

    seen: dict = {}

    def _run(job):
        from cron.jobs import _get_hermes_home, mark_job_run

        seen["home"] = str(_get_hermes_home().resolve())
        mark_job_run(job["id"], True)
        return True

    _stub_run_one_job(monkeypatch, _run)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(
        console_engine, "_get_console_run_executor", lambda: executor
    )

    # Enter the profile override on THIS (console) thread, create the job in the
    # profile store, and dispatch — mirroring `_profile_scope` wrapping a hosted
    # console command.
    token = set_hermes_home_override(str(profile_home))
    try:
        create_job(prompt="say hello", schedule="every 1h", name="alpha")
        engine = HermesConsoleEngine(context="hosted")
        result = engine.execute("cron run alpha", confirmed=True)
        assert result.status == "ok"
    finally:
        reset_hermes_home_override(token)

    executor.shutdown(wait=True)  # join the background fire

    # The background thread resolved the PROFILE store, not the process default.
    assert seen.get("home") == str(profile_home.resolve())


def test_repl_runs_non_interactive_lines_without_prompts(_isolate_hermes_home):
    stdin = io.StringIO("help\nexit\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_console_repl(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        interactive=False,
    )

    assert code == 0
    assert "Hermes Console" in stdout.getvalue()
    assert "hermes>" not in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_capture_output_surfaces_string_exit_code_as_command_error():
    from hermes_cli.console_engine import ConsoleCommandError, _capture_output

    def _boom():
        sys.exit("No credential matching \"nope\".")

    with pytest.raises(ConsoleCommandError) as exc_info:
        _capture_output(_boom)

    assert "No credential matching" in str(exc_info.value)


def test_capture_output_preserves_integer_exit_code_message():
    from hermes_cli.console_engine import ConsoleCommandError, _capture_output

    with pytest.raises(ConsoleCommandError) as exc_info:
        _capture_output(lambda: sys.exit(3))

    assert "status 3" in str(exc_info.value)


def test_execute_handler_string_exit_returns_error_not_crash(_isolate_hermes_home):
    result = HermesConsoleEngine().execute(
        "auth remove openrouter __no_such_credential__", confirmed=True
    )

    assert result.status == "error"
    assert result.output


_ORPHAN_STORE_STATUS = {
    "projects": [
        {"hash": "abc123", "workdir": "/gone/v2-project", "exists": False, "commits": 4},
    ],
    "pre_v2_projects": [],
}


def _patch_checkpoint_manager(monkeypatch, prune_calls: list) -> None:
    """Report one orphan project and record the resulting prune call."""
    import tools.checkpoint_manager as ckpt_mgr

    monkeypatch.setattr(ckpt_mgr, "store_status", lambda *a, **k: _ORPHAN_STORE_STATUS)

    def _fake_prune(**kwargs):
        prune_calls.append(kwargs)
        return {
            "scanned": 1,
            "deleted_orphan": 1,
            "deleted_stale": 0,
            "errors": 0,
            "bytes_freed": 0,
        }

    monkeypatch.setattr(ckpt_mgr, "prune_checkpoints", _fake_prune)


def test_console_checkpoints_prune_does_not_reprompt_for_orphans(
    _isolate_hermes_home, monkeypatch
):
    """`checkpoints prune` is console-mutating, so the nested prompt must be skipped.

    The console asks for confirmation itself before dispatching any command in the
    `checkpoints` mutating set, and `_apply_confirmed_defaults` exists to keep the
    CLI layer from asking a second time. `clear` and `clear-legacy` are force
    defaulted; `prune` was not, so its orphan confirmation still called `input()`.
    """
    prune_calls: list = []
    _patch_checkpoint_manager(monkeypatch, prune_calls)

    def _unexpected_input(_prompt):
        raise AssertionError(
            "input() must not be called: the console already confirmed `checkpoints prune`"
        )

    monkeypatch.setattr("builtins.input", _unexpected_input)

    result = HermesConsoleEngine().execute("checkpoints prune", confirmed=True)

    assert result.status == "ok"
    assert len(prune_calls) == 1
    assert prune_calls[0]["delete_orphans"] is True
    # No preview was shown, so there is nothing to bind the deletion to — the
    # documented `--force` case for `orphan_allowlist`.
    assert prune_calls[0]["orphan_allowlist"] is None


def test_console_checkpoints_prune_succeeds_without_a_tty(
    _isolate_hermes_home, monkeypatch
):
    """The dashboard console has no stdin, so an unskipped prompt aborts the command.

    `_capture_output` redirects stdout/stderr but never stdin, so `input()` raises
    `EOFError`, `_confirm` returns False, and `cmd_prune` returns 1 — which the
    console surfaces as a failed command for every user with an orphan project.
    """
    prune_calls: list = []
    _patch_checkpoint_manager(monkeypatch, prune_calls)

    def _eof_input(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof_input)

    result = HermesConsoleEngine().execute("checkpoints prune", confirmed=True)

    assert result.status == "ok"
    assert "Aborted." not in result.output
    assert len(prune_calls) == 1
    assert prune_calls[0]["orphan_allowlist"] is None


def test_config_set_on_unparseable_yaml_reports_error_not_crash(tmp_path, monkeypatch):
    """The fail-closed config write guard raises RuntimeError; the console must
    surface it as a command error, not let it escape execute() and kill the
    REPL / dashboard websocket session (regression for PR #71385 follow-up)."""
    config_path = tmp_path / "config.yaml"
    original = "model:\n  default: keep\nbroken: [unterminated\n"
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = HermesConsoleEngine().execute(
        "config set model.default gpt-4o", confirmed=True
    )

    assert result.status == "error"
    assert "not valid YAML" in (result.output or "") or "Failed to parse" in (result.output or "")
    # The broken-but-recoverable file must survive untouched.
    assert config_path.read_text(encoding="utf-8") == original
