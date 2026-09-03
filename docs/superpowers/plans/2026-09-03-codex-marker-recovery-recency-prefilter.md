# Codex Marker Recovery — Recency Prefilter Plan

> ## ⛔ CLOSED — DO NOT IMPLEMENT
>
> **Decision: Diego answered NO to the §2 decision gate on 2026-09-03.** The recency
> prefilter is **not** being built. Do not start at Task 1; do not "just try" §3–§4.
>
> This document is kept for its DIAGNOSIS (§1) and its ruled-out list, so the next
> person to hit a slow marker lookup does not re-derive any of it. The tasks in §4 are
> a record of what was designed and declined, not a backlog.
>
> **To reopen** you would need the §2 answer to change, and the trigger for that is
> stated in §2: `blocked` rising above 0, or the sidebar lane coming out of retirement
> (`enabled: false` / `lane_state: retired` as of 2026-09-03). Re-measure before
> reopening — every number here is dated and the corpus grows ~250 threads/day.

**Goal:** Cut the cost of `find_by_marker_including_archived` from a full-corpus
`thread/search` (~13–23s today, growing linearly with the thread corpus) to a bounded
`thread/list` head read (~0.5s) in the common case.

**Status:** **CLOSED 2026-09-03 — DECLINED.** Diagnosis complete and measured; the design
carried a semantic tradeoff (§2) that Diego declined to accept. The slow-but-sound path
stays. No code was written.

**Baseline:** `tests/session_bridge/` — 3783 passed, 11 skipped, 5 xfailed, 0 failed
(measured 2026-09-02 on `8ab19a1313`, ~22.5 min, ConPTY tests included). Every task
below must keep that green.

---

## 1. Why this exists (measured, not assumed)

`thread/search` has three cost regimes. Measured 2026-09-03, codex-cli 0.152.0,
corpus active=5031 / archived=104, interleaved with a discarded warmup round:

| regime | condition | cost |
|---|---|---|
| fast negative | term's tokens absent from index | ~1.6–2.2s |
| early exit | `true_matches > limit` → page overflows, cursor returned | ~1.4–2.6s |
| **full scan** | `true_matches <= limit` → must scan corpus to prove no more exist | **~12–23s** |

The discriminator is page overflow, not term length and not hit count:

```
"HERMES_SESSION_BRIDGE_V1"   len= 24   25 hits  cursor=yes    1.38 / 1.47 / 1.47 s
full marker prefix           len=295    2 hits  cursor=no    12.33 / 14.33 / 14.36 s
half prefix                  len=147    2 hits  cursor=no    11.22 / 12.50 / 13.58 s
"SECURITY.md"                len= 11   25 hits  cursor=yes    1.64 / 1.92 / 2.58 s
```

Scan cost is linear in corpus size — identical term, identical regime, only the corpus
differs: active (5031) 18.6–22.8s vs archived (104) 0.48–0.61s.

**A marker prefix is designed to identify exactly one thread, so it can never overflow
the page.** `find_by_marker_including_archived` therefore pays a full active-corpus scan
on every call, forever, and the cost grows ~linearly at ~250 threads/day. Raising
`_SIDEBAR_READ_REQUEST_TIMEOUT` is a treadmill — a 121.8s lookup already failed against
the current 120.0 ceiling.

**Already ruled out — do not re-derive:**

- `limit=1` (retracted after measurement). Truthful cursor, but no end-to-end saving:
  a one-match term still costs 16–18s, and the two-match case merely defers the scan to
  page 2 (2.28s + 18.61s = 20.89s vs 21.56s unlimited).
- `sortKey` / shorter search terms — measured, no effect on this regime.
- Raising the ceiling — treadmill, see above.
- A data-side cleanup of duplicate markers — no job is blocked on markers
  (`blocked: 0`, zero jobs carry a marker `error_code`).
- Making the binding durable — it already is (`session_sidebar_jobs`, UNIQUE on both
  `bridge_id` and `codex_thread_id`; 71 reconciliation proofs stored).

Full records: loops `codex-thread-search-latency-20260903`,
`codex-marker-conflict-mechanism-20260903`.

---

## 2. DECISION GATE — the semantic tradeoff (Diego must answer)

The prefilter is **not** a free win, and an earlier framing of mine that called it
"a prefilter, not a weakening" was wrong in one specific respect. Correcting it here:

Per-thread admission is unchanged — `_verified_sidebar_projection` still gates every
candidate, so the prefilter cannot admit a thread the current path would reject.
**But the aggregate conflict check changes.** Today `reconcile_marker` collects matches
across the *whole* corpus and raises `marker_conflict` when `len(matches) > 1`
(`codex_adapter.py:510`). A prefilter that returns on the first match found in a
recency window will not see a second matching thread *outside* that window, and would
return RECOVERED where today it returns BLOCKED.

That case is real, not theoretical: two threads carrying the same valid signed marker
were confirmed on 2026-09-03 (`01a04e30…` at msg[0] and `01a05842…` at msg[1335]).

There is **no sound fast path that preserves current semantics.** Proving "exactly one
thread carries this marker" is inherently a whole-corpus question. A prefilter that
short-circuits only when it finds ≥2 matches is sound but saves nothing in the common
case; a prefilter that short-circuits on 1 match is fast but weakens the check.

**The question:** for the post-create ambiguity window, is
"first verified match within the N most recently updated threads wins" acceptable, given
that duplicate deliveries arise from re-delivery and therefore cluster in time?

### ✅ ANSWERED 2026-09-03: **NO.** Plan closed, nothing implemented.

Diego declined. Rationale on the record: the measured cost is real and grows linearly,
but it is currently blocking nothing — the lane is retired, `blocked` is 0, and no job
carries a marker error. Trading a whole-corpus uniqueness guarantee on a verification
path for latency that nothing is waiting on is a bad trade today. §3–§7 below were
never started.

- **Answer NO** → stop. Close this plan; keep the slow-but-sound path, and revisit only
  if `blocked` or latency actually starts hurting. This is the status-quo-safe answer and
  costs nothing today (the lane is `enabled: false` / `lane_state: retired`, and
  `reconciliation_counts` = `{recovered: 1, absence_proven: 29, blocked: 0}`).
- **Answer YES** → proceed to §3, which implements it behind a default-off flag with the
  weakened case explicitly observable.

---

## 3. Design (only if §2 is YES)

Insert a bounded head read ahead of the existing search in
`_fresh_marker_inventory_projections` (`codex_adapter.py:642`).

```
current:  supports_search ? search_sidebar_inventory(marker_prefix)   # full corpus scan
                          : list_sidebar_inventory()                  # full enumeration
proposed: head = list_sidebar_recent(limit=N)                         # ONE page, ~0.5s
          verify markers over `head`
          if exactly one verified match -> return it            (FAST PATH, flag-gated)
          if >= two verified matches    -> marker_conflict      (sound: 2 is proof)
          otherwise                     -> fall through to the existing path unchanged
```

Notes that constrain the implementation:

- `_bounded_sidebar_inventory_kind` already sends
  `{archived, limit:100, sortKey:"updated_at", sortDirection:"desc"}` as of `21789677f7`,
  so a head read is a *page-capped* call on an already-sorted walk. Do not add a second
  paging implementation; add a `page_cap=1` style bound to the existing one.
- The archived leg is already cheap (0.48–0.61s). Leave it alone; prefilter the active
  leg only.
- `_verified_sidebar_projection` is reused verbatim. No new verification logic.
- Fast path must be **default OFF** behind config, so landing it changes nothing until
  deliberately enabled.

---

## 4. Tasks

- [ ] **T1 — Characterisation test, current behaviour.** Add a test asserting that when
      two threads carry the same valid marker, `reconcile_marker` returns BLOCKED with
      `marker_conflict`. This is the invariant the fast path puts at risk; it must exist
      and pass *before* any behaviour change. Run: `pytest tests/session_bridge/test_codex_adapter.py -q`.
- [ ] **T2 — Config flag, default off.** Add `sidebar_marker_recency_prefilter` (int,
      default `0` = disabled; >0 = head size) to `session_bridge/config.py` alongside
      `reconcile_seconds`. Test both defaults and env/TOML override. With the flag at
      `0`, every existing test must be untouched and green.
- [ ] **T3 — Bounded head read.** Add a read that returns the N most recently updated
      active threads by page-capping the existing `_bounded_sidebar_inventory_kind`.
      Failing test first: assert exactly one `thread/list` call, that it carries
      `limit`/`sortKey`/`sortDirection`, and that no cursor is followed.
- [ ] **T4 — Wire the fast path.** In `_fresh_marker_inventory_projections`, when the
      flag is >0: head-read, verify, and take the fast path only on exactly one match;
      `marker_conflict` on ≥2; otherwise fall through to today's code unchanged. Failing
      test first for all three branches.
- [ ] **T5 — Make the weakened case observable.** When the fast path returns a match,
      record it distinguishably on the reconciliation proof (e.g. an `evidence_kind` that
      says "recency-bounded, uniqueness not proven"). Without this, a weakened result is
      indistinguishable from a full-scan result in `session_sidebar_reconciliation_proofs`
      and nobody can audit it later. Test that the digest/kind differs between paths.
- [ ] **T6 — Full suite + live measurement.** `pytest tests/session_bridge/ -q` must match
      the baseline in the header. Then, read-only against the live app-server, measure the
      flag off vs on for a known one-match marker; record both numbers in the commit body.
- [ ] **T7 — Land.** Back-merge main, re-run the affected suites on the merged tree, then
      FF from the shared checkout via `ops/git-quiet-merge.py --ff`. Guard with
      `merge-base --is-ancestor` (never a hardcoded SHA — main moved three times during
      the 2026-09-02 land) and an empty `git status` in the shared checkout, both checked
      in the same invocation as the merge.

---

## 5. Verification

- **Unit:** T1's conflict invariant must still pass with the flag ON and the conflicting
  threads *outside* the head window — asserting the known weakening, so it is encoded in
  a test rather than discovered later.
- **Live, read-only:** flag off vs on, same marker, interleaved, warmup round discarded
  (round 1 is an outlier on this box — 90.16s against a 14–16s steady state).
- **No production enablement in this plan.** Landing leaves the flag at `0`.

## 6. Rollback

Set the flag to `0` — the fast path is bypassed entirely and behaviour returns to today's.
If the code must go, revert the T4 commit; T1–T3 and T5 are additive and safe to keep.
Nothing in this plan writes to `~/.codex/state_5.sqlite` or mutates any thread.

## 7. Out of scope

Duplicate-marker cleanup (nothing is blocked on it); raising the read ceilings (treadmill);
the ~400-row gap between a sorted enumeration (4626) and `state_5.sqlite` active rows
(5031), which remains an open, separate question.
