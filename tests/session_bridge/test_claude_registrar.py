from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timezone
import io
import hashlib
import json
import logging
from itertools import product
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import threading
import time
from typing import Any, cast

import pytest

from hermes_state import SessionDB

from session_bridge.claude_adapter import (
    ClaudeSourceAdapter,
    claude_project_directory_name,
)
from session_bridge.characterize import build_characterization_auth_recovery_prompt
from session_bridge.claude_registrar import (
    ClaudeNativeRegistrar,
    PtyCleanupResult,
    WindowsConPtyFactory,
    _PtyReadinessTimeout,
    _RegistrarCancelled,
    _PtyResponseTimeout,
    _redacted_launch_frame,
    _WinPtyProcess,
    _claude_main_repl_ready,
    _known_claude_input_modal_visible,
    _exact_registered_suffix,
    _has_exact_registered_response,
    _is_exact_registered_text,
    _is_provider_limit_failure,
    _normalized_terminal_output,
    _pasted_input_indicator,
    _pasted_input_visible,
    _prompt_input_registered_response,
    _registrar_pywinpty_process_type,
    _stripped_terminal_text,
)
from session_bridge.claude_visibility import (
    ClaudeVisibilityCandidate,
    ClaudeVisibilityClaim,
    build_claude_registration_prompt,
    derive_claude_visibility_identity,
)
from session_bridge.models import (
    OriginKind,
    ProjectedMessage,
    Provider,
    SessionProjection,
)
from session_bridge.store import SessionBridgeStore


SECRET = b"registrar-test-marker-secret"


def candidate() -> ClaudeVisibilityCandidate:
    return ClaudeVisibilityCandidate(
        source_session_id="codex:source-1",
        source_provider=Provider.CODEX,
        native_name="[Codex] Explain the registrar",
        source_cwd="C:/exact/project/subdir",
        git_root="C:/exact/project",
        git_branch="main",
        git_head="abc123",
        worktree_id="worktree-1",
        eligible_at=10.0,
    )


def claim(**changes: Any) -> ClaudeVisibilityClaim:
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    base = ClaudeVisibilityClaim(
        status="claimed",
        lease_kind="launch",
        job_id=identity.job_id,
        source_session_id=value.source_session_id,
        source_provider=value.source_provider,
        reserved_claude_uuid=identity.claude_uuid,
        native_name=value.native_name,
        source_cwd=value.source_cwd,
        git_root=value.git_root,
        git_branch=value.git_branch,
        git_head=value.git_head,
        worktree_id=value.worktree_id,
        signed_marker=identity.signed_marker,
        lease_digest="a" * 64,
        attempt_ordinal=1,
        registration_reserved=True,
        launch_permitted=True,
    )
    return replace(base, **changes)


def test_cancelled_claim_retries_without_spawning_or_creation_ambiguity() -> None:
    store = FakeStore()
    factory = FakeFactory()
    stop = threading.Event()
    stop.set()

    result = registrar(FakeSource(), factory, store).process(claim(), stop=stop)

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    assert factory.spawns == []
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancelled_reconciliation_does_not_write_exact_absence() -> None:
    store = FakeStore()
    stop = threading.Event()
    stop.set()
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    result = registrar(FakeSource(), FakeFactory(), store).process(item, stop=stop)

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancellation_during_reconciliation_lookup_does_not_record_absence() -> None:
    stop = threading.Event()
    store = FakeStore()
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    class CancellingSource(FakeSource):
        def find_native_session(self, native_id: str) -> Path | None:
            stop.set()
            return super().find_native_session(native_id)

    result = registrar(CancellingSource(), FakeFactory(), store).process(
        item, stop=stop
    )

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancellation_during_existing_exact_lookup_does_not_commit() -> None:
    stop = threading.Event()
    store = FakeStore()
    item = claim()

    class CancellingSource(FakeSource):
        def find_native_session(self, native_id: str) -> Path | None:
            found = super().find_native_session(native_id)
            stop.set()
            return found

    result = registrar(
        CancellingSource([projection_for(item)]), FakeFactory(), store
    ).process(item, stop=stop)

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancellation_during_exact_lookup_still_prevents_spawn() -> None:
    stop = threading.Event()
    store = FakeStore()

    class CancellingSource(FakeSource):
        def find_native_session(self, native_id: str) -> Path | None:
            stop.set()
            return super().find_native_session(native_id)

    factory = FakeFactory()

    result = registrar(CancellingSource(), factory, store).process(claim(), stop=stop)

    assert factory.spawns == []
    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    assert [call[0] for call in store.calls] == ["retry"]


def test_post_spawn_cancellation_binds_token_and_cleans_up_as_ambiguous() -> None:
    stop = threading.Event()
    store = FakeStore()

    class CancellingPty(FakePty):
        def __init__(self) -> None:
            super().__init__()
            self.bound_stop: object | None = None

        def set_cancel_event(self, value: object) -> None:
            self.bound_stop = value

        def read_until_ready(
            self, timeout: float, *, accept_workspace_trust: bool = False
        ) -> str:
            stop.set()
            raise _RegistrarCancelled()

    process = CancellingPty()
    factory = FakeFactory(process)

    result = registrar(FakeSource(), factory, store).process(claim(), stop=stop)

    assert process.bound_stop is stop
    assert process.terminated is True
    assert process.closed is True
    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancellation_during_prompt_settle_cannot_commit_and_cleans_up() -> None:
    stop = threading.Event()
    store = FakeStore()

    class CancelAfterPromptWrite(FakePty):
        def write(self, data: str) -> None:
            super().write(data)
            stop.set()

    process = CancelAfterPromptWrite()

    result = registrar(FakeSource(), FakeFactory(process), store).process(
        claim(), stop=stop
    )

    assert process.prompt_input_waits == []
    assert process.terminated is True
    assert process.closed is True
    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]


def test_cancellation_interrupts_transcript_discovery_poll() -> None:
    stop = threading.Event()
    store = FakeStore()
    item = claim()
    process = FakePty()

    class CancellingSource(FakeSource):
        def find_native_session(self, native_id: str) -> Path | None:
            found = super().find_native_session(native_id)
            if len(self.lookups) == 2:
                stop.set()
            return found

    source = CancellingSource([None, None])

    result = registrar(
        source,
        FakeFactory(process),
        store,
        discovery_timeout=30.0,
    ).process(item, stop=stop)

    assert source.lookups == [item.reserved_claude_uuid, item.reserved_claude_uuid]
    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]


def test_post_spawn_cancellation_cannot_commit_discovered_transcript() -> None:
    stop = threading.Event()
    store = FakeStore()
    item = claim()

    class CancellingSource(FakeSource):
        def find_native_session(self, native_id: str) -> Path | None:
            found = super().find_native_session(native_id)
            if len(self.lookups) == 2:
                stop.set()
            return found

    source = CancellingSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(FakePty()), store).process(item, stop=stop)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]


def test_claude_visibility_claim_rejects_positional_construction() -> None:
    with pytest.raises(TypeError):
        ClaudeVisibilityClaim("claimed", "launch")  # type: ignore[misc]


@dataclass
class FakeParse:
    projection: SessionProjection
    malformed_lines: int = 0
    unknown_records: int = 0
    entrypoint: str | None = "cli"


class FakeSource:
    def __init__(
        self,
        projections: list[SessionProjection | None] | None = None,
        *,
        parse_error: Exception | None = None,
        project_name: str | None = None,
        duplicate_paths: list[Path] | None = None,
        malformed_lines: int = 0,
        unknown_records: int = 0,
        entrypoint: str | None = "cli",
    ):
        self.projections = list(projections or [None])
        self.lookups: list[str] = []
        self.parse_error = parse_error
        self.project_name = project_name
        self.duplicate_paths = duplicate_paths
        self.malformed_lines = malformed_lines
        self.unknown_records = unknown_records
        self.entrypoint = entrypoint

    def find_native_session(self, native_id: str) -> Path | None:
        self.lookups.append(native_id)
        item = (
            self.projections.pop(0)
            if len(self.projections) > 1
            else self.projections[0]
        )
        self.current = item
        if item is None:
            return None
        project_name = self.project_name or claude_project_directory_name(
            item.cwd or ""
        )
        return (
            Path("C:/Users/test/.claude/projects") / project_name / f"{native_id}.jsonl"
        )

    def find_native_sessions(self, native_id: str) -> list[Path]:
        if self.duplicate_paths is not None:
            self.lookups.append(native_id)
            self.current = self.projections[0]
            return self.duplicate_paths
        found = self.find_native_session(native_id)
        return [] if found is None else [found]


    def parse(self, path: Path) -> FakeParse:
        if self.parse_error is not None:
            raise self.parse_error
        assert self.current is not None
        return FakeParse(
            self.current,
            malformed_lines=self.malformed_lines,
            unknown_records=self.unknown_records,
            entrypoint=self.entrypoint,
        )

    def projection_has_exact_marker(
        self, projection: SessionProjection, marker: str
    ) -> bool:
        return any(marker in (message.content or "") for message in projection.messages)


class ExactStemSource(FakeSource):
    def __init__(self) -> None:
        super().__init__()
        self.exact_stem_calls: list[str] = []

    def find_native_sessions_by_stem(self, native_id: str) -> list[Path]:
        self.exact_stem_calls.append(native_id)
        return []

    def find_native_sessions(self, native_id: str) -> list[Path]:
        raise AssertionError("registrar used the unbounded compatibility lookup")


class FakeStore:
    def __init__(self):
        self.calls: list[tuple[Any, ...]] = []

    def commit_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("commit", *args))
        return {"state": "claude_visible"}

    def retry_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("retry", *args))
        return {"state": "claude_retry"}

    def fail_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("fail", *args))
        return {"state": "claude_failed"}

    def record_claude_visibility_exact_id_absent(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("absent", *args))
        return {"state": "claude_retry"}

    def retry_claude_auth_recovery(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("retry_auth_recovery", *args))
        return {"state": "retry"}

    def begin_claude_auth_recovery(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("begin_auth_recovery", *args))
        return {"state": "leased", "call_started_at": 100.0}


class FakePty:
    def __init__(
        self,
        output: str = "REGISTERED\r\n",
        exit_code: int = 0,
        read_error: Exception | None = None,
        ready_output: str = "\x1b[?2004h\x1b[2m⏵⏵ don't ask on\x1b[0m",
        ready_error: Exception | None = None,
        prompt_input_output: str = "[Pasted text #1 +12 lines]\r\n",
        prompt_input_error: Exception | None = None,
        write_error_at: int | None = None,
        wait_error: Exception | None = None,
    ):
        self.output = output
        self.exit_code = exit_code
        self.read_error = read_error
        self.ready_output = ready_output
        self.ready_error = ready_error
        self.prompt_input_output = prompt_input_output
        self.prompt_input_error = prompt_input_error
        self.write_error_at = write_error_at
        self.wait_error = wait_error
        self.writes: list[str] = []
        self.waits: list[float] = []
        self.terminated = False
        self.closed = False
        self.cleanup_result = PtyCleanupResult(True, True, True, exit_code)
        self.ready_waits: list[float] = []
        self.ready_trust_acceptances: list[bool] = []
        self.prompt_input_waits: list[tuple[float, str]] = []

    def read_until_ready(
        self, timeout: float, *, accept_workspace_trust: bool = False
    ) -> str:
        self.ready_waits.append(timeout)
        self.ready_trust_acceptances.append(accept_workspace_trust)
        if self.ready_error is not None:
            raise self.ready_error
        return self.ready_output

    def read_until(self, timeout: float, *, prompt: str | None = None) -> str:
        if self.read_error:
            raise self.read_error
        return self.output

    def read_until_prompt_input(self, timeout: float, *, prompt: str) -> str:
        self.prompt_input_waits.append((timeout, prompt))
        if self.prompt_input_error is not None:
            raise self.prompt_input_error
        return self.prompt_input_output

    def write(self, data: str) -> None:
        if self.write_error_at == len(self.writes):
            raise RuntimeError("PTY write failed")
        self.writes.append(data)

    def wait(self, timeout: float) -> int:
        self.waits.append(timeout)
        if self.wait_error is not None:
            raise self.wait_error
        return self.exit_code

    def terminate(self, timeout: float = 1.0) -> bool:
        self.terminated = True
        return True

    def close(self, timeout: float = 1.0) -> PtyCleanupResult:
        self.closed = True
        return self.cleanup_result


class FakeFactory:
    def __init__(self, process: FakePty | None = None, error: Exception | None = None):
        self.process = process or FakePty()
        self.error = error
        self.spawns: list[tuple[list[str], str]] = []

    def spawn(self, argv: list[str], *, cwd: str):
        self.spawns.append((argv, cwd))
        if self.error:
            raise self.error
        return self.process


def projection_for(
    item: ClaudeVisibilityClaim, *, response: str = "REGISTERED", **changes: Any
) -> SessionProjection:
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    prompt = build_claude_registration_prompt(value, identity, SECRET)
    base = SessionProjection(
        provider=Provider.CLAUDE,
        native_id=item.reserved_claude_uuid or "",
        title=item.native_name,
        cwd=item.source_cwd,
        started_at=10.0,
        last_active=11.0,
        messages=[
            ProjectedMessage("u1", 0, "user", prompt, 10.0),
            ProjectedMessage("a1", 0, "assistant", response, 11.0),
        ],
        native_path=str(
            Path("C:/Users/test/.claude/projects")
            / claude_project_directory_name(item.source_cwd or "")
            / f"{item.reserved_claude_uuid}.jsonl"
        ),
        native_hash="b" * 64,
        origin_kind=OriginKind.BRIDGE_PLACEHOLDER,
        origin_bridge_id=identity.bridge_id,
    )
    return replace(base, **changes)


def registrar(
    source: FakeSource,
    factory: FakeFactory,
    store: FakeStore | None = None,
    **kwargs: Any,
):
    startup_theme = kwargs.pop("startup_theme", "light")
    sleep = kwargs.pop("sleep", lambda _value: None)
    discovery_timeout = kwargs.pop("discovery_timeout", 0.0)
    return ClaudeNativeRegistrar(
        store or FakeStore(),
        source,
        marker_secret=SECRET,
        startup_theme=startup_theme,
        pty_factory=factory,
        clock=lambda: 100.0,
        monotonic=lambda: 1.0,
        sleep=sleep,
        process_timeout=2.0,
        exit_timeout=1.0,
        discovery_timeout=discovery_timeout,
        retry_delay=5.0,
        **kwargs,
    )


@pytest.mark.parametrize(
    "startup_theme",
    [None, "", "auto", "Light", "future-theme", {"theme": "light"}],
)
def test_registrar_rejects_noncanonical_startup_theme_before_spawn(
    startup_theme: Any,
) -> None:
    factory = FakeFactory()

    with pytest.raises(ValueError, match="invalid Claude startup theme"):
        registrar(FakeSource(), factory, startup_theme=startup_theme)

    assert factory.spawns == []


_EXIT_CMD_RECORD = '<command-name>/exit</command-name> <command-message>exit</command-message> <command-args></command-args>'
_EXIT_STDOUT_RECORD = '<local-command-stdout>See ya!</local-command-stdout>'
# Built with chr() so this file carries no escape sequences:
# ESC [?2004h Claude> ESC [0m REGISTERED CR LF
_REGISTERED_PTY_OUTPUT = (
    chr(27) + "[?2004hClaude>" + chr(27) + "[0m REGISTERED" + chr(13) + chr(10)
)


def _teardown_result(item, messages):
    return registrar(
        FakeSource([None, messages]),
        FakeFactory(FakePty(output=_REGISTERED_PTY_OUTPUT)),
    ).process(item)


def test_own_exit_teardown_records_do_not_fail_the_turn_shape_check() -> None:
    """The registrar's own /exit must not make its own validator reject the turn.

    On the success branch the registrar writes "/exit"; the CLI then records that
    slash command and its stdout as USER records AFTER the response. Both land in
    messages[1:], where the turn-shape loop demands every entry be an assistant
    message carrying the response's event id. Measured live 2026-09-02 on
    transcript 4e62a4c3: turn_messages was [assistant, user, user] with ordinals
    [0, 0, 0], failing both the role check and the ordinal-contiguity check, so a
    registration that had already answered REGISTERED correctly was rejected
    bridge_conflict. Same root cause as the _is_human_user exclusion in
    69043ccdd2, one check later.
    """

    item = claim()
    base = projection_for(item)
    teardown = [
        replace(base.messages[1], native_event_id="exit-cmd", role="user",
                content=_EXIT_CMD_RECORD),
        replace(base.messages[1], native_event_id="exit-out", role="user",
                content=_EXIT_STDOUT_RECORD),
    ]
    result = _teardown_result(
        item, replace(base, messages=[*base.messages, *teardown])
    )

    assert result.status == "visible"


def test_a_real_user_turn_after_the_response_is_still_a_conflict() -> None:
    """The trim is bookkeeping-only: a genuine later turn must still be rejected."""

    item = claim()
    base = projection_for(item)
    genuine = replace(base.messages[1], native_event_id="later", role="user",
                      content="and now please do something else")
    result = _teardown_result(item, replace(base, messages=[*base.messages, genuine]))

    assert result.status == "failed" and result.error_code == "bridge_conflict"


def test_multi_part_assistant_answer_survives_the_trim() -> None:
    """Trailing-only and user-only: a multi-part assistant answer is untouched."""

    item = claim()
    base = projection_for(item)
    split = [
        replace(base.messages[1], ordinal=0, content="REGIS"),
        replace(base.messages[1], ordinal=1, content="TERED"),
        replace(base.messages[1], native_event_id="exit-cmd", role="user",
                content=_EXIT_CMD_RECORD),
    ]
    result = _teardown_result(
        item, replace(base, messages=[base.messages[0], *split])
    )

    assert result.status == "visible"


def test_launch_uses_interactive_mode_and_writes_prompt_then_exit() -> None:
    item = claim()
    process = FakePty(output="\x1b[?2004hClaude>\x1b[0m REGISTERED\r\n")
    factory = FakeFactory(process)
    source = FakeSource([None, projection_for(item)])
    result = registrar(source, factory).process(item)
    expected = build_claude_registration_prompt(
        candidate(), derive_claude_visibility_identity(candidate(), SECRET), SECRET
    )

    assert result.status == "visible"
    assert factory.spawns == [
        (
            [
                "claude",
                "--session-id",
                item.reserved_claude_uuid,
                "--name",
                item.native_name,
                "--settings",
                '{"theme":"light"}',
                "--setting-sources=",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--strict-mcp-config",
                "--no-chrome",
                "--model",
                "haiku",
                "--tools",
                "",
                "--permission-mode",
                "dontAsk",
            ],
            item.source_cwd,
        )
    ]
    argv = factory.spawns[0][0]
    assert "--print" not in argv and "-p" not in argv
    assert expected not in argv
    assert "--no-session-persistence" not in argv
    assert process.writes == [
        f"\x1b[200~{expected}\x1b[201~",
        "\r",
        "/exit\r",
    ]
    assert "tool_calls" not in expected
    assert process.ready_waits == [2.0]
    assert process.ready_trust_acceptances == [True]
    assert process.closed and process.waits == [1.0]


def test_launch_waits_for_multiline_paste_before_submitting_return() -> None:
    events: list[tuple[str, object]] = []

    class OrderedPty(FakePty):
        def write(self, data: str) -> None:
            events.append(("write", data))
            super().write(data)

        def read_until_prompt_input(self, timeout: float, *, prompt: str) -> str:
            events.append(("prompt_input", timeout))
            return super().read_until_prompt_input(timeout, prompt=prompt)

    item = claim()
    process = OrderedPty(output="REGISTERED\r\n")
    source = FakeSource([None, projection_for(item)])

    result = registrar(
        source,
        FakeFactory(process),
        sleep=lambda seconds: events.append(("sleep", seconds)),
    ).process(item)

    assert result.status == "visible"
    assert events[0][0] == "write"
    assert str(events[0][1]).startswith("\x1b[200~")
    assert events[1] == ("sleep", 0.5)
    assert events[2][0] == "prompt_input"
    assert events[3] == ("write", "\r")


def test_launch_submits_when_the_input_frame_was_unreadable() -> None:
    """An unreadable input frame is not evidence the paste self-submitted.

    "terminal_input_disabled" is the last-resort branch of
    _prompt_input_timeout_reason, reached only once every positive test has
    already failed, so it cannot support the positive conclusion that the TUI
    submitted anything.  Measured against the live TUI on 2026-08-24 with the
    real multi-line prompt: withholding the CR leaves the paste sitting in the
    input box and NO transcript is ever written, while sending it produces both
    a transcript and an answer.  A redundant CR into an already-emptied box was
    measured the same day to be a no-op -- the transcript's turn census is
    unchanged -- so submitting here is safe in both worlds.
    """

    item = claim()
    process = FakePty(
        output="REGISTERED\r\n",
        prompt_input_error=_PtyResponseTimeout("terminal_input_disabled"),
    )
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    assert process.writes[0].startswith("\x1b[200~")
    assert "\r" in process.writes
    assert process.writes[-1] == "/exit\r"


def test_launch_keeps_unverified_submission_retryable_not_fatal() -> None:
    """Sending the CR must not reclassify an unrecognized reply as fatal.

    bridge_conflict is in CLAUDE_VISIBILITY_FATAL_CODES, and one uncleared
    fatal row fail-closes the whole lane before the coordinator claims.  The
    submission flag therefore had to be split: the CR is gated on positive
    evidence of a self-submit, while retryability still covers the unverified
    case exactly as it did before.
    """

    item = claim()
    process = FakePty(
        output="input surface changed\r\n",
        prompt_input_error=_PtyResponseTimeout("terminal_input_disabled"),
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert "\r" in process.writes


@pytest.mark.parametrize(
    "prompt_input_output",
    [
        "[Pasted text #1 +12 lines]\r\nREGISTERED\r\n",
        (
            "[Pasted text #1 +12 lines]\r\n"
            "REGISTERED\r\n"
            "[Pasted text #1 +12 lines]\r\n"
        ),
    ],
)
def test_launch_accepts_auto_submitted_response_during_prompt_settle(
    prompt_input_output: str,
) -> None:
    item = claim()
    process = FakePty(
        prompt_input_output=prompt_input_output,
        read_error=_PtyResponseTimeout("no_response_output"),
    )
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    assert "\r" not in process.writes
    assert process.writes[-1] == "/exit\r"


def test_launch_rejects_substantive_text_before_auto_submitted_response() -> None:
    item = claim()
    process = FakePty(
        prompt_input_output="unexpected text\r\nREGISTERED\r\n",
        read_error=_PtyResponseTimeout("no_response_output"),
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert "\r" not in process.writes


def test_launch_keeps_unterminated_auto_submitted_response_ambiguous() -> None:
    item = claim()
    process = FakePty(
        prompt_input_output="[Pasted text #1 +12 lines]\r\nREGISTERED",
        output=" extra\r\n",
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert "\r" not in process.writes
    assert "/exit\r" not in process.writes


def test_launch_untrusted_auto_submitted_wording_yields_to_exact_transcript() -> None:
    item = claim()
    process = FakePty(
        prompt_input_output="NOT REGISTERED\r\n",
        output="REGISTERED\r\n",
    )
    store = FakeStore()
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process), store).process(item)

    assert result.status == "visible"
    assert [call[0] for call in store.calls] == ["commit"]
    assert "\r" not in process.writes
    assert "/exit\r" not in process.writes


def test_launch_malformed_auto_submitted_response_without_transcript_stays_ambiguous() -> None:
    item = claim()
    process = FakePty(
        prompt_input_output="NOT REGISTERED\r\n",
        output="REGISTERED\r\n",
    )
    store = FakeStore()

    result = registrar(FakeSource([None]), FakeFactory(process), store).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]
    assert "\r" not in process.writes
    assert "/exit\r" not in process.writes


def test_winpty_waits_until_multiline_paste_is_visible_before_submit() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m",
                    "[Pasted text #1 +12 lines]\r\n",
                ]
            )

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks)

    output = _WinPtyProcess(Process()).read_until_prompt_input(
        1.0, prompt="multiline\nregistration\nprompt"
    )

    assert "[Pasted text #1 +12 lines]" in output


def test_winpty_accepts_current_claude_multiline_editor_hint() -> None:
    output = (
        "firstline\r\nsecond line\r\nthird line\r\n"
        "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"
        "ctrl+gtoeditinNotepad"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([output])

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks)

    observed = _WinPtyProcess(Process()).read_until_prompt_input(
        1.0, prompt="a much longer multiline registration prompt"
    )

    assert "ctrl+gtoeditinNotepad" in observed


def test_winpty_accepts_cursor_positioned_pasted_text_token() -> None:
    output = (
        "\x1b[2m[Pasted\x1b[1Ctext\x1b[1C#1\x1b[1C+6\x1b[1Clines]\x1b[0m"
        " paste again to expand"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([output])

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks)

    observed = _WinPtyProcess(Process()).read_until_prompt_input(
        1.0, prompt="a much longer multiline registration prompt"
    )

    assert "paste again to expand" in observed


def test_winpty_prompt_input_wait_drains_post_acceptance_redraw() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "[Pastedtext#1+6lines] paste again to expand",
                    "\r\nlate redraw",
                ]
            )

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks)

    observed = _WinPtyProcess(Process()).read_until_prompt_input(
        1.0, prompt="a much longer multiline registration prompt"
    )

    assert "late redraw" in observed


def test_winpty_hands_auto_submitted_response_to_response_reader() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter(["REGISTERED\r\n"])

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks, None)

    prompt = "a multiline registration prompt"
    process = _WinPtyProcess(Process())

    with pytest.raises(_PtyResponseTimeout) as exc_info:
        process.read_until_prompt_input(0.01, prompt=prompt)

    assert exc_info.value.reason == "terminal_input_disabled"
    assert process.read_until(1.0, prompt=prompt).strip() == "REGISTERED"


@pytest.mark.parametrize(
    ("process", "expected_writes"),
    [
        (FakePty(write_error_at=0), []),
        (FakePty(write_error_at=1), ["prompt"]),
        (FakePty(wait_error=TimeoutError()), ["prompt", "\r", "/exit\r"]),
    ],
)
def test_interactive_write_or_exit_uncertainty_is_creation_ambiguous(
    process: FakePty, expected_writes: list[str]
) -> None:
    item = claim()
    expected = build_claude_registration_prompt(
        candidate(), derive_claude_visibility_identity(candidate(), SECRET), SECRET
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    normalized = [
        "prompt" if value == f"\x1b[200~{expected}\x1b[201~" else value
        for value in process.writes
    ]
    assert normalized == expected_writes
    assert process.terminated and process.closed


def test_malformed_interactive_response_never_sends_exit_command() -> None:
    process = FakePty(output="NOT REGISTERED")

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"
    assert len(process.writes) == 2
    assert process.writes[0].startswith("\x1b[200~")
    assert process.writes[1] == "\r"
    assert "/exit\r" not in process.writes
    assert process.terminated and process.closed


def test_tui_readiness_timeout_never_writes_registration_prompt() -> None:
    process = FakePty(ready_error=TimeoutError())

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert process.writes == []
    assert process.terminated and process.closed


def test_tui_readiness_timeout_preserves_bounded_phase_diagnostic() -> None:
    process = FakePty(
        ready_error=_PtyReadinessTimeout("known_input_modal"),
    )

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert result.detail == "Claude TUI readiness blocked: known_input_modal"
    assert process.writes == []
    assert process.terminated and process.closed


def test_tui_dialog_marker_without_main_repl_never_writes_registration_prompt() -> None:
    process = FakePty(
        ready_output=(
            "\x1b[?2004hAccessing workspace: Yes, I trust this folder "
            "No, exit Security guide"
        )
    )

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert process.writes == []
    assert process.terminated and process.closed


def test_tui_disabled_bracketed_paste_after_footer_never_writes_prompt() -> None:
    process = FakePty(
        ready_output=(
            "\x1b[?2004h\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
            "\x1b[?2004l"
        )
    )

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert process.writes == []
    assert process.terminated and process.closed


def test_tui_product_modal_after_footer_never_writes_prompt() -> None:
    process = FakePty(
        ready_output=(
            "\x1b[?2004h\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
            "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
            "1. Yes, try it\r\n2. Not now\r\n"
        )
    )

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert process.writes == []
    assert process.terminated and process.closed


@pytest.mark.parametrize(
    "ready_output",
    [
        (
            "\x1b[?2004h\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
            "1. Yes, try it\r\n2. Not now\r\n"
            "\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
        ),
        (
            "\x1b[?2004h\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
            "1. Yes, try it\r\n2. Not now\r\n"
            "\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
            "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
            "1. Yes, try it\r\n2. Not now\r\n"
            "\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
        ),
    ],
    ids=["modal-before-footer", "repeated-modal-footer-redraw"],
)
def test_tui_modal_history_before_latest_footer_never_writes_prompt(
    ready_output: str,
) -> None:
    process = FakePty(ready_output=ready_output)

    result = registrar(FakeSource(), FakeFactory(process)).process(claim())

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert process.writes == []
    assert process.terminated and process.closed


def test_print_mode_transcript_can_never_commit_native_visibility() -> None:
    item = claim()
    source = FakeSource(
        [None, projection_for(item)],
        entrypoint="sdk-cli",
    )

    result = registrar(source, FakeFactory()).process(item)

    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"


def test_auth_recovery_resumes_exact_uuid_interactively_without_create() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    process = FakePty(output="REGISTERED\r\n", exit_code=0)
    factory = FakeFactory(process)

    outcome = registrar(FakeSource(), factory).resume_auth_recovery(recovery, prompt)

    assert outcome.status == "recovered"
    assert outcome.reserved_claude_uuid == item.reserved_claude_uuid
    assert factory.spawns == [
        (
            [
                "claude",
                "--resume",
                item.reserved_claude_uuid,
                "--settings",
                '{"theme":"light"}',
                "--setting-sources=",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--strict-mcp-config",
                "--no-chrome",
                "--model",
                "haiku",
                "--tools",
                "",
                "--permission-mode",
                "dontAsk",
            ],
            item.source_cwd,
        )
    ]
    assert "--session-id" not in factory.spawns[0][0]
    assert "--print" not in factory.spawns[0][0]
    assert prompt not in factory.spawns[0][0]
    assert "--no-session-persistence" not in factory.spawns[0][0]
    assert process.writes == [
        f"\x1b[200~{prompt}\x1b[201~",
        "\r",
        "/exit\r",
    ]
    assert process.ready_trust_acceptances == [True]


def test_auth_recovery_accepts_exact_response_after_paste_auto_submit() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    process = FakePty(
        output="REGISTERED\r\n",
        prompt_input_error=_PtyResponseTimeout("terminal_input_disabled"),
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        recovery, prompt
    )

    assert outcome.status == "recovered"
    # Same unreadable-input-frame correction as the launch path; this path
    # pastes through the identical bracketed frame and inherited the same bug.
    assert "\r" in process.writes
    assert process.writes[-1] == "/exit\r"


def test_auth_recovery_keeps_auto_submit_without_exact_response_ambiguous() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    process = FakePty(
        output="input surface changed\r\n",
        prompt_input_error=_PtyResponseTimeout("terminal_input_disabled"),
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        recovery, prompt
    )

    assert outcome.status == "retry"
    assert outcome.error_code == "creation_ambiguous"
    # Retryability is unchanged by the split; only the CR gate moved.
    assert "\r" in process.writes


@pytest.mark.parametrize("phase", ["prompt_input", "response"])
def test_auth_recovery_keeps_provider_limit_transient(phase: str) -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    limited = "You've hit your limit · resets Jul 20, 4am"
    process = (
        FakePty(prompt_input_output=limited)
        if phase == "prompt_input"
        else FakePty(output=limited)
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        recovery, prompt
    )

    assert outcome.status == "retry"
    assert outcome.error_code == "creation_ambiguous"


def test_auth_recovery_never_discards_malformed_auto_submitted_response() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    process = FakePty(
        prompt_input_output="NOT REGISTERED\r\n",
        output="REGISTERED\r\n",
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        recovery, prompt
    )

    assert outcome.status == "retry"
    assert outcome.error_code == "creation_ambiguous"
    assert "\r" not in process.writes
    assert "/exit\r" not in process.writes


def test_auth_recovery_durably_marks_call_started_before_spawn() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    store = FakeStore()
    factory = FakeFactory(FakePty(output="REGISTERED\r\n", exit_code=0))

    outcome = registrar(FakeSource(), factory, store).resume_auth_recovery(
        recovery, prompt
    )

    assert outcome.status == "recovered"
    assert store.calls == [
        ("begin_auth_recovery", item.job_id, "b" * 64),
    ]
    assert len(factory.spawns) == 1


def test_auth_recovery_malformed_response_terminalizes_when_store_marks_fatal() -> None:
    class FatalStore(FakeStore):
        def retry_claude_auth_recovery(self, *args: Any) -> dict[str, Any]:
            self.calls.append(("retry_auth_recovery", *args))
            return {"state": "failed", "error_code": "bridge_conflict"}

    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    recovery = {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }
    store = FatalStore()

    outcome = registrar(
        FakeSource(), FakeFactory(FakePty(output="NOT REGISTERED", exit_code=0)), store
    ).resume_auth_recovery(recovery, prompt)

    assert outcome.status == "failed"
    assert outcome.error_code == "bridge_conflict"


def test_strict_projection_accepts_exact_2110_resume_scaffold() -> None:
    item = claim()
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    original_prompt = build_claude_registration_prompt(value, identity, SECRET)
    recovery_prompt = build_characterization_auth_recovery_prompt(
        item.reserved_claude_uuid or "", item.signed_marker or ""
    )
    messages = [
        ProjectedMessage("original", 0, "user", original_prompt, 10.0),
        ProjectedMessage(
            "auth",
            0,
            "assistant",
            "Failed to authenticate. API Error: 401 Invalid authentication credentials",
            11.0,
        ),
        ProjectedMessage("scaffold", 0, "assistant", "No response requested.", 12.0),
        ProjectedMessage("recovery-user", 0, "user", recovery_prompt, 13.0),
        ProjectedMessage("recovery-assistant", 0, "assistant", "REGISTERED", 14.0),
    ]
    projection = projection_for(item, messages=messages, last_active=14.0)
    store = FakeStore()

    result = registrar(FakeSource([projection]), FakeFactory(), store).process(item)

    assert result.status == "visible"
    assert store.calls[0][0] == "commit"


def test_terminal_echo_and_ansi_are_removed_before_exact_response_check() -> None:
    item = claim()
    expected = build_claude_registration_prompt(
        candidate(), derive_claude_visibility_identity(candidate(), SECRET), SECRET
    )
    echoed = "\r\n".join([
        f"\x1b[32mClaude>\x1b[0m {expected.splitlines()[0]}",
        *expected.splitlines()[1:],
    ])
    process = FakePty(output=f"{echoed}\r\n\x1b[32mREGISTERED\x1b[0m\r\n")
    result = registrar(
        FakeSource([None, projection_for(item)]), FakeFactory(process)
    ).process(item)
    assert result.status == "visible"


@pytest.mark.parametrize(
    "output", ["NOT REGISTERED", "REGISTERED later", "xREGISTERED", "REGISTERED\nextra"]
)
def test_registration_response_requires_exact_bounded_token(output: str) -> None:
    item = claim()
    store = FakeStore()
    process = FakePty(output=output)
    result = registrar(FakeSource(), FakeFactory(process), store).process(item)
    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"
    assert store.calls[0][0] == "fail"
    assert process.closed and process.terminated


_VALID_AUTHORITIES = {
    ("launch", True, True, False),
    ("reconciliation", False, False, True),
}
_INVALID_AUTHORITIES = [
    authority
    for authority in product(
        ("launch", "reconciliation"),
        (False, True),
        (False, True),
        (False, True),
    )
    if authority not in _VALID_AUTHORITIES
] + [(None, True, True, False), ("launch", 1, True, False)]


@pytest.mark.parametrize("authority", _INVALID_AUTHORITIES)
def test_inconsistent_claim_authority_is_rejected_before_lookup_spawn_or_store(
    authority: tuple[Any, Any, Any, Any],
) -> None:
    lease_kind, launch_permitted, registration_reserved, requires_reconciliation = (
        authority
    )
    source = FakeSource()
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(source, factory, store).process(
        claim(
            lease_kind=lease_kind,
            launch_permitted=launch_permitted,
            registration_reserved=registration_reserved,
            requires_exact_id_reconciliation=requires_reconciliation,
        )
    )
    assert result.status == "failed" and result.error_code == "bridge_conflict"
    assert factory.spawns == []
    assert source.lookups == []
    assert store.calls == []


def test_reconciliation_exact_match_commits_without_spawn() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(FakeSource([projection_for(item)]), factory, store).process(item)
    assert result.status == "visible"
    assert factory.spawns == []
    assert store.calls[0][0] == "commit"


def test_reconciliation_absence_is_recorded_and_never_launches_same_cycle() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(FakeSource([None]), factory, store).process(item)
    assert result.status == "absent"
    assert store.calls[0][0] == "absent"
    assert factory.spawns == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"native_id": "00000000-0000-4000-8000-000000000000"}, "uuid_conflict"),
        ({"title": "wrong"}, "name_conflict"),
        ({"cwd": "C:/wrong"}, "cwd_conflict"),
        ({"origin_bridge_id": "wrong"}, "bridge_conflict"),
    ],
)
def test_reconciliation_conflicts_fail(changes: dict[str, Any], code: str) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    store = FakeStore()
    result = registrar(
        FakeSource([projection_for(item, **changes)]), FakeFactory(), store
    ).process(item)
    assert result.status == "failed" and result.error_code == code
    assert store.calls[0][0] == "fail"


def test_reconciliation_fails_an_exact_uuid_with_wrong_authenticated_marker() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    messages = list(projection.messages)
    messages[0] = replace(messages[0], content="forged registration prompt")
    store = FakeStore()
    result = registrar(
        FakeSource([replace(projection, messages=messages)]), FakeFactory(), store
    ).process(item)
    assert result.status == "failed" and result.error_code == "marker_conflict"


def test_registration_prompt_must_pair_with_immediate_exact_assistant_reply() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    prompt_message = projection.messages[0]
    messages = [
        prompt_message,
        replace(projection.messages[1], content="WRONG"),
        replace(prompt_message, native_event_id="u2", content="unrelated user turn"),
        replace(projection.messages[1], native_event_id="a2", content="REGISTERED"),
    ]
    result = registrar(
        FakeSource([replace(projection, messages=messages)]), FakeFactory()
    ).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"


def test_registration_turn_aggregates_split_text_blocks_from_same_assistant_event() -> (
    None
):
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    assistant = projection.messages[1]
    messages = [
        projection.messages[0],
        replace(assistant, ordinal=0, content="REGIS"),
        replace(assistant, ordinal=1, content="TERED"),
    ]
    result = registrar(
        FakeSource([replace(projection, messages=messages)]), FakeFactory()
    ).process(item)
    assert result.status == "visible"


def test_registration_turn_rejects_extra_block_in_same_assistant_event() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    assistant = projection.messages[1]
    messages = [
        projection.messages[0],
        assistant,
        replace(assistant, ordinal=1, content="extra"),
    ]
    result = registrar(
        FakeSource([replace(projection, messages=messages)]), FakeFactory()
    ).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"


def test_exact_transcript_must_use_windows_encoded_source_project_directory() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    expected = claude_project_directory_name(item.source_cwd or "")
    assert expected == "C--exact-project-subdir"
    assert (
        registrar(FakeSource([projection_for(item)]), FakeFactory())
        .process(item)
        .status
        == "visible"
    )

    wrong = registrar(
        FakeSource([projection_for(item)], project_name="C--wrong-project"),
        FakeFactory(),
    ).process(replace(item, lease_digest="c" * 64))
    assert wrong.status == "failed" and wrong.error_code == "cwd_conflict"


def test_paid_exact_path_parse_failure_is_terminal_and_never_spawns() -> None:
    item = claim()
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(
        FakeSource([projection_for(item)], parse_error=ValueError("identity changed")),
        factory,
        store,
    ).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"
    assert factory.spawns == []
    assert store.calls[0][0] == "fail"


@pytest.mark.parametrize(
    "source",
    [
        lambda projection: FakeSource([projection], malformed_lines=1),
        lambda projection: FakeSource([projection], unknown_records=1),
    ],
)
def test_registration_transcript_rejects_malformed_or_unknown_records(
    source: Any,
) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    result = registrar(source(projection_for(item)), FakeFactory()).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"


def test_registration_transcript_rejects_any_unrelated_projected_message() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    extra = replace(
        projection.messages[1], native_event_id="later", content="unrelated work"
    )
    result = registrar(
        FakeSource([replace(projection, messages=[*projection.messages, extra])]),
        FakeFactory(),
    ).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"


@pytest.mark.parametrize(
    "response",
    [
        "You've hit your limit · resets Jul 20, 4am "
        "(America/New_York)\nAPI Error: 429 rate_limit",
        "You\u2019ve hit your weekly limit · resets Aug 3, 4am "
        "(America/New_York)",
        "You've hit your weekly limit \u00c2\u00b7 resets Aug 3, 4am "
        "(America/New_York)",
    ],
)
def test_exact_uuid_provider_limit_transcript_reconciles_without_replacement(
    response: str,
) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item, response=response)
    factory = FakeFactory()
    result = registrar(FakeSource([projection]), factory).process(item)

    assert result.status == "visible"
    assert factory.spawns == []


def test_exact_uuid_provider_limit_before_persisted_prompt_reconciles_without_replacement() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    limited = "You've hit your weekly limit · resets Aug 24, 4am (America/New_York)"
    projection = projection_for(item, response=limited)
    prompt, response = projection.messages
    projection = replace(projection, messages=[response, prompt])
    factory = FakeFactory()

    result = registrar(FakeSource([projection]), factory).process(item)

    assert result.status == "visible"
    assert factory.spawns == []


@pytest.mark.parametrize(
    "messages",
    [
        lambda prompt, limited: [
            replace(prompt, role="assistant", content=limited),
            replace(prompt, native_event_id=prompt.native_event_id),
        ],
        lambda prompt, limited: [
            replace(prompt, role="assistant", content=limited),
            prompt,
            replace(prompt, native_event_id="later", content="unrelated work"),
        ],
        lambda prompt, limited: [
            replace(prompt, role="assistant", content=limited, reasoning="hidden"),
            prompt,
        ],
        lambda prompt, limited: [
            replace(
                prompt,
                role="assistant",
                native_event_id="provider-limit",
                content=f"{limited}\nUNEXPECTED TRAILING TEXT",
            ),
            prompt,
        ],
    ],
)
def test_provider_limit_before_prompt_does_not_bypass_strict_transcript_shape(
    messages: Any,
) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    prompt = projection.messages[0]
    limited = "You've hit your weekly limit · resets Aug 24, 4am (America/New_York)"
    projection = replace(projection, messages=messages(prompt, limited))

    result = registrar(FakeSource([projection]), FakeFactory()).process(item)

    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"


@pytest.mark.parametrize(
    "response",
    [
        "You've hit your weekly limit? No; usage resets tomorrow.",
        'Assistant quoted: "You\u2019ve hit your weekly limit · resets tomorrow."',
        "You've hit your weekly limits · resets tomorrow.",
    ],
)
def test_exact_uuid_non_limit_text_never_bypasses_registered_response(
    response: str,
) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    factory = FakeFactory()

    result = registrar(
        FakeSource([projection_for(item, response=response)]),
        factory,
    ).process(item)

    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"
    assert factory.spawns == []


def test_launch_provider_limit_reconciles_created_exact_uuid_in_same_cycle() -> None:
    item = claim()
    limited = "You've hit your limit · resets Jul 20, 4am " \
        "(America/New_York)\nAPI Error: 429 rate_limit"
    source = FakeSource([None, projection_for(item, response=limited)])
    factory = FakeFactory(FakePty(output=limited))

    result = registrar(source, factory).process(item)

    assert result.status == "visible"
    assert len(factory.spawns) == 1
    assert source.lookups == [item.reserved_claude_uuid, item.reserved_claude_uuid]


def test_launch_current_session_limit_wording_retries_without_waiting_for_timeout() -> None:
    item = claim()
    limited = (
        "You've hit your session limit · resets 6:50pm (America/New_York)"
    )
    source = FakeSource([None, None])
    factory = FakeFactory(FakePty(output=limited))

    result = registrar(source, factory).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert result.detail == "Claude provider limit interrupted registration"
    assert len(factory.spawns) == 1
    assert source.lookups == [item.reserved_claude_uuid, item.reserved_claude_uuid]


@pytest.mark.parametrize("apostrophe", ["'", "\u2019"])
def test_launch_current_weekly_limit_wording_retries_without_waiting_for_timeout(
    apostrophe: str,
) -> None:
    item = claim()
    limited = (
        f"You{apostrophe}ve hit your weekly limit · "
        "resets Aug 3, 4am (America/New_York)"
    )
    source = FakeSource([None, None])
    factory = FakeFactory(FakePty(output=limited))

    result = registrar(source, factory).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert result.detail == "Claude provider limit interrupted registration"
    assert len(factory.spawns) == 1
    assert source.lookups == [item.reserved_claude_uuid, item.reserved_claude_uuid]


@pytest.mark.parametrize(
    "messages",
    [
        lambda projection: [
            replace(
                projection.messages[0], native_event_id="earlier", content="old work"
            ),
            *projection.messages,
        ],
        lambda projection: [
            projection.messages[0],
            replace(projection.messages[1], ordinal=1, content="REGISTERED"),
        ],
        lambda projection: [
            projection.messages[0],
            projection.messages[1],
            replace(projection.messages[1], content=""),
        ],
    ],
)
def test_registration_transcript_rejects_extra_turns_and_bad_block_ordinals(
    messages: Any,
) -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    projection = projection_for(item)
    result = registrar(
        FakeSource([replace(projection, messages=messages(projection))]), FakeFactory()
    ).process(item)
    assert result.status == "failed" and result.error_code == "bridge_conflict"


def test_duplicate_exact_uuid_is_fatal_before_spawn_or_commit() -> None:
    item = claim()
    project = claude_project_directory_name(item.source_cwd or "")
    paths = [
        Path("C:/Users/test/.claude/projects")
        / project
        / f"{item.reserved_claude_uuid}.jsonl",
        Path("D:/other/.claude/projects/C--other")
        / f"{item.reserved_claude_uuid}.jsonl",
    ]
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(
        FakeSource([projection_for(item)], duplicate_paths=paths), factory, store
    ).process(item)
    assert result.status == "failed" and result.error_code == "duplicate_uuid"
    assert factory.spawns == [] and store.calls[0][0] == "fail"


def test_reconciliation_uses_authoritative_stem_lookup_without_legacy_probe() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    source = ExactStemSource()
    store = FakeStore()

    result = registrar(source, FakeFactory(), store).process(item)

    assert result.status == "absent"
    assert source.exact_stem_calls == [item.reserved_claude_uuid]
    assert store.calls[0][0] == "absent"


def test_reconciliation_can_refuse_launch_authorizing_exact_absence() -> None:
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )
    source = ExactStemSource()
    store = FakeStore()
    factory = FakeFactory()

    result = registrar(source, factory, store).process(item, allow_absence=False)

    assert result.status == "absent"
    assert result.error_code == "native_transcript_not_indexed"
    assert source.exact_stem_calls == [item.reserved_claude_uuid]
    assert factory.spawns == []
    assert store.calls == []


def test_delayed_exact_transcript_is_polled_without_replacement() -> None:
    item = claim()
    source = FakeSource([None, projection_for(item)])
    factory = FakeFactory()
    ticks = iter([0.0, 0.0, 0.1, 0.1, 0.2, 0.2])
    reg = ClaudeNativeRegistrar(
        FakeStore(),
        source,
        marker_secret=SECRET,
        startup_theme="light",
        pty_factory=factory,
        clock=lambda: 100.0,
        monotonic=lambda: next(ticks),
        sleep=lambda _: None,
        process_timeout=2,
        exit_timeout=1,
        discovery_timeout=1,
        retry_delay=5,
    )
    result = reg.process(item)
    assert result.status == "visible"
    assert source.lookups == [item.reserved_claude_uuid, item.reserved_claude_uuid]
    assert len(factory.spawns) == 1


class _TranscriptCreatingLimitPty(FakePty):
    """Persist a strict provider-limit transcript during PTY interaction."""

    def __init__(self, projects_root: Path, item: ClaudeVisibilityClaim) -> None:
        super().__init__()
        self._projects_root = projects_root
        self._item = item

    def read_until_ready(
        self, timeout: float, *, accept_workspace_trust: bool = False
    ) -> str:
        self.write_exact_transcript()
        return super().read_until_ready(timeout, accept_workspace_trust=True)

    def write_exact_transcript(self) -> None:
        value = candidate()
        identity = derive_claude_visibility_identity(value, SECRET)
        prompt = build_claude_registration_prompt(value, identity, SECRET)
        project = claude_project_directory_name(self._item.source_cwd or "")
        directory = self._projects_root / project
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._item.reserved_claude_uuid}.jsonl"
        limited = (
            "You've hit your weekly limit · resets Aug 24, 4am (America/New_York)"
        )
        records = [
            {
                "type": "custom-title",
                "sessionId": self._item.reserved_claude_uuid,
                "customTitle": self._item.native_name,
            },
            {
                "type": "assistant",
                "sessionId": self._item.reserved_claude_uuid,
                "uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "timestamp": "2026-08-22T00:00:00Z",
                "cwd": self._item.source_cwd,
                "gitBranch": self._item.git_branch,
                "isSidechain": False,
                "entrypoint": "cli",
                "message": {"role": "assistant", "content": limited},
            },
            {
                "type": "user",
                "sessionId": self._item.reserved_claude_uuid,
                "uuid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "timestamp": "2026-08-22T00:00:01Z",
                "cwd": self._item.source_cwd,
                "gitBranch": self._item.git_branch,
                "isSidechain": False,
                "entrypoint": "cli",
                "message": {"role": "user", "content": prompt},
            },
        ]
        path.write_bytes(
            b"".join(
                json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"
                for record in records
            )
        )


def test_launch_provider_limit_freshly_discovers_exact_transcript_after_cached_empty_lookup(
    tmp_path: Path,
) -> None:
    item = claim()
    adapter = ClaudeSourceAdapter(tmp_path, marker_secret=SECRET)
    store = FakeStore()
    process = _TranscriptCreatingLimitPty(tmp_path, item)
    factory = FakeFactory(process)

    result = registrar(adapter, factory, store).process(item)

    assert result.status == "visible"
    assert result.error_code is None
    assert len(factory.spawns) == 1
    assert process.terminated is False
    assert process.closed is True
    expected = (
        tmp_path
        / claude_project_directory_name(item.source_cwd or "")
        / f"{item.reserved_claude_uuid}.jsonl"
    )
    assert expected.exists()
    assert [call[0] for call in store.calls] == ["commit"]


class _AmbiguousTranscriptPty(_TranscriptCreatingLimitPty):
    """Persist a valid transcript but end the PTY observation ambiguously."""

    def read_until_ready(
        self, timeout: float, *, accept_workspace_trust: bool = False
    ) -> str:
        self.write_exact_transcript()
        return super().read_until_ready(timeout, accept_workspace_trust=True)

    def read_until(self, timeout: float, *, prompt: str | None = None) -> str:
        raise TimeoutError("registration observation ended ambiguously")


def test_launch_ambiguous_response_still_reconciles_exact_transcript_after_verified_cleanup(
    tmp_path: Path,
) -> None:
    item = claim()
    adapter = ClaudeSourceAdapter(tmp_path, marker_secret=SECRET)
    store = FakeStore()
    process = _AmbiguousTranscriptPty(tmp_path, item)
    factory = FakeFactory(process)

    result = registrar(adapter, factory, store).process(item)

    assert result.status == "visible"
    assert len(factory.spawns) == 1
    assert process.terminated is True
    assert process.closed is True
    assert [call[0] for call in store.calls] == ["commit"]


def test_ambiguous_polling_without_transcript_keeps_original_creation_ambiguity(
    tmp_path: Path,
) -> None:
    item = claim()
    adapter = ClaudeSourceAdapter(tmp_path, marker_secret=SECRET)
    store = FakeStore()
    process = FakePty(prompt_input_error=_PtyResponseTimeout("blocked"))

    result = registrar(adapter, factory=FakeFactory(process), store=store).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert [call[0] for call in store.calls] == ["retry"]


@pytest.mark.parametrize(
    ("factory", "process", "code"),
    [
        (FakeFactory(error=FileNotFoundError()), None, "claude_executable_unavailable"),
        (FakeFactory(error=RuntimeError("pty unavailable")), None, "pty_unavailable"),
        (
            None,
            FakePty(output="Authentication required"),
            "claude_authentication_unavailable",
        ),
        (
            None,
            FakePty(
                output="Failed to authenticate. API Error: 401 Invalid authentication credentials"
            ),
            "claude_authentication_unavailable",
        ),
        (
            None,
            FakePty(
                output="You've hit your limit · resets Jul 20, 4am "
                "(America/New_York)\nAPI Error: 429 rate_limit"
            ),
            "creation_ambiguous",
        ),
        (None, FakePty(exit_code=7), "clean_exit_not_observed"),
        (None, FakePty(read_error=TimeoutError()), "creation_ambiguous"),
    ],
)
def test_fixed_launch_failure_codes_and_cleanup(
    factory: FakeFactory | None, process: FakePty | None, code: str
) -> None:
    item = claim()
    factory = factory or FakeFactory(process)
    result = registrar(FakeSource(), factory).process(item)
    assert result.error_code == code
    if process is not None:
        assert process.closed and process.terminated
    assert result.detail not in {"pty unavailable", "Authentication required"}


# Ceiling for in-process reader tests whose fake stream ENDS (StopIteration ->
# EOF).  EOF is what returns the read, so this is a guard and never the operative
# deadline.  A ceiling below _RESPONSE_SETTLE_SECONDS (0.5) instead makes itself
# the deadline, turning the assertion into a race against the fake's own sleeps.
# Tests that deliberately assert ON the deadline -- e.g.
# test_winpty_slow_drip_after_candidate_stays_bounded_by_global_timeout, which
# checks `elapsed < 1.0` -- keep their own small value and must NOT use this.
#
# 30.0 -> 10.0 on 2026-09-03, DEFENSIVE: 30.0 was exactly pytest-timeout's
# per-test cap (pyproject addopts `--timeout=30`), so any regression that made
# this guard the thing which actually expires would race the plugin -- and a
# plugin kill reports no assertion and no readable cause. 10.0 keeps a 20s
# margin and stays far above _RESPONSE_SETTLE_SECONDS (0.5), the floor the
# paragraph above is about. Matches _OFFLINE_FIXTURE_EXIT_GUARD_SECONDS here and
# NEW_DEADLOCK_GUARD in test_refresh_wallclock_falsifier, both 10.0 for the same
# reason.
#
# HONEST LIMIT OF THE EVIDENCE: no reachable case was found where 30.0 actually
# produced a plugin kill. Two mutations tried and failed -- blocking the fake
# stream so EOF never arrives leaves `read_until` returning normally on its
# quiet period, so this guard is NOT the operative deadline even at the two
# call sites that pass it straight to `read_until()`. It is a hang guard in
# every use. Reaching the race needs the settle logic broken AND a blocked read.
# So this is margin against a future defect, not a fix for a demonstrated one.
_READER_EOF_GUARD_SECONDS = 10.0

# Exit guard for the OFFLINE fixture processes, which exit immediately -- so this
# is a hang guard, never a deadline.  Deliberately 10.0, NOT the 120s real-ConPTY
# guard and NOT the 30s reader guard: pytest-timeout's per-test cap is 30s, and a
# guard at or above it means a regression gets KILLED by the plugin instead of
# failing here with a readable TimeoutError.  Same reasoning as
# test_refresh_wallclock_falsifier's NEW_DEADLOCK_GUARD.
_OFFLINE_FIXTURE_EXIT_GUARD_SECONDS = 10.0


def test_winpty_fallback_reader_observes_cancellation_while_read_is_blocked() -> None:
    stop = threading.Event()
    read_started = threading.Event()
    release_read = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    class Process:
        def read(self, _size: int = 1024) -> str:
            read_started.set()
            release_read.wait()
            raise EOFError

    wrapped = _WinPtyProcess(Process())
    wrapped.set_cancel_event(stop)

    def read() -> None:
        try:
            wrapped.read_until(30.0)
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    reader = threading.Thread(target=read)
    reader.start()
    try:
        assert read_started.wait(_READER_EOF_GUARD_SECONDS)
        stop.set()
        assert finished.wait(_READER_EOF_GUARD_SECONDS)
    finally:
        release_read.set()
        reader.join(_READER_EOF_GUARD_SECONDS)

    assert reader.is_alive() is False
    assert len(errors) == 1
    assert str(errors[0]) == "visibility registrar cancelled"


def test_winpty_timed_read_observes_bound_cancellation() -> None:
    stop = threading.Event()

    class Process:
        def read_with_timeout(self, _size: int, _timeout: float) -> None:
            stop.set()
            return None

    wrapped = _WinPtyProcess(Process())
    wrapped.set_cancel_event(stop)

    with pytest.raises(RuntimeError, match="^visibility registrar cancelled$"):
        wrapped.read_until(30.0)


def test_winpty_wait_observes_bound_cancellation() -> None:
    stop = threading.Event()

    class Process:
        exitstatus = None

        def isalive(self) -> bool:
            stop.set()
            return True

    wrapped = _WinPtyProcess(Process())
    wrapped.set_cancel_event(stop)

    with pytest.raises(RuntimeError, match="^visibility registrar cancelled$"):
        wrapped.wait(30.0)


def test_winpty_wrapper_uses_real_read_signature_without_unbounded_keyword() -> None:
    class Process:
        def __init__(self):
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            if self.calls > 1:
                raise EOFError
            return "REGISTERED\r\n"

    process = Process()
    assert _WinPtyProcess(process).read_until(0.2).strip() == "REGISTERED"
    assert process.calls == 2


def test_winpty_reader_does_not_stop_on_registered_text_inside_prompt_echo() -> None:
    value = candidate()
    prompt = build_claude_registration_prompt(
        value, derive_claude_visibility_identity(value, SECRET), SECRET
    )

    class Process:
        def __init__(self):
            self.chunks = iter([prompt + "\r\n", "REGISTERED\r\n"])
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            if self.calls == 2:
                time.sleep(0.01)
            return next(self.chunks)

    process = Process()
    output = _WinPtyProcess(process).read_until(
        _READER_EOF_GUARD_SECONDS, prompt=prompt
    )
    assert output.strip() == "REGISTERED"
    assert process.calls == 3


def test_winpty_reader_ignores_startup_chrome_and_wrapped_prompt_fragments() -> None:
    value = candidate()
    prompt = build_claude_registration_prompt(
        value, derive_claude_visibility_identity(value, SECRET), SECRET
    )

    class Process:
        def __init__(self):
            self.chunks = iter([
                "Claude Code ready\r\nstatus: connected\r\n",
                "Signed marker: wrapped-fragment\r\nmetadata continuation\r\n",
                "\x1b[32mClaude>\x1b[0m REGISTERED\r\n",
            ])
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            return next(self.chunks)

    process = Process()
    output = _WinPtyProcess(process).read_until(0.2, prompt=prompt)
    assert output.strip() == "REGISTERED"
    assert process.calls == 4


def test_winpty_reader_never_treats_authentication_words_in_echo_as_failure() -> None:
    class Process:
        def __init__(self):
            self.chunks = iter([
                "Bounded metadata: authentication required\r\n",
                "REGISTERED\r\n",
            ])
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            return next(self.chunks)

    process = Process()
    output = _WinPtyProcess(process).read_until(
        0.2, prompt="Bounded metadata: authentication required"
    )
    assert output.strip() == "REGISTERED"
    assert process.calls == 3


def test_winpty_timed_reader_returns_live_provider_limit_without_global_timeout() -> None:
    limited = "You've hit your session limit · resets 6:50pm (America/New_York)"

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([limited])
            self.calls = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.calls += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    process = Process()
    started = time.monotonic()
    output = _WinPtyProcess(process).read_until(
        1.0, prompt="registration prompt"
    )

    assert output.strip() == limited
    assert time.monotonic() - started < 0.5
    assert process.calls == 1


def test_winpty_response_timeout_reports_bounded_main_repl_phase() -> None:
    prompt = "registration prompt"

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    prompt
                    + "\r\n\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"
                ]
            )

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    with pytest.raises(_PtyResponseTimeout) as failure:
        _WinPtyProcess(Process()).read_until(0.05, prompt=prompt)

    assert failure.value.reason == "main_repl_after_prompt"


def test_winpty_response_timeout_reports_visible_pasted_input() -> None:
    output = (
        "[Pasted text #1 +12 lines]\r\n"
        "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([output])

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    with pytest.raises(_PtyResponseTimeout) as failure:
        _WinPtyProcess(Process()).read_until(0.05, prompt="registration prompt")

    assert failure.value.reason == "pasted_input_visible"


def test_winpty_reader_drains_extra_output_after_registered_before_acceptance() -> None:
    class Process:
        def __init__(self):
            self.chunks = iter(["REGISTERED\r\n", "extra\r\n"])
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            if self.calls == 2:
                time.sleep(0.08)
            return next(self.chunks)

    process = Process()
    output = _WinPtyProcess(process).read_until(_READER_EOF_GUARD_SECONDS)
    assert output.strip().splitlines() == ["REGISTERED", "extra"]
    assert process.calls >= 2


def test_winpty_quiet_period_resets_for_each_partial_post_response_chunk() -> None:
    class Process:
        def __init__(self):
            self.chunks = iter(["REGISTERED\r\n", "ex", "tra\r\n"])
            self.calls = 0

        def read(self, size: int = 1024) -> str:
            self.calls += 1
            if self.calls in {2, 3}:
                time.sleep(0.08)
            return next(self.chunks)

    process = Process()
    output = _WinPtyProcess(process).read_until(_READER_EOF_GUARD_SECONDS)
    assert output.strip().splitlines() == ["REGISTERED", "extra"]
    assert process.calls == 4


def test_winpty_retains_substantive_pre_response_output_for_rejection() -> None:
    class Process:
        def __init__(self):
            self.chunks = iter(["UNRELATED WORK\r\n", "REGISTERED\r\n"])

        def read(self, size: int = 1024) -> str:
            return next(self.chunks)

    output = _WinPtyProcess(Process()).read_until(0.3, prompt="registration prompt")
    assert "UNRELATED WORK" in output


def test_winpty_slow_drip_after_candidate_stays_bounded_by_global_timeout() -> None:
    release = threading.Event()

    class Process:
        def __init__(self):
            self.chunks = iter(["REGISTERED\r\n", "e", "x", "t"])

        def read(self, size: int = 1024) -> str:
            try:
                chunk = next(self.chunks)
            except StopIteration:
                release.wait(2)
                raise EOFError
            time.sleep(0.06)
            return chunk

    started = time.monotonic()
    output = _WinPtyProcess(Process()).read_until(0.22)
    elapsed = time.monotonic() - started
    release.set()
    assert output.startswith("REGISTERED")
    # The regression this guards against waits the full two-second release
    # timeout. Leave enough scheduling margin for a loaded Windows test host
    # while still proving the read is bounded well below that blocking wait.
    assert elapsed < 1.0


def test_winpty_reader_accepts_registered_split_across_chunks() -> None:
    class Process:
        def __init__(self):
            self.chunks = iter(["REGIS", "TERED\r\n"])

        def read(self, size: int = 1024) -> str:
            return next(self.chunks)

    assert _WinPtyProcess(Process()).read_until(0.2).strip() == "REGISTERED"


def _close_raw_registrar_process(process: Any) -> None:
    process.stop_transport()
    process.fileobj.close()
    process._server.close()
    process.release_native_pty()


def test_raw_winpty_read_exception_after_exit_preserves_accumulated_output() -> None:
    class Pty:
        pid = 123

        def __init__(self) -> None:
            self.reads = iter(["Authentication required\r\n", OSError("closed")])

        def read(self, size: int, *, blocking: bool) -> str:
            del size, blocking
            value = next(self.reads)
            if isinstance(value, Exception):
                raise value
            return value

        def isalive(self) -> bool:
            return False

    process = _registrar_pywinpty_process_type()(Pty())
    try:
        output = _WinPtyProcess(process).read_until(0.2)
        assert output.strip() == "Authentication required"
    finally:
        _close_raw_registrar_process(process)


def test_raw_winpty_read_exception_while_alive_remains_an_error() -> None:
    class Pty:
        pid = 123

        def read(self, size: int, *, blocking: bool) -> str:
            del size, blocking
            raise OSError("real read failure")

        def isalive(self) -> bool:
            return True

    process = _registrar_pywinpty_process_type()(Pty())
    try:
        with pytest.raises(OSError, match="real read failure"):
            process.read_with_timeout(4096, 0.01)
    finally:
        _close_raw_registrar_process(process)


def test_raw_winpty_empty_read_after_exit_is_eof() -> None:
    class Pty:
        pid = 123

        def read(self, size: int, *, blocking: bool) -> str:
            del size, blocking
            return ""

        def isalive(self) -> bool:
            return False

    process = _registrar_pywinpty_process_type()(Pty())
    try:
        with pytest.raises(EOFError):
            process.read_with_timeout(4096, 0.01)
    finally:
        _close_raw_registrar_process(process)


def test_winpty_readiness_ignores_conpty_prologue_and_requires_main_repl() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H",
                    "\x1b[?20",
                    "04h",
                    "\x1b[2m⏵⏵ don't ask on\x1b[0m",
                ]
            )

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    output = _WinPtyProcess(Process()).read_until_ready(1.0)

    assert output.startswith("\x1b[?9001h\x1b[?1004h\x1b[?25l")
    assert "\x1b[?2004h" in output
    assert "⏵⏵ don't ask on" in output


def test_winpty_readiness_accepts_claude_216_compact_main_footer() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H",
                "\x1b[?2004h",
                "\x1b[2m\u23f5\u23f5don't ask on (shift+tab to cycle)\x1b[0m",
            ])

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    output = _WinPtyProcess(Process()).read_until_ready(1.0)

    assert "\x1b[?2004h" in output
    assert "\u23f5\u23f5don't ask on" in output


def test_winpty_readiness_accepts_claude_219_permission_indicator() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H",
                "\x1b[?2004h",
                "\x1b[2m\u23f5\u23f5 Don't Ask (shift+tab to cycle)\x1b[0m",
            ])

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    output = _WinPtyProcess(Process()).read_until_ready(1.0)

    assert "\x1b[?2004h" in output
    assert "\u23f5\u23f5 Don't Ask" in output


def test_winpty_readiness_accepts_claude_219_compact_permission_indicator() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H",
                "\x1b[?2004h",
                "\x1b[2m\u23f5\u23f5 DontAsk\x1b[0m",
            ])

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    output = _WinPtyProcess(Process()).read_until_ready(1.0)

    assert "\x1b[?2004h" in output
    assert "\u23f5\u23f5 DontAsk" in output


def test_winpty_readiness_accepts_symbol_only_permission_indicator() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H",
                "\x1b[?2004h",
                "\x1b[2m\u23f5\u23f5\x1b[0m",
            ])

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

    output = _WinPtyProcess(Process()).read_until_ready(1.0)

    assert "\x1b[?2004h" in output
    assert "\u23f5\u23f5" in output


def test_winpty_readiness_waits_for_footer_then_product_modal() -> None:
    modal = (
        "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
        "1. Yes, try it\r\n2. Not now\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?2004h\x1b[2m\u23f5\u23f5don't ask on\x1b[0m",
                modal,
            ])
            self.reads = 0

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

    process = Process()
    with pytest.raises(RuntimeError, match="closed before readiness"):
        _WinPtyProcess(process).read_until_ready(1.0)

    assert process.reads == 3


def test_winpty_readiness_rejects_footer_and_product_modal_in_same_chunk() -> None:
    modal = (
        "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
        "1. Yes, try it\r\n2. Not now\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([
                "\x1b[?2004h\x1b[2m\u23f5\u23f5don't ask on\x1b[0m" + modal
            ])
            self.reads = 0

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

    process = Process()
    with pytest.raises(RuntimeError, match="closed before readiness"):
        _WinPtyProcess(process).read_until_ready(1.0)

    assert process.reads == 2


def test_main_repl_readiness_rejects_product_modal_before_footer() -> None:
    output = (
        "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
        "1. Yes, try it\r\n2. Not now\r\n"
        "\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"
    )

    assert not _claude_main_repl_ready(output)


def test_main_repl_readiness_rejects_repeated_modal_footer_redraws() -> None:
    modal = (
        "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
        "1. Yes, try it\r\n2. Not now\r\n"
    )
    footer = "\x1b[2m\u23f5\u23f5don't ask on\x1b[0m"

    assert not _claude_main_repl_ready(modal + footer + modal + footer)


def test_main_repl_readiness_rejects_auto_default_nudge() -> None:
    output = (
        "\x1b[?2004h\x1b[2JMake auto mode your default permission mode?\r\n"
        "Yes, set auto mode as my default permission mode\r\n"
        "No, keep don't ask\r\n"
        "\x1b[2m\u23f5\u23f5\x1b[0m"
    )

    assert not _claude_main_repl_ready(output)


def test_winpty_readiness_crosses_exact_workspace_trust_gate_once() -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "\x1b[?2004h",
                    trust,
                    trust,
                    "\x1b[?2004h",
                    "\x1b[2m⏵⏵ don't ask on\x1b[0m",
                ]
            )
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    output = _WinPtyProcess(process).read_until_ready(
        1.0, accept_workspace_trust=True
    )

    assert "\x1b[?2004h" in output
    assert "⏵⏵ don't ask on" in output
    assert process.writes == ["\r"]
    assert process.reads == 6


def test_winpty_readiness_crosses_restricted_workspace_trust_gate_once() -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Security guide\r\n"
        "Yes, I trust this folder\r\n"
        "No, continue without these permissions\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "\x1b[?2004h",
                    trust,
                    "\x1b[?2004h",
                    "\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m",
                ]
            )
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    output = _WinPtyProcess(process).read_until_ready(
        1.0, accept_workspace_trust=True
    )

    assert "\u23f5\u23f5 don't ask on" in output
    assert process.writes == ["\r"]
    assert process.reads == 5


def test_winpty_readiness_crosses_cursor_positioned_workspace_trust_gate() -> None:
    trust = (
        "\x1b[2JAccessing\x1b[1Cworkspace:\x1b[2C"
        "Quick\x1b[1Csafety\x1b[1Ccheck\x1b[3C"
        "Security\x1b[1Cguide\x1b[2C"
        "Yes,\x1b[1CI\x1b[1Ctrust\x1b[1Cthis\x1b[1Cfolder\x1b[2C"
        "No,\x1b[1Cexit"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    "\x1b[?2004h",
                    trust,
                    "\x1b[2m\u23f5\u23f5\x1b[0m",
                ]
            )
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    output = _WinPtyProcess(process).read_until_ready(
        1.0, accept_workspace_trust=True
    )

    assert "\u23f5\u23f5" in output
    assert process.writes == ["\r"]
    assert process.reads == 4


@pytest.mark.parametrize(
    "redraw_chunks, expected_reads",
    [
        (
            [
                "\x1b[2JAccessing workspace:\r\n"
                "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n",
                "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m",
            ],
            4,
        ),
        (
            [
                "\x1b[2JAccessing workspace:\r\n"
                "\x1b[1mYes, I trust this folder\x1b[0m\r\n"
                "No, exit\r\nSecurity guide\x1b[0m\r\n"
                "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m",
            ],
            3,
        ),
    ],
    ids=["redraw-then-footer", "redraw-and-footer-same-chunk"],
)
def test_winpty_readiness_slices_past_latest_trust_redraw_without_resubmitting(
    redraw_chunks: list[str], expected_reads: int
) -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([trust, *redraw_chunks])
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    output = _WinPtyProcess(process).read_until_ready(
        1.0, accept_workspace_trust=True
    )

    assert "\u23f5\u23f5 don't ask on" in output
    assert process.writes == ["\r"]
    assert process.reads == expected_reads


def test_winpty_readiness_keeps_post_trust_product_modal_sticky_across_redraw() -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )
    modal = (
        "\x1b[2JFable 5 is now a standard part of your Max plan\r\n"
        "1. Yes, try it\r\n2. Not now\r\n"
    )
    footer = "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([trust, modal, trust + footer, "\x1b[H"])
            self.writes: list[str] = []

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    with pytest.raises(_PtyReadinessTimeout) as failure:
        _WinPtyProcess(process).read_until_ready(
            1.0, accept_workspace_trust=True
        )

    assert failure.value.reason == "known_input_modal"
    assert process.writes == ["\r"]


def test_winpty_readiness_partial_post_trust_prefix_invalidates_old_footer() -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )
    footer = "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"
    partial_redraw = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([trust, footer, partial_redraw])
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    with pytest.raises(TimeoutError):
        _WinPtyProcess(process).read_until_ready(
            1.0, accept_workspace_trust=True
        )

    assert process.writes == ["\r"]
    assert process.reads == 4


def test_winpty_readiness_partial_trust_redraw_completes_before_new_footer() -> None:
    trust = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )
    footer = "\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"
    partial_redraw = (
        "\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\n"
    )
    redraw_tail = "No, exit\r\nSecurity guide\r\n" + footer

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([trust, footer, partial_redraw, redraw_tail])
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, timeout: float) -> str | None:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration:
                time.sleep(timeout)
                return None

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    output = _WinPtyProcess(process).read_until_ready(
        1.0, accept_workspace_trust=True
    )

    assert redraw_tail in output
    assert process.writes == ["\r"]
    assert process.reads == 5


def test_winpty_readiness_eof_before_settle_fails_closed() -> None:
    class Process:
        def __init__(self) -> None:
            self.chunks = iter(
                ["\x1b[?2004h\x1b[2m\u23f5\u23f5 don't ask on\x1b[0m"]
            )

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

    with pytest.raises(RuntimeError, match="closed before readiness"):
        _WinPtyProcess(Process()).read_until_ready(1.0)


def test_winpty_readiness_classifies_provider_limit_eof_before_main_repl() -> None:
    provider_limit = "You've hit your limit · resets 5am"

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([provider_limit])

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

    assert _WinPtyProcess(Process()).read_until_ready(1.0) == provider_limit


def test_winpty_readiness_never_returns_on_trust_dialog_marker_alone() -> None:
    trust = (
        "\x1b[?2004h\x1b[2JAccessing workspace:\r\n"
        "Yes, I trust this folder\r\nNo, exit\r\nSecurity guide\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([trust])
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    with pytest.raises(RuntimeError, match="closed before readiness"):
        _WinPtyProcess(process).read_until_ready(
            1.0, accept_workspace_trust=True
        )

    assert process.writes == ["\r"]
    assert process.reads == 2


def test_winpty_readiness_never_accepts_theme_or_onboarding_screen() -> None:
    theme = (
        "\x1b[?2004h\x1b[2JWelcome to Claude Code v2.1.110\r\n"
        "Let's get started.\r\n> 1. Dark mode\r\n2. Light mode\r\n"
        "Syntax theme: Monokai Extended\r\n"
    )

    class Process:
        def __init__(self) -> None:
            self.chunks = iter([theme])
            self.writes: list[str] = []
            self.reads = 0

        def read_with_timeout(self, _size: int, _timeout: float) -> str:
            self.reads += 1
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise EOFError from exc

        def write(self, data: str) -> None:
            self.writes.append(data)

    process = Process()
    with pytest.raises(RuntimeError, match="closed before readiness"):
        _WinPtyProcess(process).read_until_ready(
            1.0, accept_workspace_trust=True
        )

    assert process.writes == []
    assert process.reads == 2


def test_winpty_reader_timeout_is_bounded_when_underlying_read_blocks() -> None:
    release = threading.Event()

    class Process:
        def read(self, size: int = 1024) -> str:
            release.wait(2)
            raise EOFError

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        _WinPtyProcess(Process()).read_until(0.05)
    assert time.monotonic() - started < 0.5
    release.set()


def test_none_exit_code_is_never_accepted_as_clean() -> None:
    item = claim()
    process = FakePty(exit_code=None)  # type: ignore[arg-type]
    result = registrar(
        FakeSource([None, projection_for(item)]), FakeFactory(process)
    ).process(item)
    assert result.status == "retry"
    assert result.error_code == "clean_exit_not_observed"


def test_cleanup_failure_after_spawn_overrides_success_as_creation_ambiguous() -> None:
    item = claim()
    process = FakePty()
    process.cleanup_result = PtyCleanupResult(False, False, False, 0)
    store = FakeStore()
    result = registrar(
        FakeSource([None, projection_for(item)]), FakeFactory(process), store
    ).process(item)
    assert result.status == "retry" and result.error_code == "creation_ambiguous"
    assert not any(call[0] == "commit" for call in store.calls)


def test_winpty_close_is_idempotent_and_reports_all_cleanup_postconditions() -> None:
    released = threading.Event()

    class Resource:
        def __init__(self, descriptor: int):
            self.descriptor = descriptor

        def close(self) -> None:
            self.descriptor = -1
            released.set()

        def fileno(self) -> int:
            return self.descriptor

    class NativePty:
        fd = 42

        def isalive(self) -> bool:
            return False

        def get_exitstatus(self) -> int:
            return 0

    class Process:
        def __init__(self):
            self.fileobj = Resource(10)
            self._server = Resource(11)
            self.pty = NativePty()
            self.fd = 10
            self.closed = False
            self.exitstatus = 0
            self._thread = threading.Thread(target=lambda: None)
            self._thread.start()

        def read(self, size: int = 1024) -> str:
            # NOT a guard: `released` is never set, so this wait is EXPECTED to
            # expire.  It simulates a reader still blocked when close() runs, and
            # its duration is the point -- widening it to the file's 30s guard
            # constant just parks a thread for 30s (measured 2026-09-03: it cost
            # the suite ~14 minutes).  Leave it small.
            released.wait(1)
            raise EOFError

        def isalive(self) -> bool:
            return False

    wrapped = _WinPtyProcess(Process())
    with pytest.raises(TimeoutError):
        wrapped.read_until(0.02)
    first = wrapped.close(0.5)
    second = wrapped.close(0.5)
    assert first == second == PtyCleanupResult(True, True, True, 0)


def test_winpty_unknown_private_resource_layout_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="unsupported pywinpty resource layout"):
        _WinPtyProcess(object(), require_supported_layout=True)


def test_factory_sets_cli_entrypoint_and_update_lock_only_in_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class ProcessType:
        @staticmethod
        def spawn(
            argv: list[str],
            *,
            cwd: str,
            env: dict[str, str],
            dimensions: tuple[int, int],
        ) -> object:
            observed.update(
                argv=argv,
                cwd=cwd,
                env=env,
                dimensions=dimensions,
            )
            return object()

    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.delenv("DISABLE_UPDATES", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", raising=False)
    monkeypatch.delenv("DISABLE_GROWTHBOOK", raising=False)
    monkeypatch.setattr(
        "session_bridge.claude_registrar._registrar_pywinpty_process_type",
        lambda: ProcessType,
    )

    WindowsConPtyFactory()._spawn_process(["claude"], cwd="C:/exact")

    assert observed["env"]["CLAUDE_CODE_ENTRYPOINT"] == "cli"
    assert observed["env"]["DISABLE_UPDATES"] == "1"
    assert observed["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert observed["env"]["DISABLE_GROWTHBOOK"] == "1"
    assert "CLAUDE_CODE_ENTRYPOINT" not in os.environ
    assert "DISABLE_UPDATES" not in os.environ
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in os.environ
    assert "DISABLE_GROWTHBOOK" not in os.environ


@pytest.mark.parametrize(
    ("environment_name", "environment_value"),
    [
        ("CLAUDE_CONFIG_DIR", "C:/reintroduced-config-root"),
        ("CLAUDE_CODE_POWERUP_ONBOARDING", "banner"),
        ("CLAUDE_CODE_POWERUP_ONBOARDING", "step"),
        ("CLAUDE_CODE_TEAM_ONBOARDING", "banner"),
        ("CLAUDE_CODE_TEAM_ONBOARDING", "step"),
    ],
)
def test_factory_rejects_unsafe_environment_reintroduced_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    environment_value: str,
) -> None:
    spawns: list[list[str]] = []

    class ProcessType:
        @staticmethod
        def spawn(argv: list[str], **_kwargs: Any) -> object:
            spawns.append(argv)
            return object()

    factory = WindowsConPtyFactory()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_POWERUP_ONBOARDING", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_TEAM_ONBOARDING", raising=False)
    monkeypatch.setattr(
        "session_bridge.claude_registrar._registrar_pywinpty_process_type",
        lambda: ProcessType,
    )
    monkeypatch.setenv(environment_name, environment_value)

    with pytest.raises(RuntimeError, match="unsafe Claude launch environment"):
        factory._spawn_process(["claude"], cwd="C:/exact")

    assert spawns == []


def test_factory_validation_failure_reclaims_spawned_child_and_descriptors() -> None:
    class Resource:
        def __init__(self, descriptor: int):
            self.descriptor = descriptor

        def close(self) -> None:
            self.descriptor = -1

        def fileno(self) -> int:
            return self.descriptor

    class Process:
        def __init__(self):
            self.fileobj = Resource(10)
            self._server = Resource(11)
            self.fd = 10
            self.dead = False
            self._thread = threading.Thread(target=lambda: None)
            self._thread.start()

        def isalive(self) -> bool:
            return not self.dead

        def terminate(self, force: bool = False) -> bool:
            assert force
            self.dead = True
            return True

    process = Process()

    class Factory(WindowsConPtyFactory):
        def _spawn_process(self, argv: list[str], *, cwd: str) -> object:
            return process

        def _adapt_process(self, spawned: object) -> _WinPtyProcess:
            assert spawned is process
            raise RuntimeError("unsupported pywinpty resource layout")

    with pytest.raises(RuntimeError, match="pty unavailable"):
        Factory().spawn(["ignored"], cwd="C:/ignored")
    assert process.dead
    assert process.fileobj.fileno() == process._server.fileno() == -1
    assert process.fd == -1


def test_factory_surfaces_unconfirmed_post_spawn_process_death() -> None:
    class Resource:
        def close(self) -> None:
            pass

        def fileno(self) -> int:
            return -1

    class Process:
        fileobj = Resource()
        _server = Resource()
        fd = -1
        pid = None
        _thread = threading.Thread(target=lambda: None)

        def isalive(self) -> bool:
            return True

        def terminate(self, force: bool = False) -> bool:
            return False

    Process._thread.start()

    class Factory(WindowsConPtyFactory):
        def _spawn_process(self, argv: list[str], *, cwd: str) -> object:
            return Process()

        def _adapt_process(self, spawned: object) -> _WinPtyProcess:
            raise RuntimeError("unsupported pywinpty resource layout")

    with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
        Factory().spawn(["ignored"], cwd="C:/ignored")


def test_paid_launch_exact_reconciles_existing_uuid_before_any_spawn() -> None:
    item = claim()
    store = FakeStore()
    factory = FakeFactory()
    result = registrar(FakeSource([projection_for(item)]), factory, store).process(item)
    assert result.status == "visible"
    assert factory.spawns == []
    assert store.calls[0][0] == "commit"


def test_restart_reconciliation_commits_exact_uuid_without_second_spawn_or_usage(
    tmp_path: Path,
) -> None:
    now = [100.0]
    database = SessionDB(tmp_path / "state.db")
    first_store = SessionBridgeStore(
        database, clock=lambda: now[0], local_timezone=timezone.utc
    )
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    first_store.enqueue_claude_visibility_job(value, identity, SECRET)
    first_store.upsert_projection(
        SessionProjection(
            provider=Provider.CODEX,
            native_id=value.source_session_id.removeprefix("codex:"),
            title=value.native_name,
            cwd=value.source_cwd,
            started_at=10.0,
            last_active=11.0,
            messages=(ProjectedMessage("source-u1", 0, "user", "request", 10.0),),
            native_path="C:/codex/source-1.jsonl",
            native_cursor="source-cursor",
            native_hash="source-hash",
            origin_kind=OriginKind.NATIVE,
        )
    )
    first = first_store.claim_claude_visibility_job(now[0], 60, 25, "0.50", "0.02")
    assert first.lease_kind == "launch"
    first_factory = FakeFactory(FakePty(read_error=TimeoutError()))
    ambiguous = registrar(FakeSource(), first_factory, first_store).process(first)
    assert ambiguous.error_code == "creation_ambiguous"

    now[0] = 105.0
    restarted_store = SessionBridgeStore(
        database, clock=lambda: now[0], local_timezone=timezone.utc
    )
    reconciliation = restarted_store.claim_claude_visibility_job(
        now[0], 60, 25, "0.50", "0.02"
    )
    assert reconciliation.lease_kind == "reconciliation"
    restarted_factory = FakeFactory()
    visible = registrar(
        FakeSource([projection_for(reconciliation)]), restarted_factory, restarted_store
    ).process(reconciliation)

    assert visible.status == "visible"
    assert len(first_factory.spawns) == 1 and restarted_factory.spawns == []
    assert restarted_store.claude_visibility_status(now[0])["usage"]["attempts"] == 1
    gate = restarted_store.claim_claude_visibility_job(now[0], 60, 25, "0.50", "0.02")
    assert gate.status == "no_due_job" and gate.lease_kind is None
    database.close()


def test_zero_result_ambiguity_records_absence_then_authorizes_same_uuid_only(
    tmp_path: Path,
) -> None:
    now = [100.0]
    database = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(
        database, clock=lambda: now[0], local_timezone=timezone.utc
    )
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    store.enqueue_claude_visibility_job(value, identity, SECRET)
    first = store.claim_claude_visibility_job(now[0], 60, 25, "0.50", "0.02")
    first_factory = FakeFactory(FakePty(read_error=TimeoutError()))
    registrar(FakeSource(), first_factory, store).process(first)

    now[0] = 105.0
    reconciliation = store.claim_claude_visibility_job(now[0], 60, 25, "0.50", "0.02")
    reconciliation_factory = FakeFactory()
    absent = registrar(FakeSource([None]), reconciliation_factory, store).process(
        reconciliation
    )
    assert absent.status == "absent" and reconciliation_factory.spawns == []
    assert store.claude_visibility_status(now[0])["usage"]["attempts"] == 1

    second = store.claim_claude_visibility_job(now[0], 60, 25, "0.50", "0.02")
    assert second.lease_kind == "launch"
    assert (
        second.reserved_claude_uuid
        == first.reserved_claude_uuid
        == identity.claude_uuid
    )
    assert second.attempt_ordinal == 2
    assert store.claude_visibility_status(now[0])["usage"]["attempts"] == 2
    assert len(first_factory.spawns) == 1
    database.close()


def test_nonlease_store_gate_has_no_lease_kind(tmp_path: Path) -> None:
    database = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(
        database, clock=lambda: 100.0, local_timezone=timezone.utc
    )
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    store.enqueue_claude_visibility_job(value, identity, SECRET)
    gated = store.claim_claude_visibility_job(100.0, 60, 25, "0.01", "0.02")
    assert gated.status == "cost_limit" and gated.lease_kind is None
    database.close()


def test_offline_interactive_fixture_records_frames_exit_and_delayed_index(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    env = {
        **os.environ,
        "FAKE_CLAUDE_RECORD": str(record),
        "FAKE_CLAUDE_SCENARIO": "delayed_transcript_indexing",
        "FAKE_CLAUDE_INDEX_DELAY": "0.01",
    }
    # A host entrypoint (e.g. a desktop-launched runner) would be recorded in the
    # fixture's spawn event and break the exact-equality assertion below.
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    process = subprocess.Popen(
        [sys.executable, str(fixture), "--session-id", "offline-uuid"],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(b"\x1b[200~offline prompt\x1b[201~\r")
    process.stdin.flush()
    assert b"REGISTERED" in process.stdout.readline()
    process.stdin.write(b"/exit\n")
    process.stdin.flush()
    assert process.wait(timeout=_OFFLINE_FIXTURE_EXIT_GUARD_SECONDS) == 0

    events = json.loads(record.read_text(encoding="utf-8"))
    assert events[0] == {
        "argv": ["--session-id", "offline-uuid"],
        "cwd": str(tmp_path),
        "event": "spawn",
    }
    assert [event["event"] for event in events] == [
        "spawn",
        "stdin",
        "native_created",
        "index_ready",
        "stdin",
        "exit",
    ]


def test_offline_fixture_reads_complete_multiline_bracketed_paste_frame(
    tmp_path: Path,
) -> None:
    record = tmp_path / "multiline-record.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    process = subprocess.Popen(
        [sys.executable, str(fixture), "--session-id", "offline-multiline"],
        cwd=tmp_path,
        env={
            **os.environ,
            "FAKE_CLAUDE_RECORD": str(record),
            "FAKE_CLAUDE_SCENARIO": "registered",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    frame = b"\x1b[200~first line\r\nsecond line\nthird line\x1b[201~\r"
    process.stdin.write(frame)
    process.stdin.flush()
    assert b"REGISTERED" in process.stdout.readline()
    process.stdin.write(b"/exit\r\n")
    process.stdin.flush()
    assert process.wait(timeout=_OFFLINE_FIXTURE_EXIT_GUARD_SECONDS) == 0
    events = json.loads(record.read_text(encoding="utf-8"))
    assert events[1] == {
        "event": "stdin",
        "frame": frame.decode("utf-8"),
    }
    assert events[3] == {"event": "stdin", "frame": "/exit\r\n"}


def _fixture_read_frame(data: bytes) -> str:
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    namespace = runpy.run_path(str(fixture))
    return namespace["_read_frame"](io.BytesIO(data))


def test_fixture_accepts_close_marker_at_exact_frame_boundary() -> None:
    opening = b"\x1b[200~"
    closing = b"\x1b[201~"
    content = b"x" * (65_536 - len(opening) - len(closing))
    frame = opening + content + closing
    assert _fixture_read_frame(frame + b"\r") == (frame + b"\r").decode()


def test_fixture_returns_bounded_partial_frame_when_close_marker_is_missing_at_eof() -> (
    None
):
    frame = b"\x1b[200~line one\r\nline two"
    assert _fixture_read_frame(frame) == frame.decode()


@pytest.mark.parametrize(
    ("terminator", "consumed"),
    [(b"\r", b"\r"), (b"\n", b"\n"), (b"\r\n", b"\r")],
)
def test_fixture_consumes_one_terminal_normalized_trailing_terminator(
    terminator: bytes, consumed: bytes
) -> None:
    frame = b"\x1b[200~line one\nline two\x1b[201~"
    assert _fixture_read_frame(frame + terminator) == (frame + consumed).decode()


@pytest.mark.parametrize(
    ("scenario", "expected_code", "expected_output"),
    [
        ("authentication_failure", 1, b"Authentication required"),
        ("malformed_response", 0, b"NOT REGISTERED"),
        ("nonzero", 9, b"REGISTERED"),
    ],
)
def test_offline_fixture_named_terminating_scenarios_record_exit(
    tmp_path: Path, scenario: str, expected_code: int, expected_output: bytes
) -> None:
    record = tmp_path / f"{scenario}.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    process = subprocess.Popen(
        [sys.executable, str(fixture), "--session-id", "offline-uuid"],
        cwd=tmp_path,
        env={
            **os.environ,
            "FAKE_CLAUDE_RECORD": str(record),
            "FAKE_CLAUDE_SCENARIO": scenario,
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    if scenario != "authentication_failure":
        process.stdin.write(b"\x1b[200~offline prompt\x1b[201~\r")
        process.stdin.flush()
    output = process.stdout.readline()
    assert expected_output in output
    if scenario != "authentication_failure":
        process.stdin.write(b"/exit\n")
        process.stdin.flush()
    assert process.wait(timeout=_OFFLINE_FIXTURE_EXIT_GUARD_SECONDS) == expected_code
    events = json.loads(record.read_text(encoding="utf-8"))
    assert events[-1] == {
        "event": "exit",
        "scenario": scenario,
        "sequence": expected_code,
    }


# Deadlock guard for the real-ConPTY tests, which spawn a genuine python.exe
# behind a real pseudoconsole.  Nothing asserts on how much of it is consumed, so
# it is sized for the worst host rather than for expected latency: the previous
# 10s readiness budget expired on a loaded box and surfaced as
# `_PtyReadinessTimeout: terminal_input_not_enabled`.  Reads still return as soon
# as the reader settles, so a large ceiling costs nothing on the happy path.
_REAL_CONPTY_GUARD_SECONDS = 120.0


def _wait_for_fixture_event(record: Path, event: str, timeout: float) -> None:
    """Block until the fake Claude fixture has recorded ``event``.

    The record file is rewritten whole on each append, so a concurrent read can
    catch it mid-write; treat a partial parse as "not yet".
    """

    deadline = time.monotonic() + timeout
    while True:
        try:
            events = json.loads(record.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            events = []
        if any(entry.get("event") == event for entry in events):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"fixture never recorded {event!r} within {timeout}s: {events}"
            )
        time.sleep(0.01)


def _real_conpty_available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winpty  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
@pytest.mark.parametrize(
    ("scenario", "expected_exit", "expected_lines"),
    [
        ("registered", 0, ["REGISTERED"]),
        ("nonzero", 9, ["REGISTERED"]),
        *(("delayed_extra", 0, ["REGISTERED", "extra"]) for _ in range(20)),
    ],
)
def test_real_windows_conpty_fixture_exit_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_exit: int,
    expected_lines: list[str],
) -> None:
    record = tmp_path / f"{scenario}.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", scenario)
    monkeypatch.setenv("FAKE_CLAUDE_EXTRA_DELAY", "0.03")
    process = WindowsConPtyFactory().spawn(
        [sys.executable, str(fixture), "--session-id", "real-conpty-uuid"],
        cwd=str(tmp_path),
    )
    registration_prompt = (
        build_claude_registration_prompt(
            candidate(), derive_claude_visibility_identity(candidate(), SECRET), SECRET
        )
        if scenario == "registered"
        else "registration prompt"
    )
    startup = process.read_until_ready(_REAL_CONPTY_GUARD_SECONDS)
    assert "\x1b[?2004h" in startup
    process.write(f"\x1b[200~{registration_prompt}\x1b[201~\r")
    if scenario == "delayed_extra":
        # Wait for the EFFECT -- the fixture has written and flushed the trailing
        # line -- rather than betting it arrives inside the reader's
        # _RESPONSE_SETTLE_SECONDS (0.5s) window.  That bet races real ConPTY
        # transport latency and loses under load, truncating the drain to
        # ["REGISTERED"].  Whether a *temporally* delayed line still lands inside
        # the settle window is covered in-process, without a subprocess, by
        # test_winpty_reader_drains_extra_output_after_registered_before_acceptance;
        # here both lines only need to be in the stream before the drain starts.
        _wait_for_fixture_event(record, "extra", _REAL_CONPTY_GUARD_SECONDS)
    output = process.read_until(_REAL_CONPTY_GUARD_SECONDS, prompt=registration_prompt)
    process.write("/exit\r")
    assert output.strip().splitlines() == expected_lines
    assert process.wait(_REAL_CONPTY_GUARD_SECONDS) == expected_exit
    cleanup = process.close(_REAL_CONPTY_GUARD_SECONDS)
    assert cleanup == PtyCleanupResult(True, True, True, expected_exit)
    assert cleanup.registrar_reader_stopped is True
    assert cleanup.transport_reader_stopped is True
    assert process._reader_thread is None
    assert process.close(5.0) == cleanup
    events = json.loads(record.read_text(encoding="utf-8"))
    assert events[0]["cwd"] == str(tmp_path)
    assert events[0]["argv"] == ["--session-id", "real-conpty-uuid"]
    assert events[1]["frame"].rstrip("\r\n") == registration_prompt.replace("\n", "")
    assert events[-2]["frame"].strip() == "/exit"


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
def test_registrar_completes_genuine_interactive_conpty_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = replace(
        candidate(),
        source_cwd=str(tmp_path),
        git_root=str(tmp_path),
    )
    identity = derive_claude_visibility_identity(value, SECRET)
    item = replace(
        claim(),
        job_id=identity.job_id,
        source_session_id=value.source_session_id,
        reserved_claude_uuid=identity.claude_uuid,
        native_name=value.native_name,
        source_cwd=value.source_cwd,
        git_root=value.git_root,
        signed_marker=identity.signed_marker,
    )
    prompt = build_claude_registration_prompt(value, identity, SECRET)
    projection = SessionProjection(
        provider=Provider.CLAUDE,
        native_id=identity.claude_uuid,
        title=value.native_name,
        cwd=value.source_cwd,
        started_at=10.0,
        last_active=11.0,
        messages=[
            ProjectedMessage("u1", 0, "user", prompt, 10.0),
            ProjectedMessage("a1", 0, "assistant", "REGISTERED", 11.0),
        ],
        native_path=str(tmp_path / f"{identity.claude_uuid}.jsonl"),
        native_hash="c" * 64,
        origin_kind=OriginKind.BRIDGE_PLACEHOLDER,
        origin_bridge_id=identity.bridge_id,
    )
    record = tmp_path / "registrar-record.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "registered")

    result = ClaudeNativeRegistrar(
        cast(Any, FakeStore()),
        cast(Any, FakeSource([None, projection])),
        marker_secret=SECRET,
        startup_theme="light",
        pty_factory=WindowsConPtyFactory(),
        claude_command=(sys.executable, str(fixture)),
        clock=lambda: 100.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
        process_timeout=10.0,
        exit_timeout=5.0,
        discovery_timeout=0.0,
        retry_delay=5.0,
    ).process(item)

    assert result.status == "visible"
    events = json.loads(record.read_text(encoding="utf-8"))
    spawn_argv = events[0]["argv"]
    assert "--print" not in spawn_argv and "-p" not in spawn_argv
    assert prompt not in spawn_argv
    assert events[0]["entrypoint"] == "cli"
    # ConPTY consumes bracketed-paste controls and normalizes the multiline frame.
    assert events[1]["frame"].rstrip("\r\n") == prompt.replace("\n", "")
    assert events[-2] == {"event": "stdin", "frame": "/exit\r\n"}
    assert events[-1] == {"event": "exit", "scenario": "registered", "sequence": 0}


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
def test_real_windows_conpty_timeout_terminates_and_releases_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "timeout.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "timeout_after_native_creation")
    process = WindowsConPtyFactory().spawn(
        [sys.executable, str(fixture), "--session-id", "real-timeout-uuid"],
        cwd=str(tmp_path),
    )
    process.write("registration prompt\r")
    with pytest.raises(TimeoutError):
        process.read_until(0.1, prompt="registration prompt")
    assert process.terminate(5.0)
    cleanup = process.close(5.0)
    assert (
        cleanup.process_dead and cleanup.reader_stopped and cleanup.descriptors_closed
    )
    assert cleanup.registrar_reader_stopped is True
    assert cleanup.transport_reader_stopped is True
    assert process._reader_thread is None


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
def test_detached_redirected_registrar_cancellation_is_ambiguous_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child_marker = "SESSION_BRIDGE_DETACHED_CONPTY_CHILD"
    if os.environ.get(child_marker) != "1":
        stdout_path = tmp_path / "detached-stdout.txt"
        stderr_path = tmp_path / "detached-stderr.txt"
        env = {**os.environ, child_marker: "1"}
        command = [
            sys.executable,
            "-m",
            "pytest",
            f"{Path(__file__).resolve()}::test_detached_redirected_registrar_cancellation_is_ambiguous_and_cleans_up",
            "-q",
            "-s",
        ]
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            child = subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[2],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return_code = child.wait(timeout=_REAL_CONPTY_GUARD_SECONDS)
        output = stdout_path.read_text(encoding="utf-8", errors="replace")
        errors = stderr_path.read_text(encoding="utf-8", errors="replace")
        assert return_code == 0, errors
        assert "DETACHED_CONPTY_CANCELLATION_OK" in output
        return

    value = replace(candidate(), source_cwd=str(tmp_path), git_root=str(tmp_path))
    identity = derive_claude_visibility_identity(value, SECRET)
    item = replace(
        claim(),
        job_id=identity.job_id,
        reserved_claude_uuid=identity.claude_uuid,
        signed_marker=identity.signed_marker,
        source_cwd=value.source_cwd,
        git_root=value.git_root,
    )
    record = tmp_path / "detached-cancel.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "timeout_after_native_creation")
    stop = threading.Event()
    store = FakeStore()

    class CapturingFactory(WindowsConPtyFactory):
        process: _WinPtyProcess | None = None
        spawn_count = 0

        def spawn(self, argv: list[str], *, cwd: str) -> _WinPtyProcess:
            self.spawn_count += 1
            spawned = super().spawn(argv, cwd=cwd)
            assert isinstance(spawned, _WinPtyProcess)
            self.process = spawned
            return spawned

    factory = CapturingFactory()

    def cancel_after_creation() -> None:
        _wait_for_fixture_event(record, "native_created", _REAL_CONPTY_GUARD_SECONDS)
        stop.set()

    canceller = threading.Thread(target=cancel_after_creation)
    canceller.start()
    try:
        result = ClaudeNativeRegistrar(
            cast(Any, store),
            cast(Any, FakeSource()),
            marker_secret=SECRET,
            startup_theme="light",
            pty_factory=factory,
            claude_command=(sys.executable, str(fixture)),
            clock=lambda: 100.0,
            monotonic=time.monotonic,
            sleep=time.sleep,
            process_timeout=_REAL_CONPTY_GUARD_SECONDS,
            exit_timeout=5.0,
            discovery_timeout=0.0,
            retry_delay=5.0,
        ).process(item, stop=stop)
    finally:
        canceller.join(_REAL_CONPTY_GUARD_SECONDS)

    assert canceller.is_alive() is False
    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert factory.spawn_count == 1
    assert [call[0] for call in store.calls] == ["retry"]
    assert factory.process is not None
    cleanup = factory.process.close(5.0)
    assert cleanup.process_dead is True
    assert cleanup.succeeded
    assert cleanup.registrar_reader_stopped is True
    assert cleanup.transport_reader_stopped is True
    assert factory.process._reader_thread is None
    print("DETACHED_CONPTY_CANCELLATION_OK")


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
def test_real_windows_authentication_failure_is_fixed_retry_with_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = replace(candidate(), source_cwd=str(tmp_path), git_root=str(tmp_path))
    identity = derive_claude_visibility_identity(value, SECRET)
    item = replace(
        claim(),
        job_id=identity.job_id,
        reserved_claude_uuid=identity.claude_uuid,
        signed_marker=identity.signed_marker,
        source_cwd=value.source_cwd,
        git_root=value.git_root,
    )
    record = tmp_path / "authentication_failure.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "authentication_failure")

    class CapturingFactory(WindowsConPtyFactory):
        process: _WinPtyProcess | None = None

        def spawn(self, argv: list[str], *, cwd: str) -> _WinPtyProcess:
            spawned = super().spawn(argv, cwd=cwd)
            assert isinstance(spawned, _WinPtyProcess)
            self.process = spawned
            return spawned

    factory = CapturingFactory()
    result = ClaudeNativeRegistrar(
        cast(Any, FakeStore()),
        cast(Any, FakeSource()),
        marker_secret=SECRET,
        startup_theme="light",
        pty_factory=factory,
        claude_command=(sys.executable, str(fixture)),
        clock=lambda: 100.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
        process_timeout=10.0,
        exit_timeout=5.0,
        discovery_timeout=0.0,
        retry_delay=5.0,
    ).process(item)

    assert result.status == "retry"
    assert result.error_code == "claude_authentication_unavailable"
    assert result.reserved_claude_uuid == item.reserved_claude_uuid
    assert factory.process is not None
    cleanup = factory.process.close(5.0)
    assert cleanup.succeeded
    assert cleanup.registrar_reader_stopped is True
    assert cleanup.transport_reader_stopped is True
    assert factory.process._reader_thread is None


@pytest.mark.skipif(not _real_conpty_available(), reason="Windows ConPTY unavailable")
def test_registrar_spawn_does_not_mutate_standard_pywinpty_reader_during_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    from winpty import PtyProcess
    from winpty import ptyprocess as winpty_module

    original_reader = winpty_module._read_in_thread
    changed: list[object] = []

    def observing_reader(address: object, pty: object, blocking: bool) -> None:
        del blocking
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect(address)  # type: ignore[arg-type]
            while True:
                if winpty_module._read_in_thread is not observing_reader:
                    changed.append(winpty_module._read_in_thread)
                try:
                    data = pty.read(4096, blocking=False)  # type: ignore[attr-defined]
                except Exception:
                    return
                if data:
                    client.sendall(data.encode() if isinstance(data, str) else data)
                if pty.iseof():  # type: ignore[attr-defined]
                    return
                time.sleep(0.001)
        finally:
            client.close()

    monkeypatch.setattr(winpty_module, "_read_in_thread", observing_reader)
    standard = PtyProcess.spawn([
        sys.executable,
        "-c",
        "import time; time.sleep(1); print('STANDARD_OK')",
    ])
    record = tmp_path / "concurrent.json"
    fixture = Path(__file__).parent / "fixtures" / "fake_interactive_claude.py"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "registered")
    registrar_process = WindowsConPtyFactory().spawn(
        [sys.executable, str(fixture), "--session-id", "concurrent-uuid"],
        cwd=str(tmp_path),
    )
    assert winpty_module._read_in_thread is observing_reader
    registrar_process.write("\x1b[200~registration prompt\x1b[201~\r")
    assert "REGISTERED" in registrar_process.read_until(
        10.0, prompt="registration prompt"
    )
    registrar_process.write("/exit\r")
    assert registrar_process.wait(10.0) == 0
    assert registrar_process.close(5.0).succeeded
    standard_output = ""
    output_deadline = time.monotonic() + 5
    while "STANDARD_OK" not in standard_output and time.monotonic() < output_deadline:
        standard_output += standard.read(4096)
    assert "STANDARD_OK" in standard_output
    deadline = time.monotonic() + 5
    while standard.isalive() and time.monotonic() < deadline:
        time.sleep(0.01)
    standard.fileobj.close()
    standard._server.close()
    standard._thread.join(_READER_EOF_GUARD_SECONDS)
    assert not changed
    monkeypatch.setattr(winpty_module, "_read_in_thread", original_reader)
    assert winpty_module._read_in_thread is original_reader


# --- ConPTY cursor-forward layout ------------------------------------------
#
# ConPTY renders a run of blank cells as a cursor-forward escape (CSI n C)
# instead of literal spaces. Deleting the escape rather than expanding it welds
# the words on either side together, so the registrar stops recognizing the echo
# of its own prompt. Measured against the live TUI on 2026-08-23: the readiness
# frame carried 85 cursor-forward escapes and the prompt echo 7, while CSI n G
# (absolute column) never appeared once -- which is why only CSI n C is
# expanded here.
CONPTY_PROMPT_ECHO_FRAME = (
    "\x1b[7;3HReply\x1b[1Cwith\x1b[1Cexactly\x1b[1CREGISTERED\x1b[1Cand"
    "\x1b[1Cnothing\x1b[1Celse.\x1b[7m \x1b[27m\x1b[9;39H\x1b[K\x1b[82C"
)
CONPTY_ECHOED_PROMPT = "Reply with exactly REGISTERED and nothing else."


def test_cursor_forward_escape_expands_to_the_columns_it_skips() -> None:
    """The captured live frame must read back as its own text, spaces included."""

    assert (
        CONPTY_ECHOED_PROMPT
        in _stripped_terminal_text(CONPTY_PROMPT_ECHO_FRAME)
    )


def test_cursor_forward_echo_is_not_mistaken_for_a_response() -> None:
    normalized = _normalized_terminal_output(
        CONPTY_PROMPT_ECHO_FRAME, CONPTY_ECHOED_PROMPT
    )

    assert normalized == ""
    assert _prompt_input_registered_response(
        CONPTY_PROMPT_ECHO_FRAME, prompt=CONPTY_ECHOED_PROMPT
    ) == (False, None)


def test_space_rendered_echo_and_cursor_forward_echo_agree() -> None:
    """Control: the two encodings of one frame must classify identically."""

    spaced = CONPTY_PROMPT_ECHO_FRAME.replace("\x1b[1C", " ")

    assert _normalized_terminal_output(
        CONPTY_PROMPT_ECHO_FRAME, CONPTY_ECHOED_PROMPT
    ) == _normalized_terminal_output(spaced, CONPTY_ECHOED_PROMPT)


def test_cursor_forward_prompt_echo_still_submits_and_registers() -> None:
    """The whole point: an un-submitted echo must not end the attempt."""

    item = claim()
    expected = build_claude_registration_prompt(
        candidate(), derive_claude_visibility_identity(candidate(), SECRET), SECRET
    )
    process = FakePty(
        prompt_input_output=_as_cursor_forward_echo(expected),
        output="REGISTERED\r\n",
    )
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    assert "\r" in process.writes
    assert process.writes[-1] == "/exit\r"


def test_cursor_forward_response_frame_is_still_exactly_registered() -> None:
    """The reply frame is drawn the same way the echo is."""

    prompt = "Reply with exactly REGISTERED and nothing else."
    output = "\x1b[7;3H" + _as_cursor_forward_echo(prompt) + "\r\n\x1b[9;3HREGISTERED\r\n"

    assert _has_exact_registered_response(output, prompt)


def test_cursor_forward_does_not_hide_a_provider_limit_banner() -> None:
    """Every multi-word matcher shares the welding hazard, not just the echo."""

    banner = "You've hit your weekly limit · resets 3pm"
    welded = _as_cursor_forward_echo(banner)

    assert _is_provider_limit_failure(banner)
    assert _is_provider_limit_failure(welded)


@pytest.mark.parametrize(
    ("parameter", "columns"),
    [
        ("", 1),  # an absent parameter means one column
        ("0", 1),  # CSI 0 C still advances one column
        ("1", 1),
        ("82", 82),  # the widest run measured in a live frame
        # The cap is spelled out rather than read off the module under test: a
        # test that imports the value it asserts moves whenever the value moves,
        # and importing a not-yet-added name turns a red baseline into a
        # collection error that hides every other test in this file.
        ("1024", 1024),
        ("4096", 1024),  # capped
        ("99999999", 1024),  # garble, capped
    ],
)
def test_cursor_forward_expands_to_a_bounded_column_count(
    parameter: str, columns: int
) -> None:
    expanded = _stripped_terminal_text("a\x1b[%sCb" % parameter)

    assert expanded == "a" + " " * columns + "b"


def test_cursor_forward_survives_a_column_count_python_cannot_parse() -> None:
    """Above sys.get_int_max_str_digits() int() raises; a drawn frame must not.

    Nothing else in the strip path catches ValueError, so an unguarded int()
    here would take down every predicate that reads terminal output.
    """

    digits = "9" * (sys.get_int_max_str_digits() + 700)

    assert _stripped_terminal_text("a\x1b[" + digits + "Cb") == "a" + " " * 1024 + "b"


def _as_cursor_forward_echo(text: str) -> str:
    """Re-encode inter-word spaces the way ConPTY draws them."""

    return "\x1b[1C".join(text.split(" "))


# --- the reply, told apart from the screen it is drawn on -------------------
#
# CONPTY_REGISTERED_FRAME is raw pty output captured from the live TUI on
# 2026-08-25, in which the model answered REGISTERED. It is the frame the reply
# marker above was said to be unmeasurable from; it can be captured by spawning
# through WindowsConPtyFactory and reading _process.read_with_timeout directly,
# because read_until raises on timeout and throws away the buffer holding the
# answer. A second capture on 2026-08-26 agrees with it in every respect used
# here. Unwelding its rows is necessary but NOT sufficient: it is a whole
# screen, and it does not end on a line break.

CONPTY_REGISTERED_FRAME = (
    '\x1b[m\x1b]0;⠂ [Codex] probe: capture the REGISTERED frame\x07\x1b[38;'
    '2;80;80;80m\x1b[48;2;55;55;55m\x1b[6;1H❯ \x1b[38;2;255;255;255mThis'
    ' is a Hermes Session Bridge Claude visibility registration'
    '.                                                       \x1b['
    '39m  \x1b[38;2;255;255;255mDo not perform project work or use'
    ' tools.                                                   '
    '                          \x1b[39m  \x1b[38;2;255;255;255mSigned'
    ' marker: HERMES_SESSION_BRIDGE_V1:eyJicmlkZ2VfaWQiOiJjbGF1'
    'ZGUtdmlzaWJpbGl0eTpmNzY4YTM3ZGEyMTE1YjBjMjA0YWY0MmZjO \x1b[39'
    'm  \x1b[38;2;255;255;255mDRhOWM0MThjY2M1OThmOTJlOTlhYTMzNTEzN'
    'mFhYjBkYjg4OWZhIiwicG9saWN5X2dlbmVyYXRpb24iOjEsInNvdXJjZV9'
    'zZXNzaW9uX2lkIjoiY29kZX \x1b[39m\n  \x1b[38;2;255;255;255mg6cHJvY'
    'mUtY3ItZnJhbWUiLCJ0YXJnZXRfcHJvdmlkZXIiOiJjbGF1ZGUifQ.UCRW'
    '3JzKh0WHXWgYBmIG4fsQRdgHKbqQaeyC-xLjWnw\x1b[K\x1b[39m\n  \x1b[38;2;2'
    '55;255;255mBounded metadata: {"bridge_id":"claude-visibili'
    'ty:f768a37da2115b0c204af42fc84a9c418ccc598f92e99aa335136aa'
    'b0db889fa"," \x1b[39m\n  \x1b[38;2;255;255;255mgit_branch":null,"'
    'git_head":null,"git_root":null,"source_cwd":"C:\\\\Users\\\\di'
    'ego","source_provider":"codex","source_se \x1b[39m\n  \x1b[38;2;2'
    '55;255;255mssion_id":"codex:probe-cr-frame","worktree_id":'
    'null}\x1b[K\x1b[39m\n  \x1b[38;2;255;255;255mYou must reply exactly '
    'REGISTERED.\x1b[K\x1b[39m\n  \x1b[38;2;255;255;255mAfter the first s'
    'ubsequent substantive user request, call session_continue\x1b'
    '[K\x1b[39m\n  \x1b[38;2;255;255;255mwith the canonical source ses'
    'sion identity before performing project work.\x1b[K\x1b[38;2;215'
    ';119;87m\x1b[49m\x1b[18;1H✢\x1b[1CWib\x1b[38;2;235;159;127mbli\x1b[38;2;2'
    '15;119;87mng…\x1b[38;2;8;145;178m\x1b[20;1H─────────────────────'
    '────────────────────────────────────────────────────\x1b[38;2'
    ';0;0;0m\x1b[48;2;8;145;178m [Codex] probe: capture the REGIST'
    'ERED frame \x1b[38;2;8;145;178m\x1b[49m──\x1b[38;2;153;153;153m\n❯\xa0\x1b'
    '[m\x1b[7m \x1b[38;2;8;145;178m\x1b[27m\n────────────────────────────'
    '──────────────────────────────────────────────────────────'
    '──────────────────────────────────\x1b[38;2;153;153;153m\x1b[23;'
    '3Hpaste\x1b[1Cagain\x1b[1Cto\x1b[1Cexpand\x1b[m\x1b[38;2;215;119;87m\x1b[18;'
    '1H✽\x1b[1CGarnishing\x1b[38;2;235;159;127m… \x1b[m\x1b]0;⠐ [Codex] pro'
    'be: capture the REGISTERED frame\x07\x1b[38;2;235;159;127m\x1b[18;1'
    '2Hg\x1b[38;2;153;153;153m\x1b[2C(1s · \x1b[38;2;173;173;173mthinkin'
    'g\x1b[38;2;153;153;153m)\x1b[m\x1b]0;✳ [Codex] probe: capture the R'
    'EGISTERED frame\x07\x1b[38;2;255;255;255m\n●\x1b[m\x1b[1CREGISTERED\x1b[K\x1b'
    '[38;2;153;153;153m\x1b[20;1H✻ Churned for 3s\x1b[K\x1b[m\n\x1b[K\x1b[38;2;'
    '0;0;0m\x1b[48;2;8;145;178m\x1b[22;74H [Codex] probe: capture the'
    ' REGISTERED frame \x1b[m\n❯\xa0\x1b[7m \x1b[27m\x1b[K\x1b[38;2;8;145;178m\n───'
    '──────────────────────────────────────────────────────────'
    '──────────────────────────────────────────────────────────'
    "─\x1b[m\n  \x1b[38;2;255;107;128m⏵⏵ don't ask on \x1b[38;2;153;153;1"
    '53m(shift+tab to cycle) · ← for agents\x1b[K\x1b[67C\x1b[m\n\x1b[120C'
)


CONPTY_REGISTERED_PROMPT_LINE = "You must reply exactly REGISTERED."


def test_captured_registered_frame_carries_no_carriage_return() -> None:
    """Pins the measurement, because the frame contradicts the obvious story.

    The weld this module unwelds is caused by CUP being deleted, not by "\\r".
    The frame that actually carries the answer holds 8 CUP, 10 EL and 9 CUF and
    no carriage return at all, bare or paired.
    """

    assert "\r" not in CONPTY_REGISTERED_FRAME
    assert "\x1b[20;1H" in CONPTY_REGISTERED_FRAME  # the CUP that did the welding


def test_cursor_position_escape_does_not_weld_two_screen_rows() -> None:
    """The unwelding, checked against a real frame rather than a built one."""

    lines = _stripped_terminal_text(CONPTY_REGISTERED_FRAME).splitlines()

    assert "● REGISTERED" in lines
    assert not any(
        line != "● REGISTERED" and "REGISTERED" in line and "Churned" in line
        for line in lines
    )


def test_live_registered_frame_is_recognized_as_the_exact_answer() -> None:
    """Unwelding alone does not do this: the answer shares the frame with the
    whole screen, so the capture must be reduced to what Claude drew."""

    assert _has_exact_registered_response(
        CONPTY_REGISTERED_FRAME, CONPTY_REGISTERED_PROMPT_LINE
    )


def test_live_registered_frame_arms_the_read_loop_candidate() -> None:
    """Without this the read loop times out and discards the answer.

    The frame is passed exactly as captured. It ends "\\x1b[120C", a cursor move
    -- a drawn screen almost never ends on a line break -- so an earlier draft
    of this test appended a newline, passed, and left the live path still
    broken. Padding the evidence here puts the defect back out of reach.
    """

    assert not CONPTY_REGISTERED_FRAME.endswith(("\r", "\n"))
    assert _exact_registered_suffix(CONPTY_REGISTERED_FRAME) is not None


def test_answer_still_being_drawn_is_not_latched_as_complete() -> None:
    """Nothing drawn below it yet, so the row can still grow."""

    assert _exact_registered_suffix("\x1b[9;1H● REGISTERED") is None
    assert _exact_registered_suffix("\x1b[9;1H● REGISTERED\r\n") is not None
    assert (
        _exact_registered_suffix("\x1b[9;1H● REGISTERED\x1b[10;1H✻ Churned for 3s")
        is not None
    )


def test_live_registered_frame_survives_the_normalized_round_trip() -> None:
    """The production route: read_until normalizes before _launch scores it.

    The reply marker must therefore survive normalization -- it is the only
    boundary left between the answer and the frame drawn around it, and
    _strip_line_marker would remove it along with the spinner glyph.
    """

    normalized = _normalized_terminal_output(
        CONPTY_REGISTERED_FRAME, CONPTY_REGISTERED_PROMPT_LINE
    )

    assert "● REGISTERED" in normalized.splitlines()
    assert _has_exact_registered_response(normalized, CONPTY_REGISTERED_PROMPT_LINE)


def test_drawn_screen_rejects_an_answer_that_is_not_exactly_registered() -> None:
    """Reducing the screen to the reply must not become accepting any reply."""

    chatty = CONPTY_REGISTERED_FRAME.replace("REGISTERED\x1b[K", "Sure thing\x1b[K")

    assert "● Sure thing" in _stripped_terminal_text(chatty).splitlines()
    assert not _has_exact_registered_response(
        chatty, CONPTY_REGISTERED_PROMPT_LINE
    )


def test_drawn_screen_before_the_answer_is_not_a_registration() -> None:
    """The same screen one redraw earlier is still pending, not registered."""

    pending = CONPTY_REGISTERED_FRAME[: CONPTY_REGISTERED_FRAME.rfind("\n●")]

    assert not _has_exact_registered_response(
        pending, CONPTY_REGISTERED_PROMPT_LINE
    )


def test_plain_output_without_a_drawn_screen_keeps_the_whole_buffer_rule() -> None:
    """A capture Claude never bulleted is still scored in full, as before."""

    assert _has_exact_registered_response(
        "REGISTERED\r\n", CONPTY_REGISTERED_PROMPT_LINE
    )
    assert not _has_exact_registered_response(
        "REGISTERED\r\nand one more thing\r\n", CONPTY_REGISTERED_PROMPT_LINE
    )


def test_launch_reads_out_a_response_seen_but_not_yet_captured() -> None:
    """An observed-but-uncaptured response must be read, not scored as empty.

    _prompt_input_registered_response reports (True, None) while a reply is
    still arriving.  Accepting ``prompt_response or ""`` there scored the empty
    string against the prompt and burned the attempt as ambiguous.
    """

    item = claim()
    process = FakePty(
        output="REGISTERED\r\n",
        prompt_input_output="REGISTERED",  # no line terminator yet
    )
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    # Already auto-submitted, so the CR must NOT be re-sent.
    assert "\r" not in process.writes
    assert process.writes[-1] == "/exit\r"


def test_cursor_forward_input_modal_signature_still_matches() -> None:
    """Modal gates match spaced signatures; welded text made them dead."""

    welded = (
        "\x1b[2mstandard\x1b[1Cpart\x1b[1Cof\x1b[1Cyour\x1b[1Cmax\x1b[1Cplan"
        "\x1b[1CYes,\x1b[1Ctry\x1b[1Cit\x1b[1CNot\x1b[1Cnow\x1b[0m"
    )
    assert _known_claude_input_modal_visible(welded) is True


def test_factory_strips_inherited_claude_code_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host agent session exports CLAUDE_CODE_* into everything it spawns.

    An inherited copy makes the launched CLI ignore ~/.claude/.credentials.json
    and report itself logged out, so the registration turn never runs and no
    transcript is written -- which is indistinguishable, from the job's side,
    from a prompt that was never submitted.  Measured live 2026-08-24 as a
    controlled pair from one cwd: with these stripped the launch wrote a
    transcript, with them inherited it wrote none.  session-bridge is started by
    launch-session-bridge.ps1, which does not scrub them, and in practice that
    launcher is run from an agent session -- so the service carries them and
    hands them to every registrar child.

    Only the prefix is dropped.  Unrelated inherited variables must survive,
    because the child still needs PATH, USERPROFILE and the rest of the host
    environment to run at all.
    """

    observed: dict[str, Any] = {}

    class ProcessType:
        @staticmethod
        def spawn(
            argv: list[str],
            *,
            cwd: str,
            env: dict[str, str],
            dimensions: tuple[int, int],
        ) -> object:
            observed["env"] = env
            return object()

    monkeypatch.setattr(
        "session_bridge.claude_registrar._registrar_pywinpty_process_type",
        lambda: ProcessType,
    )
    for name, value in (
        ("CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "1"),
        ("CLAUDE_CODE_OAUTH_SCOPES", "inherited scopes"),
        ("CLAUDE_CODE_SESSION_ID", "host-session-id"),
        ("CLAUDE_CODE_MESSAGING_TOKEN", "host-token"),
        ("CLAUDE_CODE_EXECPATH", "C:/host/claude.exe"),
        ("PATH_SENTINEL_FOR_TEST", "must-survive"),
    ):
        monkeypatch.setenv(name, value)

    WindowsConPtyFactory()._spawn_process(["claude"], cwd="C:/exact")

    env = observed["env"]
    assert sorted(n for n in env if n.startswith("CLAUDE_CODE_")) == [
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        "CLAUDE_CODE_ENTRYPOINT",
    ]
    assert env["CLAUDE_CODE_ENTRYPOINT"] == "cli"
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["PATH_SENTINEL_FOR_TEST"] == "must-survive"
    # The host's own environment must not be mutated on the way past.
    assert os.environ["CLAUDE_CODE_SESSION_ID"] == "host-session-id"


# --- terminate() must not report failure for a process that did exit --------
#
# Measured against a real ConPTY on 2026-08-25, reproducing at 8 of 12 runs.
# _process.terminate(force=True) raises PermissionError [WinError 5] when the
# kill races the child's own exit; the except handler recorded terminated=False
# and the loop then returned `terminated is not False` -- False -- even though
# the very next isalive() said the process was gone and exitstatus was 2.
#
# A spurious False is not cosmetic: _launch sets lifecycle_verified from it, and
# a false lifecycle_verified skips the transcript-recovery poll, converting an
# attempt that would have committed into a wasted paid attempt.


class _RacedKillProcess:
    """terminate() raises Access Denied, then the child exits on its own."""

    def __init__(self, alive_polls: int = 2):
        self._alive_polls = alive_polls
        self.exitstatus = 2
        self.pid = None
        self.terminate_calls = 0

    def terminate(self, force: bool = False) -> bool:
        self.terminate_calls += 1
        raise PermissionError(5, "Access is denied")

    def isalive(self) -> bool:
        if self._alive_polls > 0:
            self._alive_polls -= 1
            return True
        return False


def test_terminate_confirms_death_when_the_kill_raced_the_exit() -> None:
    process = _WinPtyProcess(_RacedKillProcess())

    assert process.terminate(2.0) is True


def test_terminate_still_reports_failure_for_a_process_that_stays_alive() -> None:
    """Control: confirmed-alive with no pid to taskkill must still be False."""

    class Immortal:
        pid = None
        exitstatus = None

        def terminate(self, force: bool = False) -> bool:
            return False

        def isalive(self) -> bool:
            return True

    assert _WinPtyProcess(Immortal()).terminate(0.05) is False


def test_is_dead_trusts_the_exit_status_when_the_liveness_probe_raises() -> None:
    """A liveness probe that RAISES is weak evidence of death, never of life."""

    class ReapedHandle:
        exitstatus = 0

        def isalive(self) -> bool:
            raise OSError("handle is invalid")

    assert _WinPtyProcess(ReapedHandle())._is_dead() is True


def test_is_dead_stays_false_when_liveness_is_genuinely_unknown() -> None:
    """No exit status and no usable probe means unknown, which is not dead."""

    class Opaque:
        exitstatus = None

        def isalive(self) -> bool:
            raise OSError("handle is invalid")

    assert _WinPtyProcess(Opaque())._is_dead() is False

# --- ConPTY line redraw (carriage return, cursor position, erase-in-line) ---
#
# Claude Code's TUI redraws a row by emitting a bare CR and rewriting it, and
# addresses the next row with CUP rather than a newline. Deleting the CR (and
# the CUP with it) welds every drawn row into one long line, so no line ever
# equals the answer and read_until burns the whole attempt waiting for one.
#
# The bytes from the CR onward are the live 2026-08-25 capture, verbatim. The
# two rows before it are RECONSTRUCTED -- the capture was recorded from the CR --
# and test_live_redraw_frame_welds_when_the_carriage_return_is_deleted pins that
# reconstruction against the welded line the live run actually reported, so the
# fixture cannot drift into a strawman.
LIVE_REDRAW_FRAME = (
    # The REPL footer, with its inter-word spaces drawn as cursor-forward
    # escapes the way ConPTY encodes them.
    "\x1b[16;1H(shift+tab\x1b[1Cto\x1b[1Ccycle)\x1b[1C-\x1b[1Cesc\x1b[1Cto"
    "\x1b[1Cinterrupt\x1b[1C-\x1b[1C<-\x1b[1Cfor\x1b[1Cagents-"
    # The answer row, drawn once and then REDRAWN in place. The replacement is
    # longer than the draw it covers, which is why nothing of the first draw
    # survives the column reset.
    "\x1b[17;1H* Gitify*"
    "\r*\x1b[1CREGISTERED\x1b[18;1H* Baked for 1s\x1b[K\r\n"
)
LIVE_WELDED_LINE = (
    "(shift+tab to cycle) - esc to interrupt - <- for agents-"
    "* Gitify** REGISTERED* Baked for 1s"
)


def _deleted_carriage_return_text(output: str) -> str:
    """The pre-fix algorithm, spelled out here so the fixture stays honest.

    Written out rather than imported: this exists to pin what the DEFECT did,
    and an import would silently start tracking the fix instead.
    """

    expanded = re.sub(
        r"\x1b\[(\d*)C",
        lambda match: " " * (int(match.group(1) or 1) or 1),
        output,
    )
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", expanded).replace("\r", "")


def test_live_redraw_frame_welds_when_the_carriage_return_is_deleted() -> None:
    """Fixture fidelity: reproduce the welded line the live run reported."""

    welded = _deleted_carriage_return_text(LIVE_REDRAW_FRAME)

    assert [line for line in welded.splitlines() if line] == [LIVE_WELDED_LINE]


def test_carriage_return_resets_the_column_instead_of_deleting_the_row() -> None:
    """The redrawn answer must land on its own row, not on the footer's tail."""

    rendered = [
        line for line in _stripped_terminal_text(LIVE_REDRAW_FRAME).splitlines() if line
    ]

    assert "* REGISTERED" in rendered


def test_cursor_position_starts_a_row_instead_of_welding_the_next_one() -> None:
    """CUP moves to another row; the row it leaves must end there."""

    rendered = [
        line for line in _stripped_terminal_text(LIVE_REDRAW_FRAME).splitlines() if line
    ]

    assert "* Baked for 1s" in rendered
    assert rendered[0] == "(shift+tab to cycle) - esc to interrupt - <- for agents-"


def test_registered_suffix_matches_the_live_redraw_frame() -> None:
    """The predicate that actually gates read_until must see the answer."""

    assert _exact_registered_suffix(LIVE_REDRAW_FRAME) is not None


def test_registered_response_survives_a_bare_carriage_return_redraw() -> None:
    """A response frame that redraws its own row still reads as REGISTERED."""

    prompt = "Reply with exactly REGISTERED and nothing else."
    output = "Thinking\r* REGISTERED\x1b[K\r\n"

    assert _has_exact_registered_response(output, prompt)


def test_redrawn_spinner_collapses_to_one_row() -> None:
    """Why CR -> LF is wrong: overwritten text must not become its own rows.

    A spinner redrawn forty times is one row of the terminal, not forty lines of
    meaningful output. Promoting each redraw to a line trades the weld for forty
    phantom lines, which breaks the exact-match predicates a second way.
    """

    frame = "".join("\rBaked for %ds" % second for second in range(1, 41))

    rendered = [line for line in _stripped_terminal_text(frame).splitlines() if line]

    assert rendered == ["Baked for 40s"]


def test_erase_in_line_drops_the_tail_the_redraw_left_behind() -> None:
    """A shorter redraw leaves the longer draw's tail until EL clears it."""

    assert _stripped_terminal_text("Baked for 12s\rOK\x1b[K") == "OK"
    assert _stripped_terminal_text("Baked for 12s\rOK") == "OKked for 12s"


def test_line_feed_still_starts_a_row_at_column_zero() -> None:
    """Regression pin: plain newline-separated output is unchanged."""

    assert _stripped_terminal_text("first\r\nsecond\r\n") == "first\nsecond\n"
    assert _stripped_terminal_text("first\nsecond") == "first\nsecond"
    assert _stripped_terminal_text("plain") == "plain"


@pytest.mark.parametrize(
    "marker",
    [
        "\u25cf",  # BLACK CIRCLE
        "\u23fa",  # BLACK CIRCLE FOR RECORD
        "\u2022",  # BULLET
        "*",
        "\u23f5\u23f5",  # the doubled glyph the REPL footer already uses
        ">",
        "Claude>",
    ],
)
def test_tui_marker_prefix_is_stripped_from_the_answer(marker: str) -> None:
    """The reply is drawn as "<marker> REGISTERED", never as bare REGISTERED.

    The exact glyph is deliberately not hardcoded. It could not be measured --
    the registrar's isolation argv renders no TUI at all on the installed CLI
    (2.1.246 against a 2.1.216 pin) -- and a wrong guess fails closed and
    silently. Any one- or two-character symbolic marker is treated the same way,
    which is what makes the rule survive a glyph change.
    """

    prompt = "Reply with exactly REGISTERED and nothing else."
    output = "%s REGISTERED\r\n" % marker

    assert _has_exact_registered_response(output, prompt)
    assert _exact_registered_suffix(output) is not None


def test_private_csi_parameters_are_dropped_rather_than_parsed() -> None:
    """A private parameter must never reach int(), which would raise.

    Added after a mutation of the drop survived the whole suite: the branch is
    not dead, no test reached it. `_cursor_forward_columns("?2")` raises
    ValueError, and nothing on the strip path catches it, so an unguarded
    private-parameter CSI whose final byte happens to be a layout one would take
    down every predicate that reads terminal output.
    """

    assert _stripped_terminal_text("a\x1b[?2Cb") == "ab"
    assert _stripped_terminal_text("a\x1b[?2;3Hb") == "ab"
    assert _stripped_terminal_text("ab\x1b[?1K") == "ab"
    assert _stripped_terminal_text("a\x1b[?2004hb\x1b[?2004l") == "ab"


def test_cursor_position_lands_on_the_column_it_names() -> None:
    """CUP carries a column, and dropping it welds what was drawn apart.

    The same hazard CSI n C expansion exists for: two runs drawn into one row at
    different columns must read back as two words, not one token.
    """

    assert _stripped_terminal_text("\x1b[1;5HX") == "\n    X"
    assert _stripped_terminal_text("\x1b[3;1Hleft\x1b[3;9Hright") == "\nleft\n        right"


def test_marker_stripping_does_not_invent_an_answer() -> None:
    """A marker in front of other text must not become the answer."""

    prompt = "Reply with exactly REGISTERED and nothing else."

    assert not _has_exact_registered_response("* NOT REGISTERED\r\n", prompt)
    assert _exact_registered_suffix("* REGISTEREDX\r\n") is None
    assert _exact_registered_suffix("*REGISTERED\r\n") is None


def test_materialize_claim_accepts_pre_rotation_signed_marker_via_retired_keys() -> (
    None
):
    retired_secret = b"registrar-retired-marker-secret"
    value = candidate()
    old_identity = derive_claude_visibility_identity(value, retired_secret)
    item = claim(signed_marker=old_identity.signed_marker)

    pinned = registrar(FakeSource(), FakeFactory())
    with pytest.raises(ValueError):
        pinned._materialize_claim(item)

    keyring = registrar(
        FakeSource(),
        FakeFactory(),
        retired_marker_secrets=(retired_secret,),
    )
    materialized_candidate, materialized_identity = keyring._materialize_claim(item)
    assert materialized_candidate.source_session_id == value.source_session_id
    assert materialized_identity.signed_marker == old_identity.signed_marker
    assert materialized_identity.job_id == old_identity.job_id

    result = pinned.process(item)
    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"


@pytest.mark.parametrize(
    "reply",
    ["REGISTERED.", "REGISTERED!", "REGISTERED ", "REGISTERED...", "REGISTERED. "],
)
def test_registered_reply_is_accepted_with_trailing_punctuation(reply: str) -> None:
    """A compliant answer must not be rejected on a full stop.

    The registration prompt says "You must reply exactly REGISTERED." -- a
    sentence that itself ends in a full stop, so a model cannot tell whether
    the stop belongs to the token or the sentence. Measured live 2026-09-01
    with a standalone PTY harness driving the production argv and the real
    prompt: 4 of 10 attempts had the model answer literally "REGISTERED." and
    every one was rejected by the exact equality, so the read loop never
    latched, burned its whole budget, and the attempt was classified
    main_repl_without_prompt_echo -- a paid failure caused by punctuation.
    """

    frame = f"\x1b[?2004h> \r\n{reply}\r\n"
    assert _has_exact_registered_response(frame, "prompt") is True
    assert _exact_registered_suffix(frame) is not None


@pytest.mark.parametrize(
    "reply",
    [
        "NOT REGISTERED.",
        "REGISTERED FAILED",
        "REGISTERED?",
        "UNREGISTERED.",
        "REGISTERED elsewhere.",
        "already REGISTERED.",
    ],
)
def test_registered_matcher_still_refuses_anything_but_the_token(reply: str) -> None:
    """Tolerating a trailing stop must not tolerate a different answer.

    Only TRAILING sentence punctuation is forgiven; the rest of the line has
    to be exactly the token. A question mark is deliberately NOT forgiven --
    "REGISTERED?" is not an assertion that registration happened.
    """

    frame = f"\x1b[?2004h> \r\n{reply}\r\n"
    assert _has_exact_registered_response(frame, "prompt") is False
    assert _exact_registered_suffix(frame) is None


@pytest.mark.parametrize("reply", ["REGISTERED.", "REGISTERED!", "REGISTERED..."])
def test_registered_tolerance_reaches_the_final_validation_gate(reply: str) -> None:
    """The read-loop gate and the commit gate must agree on what counts.

    _is_exact_registered_text is the LAST check in _validate_projection.
    Widening only _has_exact_registered_response (45bf4db290) split the two:
    a punctuated answer latched in the read loop, got /exit written, reached
    _validate_and_commit -- and was rejected at the final line with
    bridge_conflict, which is FATAL, where the pre-fix path timed out to
    creation_ambiguous, which is RETRYABLE. That converted a slow retryable
    failure into a fast terminal one for exactly the case the fix targeted,
    and with max_attempts=2 it kills the job on attempt 1. The two gates must
    move together.
    """

    frame = f"\x1b[?2004h> \r\n{reply}\r\n"
    assert _has_exact_registered_response(frame, "prompt") is True
    assert _is_exact_registered_text(reply) is True


@pytest.mark.parametrize(
    "reply", ["NOT REGISTERED.", "UNREGISTERED.", "REGISTERED?", "REGISTERED FAILED"]
)
def test_final_validation_gate_still_refuses_anything_but_the_token(reply: str) -> None:
    assert _is_exact_registered_text(reply) is False


def test_launch_failure_names_its_reason_in_the_service_log(caplog) -> None:
    """A failed launch must say WHY in the log, at the moment it happens.

    Measured 2026-09-02 on a live Mode A exhaustion (job b8a672937eb5fd, three
    attempts of 361.9/360.8/360.5s, all reconciliations 'absent', no
    transcript): service.stderr.log covered the whole window without rotating
    -- 532,480 bytes spanning 08:38 to 10:03 -- and contained WARNING 0,
    ERROR 0, and ZERO occurrences of "registrar", "creation_ambiguous",
    "main_repl", the job id or the reserved uuid. The launch path is silent.

    Every launch failure funnels into pending=("retry", "creation_ambiguous",
    <reason>), and that reason is the only thing separating a paste that never
    submitted from a model turn that never completed. It reaches the job row
    and is overwritten by the next attempt, so after an exhaustion it is gone.
    Three sessions failed to diagnose this after the fact for want of this one
    line. DISCOVERY already has exactly this (coordinator.py's
    _log_visibility_discovery_degraded, which is what resolved
    provider_degraded to _CodexReadBudgetExceeded); the launch path did not.
    """

    item = claim()
    process = FakePty(read_error=_PtyResponseTimeout("main_repl_without_prompt_echo"))
    source = FakeSource([None, None])

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    text = caplog.text
    assert "claude_visibility_launch_failed" in text, "launch failure was not logged"
    # The discriminating reason -- not merely the generic code -- must survive.
    assert "main_repl_without_prompt_echo" in text
    assert result.error_code in text


def test_successful_launch_logs_no_failure(caplog) -> None:
    """The new line must fire on failure only, not on every registration."""

    item = claim()
    process = FakePty(
        prompt_input_output="[Pasted text #1 +12 lines]\r\nREGISTERED\r\n",
        read_error=_PtyResponseTimeout("no_response_output"),
    )
    source = FakeSource([None, projection_for(item)])

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    assert "claude_visibility_launch_failed" not in caplog.text


def test_launch_logs_a_failure_resolved_before_the_discovery_poll(caplog) -> None:
    """The EARLY resolution path must log too, not just the discovery timeout.

    _launch has two non-committing exits. The discovery-timeout one covers the
    Mode A shape; this one fires first, whenever pending is neither a provider
    limit nor an ambiguous reconciliation -- e.g. an auth refusal, which
    returns immediately without ever polling for a transcript. Mutation
    testing found this site bound to nothing: deleting its log call failed no
    test, because every existing case reached the poll instead.
    """

    item = claim()
    process = FakePty(output="Authentication required\r\n")
    source = FakeSource([None])

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "claude_authentication_unavailable"
    assert "claude_visibility_launch_failed" in caplog.text
    assert "claude_authentication_unavailable" in caplog.text


def test_swallowed_store_failure_is_logged_with_the_operation_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A store failure the registrar converts to a bare code must still be named.

    These call sites catch Exception and return session_bridge_unavailable /
    "store transition unavailable". Returning that is correct; being SILENT
    about it is what cost three sessions. A visibility job livelocked from
    2026-09-02 to 2026-09-04 -- lease reclaimed and retaken every ~8 minutes,
    retry/session_bridge_unavailable each time, nothing written and nothing
    logged. The cause was commit_claude_visibility_job raising
    ValueError('claude_lineage_missing_source'); one log line would have named
    it on the first cycle.
    """

    class RaisingStore(FakeStore):
        def commit_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
            raise ValueError("claude_lineage_missing_source")

    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(
            FakeSource([projection_for(item)]), FakeFactory(), RaisingStore()
        ).process(item)

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    records = [
        record
        for record in caplog.records
        if "store transition failed" in record.getMessage()
    ]
    assert len(records) == 1, "exactly one swallow should be reported"
    message = records[0].getMessage()
    assert "operation=commit_claude_visibility_job" in message
    assert "lease_kind=reconciliation" in message
    # The exception TYPE and text are the whole discriminator -- without
    # exc_info the line names the call but still not the reason.
    assert records[0].exc_info is not None
    assert "claude_lineage_missing_source" in caplog.text


def test_swallowed_absence_store_failure_is_logged_with_its_own_operation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The absence path swallows separately and must not borrow another name."""

    class RaisingStore(FakeStore):
        def record_claude_visibility_exact_id_absent(
            self, *args: Any
        ) -> dict[str, Any]:
            raise ValueError("exact active Claude reconciliation lease required")

    class MissingSource(FakeSource):
        def find_native_sessions_by_stem_fresh(self, native_id: str) -> list[Path]:
            return []

        def find_native_sessions_by_stem(self, native_id: str) -> list[Path]:
            return []

        def find_native_sessions(self, native_id: str) -> list[Path]:
            return []

        def find_native_session(self, native_id: str) -> Path | None:
            return None

    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(MissingSource(), FakeFactory(), RaisingStore()).process(item)

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    messages = [
        record.getMessage()
        for record in caplog.records
        if "store transition failed" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "operation=record_claude_visibility_exact_id_absent" in messages[0]


def test_swallowed_retry_store_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_retry rewrites its own code on failure; without a log the cause is gone."""

    class RaisingStore(FakeStore):
        def retry_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
            raise ValueError("exact active Claude visibility lease required")

    stop = threading.Event()
    stop.set()
    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(FakeSource(), FakeFactory(), RaisingStore()).process(
            item, stop=stop
        )

    assert result.status == "retry"
    assert result.error_code == "session_bridge_unavailable"
    messages = [
        record.getMessage()
        for record in caplog.records
        if "store transition failed" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "operation=retry_claude_visibility_job" in messages[0]


def test_swallowed_fail_store_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_fail rewrites a real terminal verdict into session_bridge_unavailable."""

    class RaisingStore(FakeStore):
        def fail_claude_visibility_job(self, *args: Any) -> dict[str, Any]:
            raise ValueError("exact active Claude visibility lease required")

    class ConflictingSource(FakeSource):
        def find_native_sessions_by_stem_fresh(self, native_id: str) -> list[Path]:
            return [Path("a.jsonl"), Path("b.jsonl")]

        def find_native_sessions_by_stem(self, native_id: str) -> list[Path]:
            return [Path("a.jsonl"), Path("b.jsonl")]

    item = claim(
        lease_kind="reconciliation",
        launch_permitted=False,
        registration_reserved=False,
        requires_exact_id_reconciliation=True,
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(ConflictingSource(), FakeFactory(), RaisingStore()).process(
            item
        )

    assert result.status == "failed"
    assert result.error_code == "session_bridge_unavailable"
    messages = [
        record.getMessage()
        for record in caplog.records
        if "store transition failed" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "operation=fail_claude_visibility_job" in messages[0]


_FRAME_MARKER = (
    "Signed marker: HERMES_SESSION_BRIDGE_V1:eyJicmlkZ2VfaWQiOiJ4In0.AbCd-_1"
)


def test_redacted_launch_frame_removes_the_signed_marker_token() -> None:
    """The marker authenticates the bridge; it must never reach a log."""

    frame = _redacted_launch_frame(
        "This is a Hermes Session Bridge Claude visibility registration.\n"
        + _FRAME_MARKER
        + "\nBounded metadata: {\"source_cwd\":\"C:\\\\x\"}\n> \n"
    )

    assert "eyJicmlkZ2VfaWQiOiJ4In0" not in frame
    assert "HERMES_SESSION_BRIDGE_V1:<redacted>" in frame
    assert "source_cwd" not in frame
    assert "Bounded metadata: <redacted>" in frame
    # The preamble is the single most informative bit -- whether the prompt
    # reached the screen at all -- so it is deliberately kept.
    assert "Hermes Session Bridge Claude visibility registration" in frame


def test_redacted_launch_frame_bounds_a_huge_frame_and_says_how_much() -> None:
    frame = _redacted_launch_frame("A" * 12000)

    assert len(frame) < 12000
    assert "chars elided" in frame


def test_redacted_launch_frame_is_empty_for_no_output() -> None:
    assert _redacted_launch_frame("") == ""
    assert _redacted_launch_frame(None) == ""
    assert _redacted_launch_frame(b"bytes") == ""


def test_response_timeout_carries_the_screen_its_reason_came_from() -> None:
    """Without this the reason is computed and the evidence discarded."""

    error = _PtyResponseTimeout("main_repl_without_prompt_echo", "drawn screen")

    assert error.reason == "main_repl_without_prompt_echo"
    assert error.output == "drawn screen"
    # Default keeps every existing construction valid.
    assert _PtyResponseTimeout("no_response_output").output == ""


def test_launch_logs_the_frame_a_response_timeout_failed_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The production Mode A shape: a timeout whose screen must reach the log.

    Job d488ac51...614a723abf48 failed three times on 2026-09-04 with
    creation_ambiguous / main_repl_without_prompt_echo and wrote no transcript.
    The service log carried the reason and nothing else, so four sessions could
    not tell which upstream produced it. This pins that the screen now lands
    beside the reason.
    """

    item = claim()
    process = FakePty(
        read_error=_PtyResponseTimeout(
            "main_repl_without_prompt_echo",
            "Signed marker: HERMES_SESSION_BRIDGE_V1:secrettoken\n> \n",
        )
    )
    source = FakeSource([None])

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    frames = [
        record.getMessage()
        for record in caplog.records
        if "claude_visibility_launch_failed_frame" in record.getMessage()
    ]
    assert len(frames) == 1, "exactly one frame record per failed launch"
    assert "main_repl_without_prompt_echo" in frames[0]
    assert "secrettoken" not in frames[0], "marker must be redacted in the log"
    assert "HERMES_SESSION_BRIDGE_V1:<redacted>" in frames[0]
    # The one-line summary must survive alongside it, unchanged and greppable.
    summaries = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("claude_visibility_launch_failed job=")
    ]
    assert len(summaries) == 1


def test_launch_failure_without_a_frame_still_logs_the_summary_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failure with no captured screen must not gain an empty frame record."""

    item = claim()
    process = FakePty(ready_error=_PtyReadinessTimeout("known_input_modal"))
    source = FakeSource([None])

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        registrar(source, FakeFactory(process)).process(item)

    assert not [
        record
        for record in caplog.records
        if "claude_visibility_launch_failed_frame" in record.getMessage()
    ]


def test_response_read_raise_site_attaches_the_screen_it_classified() -> None:
    """Drive the REAL raise site, not an injected exception.

    Caught by mutation-testing: deleting the `joined` argument at
    _read_until_cancellable's raise left every other frame test green, because
    they inject _PtyResponseTimeout through FakePty and never reach the site
    that actually constructs it in production. This is the only test that fails
    if the production raise site stops carrying its screen.
    """

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(["a drawn but unregistered screen\r\n"])

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks, None)

    process = _WinPtyProcess(Process())

    with pytest.raises(_PtyResponseTimeout) as exc_info:
        process.read_until(0.05, prompt="a multiline registration prompt")

    assert exc_info.value.reason
    assert "a drawn but unregistered screen" in exc_info.value.output


def test_prompt_input_raise_site_attaches_the_screen_it_classified() -> None:
    """Same wiring, the prompt-input phase's own raise site."""

    class Process:
        def __init__(self) -> None:
            self.chunks = iter(["an unsettled paste screen\r\n"])

        def read_with_timeout(self, _size: int, _timeout: float) -> str | None:
            return next(self.chunks, None)

    process = _WinPtyProcess(Process())

    with pytest.raises(_PtyResponseTimeout) as exc_info:
        process.read_until_prompt_input(0.05, prompt="a registration prompt")

    assert "an unsettled paste screen" in exc_info.value.output


def test_launch_argv_has_no_debug_file_when_no_debug_dir_is_configured() -> None:
    """The default keeps the production argv byte-identical (the exact pins above)."""

    item = claim()
    factory = FakeFactory()
    registrar(FakeSource([None, projection_for(item)]), factory).process(item)

    assert "--debug-file" not in factory.spawns[0][0]


def test_launch_appends_a_per_attempt_cli_debug_log_when_configured(
    tmp_path: Path,
) -> None:
    """The CLI's own account of a launch that writes no transcript.

    Mode A was undiagnosable from the registrar's side: the drawn screen at
    timeout was 40 bytes of footer. The CLI's --debug-file records whether
    [engine] turn 1 ever started, its config-lock waits against ~/.claude.json
    (contended by every concurrent Claude process on the box) and its file
    index refresh -- the stretch in which a healthy 2026-09-06 run spent 53s
    before its first turn.
    """

    item = claim(attempt_ordinal=2)
    factory = FakeFactory()
    log_dir = tmp_path / "registrar"
    registrar(
        FakeSource([None, projection_for(item)]), factory, debug_log_dir=log_dir
    ).process(item)

    argv = factory.spawns[0][0]
    assert argv[-2] == "--debug-file"
    expected_stem = str(item.job_id).rsplit(":", 1)[-1][:12]
    assert argv[-1] == str(log_dir / f"{expected_stem}-att2.log")
    assert log_dir.is_dir(), "the directory is prepared before the CLI spawns"
    # The registration argv proper is untouched ahead of the appended pair.
    assert argv[:-2][-2:] == ["--permission-mode", "dontAsk"]


def test_launch_debug_logs_are_capped_so_the_directory_cannot_grow_forever(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "registrar"
    log_dir.mkdir()
    for index in range(45):
        stale = log_dir / f"old-{index:02d}.log"
        stale.write_text("x", encoding="utf-8")
        os.utime(stale, (1_700_000_000 + index, 1_700_000_000 + index))

    item = claim()
    registrar(
        FakeSource([None, projection_for(item)]), FakeFactory(), debug_log_dir=log_dir
    ).process(item)

    remaining = sorted(p.name for p in log_dir.glob("*.log"))
    assert len(remaining) <= ClaudeNativeRegistrar._DEBUG_LOGS_KEPT
    # Oldest go first, newest survive.
    assert "old-00.log" not in remaining
    assert "old-44.log" in remaining


def test_launch_degrades_to_no_debug_file_when_the_directory_is_unusable(
    tmp_path: Path,
) -> None:
    """Evidence is optional; the launch is the product."""

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")

    item = claim()
    factory = FakeFactory()
    result = registrar(
        FakeSource([None, projection_for(item)]), factory, debug_log_dir=blocker
    ).process(item)

    assert result.status == "visible"
    assert "--debug-file" not in factory.spawns[0][0]


def test_registrar_rejects_a_non_path_debug_dir() -> None:
    with pytest.raises(TypeError):
        registrar(FakeSource(), FakeFactory(), debug_log_dir="C:/tmp")  # type: ignore[arg-type]


class _ShortWritingProcess:
    """A pty wrapper whose write() accepts a bounded slice per call, like a
    real pipe under pressure: pywinpty documents PTY.write as returning the
    number of bytes written, which may be fewer than offered."""

    def __init__(self, accept: list[int]) -> None:
        self.accept = list(accept)
        self.received = bytearray()
        self.calls = 0

    def write(self, data: str) -> int:
        # pywinpty takes TEXT and reports the BYTE count it accepted (measured
        # on 2.0.15: 5 x U+00E9 -> 10). A text API cannot accept HALF a
        # character, so a byte limit landing mid-character is rounded down --
        # modelling a device that splits one would be modelling an impossible
        # one, and would let the loop appear broken for a case that cannot
        # occur.
        self.calls += 1
        encoded = data.encode("utf-8")
        limit = self.accept.pop(0) if self.accept else len(encoded)
        taken = encoded[:limit]
        while taken:
            try:
                taken.decode("utf-8")
                break
            except UnicodeDecodeError:
                taken = taken[:-1]
        self.received += taken
        return len(taken)


def test_winpty_write_delivers_every_byte_across_short_writes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The registration prompt is one ~1.1 KB paste frame followed by a Return.

    A dropped tail loses the paste-END marker and the Return then lands INSIDE
    the paste as literal text: idle REPL, no turn, no transcript, footer-only
    frame -- byte-for-byte the Mode A capture of 2026-09-06. The old write()
    discarded the count pywinpty returns.
    """

    target = _ShortWritingProcess(accept=[100, 7, 300])
    process = _WinPtyProcess(target)
    frame = "\x1b[200~" + ("x" * 1000) + "\x1b[201~"

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        process.write(frame)

    assert bytes(target.received) == frame.encode("utf-8")
    assert target.calls == 4
    shorts = [r for r in caplog.records if "PTY short write" in r.getMessage()]
    assert len(shorts) == 3, "each short acceptance is named in the log"


def test_winpty_write_raises_when_the_pipe_makes_no_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled pipe is a named, retryable failure, not a silent budget burn."""

    class Stalled:
        def write(self, data: str) -> int:
            return 0

    import session_bridge.claude_registrar as module

    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    process = _WinPtyProcess(Stalled())

    with pytest.raises(RuntimeError, match="PTY write stalled: 0 of 5 bytes"):
        process.write("hello")


def test_winpty_write_accepts_a_wrapper_that_reports_no_count() -> None:
    class Countless:
        def __init__(self) -> None:
            self.received: list[bytes] = []

        def write(self, data: str) -> None:
            self.received.append(data.encode("utf-8"))

    target = Countless()
    _WinPtyProcess(target).write("abc")

    assert target.received == [b"abc"]


def test_winpty_write_direct_path_delivers_multibyte_text_in_full() -> None:
    """Production uses the direct native path.

    MEASURED against pywinpty 2.0.15: PTY.write takes TEXT and returns a BYTE
    count (5 x U+00E9 -> 10). winpty.pyi annotates bytes, which is wrong at
    runtime; sending bytes raises TypeError and broke 26 real-ConPTY tests
    against a 0-failure baseline. This pins text-in / bytes-counted.
    """

    class Native:
        def __init__(self) -> None:
            self.pty = _ShortWritingProcess(accept=[2])

    native = Native()
    _WinPtyProcess(native, direct_native_pty=True).write("héllo")  # 6 UTF-8 bytes

    assert bytes(native.pty.received) == "héllo".encode("utf-8")
    assert native.pty.calls > 1, "a short write must be resumed, not dropped"


def test_launch_logs_the_pre_return_screen_beside_the_response_frame(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A footer-only response frame cannot say whether the paste ever arrived.

    The prompt-input capture -- what the CLI drew in response to the PASTE,
    before Return -- can. Both now travel with the failure.
    """

    item = claim()
    process = FakePty(
        prompt_input_output="[Pasted text #1 +12 lines]\r\n",
        read_error=_PtyResponseTimeout("main_repl_without_prompt_echo", "> \n"),
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        result = registrar(FakeSource([None]), FakeFactory(process)).process(item)

    assert result.error_code == "creation_ambiguous"
    prompt_frames = [
        r.getMessage()
        for r in caplog.records
        if "claude_visibility_launch_failed_prompt_frame" in r.getMessage()
    ]
    assert len(prompt_frames) == 1
    assert "Pasted text #1" in prompt_frames[0]
    assert any(
        "claude_visibility_launch_failed_frame" in r.getMessage()
        for r in caplog.records
    ), "the response frame is still logged alongside"


def test_launch_logs_no_prompt_frame_when_the_paste_drew_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item = claim()
    process = FakePty(
        prompt_input_output="",
        read_error=_PtyResponseTimeout("main_repl_without_prompt_echo", "> \n"),
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.claude_registrar"):
        registrar(FakeSource([None]), FakeFactory(process)).process(item)

    assert not [
        r
        for r in caplog.records
        if "claude_visibility_launch_failed_prompt_frame" in r.getMessage()
    ]


class _CharacterSplittingPty:
    """A device that accepts a byte count landing INSIDE a character.

    Whether the native binding can do this is not established -- it takes text
    and reports bytes, so it need not respect character boundaries. The loop
    must survive it either way: the next slice is produced by decoding the
    remaining bytes, so resuming mid-sequence would raise UnicodeDecodeError
    and turn a short write into a crash.
    """

    def __init__(self) -> None:
        self.received = bytearray()
        self.calls = 0

    def write(self, data: str) -> int:
        self.calls += 1
        encoded = data.encode("utf-8")
        if self.calls == 1:
            # Split the 2-byte U+00E9 that starts this payload.
            self.received += encoded[:1]
            return 1
        self.received += encoded
        return len(encoded)


def test_winpty_write_survives_a_count_landing_inside_a_character() -> None:
    target = _CharacterSplittingPty()

    _WinPtyProcess(target).write("éllo")  # 5 UTF-8 bytes

    # It completes rather than raising UnicodeDecodeError, and every character
    # arrives; the split character's first byte is re-sent, which is the only
    # thing a text API can do.
    assert target.calls == 2
    assert bytes(target.received).endswith("éllo".encode("utf-8"))


def test_winpty_write_raises_rather_than_spinning_on_an_always_splitting_pty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device that never completes a character must not hang the launch.

    Rounding down to a character boundary means zero forward progress, so
    without counting that as a stall the loop would resend the same slice
    forever and burn the whole process budget with no diagnosis -- the exact
    silent-hang shape this work exists to remove.
    """

    class AlwaysSplits:
        def __init__(self) -> None:
            self.calls = 0

        def write(self, data: str) -> int:
            self.calls += 1
            return 1  # always the first byte of the 2-byte character

    import session_bridge.claude_registrar as module

    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    target = AlwaysSplits()

    with pytest.raises(RuntimeError, match="PTY write stalled: 0 of 5 bytes"):
        _WinPtyProcess(target).write("éllo")

    assert target.calls == _WinPtyProcess._WRITE_STALL_RETRIES


def test_winpty_write_completes_a_payload_needing_more_writes_than_the_stall_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many small ACCEPTED writes are progress, not a stall.

    The 1.1 KB registration frame can need far more than _WRITE_STALL_RETRIES
    passes on a slow pipe. The counter must reset on real forward progress, or
    a healthy-but-slow write raises after 50 chunks and the launch fails for no
    reason -- trading a silent truncation for a spurious refusal.
    """

    class SplitsThenProgresses:
        """Splits each 2-byte character once, then completes it.

        Interleaves no-progress and progress, which is the ONLY shape that
        exercises the reset: a device that never stalls never increments the
        counter, and one that always stalls raises on the first character.
        """

        def __init__(self) -> None:
            self.received = bytearray()
            self.calls = 0
            self.split_next = True

        def write(self, data: str) -> int:
            self.calls += 1
            encoded = data.encode("utf-8")
            if self.split_next:
                self.split_next = False
                self.received += encoded[:1]
                return 1  # half of the leading character -- no usable progress
            self.split_next = True
            self.received += encoded[:2]
            return 2  # one whole character

    import session_bridge.claude_registrar as module

    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    target = SplitsThenProgresses()
    characters = _WinPtyProcess._WRITE_STALL_RETRIES + 10
    payload = "é" * characters

    _WinPtyProcess(target).write(payload)

    assert bytes(target.received).endswith(payload[-1].encode("utf-8"))
    assert target.calls == characters * 2, "one split plus one completion each"


# The pre-Return screen claude 2.1.260 drew in production on 2026-09-06, taken
# verbatim from the claude_visibility_launch_failed_prompt_frame log line for
# job ...b6b9fa34d908e54d attempts 2 and 3. The hint sits on its OWN row.
_PRODUCTION_TWO_ROW_PASTE_CHIP = (
    "\n\n  [Pasted text #1 +6 lines] \n  paste again to expand"
)

# The same frame as production drew it 20 minutes later, with the redraw
# having blanked the "o" out of the hint row.
_PRODUCTION_TWO_ROW_PASTE_CHIP_REDRAWN = (
    "\n\n  [Pasted text #1 +6 lines] \n  paste again t  expand"
)


def test_pasted_input_indicator_matches_a_lone_hint_row() -> None:
    assert _pasted_input_indicator("paste again to expand")
    assert _pasted_input_indicator("[Pasted text #1 +6 lines]")
    assert _pasted_input_indicator("[Pasted text #1 +6 lines] paste again to expand")
    assert not _pasted_input_indicator("REGISTERED")


def test_pasted_input_indicator_survives_a_dropped_character() -> None:
    """ConPTY blanks the cell a redraw lands on, so the row loses a letter.

    Taken from production 2026-09-06 23:25, job ...c20997bec5e23ab0 attempt 1,
    which reached the prompt frame as "paste again t  expand" -- one letter
    short -- and defeated an exact-match on the hint. Rendering can DROP
    characters from a row; it cannot invent new ones.
    """

    assert _pasted_input_indicator("paste again t  expand")
    assert _pasted_input_indicator("paste  gain to expand")
    assert not _pasted_input_indicator("please expand")
    assert not _pasted_input_indicator("pasting a note to expand on")


def test_two_row_paste_chip_is_not_scored_as_a_response() -> None:
    """The frame that broke the lane must read as "nothing has answered yet".

    Scoring it as a response set paste_auto_submitted, which suppressed the
    registrar's own Return; the CLI then sat at an idle REPL with the paste
    still in the box and no turn ever started -- Mode A.
    """

    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    prompt = build_claude_registration_prompt(value, identity, SECRET)

    assert _normalized_terminal_output(_PRODUCTION_TWO_ROW_PASTE_CHIP, prompt) == ""
    assert _prompt_input_registered_response(
        _PRODUCTION_TWO_ROW_PASTE_CHIP, prompt=prompt
    ) == (False, None)
    assert _pasted_input_visible(_PRODUCTION_TWO_ROW_PASTE_CHIP)


@pytest.mark.parametrize(
    "frame",
    [_PRODUCTION_TWO_ROW_PASTE_CHIP, _PRODUCTION_TWO_ROW_PASTE_CHIP_REDRAWN],
)
def test_launch_presses_return_for_a_two_row_paste_chip(frame: str) -> None:
    item = claim()
    process = FakePty(
        prompt_input_output=frame,
        read_error=_PtyResponseTimeout("main_repl_without_prompt_echo"),
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert "\r" in process.writes


# A row the normalizer has never seen, sitting under the paste chip. Stands in
# for whatever the CLI draws next under its input box -- a tip banner, a mode
# hint, a reworded chip -- none of which is an answer to the prompt.
_UNSEEN_CLI_BANNER_ROW = "  ✻ Tip: press ctrl+g to open the prompt in your editor"
_PROMPT_FRAME_WITH_UNSEEN_BANNER = (
    "\n\n  [Pasted text #1 +6 lines] \n  paste again to expand\n"
    + _UNSEEN_CLI_BANNER_ROW
)


def test_unrecognised_prompt_frame_residue_is_not_an_answer() -> None:
    """Residue the normalizer cannot name is the ABSENCE of evidence.

    Until 2026-09-07 any non-empty residue scored as "the paste self-submitted
    and this is the reply", which set paste_auto_submitted and withheld the
    registrar's own Return -- Mode A, every time the CLI drew a row under the
    input box that the normalizer had not been taught. Only an answer signal
    counts now: a REGISTERED-bearing line, or the reply bullet.
    """

    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    prompt = build_claude_registration_prompt(value, identity, SECRET)

    assert _normalized_terminal_output(_PROMPT_FRAME_WITH_UNSEEN_BANNER, prompt)
    assert _prompt_input_registered_response(
        _PROMPT_FRAME_WITH_UNSEEN_BANNER, prompt=prompt
    ) == (False, None)
    assert _prompt_input_registered_response(
        _PROMPT_FRAME_WITH_UNSEEN_BANNER + "\r\n", prompt=prompt
    ) == (False, None)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ("REGISTERED", (True, None)),
        ("REGISTERED\r\n", (True, "REGISTERED\n")),
        ("NOT REGISTERED\r\n", (True, "NOT REGISTERED\n")),
        ("● REGISTERED\r\n", (True, "● REGISTERED\n")),
        ("● Sure, I can help with that.\r\n", (True, "● Sure, I can help with that.\n")),
        ("[Pasted text #1 +12 lines]\r\nREGISTERED\r\n", (True, "REGISTERED\n")),
        ("Registered!\r\n", (False, None)),
        ("UNREGISTERED\r\n", (False, None)),
        ("Ruminating…\r\n", (False, None)),
    ],
)
def test_prompt_input_answer_evidence_is_positive_only(
    frame: str, expected: tuple[bool, str | None]
) -> None:
    prompt = "a multiline registration prompt"

    assert _prompt_input_registered_response(frame, prompt=prompt) == expected


def test_launch_presses_return_for_prompt_frame_residue_it_cannot_name() -> None:
    """The next unrecognised row under the input box must not skip Return."""

    item = claim()
    process = FakePty(
        prompt_input_output=_PROMPT_FRAME_WITH_UNSEEN_BANNER,
        read_error=_PtyResponseTimeout("main_repl_without_prompt_echo"),
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert "\r" in process.writes


def test_launch_registers_through_unrecognised_prompt_frame_residue() -> None:
    item = claim()
    process = FakePty(
        prompt_input_output=_PROMPT_FRAME_WITH_UNSEEN_BANNER,
        output="REGISTERED\r\n",
    )
    source = FakeSource([None, projection_for(item)])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "visible"
    assert "\r" in process.writes
    assert process.writes[-1] == "/exit\r"


def test_launch_keeps_malformed_answer_after_unrecognised_residue_retryable() -> None:
    """Residue no longer withholds Return, but it still withholds CERTAINTY.

    A frame with unrecognised residue is one the registrar cannot fully read,
    so a malformed answer after its Return stays creation_ambiguous (retry)
    exactly as the auto-submitted and unverified cases do -- never the fatal
    bridge_conflict reserved for a clean frame the registrar submitted itself.
    """

    item = claim()
    process = FakePty(
        prompt_input_output=_PROMPT_FRAME_WITH_UNSEEN_BANNER,
        output="Registered!\r\n",
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "retry"
    assert result.error_code == "creation_ambiguous"
    assert "\r" in process.writes


def test_launch_clean_frame_malformed_answer_is_still_fatal() -> None:
    """Control for the test above: the fatal branch is untouched."""

    item = claim()
    process = FakePty(
        prompt_input_output=_PRODUCTION_TWO_ROW_PASTE_CHIP,
        output="Registered!\r\n",
    )
    source = FakeSource([None])

    result = registrar(source, FakeFactory(process)).process(item)

    assert result.status == "failed"
    assert result.error_code == "bridge_conflict"
    assert "\r" in process.writes


def _auth_recovery_record(item, prompt: str) -> dict:
    return {
        "status": "claimed",
        "job_id": item.job_id,
        "reserved_claude_uuid": item.reserved_claude_uuid,
        "lease_digest": "b" * 64,
        "attempt_ordinal": 4,
        "operation_id": "6ae1c4de-0000-4000-8000-000000000001",
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "source_cwd": item.source_cwd,
    }


def test_auth_recovery_presses_return_for_prompt_frame_residue_it_cannot_name() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    process = FakePty(
        prompt_input_output=_PROMPT_FRAME_WITH_UNSEEN_BANNER,
        read_error=_PtyResponseTimeout("main_repl_without_prompt_echo"),
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        _auth_recovery_record(item, prompt), prompt
    )

    assert outcome.status == "retry"
    assert outcome.error_code == "creation_ambiguous"
    assert "\r" in process.writes


def test_auth_recovery_keeps_malformed_answer_after_unrecognised_residue_retryable() -> None:
    item = claim()
    prompt = "bounded same-UUID authentication recovery prompt"
    process = FakePty(
        prompt_input_output=_PROMPT_FRAME_WITH_UNSEEN_BANNER,
        output="Registered!\r\n",
    )

    outcome = registrar(FakeSource(), FakeFactory(process)).resume_auth_recovery(
        _auth_recovery_record(item, prompt), prompt
    )

    assert outcome.status == "retry"
    assert outcome.error_code == "creation_ambiguous"
    assert "\r" in process.writes
