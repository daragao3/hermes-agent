"""Frozen, JSON-serializable records for the P6 fleet controller.

Everything here is immutable data. The planner consumes and produces these;
the controller serializes them into event payloads. No I/O, no clocks.

Payload hygiene contract (plan-approved): event payloads built from these
records carry process IDENTITIES (``pid:create_time``), never full command
lines, transcript contents, or anything credential-shaped. ``ProcessRecord``
itself keeps argv so the planner can classify — it just never leaves the
process through ``to_payload`` methods.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

SCHEMA_VERSION = 1

# The three recognized modes. Anything else behaves as "disabled" — an
# unknown mode must fail toward inaction, not toward a default that acts.
MODE_DISABLED = "disabled"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
VALID_MODES = (MODE_DISABLED, MODE_SHADOW, MODE_ENFORCE)

# The one action this controller can ever project or take. Named for what
# Windows ``taskkill /T /F`` actually is — there is no graceful variant here,
# and calling it "terminate" would understate it.
ACTION_HARD_TERMINATE = "hard_terminate"


def identity_of(pid: int, create_time: float) -> str:
    """Stable process identity: PID alone is recyclable, PID+create_time is not."""
    return f"{pid}:{int(create_time)}"


@dataclass(frozen=True)
class ProcessRecord:
    """One process, as read in a single snapshot pass.

    ``complete`` means every field was read successfully. An incomplete
    member anywhere in a tree protects the WHOLE tree — unknown is protected.
    """

    pid: int
    ppid: Optional[int]
    name: str
    exe: Optional[str]
    cmdline: Tuple[str, ...]
    create_time: float
    rss: int
    username: Optional[str]
    complete: bool

    @property
    def identity(self) -> str:
        return identity_of(self.pid, self.create_time)


@dataclass(frozen=True)
class ProcessSnapshot:
    """A whole-box process census taken at one moment."""

    taken_at: float
    records: Tuple[ProcessRecord, ...]
    complete: bool  # False if the iteration itself failed partway
    # True when a deadline cut the census short. Defaulted so every
    # existing constructor (and every test fake) stays valid.
    truncated: bool = False


# Transcript resolution outcomes. Only "exact" and "fallback" are usable;
# every other resolution protects the tree.
TRANSCRIPT_EXACT = "exact"          # --resume UUID matched an existing file
TRANSCRIPT_FALLBACK = "fallback"    # newest transcript, folder unshared
TRANSCRIPT_AMBIGUOUS = "ambiguous"  # >1 live root maps to the same folder
TRANSCRIPT_MISSING = "missing"      # no cwd / no folder / no transcripts


@dataclass(frozen=True)
class TranscriptEvidence:
    resolution: str
    path: Optional[str]
    mtime: Optional[float]


# Which payload field the spawn_latency verdict was read from. Audit labels,
# not policy: neither value changes what the trigger decides.
AXIS_SOURCE_LATCHED = "axes_latched"   # the producer's own open-episode set
AXIS_SOURCE_REASONS = "reasons"        # pre-2026-09-01 producer, or a replay

# The pressure axes that can arm the trigger. Each is a payload axis label
# from ResourcePressureMonitor; the trigger ORs them.
AXIS_SPAWN_LATENCY = "spawn_latency"
AXIS_COMMIT_HIGH = "commit_high"


@dataclass(frozen=True)
class PressureEvidence:
    """The D7 trigger, validated. ``valid`` is the only field the trigger
    logic consults; the rest is audit detail."""

    valid: bool
    reason_code: str  # ok | missing | stale | future | malformed | disarmed | tied_contradictory | bus_error
    event_id: Optional[str] = None
    event_timestamp: Optional[str] = None
    age_seconds: Optional[float] = None
    sustained_ms: Optional[float] = None
    # Which payload field carried the axis verdict (2026-09-01). AUDIT ONLY —
    # the trigger never reads it. ``axes_latched`` is a superset of
    # ``reasons``: it also holds an axis sitting in its hysteresis band, a
    # weaker signal than an active breach. Stamping the split makes the
    # widening measurable off the CLAUDE_FLEET_PLAN events instead of
    # arguable. ``None`` where no event was evaluated at all (missing /
    # bus_error / a malformed or ill-timed event that never reached the axis
    # test). See planner.evaluate_pressure.
    axis_source: Optional[str] = None
    # WHICH axes justified arming (2026-09-02, P2). Audit only — the trigger
    # reads ``valid``. Empty whenever the pass is not armed. With more than
    # one axis able to arm, "pressure.valid was true" stopped being a
    # self-explaining statement; this says which one spoke.
    armed_axes: Tuple[str, ...] = ()
    commit_pct: Optional[float] = None  # the reading the commit axis judged

    def to_payload(self) -> Dict[str, object]:
        return {
            "valid": self.valid,
            "reason_code": self.reason_code,
            "event_id": self.event_id,
            "event_timestamp": self.event_timestamp,
            "age_seconds": self.age_seconds,
            "sustained_ms": self.sustained_ms,
            "axis_source": self.axis_source,
            "armed_axes": list(self.armed_axes),
            "commit_pct": self.commit_pct,
        }


@dataclass(frozen=True)
class FleetPolicy:
    """The complete, versioned decision policy.

    ``digest()`` covers every parameter EXCEPT ``mode`` and the approval
    field: the digest names WHAT would be enforced, and the enforce config
    pins that exact digest — including mode would make the pin circular.
    """

    mode: str = MODE_DISABLED
    policy_version: str = "p6-unversioned"
    fleet_min_roots: int = 30            # trigger requires root count STRICTLY above this
    # DEPLOYMENT NOTE (2026-09-02): this DEFAULT is deliberately left at the
    # original 360.0 because tests pin it, but it is NOT a safe value to ship.
    # The freshness window must outlive the producer's sustained re-ping
    # interval (resource_monitor.DEFAULT_RE_ALERT_COOLDOWN_SECONDS = 900.0) or
    # a live episode goes dark between re-pings and the trigger reads "stale"
    # through most of it — the defect that held the controller at 295-of-295
    # disarmed. The deployed config.json uses 1200.0; any new config must
    # exceed 900.0 too. Pinned by
    # test_d7_freshness_window_outlives_the_producers_reping_interval.
    d7_max_age_seconds: float = 360.0
    # Commit-charge arming axis (2026-09-02, P2). None = axis OFF, which is
    # the default so nothing inherits a kill trigger it did not ask for; the
    # deployed config opts in at 90.0. ORed with spawn_latency, never ANDed.
    #
    # WHY NOT 85, the number the retired reaper used: 85.0 is
    # resource_monitor's own DEFAULT_COMMIT_PCT_THRESHOLD, i.e. where
    # ALERTING fires and where the historical cascade merely BEGINS. The
    # documented crash-loop band (agent memory
    # gateway_crashloop_commit_exhaustion.md, mempalace_zombie_watchdog_recovery.md)
    # is 89-94%. 90.0 sits inside that band and above the alerting edge, so
    # the controller acts INSIDE the cascade while 85-90 stays alerting's
    # business. It deliberately does NOT align with COMMIT_BANDS' "severe"
    # edge (92.0): 92 would miss the documented 89-91 onset.
    commit_pct_arm: Optional[float] = None
    # Commit-axis fleet-size bypass (2026-09-02, P5). None = OFF, and OFF is
    # the default so nothing inherits a widened kill trigger it did not ask
    # for. When set, and ONLY when the commit axis is among the axes that
    # actually ARMED this pass, the fleet-size floor drops from
    # ``fleet_min_roots`` to this value.
    #
    # WHY: ``triggers_armed`` ANDs the pressure half with the fleet-size half,
    # so before this a box deep in the documented 89-94% crash-loop band got
    # NO relief from the commit axis while its root count sat at or below
    # ``fleet_min_roots``. The original rationale for that AND — "if there are
    # few trees, they are probably not the cause" — is a fair prior at 79%
    # commit and a bad one at 92%, where the box is degrading regardless of
    # which process is to blame and the session trees are the only lever this
    # lane holds.
    #
    # It can only ever LOWER the floor (``min`` is taken), so a value ABOVE
    # ``fleet_min_roots`` is inert rather than a back door for tightening the
    # gate without re-approving a digest that reads like a loosening.
    #
    # NOT zero, deliberately: a floor of 0 authorizes killing the last
    # remaining tree, which on this box is routinely the session doing the
    # diagnosing. The deployed config uses 2, i.e. act from 3 trees up.
    commit_bypass_min_roots: Optional[int] = None
    idle_min_minutes: float = 30.0
    strikes_required: int = 2
    strike_max_age_seconds: float = 900.0  # a strike older than this is not "the previous pass"
    max_trees_per_pass: int = 1
    max_tree_processes: int = 24
    max_tree_rss_bytes: int = 2 * 1024 ** 3
    cooldown_seconds: float = 1800.0
    approved_enforce_digest: Optional[str] = None

    def digest(self) -> str:
        canonical = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "policy_version": self.policy_version,
                "fleet_min_roots": self.fleet_min_roots,
                "d7_max_age_seconds": self.d7_max_age_seconds,
                "commit_pct_arm": self.commit_pct_arm,
                "commit_bypass_min_roots": self.commit_bypass_min_roots,
                "idle_min_minutes": self.idle_min_minutes,
                "strikes_required": self.strikes_required,
                "strike_max_age_seconds": self.strike_max_age_seconds,
                "max_trees_per_pass": self.max_trees_per_pass,
                "max_tree_processes": self.max_tree_processes,
                "max_tree_rss_bytes": self.max_tree_rss_bytes,
                "cooldown_seconds": self.cooldown_seconds,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Tree/pass rejection reason codes — stable strings, asserted by tests.
REASON_CENSUS_TRUNCATED = "census_truncated"
REASON_INCOMPLETE_MEMBER = "incomplete_member"
REASON_INFRA_MEMBER = "infra_member"
REASON_ACTOR_MEMBER = "actor_member"
REASON_CROSS_USER_MEMBER = "cross_user_member"
REASON_DESKTOP_MEMBER = "desktop_member"
REASON_TRANSCRIPT_MISSING = "transcript_missing"
REASON_TRANSCRIPT_AMBIGUOUS = "transcript_ambiguous"
REASON_TRANSCRIPT_FUTURE = "transcript_future_mtime"
REASON_TRANSCRIPT_ACTIVE = "transcript_active"
REASON_OVERSIZE_PROCESSES = "oversize_processes"
REASON_OVERSIZE_RSS = "oversize_rss"
REASON_FIRST_STRIKE = "first_strike"
REASON_COOLDOWN_ACTIVE = "cooldown_active"
REASON_TRIGGERS_DISARMED = "triggers_disarmed"
REASON_FLEET_BELOW_MIN = "fleet_at_or_below_min"
REASON_STATE_CORRUPT = "state_corrupt"


@dataclass(frozen=True)
class TreeAssessment:
    """One whole session tree, classified. Never a partial tree."""

    root: ProcessRecord
    members: Tuple[ProcessRecord, ...]  # includes root
    total_rss: int
    transcript: TranscriptEvidence
    idle_minutes: Optional[float]
    protected: bool
    reasons: Tuple[str, ...]
    eligible: bool  # passes everything EXCEPT the strike count
    strike_key: Optional[str]


@dataclass(frozen=True)
class TargetSummary:
    """The bounded, payload-safe description of a selected tree."""

    root_identity: str
    root_pid: int
    root_create_time: float
    member_identities: Tuple[str, ...]
    member_count: int
    total_rss: int
    transcript_path: str
    transcript_mtime: float
    idle_minutes: float
    strike_key: str
    strikes: int
    action: str = ACTION_HARD_TERMINATE

    def to_payload(self) -> Dict[str, object]:
        return {
            "root_identity": self.root_identity,
            "root_pid": self.root_pid,
            "root_create_time": self.root_create_time,
            "member_identities": list(self.member_identities),
            "member_count": self.member_count,
            "total_rss": self.total_rss,
            "transcript_path": self.transcript_path,
            "transcript_mtime": self.transcript_mtime,
            "idle_minutes": round(self.idle_minutes, 1),
            "strike_key": self.strike_key,
            "strikes": self.strikes,
            "action": self.action,
        }


# Plan decisions.
DECISION_NO_ACTION = "no_action"
DECISION_SHADOW_PROJECTED = "shadow_projected"
DECISION_ENFORCE_PROJECTED = "enforce_projected"

# Result states.
RESULT_NO_ACTION = "no_action"
RESULT_SHADOW_PROJECTED = "shadow_projected"
RESULT_CANCELLED = "cancelled"
RESULT_HARD_TERMINATED = "hard_terminated"
RESULT_FAILED = "failed"


@dataclass(frozen=True)
class FleetPlan:
    schema_version: int
    policy_version: str
    policy_digest: str
    run_id: str
    mode: str
    decision: str
    triggers_armed: bool
    trigger_reasons: Tuple[str, ...]
    fleet_root_count: int
    pressure: PressureEvidence
    selected: Optional[TargetSummary]
    rejections: Tuple[Tuple[str, int], ...]  # (reason_code, count), sorted
    digest: str  # deterministic digest over policy + evidence + identities
    new_strikes: Mapping[str, Dict[str, float]] = field(default_factory=dict)
    # The fleet-size floor this pass actually compared ``fleet_root_count``
    # against (2026-09-02, P5). Normally ``policy.fleet_min_roots``; lower
    # when the commit-axis bypass applied. Recorded because "why did this arm
    # at 4 roots?" has to be answerable from the plan event ALONE, without
    # also having to know which config was live at the time — configs here
    # change under Diego's hand between passes.
    fleet_floor_applied: Optional[int] = None

    @property
    def plan_id(self) -> str:
        return self.digest[:16]

    def to_payload(self) -> Dict[str, object]:
        """The bounded audit payload. No cmdlines, no transcript contents."""
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "mode": self.mode,
            "decision": self.decision,
            "triggers_armed": self.triggers_armed,
            "trigger_reasons": list(self.trigger_reasons),
            "fleet_root_count": self.fleet_root_count,
            "fleet_floor_applied": self.fleet_floor_applied,
            "pressure": self.pressure.to_payload(),
            "selected": self.selected.to_payload() if self.selected else None,
            "rejections": {code: count for code, count in self.rejections},
            "plan_digest": self.digest,
        }


@dataclass(frozen=True)
class FleetResult:
    run_id: str
    plan_id: str
    status: str  # RESULT_* above; "failed" is the value evaluate_outcome promotes
    executor_called: bool
    detail: str = ""
    exited_identities: Tuple[str, ...] = ()
    surviving_identities: Tuple[str, ...] = ()

    def to_payload(self) -> Dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            # Key name is load-bearing: events.outcomes scans "status", so
            # status=="failed" reaches a FAILED verdict and routing promotes
            # it TRACE->WARN with zero fleet-specific hook code.
            "status": self.status,
            "executor_called": self.executor_called,
            "detail": self.detail,
            "exited_identities": list(self.exited_identities),
            "surviving_identities": list(self.surviving_identities),
        }
