"""DDP control-plane CLI — for scripts/producers that cannot import the
package in-process, and for operator/script-slot ticks.

    <request-json> | python -m devflow_delegation.cli delegate [--dry-run]
    python -m devflow_delegation.cli status
    python -m devflow_delegation.cli reconcile
    python -m devflow_delegation.cli triage [--limit N]
    python -m devflow_delegation.cli executor --synthetic-only
    python -m devflow_delegation.cli executor-shadow [--request-id RID] [--actor NAME]
    python -m devflow_delegation.cli executor-canary --i-understand-this-opens-a-real-pr \
        --request-id RID [--actor NAME]
    python -m devflow_delegation.cli gate --request-id RID --action {merge,deploy} \
        --changed-path PATH [--changed-path PATH ...] --changed-lines N \
        (--reversible | --not-reversible)
    python -m devflow_delegation.cli adopt-history [--dry-run] [--actor NAME]
    python -m devflow_delegation.cli transition --request-id RID --to STATE --actor NAME

The executor command requires ``--synthetic-only`` and runs a shadow tick
(no push, no PR, no remote side effect) against allowlist-configured targets.

executor-shadow runs the same shadow tick directly and is safe to schedule:
it never constructs a PR client and can never open a PR or push.

executor-canary is a one-off, explicitly-authorized command that opens ONE
real GitHub PR. It refuses (exit 2) unless both
``--i-understand-this-opens-a-real-pr`` and ``--request-id`` are supplied,
and only then constructs a real PR client. The designated request must be
PLANNED, or VALIDATED with a ``shadow`` artifact and no ``pr``/``pr_attempt``
artifact (a bounded resume of a request already shadow-verified by an
earlier executor-shadow tick, that has not already had a PR attempted) --
any other state, a VALIDATED request without a ``shadow`` artifact, or a
VALIDATED request that already carries ``pr``/``pr_attempt`` evidence,
refuses before the tick and before any PR client is constructed.

executor-canary additionally REFUSES (exit 30) when it is typed from what
looks like an agent session, before anything is parsed or opened. It is the
only command here that acts outside this machine, and the machine-wide git
guard cannot see a subprocess publish. Override with
``HERMES_ALLOW_AGENT_CANARY_PR=1``; ``executor-shadow`` is never gated and
does all the same work up to VALIDATED. See AGENT CANARY GATE below.
"""
from __future__ import annotations

import argparse
import json
import sys

from devflow_delegation.emitter import DelegationEmitter
from devflow_delegation.lifecycle import IllegalTransitionError, transition


def _cmd_delegate(args) -> int:
    try:
        kwargs = json.loads(sys.stdin.read())
    except ValueError as exc:
        print(f"ERROR: stdin is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(kwargs, dict):
        print("ERROR: stdin JSON must be an object of delegate() kwargs", file=sys.stderr)
        return 2
    if args.dry_run:
        kwargs["mode"] = "dry_run"
    try:
        result = DelegationEmitter().delegate(**kwargs)
    except TypeError as exc:
        print(f"ERROR: bad delegate kwargs: {exc}", file=sys.stderr)
        return 2
    print(f"status={result.status} request_id={result.request_id} "
          f"fingerprint={result.fingerprint} reason={result.reason}")
    return 0


def _cmd_status(args) -> int:
    em = DelegationEmitter()
    counts = em.ledger.summary_counts()
    print(f"total={counts['total']} by_state={json.dumps(counts['by_state'])} "
          f"by_source={json.dumps(counts['by_source'])}")
    oldest = em.ledger.oldest_requested()
    if oldest:
        print(f"oldest_requested={oldest['created_at']} request_id={oldest['request_id']}")
    return 0


def _cmd_reconcile(args) -> int:
    counts = DelegationEmitter().reconcile()
    print(f"adopted={counts['adopted']} rewritten={counts['rewritten']}")
    return 0


def _cmd_triage(args) -> int:
    from devflow_delegation.triage import run_triage

    em = DelegationEmitter()
    counts = run_triage(em.ledger, em.bus, actor=args.actor, limit=args.limit)
    print(f"considered={counts['considered']} triaged={counts['triaged']} "
          f"errors={counts['errors']}")
    return 0 if counts["errors"] == 0 else 1


def _cmd_executor(args) -> int:
    # There is deliberately no real PR client construction in this command.
    # This runs a real shadow tick (lease, BUILDING, worktree, implementation
    # command, ledger writes) but never pushes or opens a PR: pr_client is
    # always None and mode is always "shadow".
    if not args.synthetic_only:
        print("ERROR: --synthetic-only is required; no live executor CLI exists", file=sys.stderr)
        return 2
    from devflow_delegation.executor import run_executor_tick

    em = DelegationEmitter()
    counts = run_executor_tick(
        em.ledger, em.allowlist, em.bus, actor=args.actor, pr_client=None, mode="shadow",
        synthetic_only=True,
    )
    print(f"processed={counts['processed']} errors={counts['errors']} skipped={counts['skipped']} mode=shadow pr_client=none")
    return 0 if counts["errors"] == 0 else 1


def _cmd_executor_shadow(args) -> int:
    """Run a shadow executor tick — no push, no PR, no remote side effect."""
    from devflow_delegation.executor import run_executor_tick

    em = DelegationEmitter()
    counts = run_executor_tick(
        em.ledger, em.allowlist, em.bus, actor=args.actor,
        pr_client=None, mode="shadow", request_id=args.request_id or None,
    )
    print(f"processed={counts['processed']} errors={counts['errors']} skipped={counts['skipped']} mode=shadow")
    return 0 if counts["errors"] == 0 else 1


def _cmd_executor_canary(args) -> int:
    """Open ONE real PR for a designated request. Requires explicit understanding."""
    if not args.i_understand_this_opens_a_real_pr:
        print("ERROR: --i-understand-this-opens-a-real-pr is required to open a real PR", file=sys.stderr)
        return 2
    if not args.request_id:
        print("ERROR: --request-id is required for a canary run", file=sys.stderr)
        return 2

    em = DelegationEmitter()

    # A silent processed=0 is indistinguishable from "no eligible target" and
    # is a real operator footgun right when a canary is being run -- most
    # commonly because a prior shadow tick already advanced the SAME request
    # to VALIDATED, or a prior canary attempt already touched it. Fail
    # loudly, before the tick (and before GhPrClient is ever imported or
    # constructed), naming the actual state.
    #
    # run_executor_tick supports a bounded canary resume: a designated
    # request in VALIDATED that carries a `shadow` artifact and NO
    # `pr`/`pr_attempt` artifact (durable proof this executor already
    # shadow-verified it, and that a PR was never already attempted for it)
    # is a legitimate target here, not an error. `canary_resume_reason` is
    # the single source of truth for this rule -- shared with
    # executor._canary_resumable_rows so the CLI guard and the tick's own
    # selection logic cannot drift. Importing it does not import or
    # construct GhPrClient; that stays deferred below, after this guard.
    from devflow_delegation.executor import canary_resume_reason

    designated = em.ledger.get_request(args.request_id)
    if designated is None:
        print(f"ERROR: unknown request: {args.request_id}", file=sys.stderr)
        return 2
    if designated["state"] == "VALIDATED":
        reason = canary_resume_reason(em.ledger, args.request_id)
        if reason == "has-pr-attempt":
            print(
                f"ERROR: request {args.request_id} is VALIDATED but already carries a "
                "pr/pr_attempt artifact (a PR was already attempted for it); it cannot be "
                "resumed -- resuming would risk opening a second, duplicate PR for the same "
                "request",
                file=sys.stderr,
            )
            return 2
        if reason == "no-shadow":
            print(
                f"ERROR: request {args.request_id} is VALIDATED but was not shadow-verified "
                "(no shadow artifact); it cannot be resumed. Run executor-shadow for it first, "
                "or use a PLANNED request",
                file=sys.stderr,
            )
            return 2
        # reason == "ok": a legitimate bounded resume candidate; fall through.
    elif designated["state"] != "PLANNED":
        print(
            f"ERROR: request {args.request_id} is in state {designated['state']}, not PLANNED; "
            "canary requires a PLANNED request, or a VALIDATED request that was shadow-verified "
            "and has no PR attempted yet (a prior shadow tick advances a request to VALIDATED "
            "and records a shadow artifact, which canary can then resume)",
            file=sys.stderr,
        )
        return 2

    from devflow_delegation.executor import GhPrClient, run_executor_tick

    counts = run_executor_tick(
        em.ledger, em.allowlist, em.bus, actor=args.actor,
        pr_client=GhPrClient(), mode="canary", request_id=args.request_id,
    )
    pr = next((a["ref"] for a in em.ledger.artifacts_for(args.request_id) if a["kind"] == "pr"), "")
    print(f"processed={counts['processed']} errors={counts['errors']} skipped={counts['skipped']} mode=canary pr={pr}")
    return 0 if counts["errors"] == 0 else 1


def _cmd_gate(args) -> int:
    """Record a deterministic Stage-3 gate decision without acting on it."""
    if not args.request_id:
        print("ERROR: --request-id is required", file=sys.stderr)
        return 2
    if args.action not in {"merge", "deploy"}:
        print("ERROR: --action must be merge or deploy", file=sys.stderr)
        return 2
    if not args.changed_path:
        print("ERROR: --changed-path is required", file=sys.stderr)
        return 2
    if args.changed_lines is None:
        print("ERROR: --changed-lines is required", file=sys.stderr)
        return 2
    if args.reversible is None:
        print("ERROR: one of --reversible or --not-reversible is required", file=sys.stderr)
        return 2

    from events.paths import autonomy_sentinel_path

    from devflow_delegation.allowlist import resolve_target
    from devflow_delegation.gate import GateRequest, evaluate_gate, record_shadow_decision
    from devflow_delegation.risk import RiskInput

    em = DelegationEmitter()
    row = em.ledger.get_request(args.request_id)
    if row is None:
        print(f"ERROR: unknown request: {args.request_id}", file=sys.stderr)
        return 2
    target = resolve_target(em.allowlist, row["target_repo"])
    if target is None:
        print(f"ERROR: target unresolved: {row['target_repo']}", file=sys.stderr)
        return 2

    decision = evaluate_gate(
        target,
        GateRequest(
            request_id=row["request_id"],
            action=args.action,
            risk_input=RiskInput(
                changed_paths=tuple(args.changed_path),
                changed_lines=args.changed_lines,
                reversible=args.reversible,
                severity=row["severity"],
                source_kind=row["source_kind"],
            ),
        ),
        sentinel_path=autonomy_sentinel_path(),
    )
    artifact = record_shadow_decision(em.ledger, decision)
    print(
        f"request_id={decision.request_id} action={decision.action} mode={decision.mode} "
        f"eligible={decision.eligible} authorized={decision.authorized} "
        f"risk={decision.risk.tier}/{decision.risk.score} reason={decision.reason} "
        f"artifact={artifact['ref']}"
    )
    return 0


def _cmd_transition(args) -> int:
    em = DelegationEmitter()
    try:
        row = em.ledger.get_request(args.request_id)
        if (
            row is not None
            and row["state"] == "TRIAGED"
            and args.to in {"PLANNED", "DECLINED"}
        ):
            command = "/ddp-approve" if args.to == "PLANNED" else "/ddp-decline"
            raise IllegalTransitionError(
                f"TRIAGED -> {args.to} is a human decision; use authenticated "
                f"{command} with its confirmation command instead"
            )
        expected_from_state = row["state"] if row is not None else None
        new_state = transition(
            em.ledger, em.bus, args.request_id, args.to,
            actor=args.actor, evidence_ref=args.evidence_ref,
            expected_from_state=expected_from_state)
    except IllegalTransitionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"request_id={args.request_id} state={new_state}")
    return 0


def _cmd_adopt_history(args) -> int:
    from devflow_delegation.adopt_history import (
        adopt, dry_run, gather_approved_keys, gather_fix_requests,
    )

    approved_keys = gather_approved_keys()
    fixes = gather_fix_requests()
    matched, unmatched, _ = dry_run(approved_keys, fixes)
    print(f"approved_keys={len(approved_keys)} fixes={len(fixes)} "
          f"matched={matched} unmatched={unmatched}")
    if args.dry_run:
        print("[dry-run] No writes performed.")
        return 0
    if matched == 0:
        print("Nothing to adopt (0 matched).")
        return 0
    ledger = DelegationEmitter().ledger
    try:
        result = adopt(approved_keys, fixes, ledger, actor=args.actor)
    finally:
        ledger.close()
    print(f"adopted={result['adopted']} triaged={result['triaged']} "
          f"skipped={result['skipped_already_triaged']} errors={result['errors']}")
    return 0 if result["errors"] == 0 else 1


# -- AGENT CANARY GATE ------------------------------------------------------
#
# ``executor-canary`` is the ONE command in this package that performs a real
# git publish (executor.py ``_stage_commit_push``) and opens a real GitHub PR.
# Both calls are ``subprocess``/``gh`` invocations made INSIDE this package, so
# they carry no git verb in the ARGV of anything an agent runs. The
# machine-wide guard at ``~/.claude/hooks/block-destructive-git.py`` reads that
# ARGV and therefore never sees them: no block, no pending id, no grant. A
# content scan of launched scripts was measured over 436 of them on 2026-09-09
# and rejected -- it fired on prose while missing the real callers, this one
# included. Record: loops ``gitguard-script-file-argument-gap-20260909``.
#
# WHY THE GATE IS HERE AND NOT AT THE PUBLISH. Placement was decided by
# measurement, not taste. ``tests/devflow_delegation/test_executor.py`` calls
# ``run_executor_tick(mode="canary")`` ~20 times and
# ``tests/devflow_delegation/test_cli.py`` drives ``cli.main(["executor-canary",
# ...])`` end-to-end twice, both against a real temp git repo with a real local
# bare remote -- so they DO reach ``_stage_commit_push`` and DO publish there.
# The suite itself runs inside an agent session. A gate reading ambient
# environment in ``_stage_commit_push``, ``run_executor_tick`` or ``main()``
# would fail every one of those. That is not hypothetical: the same mistake in
# the sibling ``hermes update`` gate turned 7 failures into 41 before it was
# moved to the dispatch seam.
#
# So the seam is the TYPED-COMMAND boundary -- the ``__main__`` block below,
# which ``python -m devflow_delegation.cli ...`` reaches and an in-process
# ``cli.main([...])`` does not. The accident worth preventing is an agent
# TYPING the command; a programmatic caller injecting a fake PR client is
# already doing something deliberate. Nothing has been parsed, opened or
# mutated when this runs, so a refusal is inert by construction -- and a gate
# that is somehow missed still dies at the allowlist's own three disabled
# flags rather than publishing quietly.
#
# NOT AN AUTHORIZATION BOUNDARY, and it cannot be one: anything that can run
# the command can set the override. Like the hook it complements, it stops an
# ACCIDENT. Codex sessions are NOT detected -- their environment has never been
# measured on this box, and a guessed marker that never fires is worse than a
# documented gap.
#
# The detector is IMPORTED from ``hermes_cli._agent_session`` rather than
# copied. ``scripts/release.py`` carries the one deliberate duplicate (it runs
# standalone and cannot import the package); this module is already inside the
# tree, so a third copy would only be a third thing to drift. The exit code is
# shared for the same reason: one number means one thing across the family
# (``hermes update``, ``scripts/release.py``, jobflow-platform's
# ``scripts/ops/refresh-ci-snapshot.ps1``, and this).

#: Set to any non-empty value to run the canary anyway. Deliberately DISTINCT
#: from the ``hermes update`` override: authorizing a self-update must never
#: also authorize publishing a branch and opening a PR on someone's repo.
CANARY_OVERRIDE_ENV = "HERMES_ALLOW_AGENT_CANARY_PR"

#: The subcommand this gate guards. Every other subcommand in this CLI is
#: local-only (``executor-shadow`` in particular is documented as unable to
#: publish or open a PR), so gating them would be pure friction.
_GATED_SUBCOMMAND = "executor-canary"


def _subcommand_of(argv) -> str:
    """The subcommand in ``argv``, or "" when there is none.

    The first token that is not an option IS the subcommand for this parser:
    it defines no top-level flags of its own beyond ``-h``, so argparse
    requires the subcommand first in every argv it accepts. A token that only
    LOOKS like a subcommand because it is some other flag's value therefore
    cannot be reached before a real one, and an argv where it could be is one
    argparse would reject anyway.
    """
    for token in argv or ():
        if not str(token).startswith("-"):
            return str(token)
    return ""


def canary_refusal_lines(evidence) -> list:
    """The refusal, as lines. Separated from printing so tests can read it."""
    lines = [
        "",
        "=" * 72,
        "  REFUSED: 'executor-canary' from what looks like an agent session",
        "=" * 72,
        "",
    ]
    lines += ["  * %s" % item for item in evidence]
    lines += [
        "",
        "Nothing has been read, leased, built, committed, published or opened.",
        "",
        "WHY. This is the only command here that acts outside this machine: it",
        "publishes a branch to the allowlist target's own remote from a fresh",
        "worktree, then opens a real GitHub PR. Both run as subprocesses inside this",
        "package, so the machine-wide git guard never sees them -- there is no block,",
        "no pending id and no grant to mint.",
        "",
        "DO THIS INSTEAD:",
        "",
        "  1. Everything except the publish and the PR, which is NOT gated:",
        "         python -m devflow_delegation.cli executor-shadow --request-id <RID>",
        "     It builds the worktree, runs the implementation command and fully",
        "     validates -- it just stops at VALIDATED and records a shadow artifact.",
        "     A canary can then RESUME that same request, so this is not wasted work.",
        "",
        "  2. Leave the canary to Diego, who can see which repo is about to receive a",
        "     branch and a PR.",
        "",
        "OVERRIDE. If Diego has authorized THIS canary:  %s=1 ..." % CANARY_OVERRIDE_ENV,
        "  It is not a way around the grant -- it is the operator standing in for one.",
        "",
        "READ THIS EVEN IF YOU ARE A HUMAN WHO HIT THIS BY ACCIDENT.",
        "The target is the allowlist entry's own 'remote', which is whatever that",
        "checkout's git config says -- NOT necessarily a repo you own. Check before",
        "overriding:",
        "",
        "    git -C <target.checkout_path> remote -v",
        "",
    ]
    return lines


def enforce_canary_agent_gate(argv, *, environ=None, cwd=None, printer=print) -> None:
    """Refuse ``executor-canary`` from an agent session.

    Returns normally when the command may proceed; raises ``SystemExit`` with
    the family's shared exit code otherwise. Both ``environ`` and ``cwd`` are
    parameters rather than reads of the ambient process so the tests can drive
    every branch -- including the NEGATIVE case, which cannot otherwise be
    expressed from inside an agent session.
    """
    import os

    from hermes_cli._agent_session import (
        EXIT_REFUSED_AGENT_ACTION,
        agent_session_evidence,
    )

    if _subcommand_of(argv) != _GATED_SUBCOMMAND:
        return
    env = os.environ if environ is None else environ
    if str(env.get(CANARY_OVERRIDE_ENV, "") or "").strip():
        return
    evidence = agent_session_evidence(environ=env, cwd=cwd)
    if not evidence:
        return
    for line in canary_refusal_lines(evidence):
        printer(line)
    raise SystemExit(EXIT_REFUSED_AGENT_ACTION)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devflow_delegation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_delegate = sub.add_parser("delegate", help="queue a work request (JSON kwargs on stdin)")
    p_delegate.add_argument("--dry-run", action="store_true",
                            help="classify only; no ledger/mailbox/event side effects")
    p_delegate.set_defaults(func=_cmd_delegate)

    p_status = sub.add_parser("status", help="queue depth by state/source")
    p_status.set_defaults(func=_cmd_status)

    p_reconcile = sub.add_parser("reconcile", help="idempotent ledger<->mailbox reconciliation")
    p_reconcile.set_defaults(func=_cmd_reconcile)

    p_triage = sub.add_parser("triage", help="advance REQUESTED work to the TRIAGED approval gate")
    p_triage.add_argument("--limit", type=int, default=50,
                          help="maximum REQUESTED rows to process (default: 50)")
    p_triage.add_argument("--actor", default="ddp.triage")
    p_triage.set_defaults(func=_cmd_triage)

    p_executor = sub.add_parser("executor", help="run a shadow executor tick without PR authority")
    p_executor.add_argument("--synthetic-only", action="store_true",
                            help="required safety gate; never constructs a real PR client")
    p_executor.add_argument("--actor", default="ddp.executor.cli")
    p_executor.set_defaults(func=_cmd_executor)

    p_shadow = sub.add_parser("executor-shadow", help="run a shadow executor tick (no push, no PR)")
    p_shadow.add_argument("--request-id", default=None, help="restrict to one designated request")
    p_shadow.add_argument("--actor", default="ddp.executor.shadow")
    p_shadow.set_defaults(func=_cmd_executor_shadow)

    p_canary = sub.add_parser("executor-canary", help="open ONE real canary PR for a designated request")
    p_canary.add_argument(
        "--i-understand-this-opens-a-real-pr", dest="i_understand_this_opens_a_real_pr",
        action="store_true", help="required acknowledgement that this opens a real PR",
    )
    p_canary.add_argument("--request-id", default=None, help="the designated request_id to build")
    p_canary.add_argument("--actor", default="ddp.executor.canary")
    p_canary.set_defaults(func=_cmd_executor_canary)

    p_gate = sub.add_parser("gate", help="record a shadow-only merge/deploy gate decision")
    p_gate.add_argument("--request-id", required=True)
    p_gate.add_argument("--action", choices=("merge", "deploy"), required=True)
    p_gate.add_argument("--changed-path", action="append", default=[],
                        help="observed changed path; repeat for each path")
    p_gate.add_argument("--changed-lines", type=int, default=None,
                        help="observed total added plus removed lines")
    reversibility = p_gate.add_mutually_exclusive_group()
    reversibility.add_argument("--reversible", action="store_const", const=True, dest="reversible")
    reversibility.add_argument("--not-reversible", action="store_const", const=False, dest="reversible")
    p_gate.set_defaults(func=_cmd_gate, reversible=None)

    p_transition = sub.add_parser("transition", help="apply a legal lifecycle transition")
    p_transition.add_argument("--request-id", required=True)
    p_transition.add_argument("--to", required=True)
    p_transition.add_argument("--actor", required=True)
    p_transition.add_argument("--evidence-ref", default=None)
    p_transition.set_defaults(func=_cmd_transition)

    p_adopt = sub.add_parser("adopt-history",
                              help="adopt historically-approved v2 fix-requests into the v3 ledger at TRIAGED")
    p_adopt.add_argument("--dry-run", action="store_true",
                          help="report what would happen without writing")
    p_adopt.add_argument("--actor", default="ddp.historical-adoption")
    p_adopt.set_defaults(func=_cmd_adopt_history)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except IllegalTransitionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - last-resort guard
        print(f"ERROR: unexpected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Gate FIRST -- before argparse, before any import of the executor,
    # before the ledger is opened. See AGENT CANARY GATE above.
    enforce_canary_agent_gate(sys.argv[1:])
    raise SystemExit(main())
