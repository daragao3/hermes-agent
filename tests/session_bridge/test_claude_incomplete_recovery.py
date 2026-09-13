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


_WEEKLY_LIMIT_BANNER = (
    "You've hit your weekly limit \u00b7 resets Sep 14, 4am (America/New_York)"
)


def _transcript_for(messages):
    """One placeholder-origin transcript carrying exactly these messages."""

    identity = derive_claude_visibility_identity(candidate(), SECRET)
    projection = replace(projection_for(claim()), messages=messages)
    source = FakeSource([projection])
    path = source.find_native_session(identity.claude_uuid)
    return _ExactTranscript(path, source.parse(path)), identity


def _recovery_prompt():
    from session_bridge.claude_registrar import (
        build_incomplete_registration_recovery_prompt,
    )

    return build_incomplete_registration_recovery_prompt(
        derive_claude_visibility_identity(candidate(), SECRET)
    )


@pytest.mark.parametrize("scaffolded", [False, True])
def test_provider_limit_banner_leaves_the_registration_resumably_incomplete(
    scaffolded,
):
    """The exact shape job aba0f323 held after its 2026-09-12 18:09Z resume.

    A paid resume that reached the CLI and drew a weekly-limit banner instead
    of a reply used to classify as nothing at all, so the operator verb refused
    a job whose only problem was a rate-limited account.
    """

    messages = [projection_for(claim()).messages[0]]
    if scaffolded:
        messages.append(
            ProjectedMessage("scaffold", 0, "assistant", "No response requested.", 11)
        )
    messages += [
        ProjectedMessage("u2", 0, "user", _recovery_prompt(), 12),
        ProjectedMessage("a2", 0, "assistant", _WEEKLY_LIMIT_BANNER, 13),
    ]
    transcript, identity = _transcript_for(messages)

    assert (
        _validate_projection(
            transcript, candidate(), identity, SECRET, allow_incomplete=True
        )
        == "incomplete_provider_limited"
    )
    # Widening the INCOMPLETE verdict must never widen the launch path: an
    # unanswered recovery turn is still not a registration.
    with pytest.raises(Exception, match="bridge_conflict"):
        _validate_projection(transcript, candidate(), identity, SECRET)


def test_repeated_provider_limit_banners_classify_only_within_the_attempt_bound():
    from session_bridge.claude_registrar import _MAX_AUTH_RECOVERY_ATTEMPTS

    recovery_prompt = _recovery_prompt()

    def attempts(count):
        messages = [projection_for(claim()).messages[0]]
        for index in range(count):
            messages += [
                ProjectedMessage(
                    "retry-u%d" % index, 0, "user", recovery_prompt, 12 + 2 * index
                ),
                ProjectedMessage(
                    "retry-a%d" % index,
                    0,
                    "assistant",
                    _WEEKLY_LIMIT_BANNER,
                    13 + 2 * index,
                ),
            ]
        return messages

    bounded, identity = _transcript_for(attempts(_MAX_AUTH_RECOVERY_ATTEMPTS))
    assert (
        _validate_projection(
            bounded, candidate(), identity, SECRET, allow_incomplete=True
        )
        == "incomplete_provider_limited"
    )

    over, over_identity = _transcript_for(attempts(_MAX_AUTH_RECOVERY_ATTEMPTS + 1))
    with pytest.raises(Exception, match="bridge_conflict"):
        _validate_projection(
            over, candidate(), over_identity, SECRET, allow_incomplete=True
        )


@pytest.mark.parametrize(
    "mutation",
    ["wrong_prompt", "banner_with_prose", "banner_from_user", "answered_with_work"],
)
def test_provider_limit_widening_still_refuses_everything_else(mutation):
    messages = [
        projection_for(claim()).messages[0],
        ProjectedMessage("u2", 0, "user", _recovery_prompt(), 12),
        ProjectedMessage("a2", 0, "assistant", _WEEKLY_LIMIT_BANNER, 13),
    ]
    if mutation == "wrong_prompt":
        messages[1] = replace(messages[1], content="continue")
    elif mutation == "banner_with_prose":
        messages[2] = replace(
            messages[2], content=_WEEKLY_LIMIT_BANNER + "\nI will stop here."
        )
    elif mutation == "banner_from_user":
        messages[2] = replace(messages[2], role="user")
    else:
        messages[2] = replace(messages[2], content="Working on the project.")
    transcript, identity = _transcript_for(messages)

    with pytest.raises(Exception, match="bridge_conflict"):
        _validate_projection(
            transcript, candidate(), identity, SECRET, allow_incomplete=True
        )


def test_every_refusal_the_recovery_module_raises_has_a_named_cause():
    """No refusal in the wrapped module may reach the operator unnamed.

    cli.py collapses every ValueError out of recover_incomplete_registration
    into one gate name. This walks the module's own raise sites, so adding a
    refusal without adding its slug fails here instead of quietly restoring the
    "nine causes, one name" defect.
    """

    import ast
    import inspect as inspect_module

    import session_bridge.claude_incomplete_recovery as recovery
    from session_bridge.cli import _incomplete_recovery_refusal_reason

    tree = ast.parse(inspect_module.getsource(recovery))
    messages = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        if getattr(node.exc.func, "id", None) != "ValueError" or not node.exc.args:
            continue
        argument = node.exc.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            messages.append(argument.value)
        elif isinstance(argument, ast.BinOp) and isinstance(
            argument.left, ast.Constant
        ):
            # "incomplete recovery unavailable: " + <bounded store status>
            messages.append(argument.left.value + "no_due_job")
        else:
            raise AssertionError("unrecognized refusal shape: " + ast.dump(argument))

    assert len(messages) >= 9
    assert [
        message
        for message in messages
        if _incomplete_recovery_refusal_reason(ValueError(message)) == "unrecognized"
    ] == []


def test_refusal_reason_names_bounded_causes_and_never_echoes_free_text():
    from session_bridge.claude_registrar import _TranscriptConflict
    from session_bridge.cli import _incomplete_recovery_refusal_reason

    assert (
        _incomplete_recovery_refusal_reason(
            ValueError("incomplete recovery job already dismissed")
        )
        == "job_already_dismissed"
    )
    assert (
        _incomplete_recovery_refusal_reason(
            ValueError("exact failed Claude visibility job required")
        )
        == "no_exact_uncleared_failed_job"
    )
    assert (
        _incomplete_recovery_refusal_reason(_TranscriptConflict("bridge_conflict"))
        == "native_transcript_bridge_conflict"
    )
    assert (
        _incomplete_recovery_refusal_reason(
            ValueError("incomplete recovery unavailable: max_attempts_exhausted")
        )
        == "recovery_lease_unavailable_max_attempts_exhausted"
    )
    # A status that is not a plain slug is reported without its payload.
    assert (
        _incomplete_recovery_refusal_reason(
            ValueError("incomplete recovery unavailable: C:/secret path")
        )
        == "recovery_lease_unavailable"
    )
    # Anything unaccounted for is named, never echoed.
    assert (
        _incomplete_recovery_refusal_reason(
            ValueError("transcript said: my password is hunter2")
        )
        == "unrecognized"
    )
    assert (
        _incomplete_recovery_refusal_reason(_TranscriptConflict("Not A Slug"))
        == "native_transcript_conflict"
    )


def test_resume_backend_reports_which_cause_refused_without_changing_the_gate(
    monkeypatch,
):
    import session_bridge.claude_incomplete_recovery as recovery
    import session_bridge.cli as cli
    from session_bridge.config import BridgeConfig

    backend = cli.ProductionBackend(BridgeConfig())
    monkeypatch.setattr(cli, "resolve_marker_key", lambda: SECRET)
    monkeypatch.setattr(cli, "resolve_retired_marker_keys", lambda **kwargs: ())
    monkeypatch.setattr(backend, "_require_store", lambda: object())

    def refuse(**kwargs):
        raise ValueError(
            "incomplete recovery already started; exact reconciliation required"
        )

    monkeypatch.setattr(recovery, "recover_incomplete_registration", refuse)

    with pytest.raises(cli.RolloutGateBlocked) as blocked:
        backend.resume_incomplete_claude_visibility_job(
            job_id="job-1", reserved_claude_uuid="uuid-1", apply=False
        )

    assert blocked.value.gate == "visibility_incomplete_recovery_refused"
    assert blocked.value.reason == "recovery_call_already_started"


@pytest.mark.parametrize("reason", [None, "job_already_dismissed"])
def test_blocked_gate_payload_carries_the_reason_only_when_there_is_one(capsys, reason):
    from session_bridge.cli import RolloutGateBlocked
    from tests.session_bridge.test_cli import FakeBackend, _run

    class Backend(FakeBackend):
        def resume_incomplete_claude_visibility_job(self, **kwargs):
            raise RolloutGateBlocked("visibility_incomplete_recovery_refused", reason)

    exit_code = _run(
        [
            "claude-visibility-resume-incomplete",
            "--job-id",
            "job-1",
            "--reserved-claude-uuid",
            "11111111-1111-4111-8111-111111111111",
            "--dry-run",
        ],
        Backend(),
    )

    assert exit_code != 0
    expected = {
        "error": "rollout_gate_blocked",
        "gate": "visibility_incomplete_recovery_refused",
    }
    if reason is not None:
        expected["reason"] = reason
    assert json.loads(capsys.readouterr().out) == expected



def test_second_attempt_transcript_still_classifies_with_its_own_scaffold():
    """The shape an AUTHORIZED second attempt writes must stay readable.

    Every native --resume records its own inert scaffold. If only the leading
    one were tolerated, the retry this policy exists to permit would itself
    make the job unclassifiable again on the attempt after it.
    """

    recovery_prompt = _recovery_prompt()
    messages = [projection_for(claim()).messages[0]]
    for attempt in range(2):
        messages += [
            ProjectedMessage(
                "scaffold-%d" % attempt,
                0,
                "assistant",
                "No response requested.",
                10 + 3 * attempt,
            ),
            ProjectedMessage(
                "retry-u%d" % attempt, 0, "user", recovery_prompt, 11 + 3 * attempt
            ),
            ProjectedMessage(
                "retry-a%d" % attempt,
                0,
                "assistant",
                _WEEKLY_LIMIT_BANNER,
                12 + 3 * attempt,
            ),
        ]
    transcript, identity = _transcript_for(messages)

    assert (
        _validate_projection(
            transcript, candidate(), identity, SECRET, allow_incomplete=True
        )
        == "incomplete_provider_limited"
    )


def test_a_resume_that_recorded_nothing_is_not_a_provider_refusal():
    """A trailing scaffold is a call that may still be in flight, not a refusal."""

    recovery_prompt = _recovery_prompt()
    messages = [
        projection_for(claim()).messages[0],
        ProjectedMessage("u2", 0, "user", recovery_prompt, 12),
        ProjectedMessage("a2", 0, "assistant", _WEEKLY_LIMIT_BANNER, 13),
        ProjectedMessage("scaffold", 0, "assistant", "No response requested.", 14),
    ]
    transcript, identity = _transcript_for(messages)

    with pytest.raises(Exception, match="bridge_conflict"):
        _validate_projection(
            transcript, candidate(), identity, SECRET, allow_incomplete=True
        )


class _RecordingStore:
    """Minimal store that records how the paid claim was asked for."""

    def __init__(self, job, recovery):
        self._job = job
        self._recovery = recovery
        self.claims = []

        class _DB:
            def __init__(self, outer):
                self._outer = outer
                self._lock = __import__("threading").Lock()

            @property
            def _conn(self):
                return self._outer

        self.db = _DB(self)

    def execute(self, sql, params):
        row = self._job if "session_claude_visibility_jobs" in sql else self._recovery

        class _Cursor:
            def fetchone(self_inner):
                return row

        return _Cursor()

    def inspect_failed_claude_visibility_reconciliation(self, **kwargs):
        return {"status": "repairable"}

    def claim_claude_auth_recovery(self, **kwargs):
        self.claims.append(kwargs)
        return {"status": "no_due_job"}


def _recovery_job_row():
    identity = derive_claude_visibility_identity(candidate(), SECRET)
    value = candidate()
    return {
        "state": "claude_failed",
        "operator_cleared_at": None,
        "lease_digest": None,
        "error_code": "bridge_conflict",
        "error_detail": "exact transcript conflict",
        "source_session_id": value.source_session_id,
        "source_provider": value.source_provider.value,
        "native_name": value.native_name,
        "source_cwd": value.source_cwd,
        "git_root": value.git_root,
        "git_branch": value.git_branch,
        "git_head": value.git_head,
        "worktree_id": value.worktree_id,
        "eligible_at": value.eligible_at,
        "bridge_id": identity.bridge_id,
        "idempotency_key": identity.idempotency_key,
        "signed_marker": identity.signed_marker,
        "attempts": 2,
    }


class _KindRegistrar:
    def __init__(self, kind):
        self._kind = kind

    def inspect_incomplete_registration(self, candidate_value, identity):
        from session_bridge.claude_registrar import (
            build_incomplete_registration_recovery_prompt,
        )

        return {
            "kind": self._kind,
            "evidence_digest": "e" * 64,
            "transcript_digest": "d" * 64,
            "prompt": build_incomplete_registration_recovery_prompt(identity),
        }


def _recovery_row(prompt, call_started):
    import hashlib

    identity = derive_claude_visibility_identity(candidate(), SECRET)
    return {
        "operation_id": "incomplete-registration:" + identity.job_id,
        "evidence_digest": "e" * 64,
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "reserved_claude_uuid": identity.claude_uuid,
        "call_started_at": call_started,
        "state": "retry",
    }


@pytest.mark.parametrize(
    "kind,expected",
    [("incomplete_provider_limited", True), ("incomplete", False)],
)
def test_only_a_provider_limited_transcript_authorizes_a_repeated_paid_call(
    kind, expected
):
    """The second call is granted by NATIVE EVIDENCE, never by an operator flag.

    Diego authorized a second paid call after a provider limit on 2026-09-13.
    A plain incomplete registration whose call already started must still
    demand exact reconciliation, because there the transcript does not prove
    the provider refused the turn.
    """

    from session_bridge.claude_incomplete_recovery import (
        recover_incomplete_registration,
    )
    from session_bridge.claude_registrar import (
        build_incomplete_registration_recovery_prompt,
    )

    identity = derive_claude_visibility_identity(candidate(), SECRET)
    prompt = build_incomplete_registration_recovery_prompt(identity)
    store = _RecordingStore(_recovery_job_row(), _recovery_row(prompt, 500.0))
    policy = SimpleNamespace(
        lease_seconds=60,
        daily_registration_limit=25,
        emergency_daily_cost_usd="1.00",
        reserved_cost_per_attempt_usd="0.02",
        max_attempts=5,
    )
    kwargs = dict(
        store=store,
        registrar=_KindRegistrar(kind),
        job_id=identity.job_id,
        reserved_uuid=identity.claude_uuid,
        policy=policy,
        now=lambda: 1000.0,
    )

    if not expected:
        with pytest.raises(ValueError, match="already started"):
            recover_incomplete_registration(**kwargs, apply=False)
        assert store.claims == []
        return

    preview = recover_incomplete_registration(**kwargs, apply=False)
    assert preview["status"] == "resumable"
    # The preview must SAY that --apply spends another attempt.
    assert preview["provider_limit_retry"] is True
    assert store.claims == []

    with pytest.raises(ValueError, match="incomplete recovery unavailable"):
        recover_incomplete_registration(**kwargs, apply=True)
    assert len(store.claims) == 1
    assert store.claims[0]["allow_repeated_call"] is True
    # The ceilings are still handed to the store, which is what books the spend.
    assert store.claims[0]["max_attempts"] == 5
    assert store.claims[0]["daily_limit"] == 25
    assert store.claims[0]["cost_limit"] == "1.00"


def test_repeated_paid_call_is_still_refused_past_the_store_ceiling(tmp_path):
    """Relaxing the flag must not relax the spend ceiling the store enforces."""

    from hermes_state import SessionDB
    from session_bridge.store import SessionBridgeStore
    from tests.session_bridge.test_store import (
        _seed_claude_visibility_native_source,
    )

    db = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    value = candidate()
    identity = derive_claude_visibility_identity(value, SECRET)
    store.enqueue_claude_visibility_job(value, identity, SECRET)
    _seed_claude_visibility_native_source(db, store, value)
    launch = store.claim_claude_visibility_job(100.0, 60, 25, "1.00", "0.02")
    store.fail_claude_visibility_job(
        identity.job_id, launch.lease_digest, "bridge_conflict",
        "exact transcript conflict",
    )
    shared = dict(
        job_id=identity.job_id,
        reserved_claude_uuid=identity.claude_uuid,
        operation_id="incomplete-registration:" + identity.job_id,
        evidence_digest="a" * 64,
        prompt_digest="b" * 64,
        lease_seconds=60,
        daily_limit=25,
        cost_limit="1.00",
        reserved_cost="0.02",
    )
    first = store.claim_claude_auth_recovery(
        **shared, now=100.0, max_attempts=5, allow_repeated_call=True
    )
    assert first["status"] == "claimed"
    store.begin_claude_auth_recovery(identity.job_id, first["lease_digest"])
    store.retry_claude_auth_recovery(
        identity.job_id, first["lease_digest"], "creation_ambiguous", 150.0
    )

    # Authorized repeat, but the job has already spent its allowance.
    exhausted = store.claim_claude_auth_recovery(
        **shared, now=200.0, max_attempts=1, allow_repeated_call=True
    )
    assert exhausted["status"] == "max_attempts_exhausted"
    db.close()
