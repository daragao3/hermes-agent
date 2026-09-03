"""Source contracts for the deployed shadow lane.

These parse the operational files WITHOUT executing them and pin the
shadow-only guarantees: the runner never passes --allow-enforce and never
references the legacy culler; the task carries an execution limit that cannot
exceed its own cadence, IgnoreNew, StartWhenAvailable, and least privilege.
The files live in the outer ~/.hermes repo (ops/tasks + bin), so these skip
cleanly on a checkout that lacks them rather than failing.

PIN RELATIONS, NOT VALUES. Every assertion here that named an exact operator
value has gone red on a legitimate change and stayed red: PT5M/PT2M when
Diego retuned the task for load headroom, fleet_min_roots==30 when he lowered
it to 25. A characterization gate that cries wolf on approved changes is one
people learn to skip, which is worse than no gate. Assert the invariant the
value exists to serve.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_HERMES = Path.home() / ".hermes"
_TASK = _HERMES / "ops" / "tasks" / "Hermes-Claude-Fleet-Controller.xml"
_RUNNER = _HERMES / "bin" / "claude_fleet_controller_run.ps1"
_CONFIG = Path(__file__).resolve().parents[2] / "claude_fleet_control" / "config.json"
_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _iso_minutes(text):
    """Minutes in an ISO-8601 duration of the PT[nH][nM][nS] shape.

    Deliberately strict: an unrecognised duration raises rather than
    returning 0, which would make ``0 < limit`` fail loudly instead of
    silently passing a comparison against a value nobody parsed.
    """
    import re as _re

    m = _re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m or not any(m.groups()):
        raise AssertionError(f"unparseable ISO-8601 duration: {text!r}")
    h, mi, s = (float(g or 0) for g in m.groups())
    return h * 60.0 + mi + s / 60.0


requires_task = pytest.mark.skipif(not _TASK.exists(), reason="task XML not present in this checkout")
requires_runner = pytest.mark.skipif(not _RUNNER.exists(), reason="runner not present in this checkout")


@requires_task
def test_task_xml_is_well_formed_and_shadow_bounded():
    root = ET.parse(_TASK).getroot()
    settings = root.find("t:Settings", _NS)
    assert settings.find("t:MultipleInstancesPolicy", _NS).text == "IgnoreNew"
    assert settings.find("t:StartWhenAvailable", _NS).text == "true"

    # The real invariant is a RELATION, not two magic strings: the execution
    # limit must be bounded and must not exceed the cadence, so a slow pass
    # cannot overlap the next fire (IgnoreNew also guards this).
    #
    # This used to pin ExecutionTimeLimit to a list ending at PT5M and the
    # cadence to exactly PT5M. Both went red on 2026-09-01 when Diego widened
    # the task to PT8M/PT10M for PT-limit headroom under load (hermes
    # 776c3eb3f) — a deliberate, reasoned change that this test reported as a
    # failure for a day. Pinning the relation keeps the guarantee while
    # letting the operator retune the pair.
    limit = _iso_minutes(settings.find("t:ExecutionTimeLimit", _NS).text)
    rep = root.find(".//t:TimeTrigger/t:Repetition", _NS)
    cadence = _iso_minutes(rep.find("t:Interval", _NS).text)
    assert 0 < limit <= cadence, f"limit={limit}m cadence={cadence}m"
    # Bounded above so a wedged pass cannot hold the singleton lock all day.
    assert cadence <= 15.0, cadence

    principal = root.find(".//t:Principals/t:Principal", _NS)
    assert principal.find("t:RunLevel", _NS).text == "LeastPrivilege"

    args = root.find(".//t:Actions/t:Exec/t:Arguments", _NS).text
    assert "claude_fleet_controller_run.ps1" in args


@requires_task
def test_task_never_references_the_legacy_culler():
    text = _TASK.read_text(encoding="utf-8")
    assert "cull-claude-sessions" not in text
    assert "cull-idle-claude-sessions" not in text
    # The task opens gate 2 via the -AllowEnforce SWITCH, never the raw
    # --allow-enforce (that belongs only inside the runner's guarded branch).
    args = ET.parse(_TASK).getroot().find(".//t:Actions/t:Exec/t:Arguments", _NS).text
    assert "--allow-enforce" not in args


@requires_runner
def test_runner_gates_enforce_behind_the_switch():
    """Post-cutover the runner CAN pass --allow-enforce, but only inside the
    -AllowEnforce guard, so an ad-hoc run stays shadow-safe. Pin that
    structure and the absence of the legacy culler."""
    code_lines = [
        ln for ln in _RUNNER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "param([switch]$AllowEnforce)" in code       # declares the switch
    assert "if ($AllowEnforce)" in code                 # the flag is guarded

    # Pin the INVARIANT, not the exact command literal. This previously read
    #     assert "$Py $Script --allow-enforce" in code
    # which pinned incidental spelling: adding `-u` (needed so a killed pass's
    # streamed output is not lost to python's block buffering) broke it on
    # 2026-09-02 while the safety property it guards was untouched. A gate test
    # that goes red on an unrelated correct change gets "fixed" by loosening
    # it, so assert the property instead: --allow-enforce is invoked exactly
    # once, and only inside the -AllowEnforce guard.
    # An INVOCATION, not any mention: the $gate line names the flag in a log
    # string, and counting that as a call site is how this assertion first
    # went wrong.
    _INVOKE = re.compile(r"&\s+\$Py\b.*\$Script")
    lines = code.splitlines()
    enforce_invocations = [
        ln for ln in lines if _INVOKE.search(ln) and "--allow-enforce" in ln
    ]
    assert len(enforce_invocations) == 1, enforce_invocations

    guard_idx = next(i for i, ln in enumerate(lines)
                     if "if ($AllowEnforce)" in ln and _INVOKE.search(ln) is None
                     and ln.lstrip().startswith("if"))
    enforce_idx = next(i for i, ln in enumerate(lines)
                       if _INVOKE.search(ln) and "--allow-enforce" in ln)
    assert enforce_idx > guard_idx, "the enforce branch must sit inside the guard"

    # The shadow default must invoke the SAME script with NO enforce flag.
    shadow = [ln for ln in code.splitlines()
              if re.search(r"&\s+\$Py\b.*\$Script", ln) and "--allow-enforce" not in ln]
    assert shadow, "no shadow-default invocation found"

    assert "cull-claude-sessions" not in code
    assert "cull-idle-claude-sessions" not in code
    assert "run_claude_fleet_controller.py" in code


def test_tracked_config_enforce_is_coherently_pinned():
    import json
    import re

    cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert cfg["mode"] in ("shadow", "enforce")
    if cfg["mode"] == "enforce":
        assert re.fullmatch(r"[0-9a-f]{64}", cfg.get("approved_enforce_digest") or "")
    else:
        assert cfg["approved_enforce_digest"] is None
    # Budget invariant, not a policy value: at most one tree may die per pass.
    assert cfg["max_trees_per_pass"] == 1


def test_approved_digest_actually_matches_the_policy_it_pins():
    """THE invariant the pin exists for, and the one nothing was checking.

    ``fleet_min_roots == 30`` used to be asserted here. That pinned a VALUE,
    which is not what the digest protects, and it went red the moment Diego
    lowered it to 25 on 2026-09-01 — a legitimate change reported as a test
    failure, which trains people to ignore this gate.

    What matters is COHERENCE: enforce mode demands the pin equal the digest
    of the very policy in this file. A field edited without re-approving in
    the same commit leaves a stale pin, and the controller then silently
    demotes to shadow while still emitting healthy-looking ``no_action``
    plans — no error, no log line, nothing to notice. It nearly happened
    twice in the 2026-09-02 d7_max_age edit that added this test: once on the
    d7 change itself, and again because ``policy_version`` is ALSO a digest
    input, so bumping it moved the digest a second time.

    Derive the digest through ``load_policy`` rather than reconstructing a
    FleetPolicy from the raw JSON — the loader coerces each field to its
    dataclass default's type, and ``json.dumps(360) != json.dumps(360.0)``,
    so a hand-rolled reconstruction computes a DIFFERENT digest and reports a
    coherent config as broken.
    """
    from pathlib import Path

    from claude_fleet_control.controller import load_policy

    policy, notes = load_policy(Path(_CONFIG))
    assert policy is not None, f"config did not load: {notes}"
    assert notes == [], notes
    if policy.mode == "enforce":
        assert policy.digest() == policy.approved_enforce_digest, (
            "approved_enforce_digest is stale — a policy field changed without "
            "re-approving it in the same edit. ENFORCE IS SILENTLY OFF. "
            f"expected {policy.digest()}, pinned {policy.approved_enforce_digest}"
        )


def test_d7_freshness_window_outlives_the_producers_reping_interval():
    """P1, 2026-09-02. The freshness window must exceed the interval at which
    the producer re-pings a merely-sustained episode, or a live episode goes
    dark between re-pings and the trigger reads ``stale`` for most of it.

    This is the defect that kept the controller at 295-of-295 ``disarmed``,
    and it is a PRODUCER constraint, not a task-cadence one: no scheduler
    interval beats a 900s emission interval. Pinned as a relation between the
    two modules so lowering either one re-opens the hole loudly.
    """
    import json
    from pathlib import Path

    from claude_fleet_control.controller import load_policy
    from events.producers.resource_monitor import DEFAULT_RE_ALERT_COOLDOWN_SECONDS

    policy, _notes = load_policy(Path(_CONFIG))
    assert policy.d7_max_age_seconds > DEFAULT_RE_ALERT_COOLDOWN_SECONDS, (
        f"d7_max_age_seconds={policy.d7_max_age_seconds} does not outlive the "
        f"producer's {DEFAULT_RE_ALERT_COOLDOWN_SECONDS}s sustained re-ping"
    )
    # And the tracked value is the reviewed one, not merely a passing number.
    cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert cfg["d7_max_age_seconds"] == 1200


def test_commit_arming_bar_sits_above_the_producers_alerting_threshold():
    """P2, 2026-09-02. The commit axis must authorize a KILL strictly deeper
    than the point the producer merely ALERTS at, or the controller acts at
    the cascade's onset instead of inside it — which is the behaviour of the
    retired reaper this axis replaces, at the reaper's own number.

    Pinned as a cross-module relation so raising resource_monitor's alerting
    threshold past the arming bar fails here instead of silently inverting
    the two.
    """
    import json
    from pathlib import Path

    from claude_fleet_control.controller import load_policy
    from events.producers.resource_monitor import DEFAULT_COMMIT_PCT_THRESHOLD

    policy, _notes = load_policy(Path(_CONFIG))
    assert policy.commit_pct_arm is not None, "P2 commit axis is switched off"
    assert policy.commit_pct_arm > DEFAULT_COMMIT_PCT_THRESHOLD, (
        f"commit_pct_arm={policy.commit_pct_arm} is not deeper than the "
        f"producer's {DEFAULT_COMMIT_PCT_THRESHOLD} alerting threshold"
    )
    # Below 100 or the axis can never fire; the reviewed value is 90.
    assert policy.commit_pct_arm < 100.0
    cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
    assert cfg["commit_pct_arm"] == 90


@requires_task
def test_config_and_task_enforce_state_are_consistent():
    """Both gates must agree: config in enforce mode (with a digest) iff the
    task opens gate 2 with -AllowEnforce. A half-applied cutover or half
    rollback (one gate flipped, not the other) fails here. The controller
    stays safe either way (both gates required for any kill), but an
    inconsistent deployment is worth catching."""
    import json

    cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
    config_enforce = cfg["mode"] == "enforce" and bool(cfg.get("approved_enforce_digest"))
    args = ET.parse(_TASK).getroot().find(".//t:Actions/t:Exec/t:Arguments", _NS).text
    task_enforce = "-AllowEnforce" in args
    assert config_enforce == task_enforce, (
        f"gate mismatch: config_enforce={config_enforce} task_enforce={task_enforce}"
    )
