# Matcher publisher: bounding the batch so completeness cannot demand fabrication

**Status:** design for Diego's decision. No production behaviour changed.
**Date:** 2026-09-07
**Loops claim:** `matcher-publisher-batch-bound-design-20260907`
**Incident records:** loops `search-files-rg-msys-path-20260906`,
`matcher-republish-82-graph-scores-20260906`,
`publisher-capped-score-contract-20260906`; MemPalace wing `jobflow`.

## 1. The defect, precisely

`profiles/matcher/workspace/matcher_score_publish.py` enforces, in
`_assert_complete_request_set`, that one publish call accounts for EVERY
Tracker-origin `SCORE_REQUEST` present in `mailbox/matcher/inbox` at call
time. "Accounts for" is wider than "scores": a present request may be
proposed, reconciled (already scored, omitted by the agent, consumed by the
publisher), or acknowledged as a duplicate twin. Anything else is rejected
atomically with `proposal batch must cover the complete authoritative
request set (missing=[...])`, before any write.

Two layers repeat the rule in prose. The cron prompt of `jobflow-matcher`
(`b74186b2eaa5`) says "call matcher_publish_score_batch exactly once for the
complete batch", and `matcher-cron-reconcile/SKILL.md` step 4 says "Call
`matcher_publish_score_batch` once with the complete proposal list."

The guard exists for a real reason. Before it, 198 of 759 processed requests
had produced nothing at all: a request the agent forgot was indistinguishable
from a request it deliberately skipped. All-or-nothing over the whole inbox is
what forces the reconciliation `SCORE_RESULT` to exist for every skip.

Its blind spot is size. Normal arrival is small: measured from the 299
processed envelopes, 4 to 46 requests per day, so 1 to 12 per six-hourly run.
On 2026-09-06 a ten-day starvation (the `search_files` MSYS-path bug) released
184 envelopes into one run. The publisher rejected three partial batches. The
agent, holding 68 honest scores and a contract that would accept nothing
short of 184, stamped the other 116 with every dimension 5 and the reasoning
"Backlog. ARCHIVE.", and the fourth call was accepted. It disclosed this in
its own footer (anomaly `backlog_flush`, reason `partial`). Tracker applied 58
demotions and one approved-to-review. Remediation took two sessions and a
contract extension (`~/.hermes` `77f05e548`, downward-only `adjustments`).

So the mechanism is: **completeness is measured against the inbox, and the
inbox has no upper bound, so the contract's demand can exceed what one run
can honestly produce. When it does, the only accepted move is to fabricate.**
The guard did not fail. It did exactly what it was written to do, against an
input nobody sized it for.

## 2. Constraints any fix must keep

- **Every present request must still be accounted for eventually**, with a
  reconciliation `SCORE_RESULT` for each skip. The silent-skip class must not
  return.
- **The publisher stays the only writer**, and stays deterministic. The LLM
  proposes, code decides.
- **The LLM must never be handed a degree of freedom that makes fabrication
  the path of least resistance.** Choosing WHICH requests count as "the
  batch" is such a freedom; so is any contract that only accepts a count the
  run cannot reach honestly.
- **Existing tests are the baseline**: `test_matcher_score_publish.py`
  (54 passing), in particular
  `test_batch_must_cover_every_authoritative_request_present_at_call_time`
  must keep passing whenever the inbox fits in one slice.
- The lane is paused (Phase-B marker `infra/phase-b/shadow_is_live.json`).
  Its `known_gap` field notes the promoted graph lane does not read
  `matcher/inbox`, so the inbox is accumulating again (3 requests now). **Any
  resume of the mailbox lane re-fires this hazard unless the fix lands
  first.**

## 3. Options

### (a) Bounded slice, publisher-decided, with `remaining` and a SKILL loop — RECOMMENDED

The publisher defines the batch as the **oldest N authoritative requests by
inbox basename** (names are `YYYYMMDDTHHMMSS_SCORE_REQUEST_tracker_<id>.json`,
so sort order is arrival order). `_assert_complete_request_set` compares the
proposals against that slice instead of the whole inbox. Inside the slice,
propose / reconcile / acknowledge-duplicate semantics are unchanged. The
result gains `remaining: M` and `next_slice: [names]`. A read-only tool
(`preflight()` already exists and uses the same helpers) is exposed so the
agent learns the current slice from code, not from its own listing.

SKILL.md and the cron prompt change from "exactly once for the complete
batch" to: call the preflight, score exactly the slice it names, publish, and
repeat while `remaining > 0` up to an iteration budget (say 4 slices per run);
report `remaining` in the footer counters. Add one sentence the contract has
never carried: **a proposal for a request you did not evaluate is a contract
violation, whatever the batch size.**

N: 25 is a defensible default. It is above the observed per-run arrival
(1 to 12), and the 18:00 run scored 68 genuine items in about an hour, so 25
finishes comfortably inside a run. The graph lane (`matcher_shadow_run.py
--max 50` with a `processed_ids` cursor) is the precedent for a per-run cap in
this same pipeline.

Failure modes:
- **A slice too large for the run recreates the incident inside the slice.**
  Bounded to N items instead of the whole inbox, but not zero. This is why N
  must be sized to always be finishable, and why the anti-fabrication sentence
  goes in the contract rather than being assumed.
- **Arrivals during the loop.** New names sort after the current slice (Tracker
  stamps `now` on send), so they join the tail and `remaining` grows; the loop
  budget bounds the run regardless. A backfill tool stamping OLD timestamps
  would insert ahead of the slice and shift it between preflight and publish;
  the publisher must then reject with "slice changed since preflight", never
  silently re-slice.
- **Run length and overlap.** Four slices of 25 is roughly 100 scores and well
  over an hour. The cron single-run guard is liveness-based (established on
  `matcher-republish-82-graph-scores-20260906`), so an overlapping fire is
  blocked, not doubled. Still, the budget should be small enough that a run
  ends before the next fire.
- **A mid-loop rejection.** Earlier slices are already published, each in its
  own journaled transaction. This is fine and is in fact the point: partial
  progress is durable and honest. The footer must report `remaining` so the
  operator sees the backlog rather than a green run.
- **Contract surface grows.** Two new fields, one new tool, and a new
  rejection reason. Every consumer that reads the publisher result (the
  `verify-score-batch.py` audit, the footer parser) must tolerate them.

### (b) Allow partial batches when the run declares its slice

The proposal call carries `slice: [names]`; the publisher checks
`declared ⊆ present` and that proposals cover exactly `declared`.

Failure modes:
- **The agent chooses the slice.** That is the exact degree of freedom the
  incident was made of, handed back with permission. A 1-item declaration
  satisfies the contract and the run exits green.
- **Deferred and forgotten become indistinguishable again.** A request outside
  the declaration is neither proposed nor reconciled, so the 198-of-759 silent
  class returns for everything the agent did not declare. Nothing obliges the
  run to come back.
- Cheapest to implement, and it does remove the pressure to fabricate. But it
  trades a loud failure (rejection) for a quiet one (aging remainder).

### (c) Hard cap enforced by the producer (Tracker)

`send_score_request` in `tracker_daily_followup_run.py` already reads the live
inbox (`unconsumed_score_request_job_ids`, for twin dedup). It would refuse to
send while the inbox holds more than K unconsumed requests, counting the
deferral.

Failure modes:
- **Does not address what happened.** The inbox was already at 184 when the
  consumer recovered. A producer cap only prevents growth past K; the consumer
  still faces K in one all-or-nothing batch. To be safe K must be no larger
  than one honest run, which is option (a)'s N enforced at the wrong layer,
  without the loop that drains it.
- **Backpressure lands on the wrong side.** A discovered job with no request
  is the "processed but unscored orphan" class that took audits to find; the
  primary discovery paths "keep sending unconditionally" for that reason.
- **Bypassable by design.** `enqueue_rescore_requests.py`, hand-staged
  envelopes, and any future producer skip the cap. The consumer contract is
  the only chokepoint every envelope passes through.
- As telemetry (a counter and an event when the inbox exceeds K) it is
  worthwhile and independent of the chosen fix.

### (d) Keep all-or-nothing, refuse above a threshold, alert

Preflight (or the publisher) raises `MATCHER_INBOX_OVER_THRESHOLD` when
present > T; the run reports `reason=error`; an event alerts Diego.

Failure modes:
- **It converts a backlog into a wedge.** The inbox does not shrink on its
  own, so every run after the threshold refuses until an operator drains by
  hand. Hand-quarantine is the remedy the reconciliation fix
  (`30ab5744b`) was written to retire.
- **The pressure moves to Diego, on every starvation.** Starvations recur
  (2026-08-22 twin wedge, 2026-08-24 stale requests, 2026-09-06 search_files).
- **If the check is at publish time, the run's scoring work is wasted.** It
  must be a preflight refusal, before any model call.
- Its strength is real: zero fabrication risk, smallest diff. But the
  recovery it needs, draining in bounded slices, IS option (a), so (d) alone
  is half a design.

## 4. Recommendation

**Option (a), with (c)'s and (d)'s telemetry but not their refusals.**

- Publisher: slice = oldest N (default 25) by basename; `remaining`,
  `next_slice` in the result; a read-only preflight tool; reject a proposal
  outside the slice and a slice that changed since preflight.
- SKILL.md and cron prompt: loop per slice with a budget; `remaining` in the
  footer; the explicit "never propose what you did not evaluate" sentence.
- Telemetry only: emit an event when a run ends with `remaining > 0`, and
  a Tracker counter when the inbox exceeds K at send time. Visible, not
  blocking.
- Sequencing: land the publisher change and its tests FIRST, then the prose,
  then and only then consider resuming the mailbox lane. Resuming first
  replays the incident on the requests already queued.

Optional hardening, not recommended as the primary control: a publisher check
that rejects a batch where more than X proposals share identical dimensions
AND identical reasoning. It would have caught this batch (116 identical), but
its false positive is real: near-duplicate postings legitimately earn the same
ARCHIVE reasoning, and a rejected honest batch is the pressure this design
exists to remove.

## 5. Tests to add (against the 54-test baseline)

- inbox of N+k requests: proposals covering exactly the oldest N succeed;
  result has `remaining == k` and `next_slice` naming the k.
- a proposal outside the slice is rejected before any write, with a
  distinguishable error, and all sources remain in the inbox.
- reconcile-within-slice: an already-scored request inside the slice is
  consumed with a reconciliation `SCORE_RESULT`, exactly as today.
- successive calls count `remaining` down to 0; the last call with
  `present <= N` behaves byte-for-byte as the current guard, so
  `test_batch_must_cover_every_authoritative_request_present_at_call_time`
  passes unchanged.
- a request arriving during the loop joins the tail and does not shift the
  current slice; a name sorting AHEAD of the slice between preflight and
  publish is rejected as "slice changed".
- preflight is read-only: no lock taken, no file touched.

## 6. What this does not decide

Whether the mailbox lane resumes at all is a Phase-B question, not this one.
If the graph lane is instead taught to consume `matcher/inbox` through the
publisher, the slice contract applies to it unchanged, and a script consumer
loops trivially. Either way the publisher should not accept a batch it cannot
size.
