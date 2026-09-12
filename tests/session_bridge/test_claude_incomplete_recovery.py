from dataclasses import replace
from datetime import timezone
from types import SimpleNamespace
import json

import pytest

from session_bridge.claude_registrar import _ExactTranscript, _validate_projection
from session_bridge.claude_visibility import derive_claude_visibility_identity
from session_bridge.models import OriginKind, ProjectedMessage
from tests.session_bridge.test_claude_registrar import (
    SECRET,
    FakeSource,
    FakeFactory,
    FakePty,
    registrar,
    candidate,
    claim,
    projection_for,
)


@pytest.mark.parametrize("completed", [False, True])
def test_incomplete_registration_remains_failed_until_exact_native_reply(completed):
    from session_bridge.claude_registrar import (
        build_incomplete_registration_recovery_prompt,
    )

    item = claim()
    identity = derive_claude_visibility_identity(candidate(), SECRET)
    projection = projection_for(item)
    messages = list(projection.messages[:1])
    if completed:
        messages += [
            ProjectedMessage(
                "u2",
                0,
                "user",
                build_incomplete_registration_recovery_prompt(identity),
                12,
            ),
            ProjectedMessage("a2", 0, "assistant", "REGISTERED", 13),
        ]
    source = FakeSource([replace(projection, messages=messages)])
    path = source.find_native_session(identity.claude_uuid)
    transcript = _ExactTranscript(path, source.parse(path))
    if completed:
        _validate_projection(transcript, candidate(), identity, SECRET)
    else:
        with pytest.raises(Exception, match="bridge_conflict"):
            _validate_projection(transcript, candidate(), identity, SECRET)
    assert _validate_projection(
        transcript, candidate(), identity, SECRET, allow_incomplete=True
    ) == ("incomplete_recovered" if completed else "incomplete")


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_prompt",
        "work",
        "tools",
        "duplicate",
        "missing_reply",
        "wrong_name",
        "resume_user",
        "resume_reply",
        "weekly_limit",
    ],
)
def test_incomplete_recovery_never_accepts_unrelated_or_unanswered_work(mutation):
    from session_bridge.claude_registrar import (
        build_incomplete_registration_recovery_prompt,
    )

    item = claim()
    identity = derive_claude_visibility_identity(candidate(), SECRET)
    projection = projection_for(item)
    messages = [
        projection.messages[0],
        ProjectedMessage(
            "u2", 0, "user", build_incomplete_registration_recovery_prompt(identity), 12
        ),
        ProjectedMessage("a2", 0, "assistant", "REGISTERED", 13),
    ]
    if mutation == "wrong_prompt":
        messages[1] = replace(messages[1], content="continue")
    elif mutation == "work":
        messages.append(ProjectedMessage("u3", 0, "user", "do project work", 14))
    elif mutation == "tools":
        messages[2] = replace(messages[2], tool_calls=[])
    elif mutation == "duplicate":
        messages[2] = replace(messages[2], native_event_id="u2")
    elif mutation == "missing_reply":
        messages.pop()
    elif mutation in {"resume_user", "resume_reply", "weekly_limit"}:
        messages[1:1] = [
            ProjectedMessage(
                "resume-user", 0, "user", "Continue from where you left off.", 11
            ),
            ProjectedMessage(
                "resume-assistant", 0, "assistant", "No response requested.", 11
            ),
        ]
        if mutation == "resume_user":
            messages[1] = replace(messages[1], content="Continue project work.")
        elif mutation == "resume_reply":
            messages[2] = replace(messages[2], content="Working on the project.")
        else:
            messages[-1] = replace(
                messages[-1],
                content="You've hit your weekly limit · resets Sep 14, 4am (America/New_York)",
            )
    projection = replace(
        projection,
        messages=messages,
        title="wrong" if mutation == "wrong_name" else projection.title,
        origin_kind=OriginKind.BRIDGE_CONTINUATION
        if mutation.startswith("resume_") or mutation == "weekly_limit"
        else projection.origin_kind,
    )
    source = FakeSource([projection])
    path = source.find_native_session(identity.claude_uuid)
    with pytest.raises(Exception):
        _validate_projection(
            _ExactTranscript(path, source.parse(path)),
            candidate(),
            identity,
            SECRET,
            allow_incomplete=True,
        )


@pytest.mark.parametrize("finish", [True, False, "commit_crash"])
def test_paid_incomplete_resume_uses_real_adapter_and_ledger_once(
    tmp_path, finish, monkeypatch
):
    from hermes_state import SessionDB
    from session_bridge.store import SessionBridgeStore
    from session_bridge.claude_adapter import (
        ClaudeSourceAdapter,
        claude_project_directory_name,
    )
    from session_bridge.claude_incomplete_recovery import (
        recover_incomplete_registration,
    )
    from session_bridge.claude_visibility import build_claude_registration_prompt
    from tests.session_bridge.test_store import _seed_claude_visibility_native_source

    db = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    store.enqueue_claude_visibility_job(value, identity, SECRET)
    _seed_claude_visibility_native_source(db, store, value)
    launch = store.claim_claude_visibility_job(100.0, 60, 25, "1.00", "0.02")
    store.fail_claude_visibility_job(
        identity.job_id,
        launch.lease_digest,
        "bridge_conflict",
        "exact transcript conflict",
    )
    directory = tmp_path / "projects" / claude_project_directory_name(value.source_cwd)
    directory.mkdir(parents=True)
    path = directory / f"{identity.claude_uuid}.jsonl"

    def record(role, content, event_id):
        return {
            "type": role,
            "sessionId": identity.claude_uuid,
            "uuid": event_id,
            "timestamp": "2026-09-12T00:00:00Z",
            "cwd": value.source_cwd,
            "entrypoint": "cli",
            "isSidechain": False,
            "message": {"role": role, "content": content},
        }

    records = [
        {
            "type": "custom-title",
            "sessionId": identity.claude_uuid,
            "customTitle": value.native_name,
        },
        record(
            "user",
            build_claude_registration_prompt(value, identity, SECRET),
            "11111111-1111-4111-8111-111111111111",
        ),
    ]
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
    )
    original = path.read_bytes()

    class NativePty(FakePty):
        def read_until(self, timeout, *, prompt=None):
            if finish:
                with path.open("a", encoding="utf-8") as stream:
                    for row in [
                        record(
                            "user",
                            "Continue from where you left off.",
                            "44444444-4444-4444-8444-444444444444",
                        ),
                        record(
                            "assistant",
                            "No response requested.",
                            "55555555-5555-4555-8555-555555555555",
                        ),
                        record("user", prompt, "22222222-2222-4222-8222-222222222222"),
                        record(
                            "assistant",
                            "REGISTERED",
                            "33333333-3333-4333-8333-333333333333",
                        ),
                    ]:
                        stream.write(json.dumps(row) + "\n")
            return super().read_until(timeout, prompt=prompt)

    factory = FakeFactory(NativePty())
    reg = registrar(
        ClaudeSourceAdapter(tmp_path / "projects", marker_secret=SECRET), factory, store
    )
    policy = SimpleNamespace(
        lease_seconds=60,
        daily_registration_limit=25,
        emergency_daily_cost_usd="1.00",
        reserved_cost_per_attempt_usd="0.02",
        max_attempts=5,
    )
    kwargs = dict(
        store=store,
        registrar=reg,
        job_id=identity.job_id,
        reserved_uuid=identity.claude_uuid,
        policy=policy,
        now=lambda: 100.0,
    )
    assert (
        recover_incomplete_registration(**kwargs, apply=False)["status"] == "resumable"
    )
    assert factory.spawns == []
    if finish == "commit_crash":
        commit = store.commit_claude_auth_recovery

        def crash(**kwargs):
            raise RuntimeError("commit interrupted")

        monkeypatch.setattr(store, "commit_claude_auth_recovery", crash)
        with pytest.raises(RuntimeError, match="commit interrupted"):
            recover_incomplete_registration(**kwargs, apply=True)
        monkeypatch.setattr(store, "commit_claude_auth_recovery", commit)
        assert (
            recover_incomplete_registration(**kwargs, apply=False)["status"]
            == "reconcilable"
        )
        assert (
            recover_incomplete_registration(**kwargs, apply=True)["status"] == "visible"
        )
    elif finish:
        assert (
            recover_incomplete_registration(**kwargs, apply=True)["status"] == "visible"
        )
    else:
        with pytest.raises(ValueError, match="not completed"):
            recover_incomplete_registration(**kwargs, apply=True)
        with pytest.raises(ValueError, match="already started"):
            recover_incomplete_registration(**kwargs, apply=True)
    assert len(factory.spawns) == 1
    argv = factory.spawns[0][0]
    assert argv[argv.index("--resume") + 1] == identity.claude_uuid
    assert "--session-id" not in argv
    assert path.read_bytes().startswith(original)
    assert store.claude_visibility_status(100.0)["usage"]["attempts"] == 2
    # The store, not only the orchestration snapshot, must forbid a second call.
    with db._lock:
        recovery = dict(
            db._conn.execute(
                "SELECT * FROM session_claude_auth_recoveries WHERE job_id = ?",
                (identity.job_id,),
            ).fetchone()
        )
    refused = store.claim_claude_auth_recovery(
        job_id=identity.job_id,
        reserved_claude_uuid=identity.claude_uuid,
        operation_id=recovery["operation_id"],
        evidence_digest=recovery["evidence_digest"],
        prompt_digest=recovery["prompt_digest"],
        now=1000.0,
        lease_seconds=60,
        daily_limit=25,
        cost_limit="1.00",
        reserved_cost="0.02",
        max_attempts=5,
        allow_repeated_call=False,
    )
    assert refused["status"] in {"completed", "call_already_started"}
    assert store.claude_visibility_status(100.0)["usage"]["attempts"] == 2
    db.close()


@pytest.mark.parametrize("apply", [False, True])
def test_operator_resume_cli_passes_exact_identity_and_explicit_mode(capsys, apply):
    from tests.session_bridge.test_cli import FakeBackend, _run

    calls = []

    class Backend(FakeBackend):
        def resume_incomplete_claude_visibility_job(self, **kwargs):
            calls.append(kwargs)
            return {"status": "visible" if kwargs["apply"] else "resumable"}

    args = [
        "claude-visibility-resume-incomplete",
        "--job-id",
        "job-1",
        "--reserved-claude-uuid",
        "11111111-1111-4111-8111-111111111111",
        "--apply" if apply else "--dry-run",
    ]
    assert _run(args, Backend()) == 0
    assert calls == [
        {
            "job_id": "job-1",
            "reserved_claude_uuid": "11111111-1111-4111-8111-111111111111",
            "apply": apply,
        }
    ]


def test_resume_backend_preserves_sanitized_native_failure(monkeypatch):
    import session_bridge.cli as cli
    import session_bridge.claude_incomplete_recovery as recovery
    from session_bridge.claude_registrar import ClaudeRegistrarOutcome
    from session_bridge.config import BridgeConfig

    backend = cli.ProductionBackend(BridgeConfig())
    monkeypatch.setattr(cli, "resolve_marker_key", lambda: SECRET)
    monkeypatch.setattr(cli, "resolve_retired_marker_keys", lambda **kwargs: ())
    monkeypatch.setattr(backend, "_require_store", lambda: object())

    def failed(**kwargs):
        raise recovery.IncompleteRecoveryFailed(
            ClaudeRegistrarOutcome(
                "retry",
                "job-1",
                "uuid-1",
                "creation_ambiguous",
                "Claude provider limit interrupted authentication recovery",
            )
        )

    monkeypatch.setattr(recovery, "recover_incomplete_registration", failed)
    result = backend.resume_incomplete_claude_visibility_job(
        job_id="job-1",
        reserved_claude_uuid="uuid-1",
        apply=False,
    )
    assert result == {
        "status": "failed",
        "job_id": "job-1",
        "reserved_claude_uuid": "uuid-1",
        "error_code": "creation_ambiguous",
        "error_detail": "Claude provider limit interrupted authentication recovery",
    }
