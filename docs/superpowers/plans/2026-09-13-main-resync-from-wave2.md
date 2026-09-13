# Plan: resync `main` from `codex/wave2-hermes-accepted` (agent-src)

Status: **PLAN ONLY -- NOT EXECUTED, NOT AUTHORIZED TO EXECUTE.**
Written 2026-09-13 on Diego's instruction ("write the plan, don't execute").
Nothing in this document has been run. No branch was touched to produce it.

Record: loops `wave2-main-session-bridge-divergence-20260912`.
Companion: `session_bridge/README.md` (the abandonment marker, landed 2026-09-13).

---

## 1. What this is, and the decision it serves

The 2026-09-13 divergence audit left three options: (a) mark `main` abandoned for
session_bridge, (b) resync `main` from wave2 so the two stop diverging, (c) declare
the divergence acceptable and record why.

**(a) is DONE** -- `session_bridge/README.md` landed on both branches (`ef3e33ad6e`
on main, `372fbb343b` on wave2, identical blob `c23c931cee`). That removed the
*hazard*. This plan covers (b), which would remove the *divergence*. They are
different problems and only the first one was urgent.

**The recommendation in section 8 is: do not execute this plan.** It is written so
that the option stays open and costed, not because it should be taken.

---

## 2. Measured current state (2026-09-13, re-measure before acting)

| Fact | Value |
|---|---|
| Deployed branch | `codex/wave2-hermes-accepted` (editable install; `import session_bridge` resolves into `agent-src/`) |
| Merge base | `b9ad9d2058` (2026-09-08) |
| wave2 ahead of main | 16,202 commits |
| main ahead of wave2 | 171 total / **93 non-merge** |
| main-only date span | 2026-09-08 .. 2026-09-13 (5 days) |
| main-only by type | 42 fix, 25 docs, 12 feat, 5 test, 3 perf, 2 tools, 2 ci, 1 refactor, 1 chore |
| main reflog depth | 943 entries (rollback source) |
| Pushed? | No. `origin/main` is 2,505 commits behind main; nothing here has ever been pushed |

Re-measure command block:

```
git -C ~/.hermes/agent-src rev-list --count codex/wave2-hermes-accepted..main
git -C ~/.hermes/agent-src rev-list --no-merges --count codex/wave2-hermes-accepted..main
git -C ~/.hermes/agent-src merge-base codex/wave2-hermes-accepted main
```

---

## 3. THE BLOCKING PREREQUISITE -- do not skip, and do not use `git cherry`

A resync **discards main's 93 non-merge commits**. That is only safe if their content
is genuinely already on wave2. Status of that question today:

- **14 of 93 are PROVEN present by content.** Those are the session_bridge ones. The
  audit searched every significant added line in wave2's copy of the same file and
  then anywhere in a wave2 snapshot. Carried in by `8586e305a2`, in places relocated
  (`9b6e8b38ca`'s schema half now lives in `hermes_state_bridge_schema.py`).
- **The other ~79 are NOT line-verified.** The audit's note that they are "docs/i18n/
  skills or already on wave2 by content" was an explicit side finding, not the
  rigorous pass. **This is the gap that must be closed before any destructive step.**

**`git cherry` / `git log --cherry-pick` / any patch-id comparison is the WRONG
INSTRUMENT here and will mislead you.** Measured 2026-09-13: `git cherry
codex/wave2-hermes-accepted main` reports **92 of 93 as having no equivalent on
wave2** -- including all 14 that were proven present by content. The over-report is
structural: wave2 relocated, renamed and rewrote the code, so patch-ids cannot match.
A reader who runs `git cherry` and believes it will conclude that a resync destroys 92
commits of unique work. A reader who runs it and *discounts* it entirely may miss the
one real gap. It answers a different question than the one being asked.

**Required pre-flight (likely the largest part of the work):** repeat the audit's
content method over the ~79 unverified commits. For each, take its added lines and
search (1) wave2's copy of the same file, then (2) anywhere in a wave2 snapshot, to
catch relocation. Produce a per-commit coverage percentage and a list of genuinely
absent lines. Treat anything below ~90% as needing human adjudication -- in the audit
the low scores were all renames and supersessions, but that was established per
commit, not assumed.

**Gate: if any commit carries content absent from wave2, port it FIRST (as
`37f0b4f0ed` did for the one real gap) and re-verify. Do not proceed with unported
content.**

---

## 4. Guard landscape -- read before choosing a command

This is the part most likely to go wrong, because **the dangerous command is the
unguarded one**.

`~/.claude/hooks/block-destructive-git.py` BLOCKED table (read 2026-09-13) contains:
`git clean` (forcing/ignored flags), **`git reset --hard`**, repo-wide `checkout` /
`restore` discards, `git stash drop|clear`, **`git branch -D`**, `git push`,
`worktree add -f <branch>`, `gc`, `prune`, `reflog expire|delete`, `repack`,
`maintenance run`.

It does **NOT** contain:

- **`git branch -f main <sha>`** -- the most natural resync spelling. Force-moving a
  branch tip is not a rule in the table. It would execute silently and instantly.
- **`git update-ref`** in any form. The guard's own docstring says so explicitly
  ("`git update-ref` IS NOT GUARDED IN ANY FORM"), on the reasoning that guarding it
  would block the undo path rather than the hazard.

**Consequence, and the single most important line in this plan: the absence of a block
is not authorization, and there is no hook backstop on the easy route.** If this plan
is ever executed, **deliberately use the GUARDED spelling** (`reset --hard` inside a
throwaway worktree, section 5) rather than the unguarded `branch -f`, specifically so
that a human click is forced into the loop and the operation is recorded. Choosing the
guarded path when an unguarded one exists is the point, not an inconvenience.

**Grant mechanics** (from CLAUDE.md, unchanged): attempt the command so the hook emits
a pending id; hand Diego the single printed
`gitguard.py grant --pending <id> --reason "..."` line to run **in his own terminal**
(keep `--reason` QUOTED -- unquoted multi-word dies on "unrecognized arguments"); then
re-issue the command **BYTE-IDENTICALLY**. The grant binds to the whole normalized
command line, is single-use, and expires in 15 minutes. Success prints `granted <id>`
and echoes the bound string; **anything else, including no output at all, means no
grant exists.** Grants convert at roughly 0.6% on this box, so a block is a hard stop,
not a speed bump.

**Related prior incident, same repo, same branch:** `worktree add <path> main -f`
reverted a merge on agent-src main 17 seconds after it landed (loops
`agent-src-main-reset-after-landing-20260907`). That is why section 5 never passes
`-f`.

---

## 5. Candidate shapes

### S1 -- Force `main` to wave2 (the literal "resync")

Result: `main` becomes identical to wave2. Divergence goes to zero. main's 93
non-merge commits leave the branch, recoverable only via the tag in step 0 and the
reflog.

**The wrinkle that decides the spelling:** a `reset --hard` on a *detached* worktree
moves no branch, so it would not resync anything; the ref move would then have to be
`branch -f`, which is unguarded. To keep the whole operation behind one grant, check
`main` itself out in the throwaway worktree -- the **non-forced** `worktree add <path>
main`, which git refuses outright if any sibling holds the branch -- and let the
branch move as a side effect of the guarded reset.

```
# 0. SAFETY TAG FIRST -- this is what makes the operation reversible.
git -C ~/.hermes/agent-src tag main-preresync-20260913 main
git -C ~/.hermes/agent-src rev-parse main-preresync-20260913   # record this oid

# 1. Throwaway worktree WITH main checked out. Non-forced on purpose: git's own
#    refusal is the interlock against a sibling holding the branch. Never -f.
git -C ~/.hermes/agent-src worktree add \
    ~/.hermes/agent-src/.claude/worktrees/main-resync-20260913 main

# 2. The GUARDED spelling, run inside that worktree. This is REFUSED by the hook:
#    take the pending id from the refusal, have Diego run the printed grant line in
#    his own terminal, then re-issue BYTE-IDENTICALLY. Moves the branch ref too.
cd ~/.hermes/agent-src/.claude/worktrees/main-resync-20260913
git reset --hard codex/wave2-hermes-accepted

# 3. Verify BEFORE cleanup, while the tag is still the only other witness.
git -C ~/.hermes/agent-src rev-parse main codex/wave2-hermes-accepted   # must match
git -C ~/.hermes/agent-src rev-list --count codex/wave2-hermes-accepted..main  # must be 0

# 4. Clean up.
git -C ~/.hermes/agent-src worktree remove \
    ~/.hermes/agent-src/.claude/worktrees/main-resync-20260913
```

### S2 -- Merge wave2 into main

Preserves main's history; produces a hybrid whose tree is wave2's plus whatever main's
older shapes conflict into. **Rejected.** It creates a third code shape that is
neither branch, guarantees conflicts across 16,202 commits of drift, and resolving
them means re-litigating supersessions the audit already established (main's remaining
lines are *older shapes of code wave2 rewrote*). It would also produce a `main` that
is not a usable fallback either -- the exact property the marker exists to warn about,
now harder to describe.

### S3 -- Retire the name

Stop committing to main, without moving the ref. Optionally tag it as an archive
point. This is what the marker already achieves in practice. Note `git branch -D` IS
guarded, so retiring by *deletion* would need a grant -- but deletion is not
recommended: main is a useful archaeological reference precisely because it predates
wave2's renumbering.

---

## 6. Rollback

- `main-preresync-20260913` (step 0) is the primary restore point; restoring is a ref
  move back to that tag.
- Secondary: the `main` reflog, 943 entries deep as measured. `main@{1}` is
  `b981661f94`.
- **Nothing was ever pushed**, so no remote can diverge and no force-push is involved
  at any point. `origin/main` is 2,505 behind and is not a factor.
- The tag survives `worktree remove`; a worktree's own HEAD reflog does not, which is
  the trace that went missing in the 2026-09-07 incident.

---

## 7. What this does NOT fix, and one thing it would break

- It does **not** change anything about deployment. wave2 is deployed via the editable
  install; main is not deployed and would not become deployed.
- It does **not** resolve the schema-numbering split. wave2's `SCHEMA_VERSION = 30`
  with the offline local33/local34 conversion path is the branch's real contract; a
  resync propagates that to main rather than reconciling it with main's 34.
- **It would falsify the abandonment marker.** `session_bridge/README.md` says main is
  abandoned. After a resync, main *is* wave2 -- the file would still be present (it is
  on wave2 too) but its central claim would be false and actively misleading. **Any
  execution of this plan MUST rewrite or remove `session_bridge/README.md` on both
  branches in the same change**, and correct the loops record. A resync that leaves
  the marker standing is worse than no resync.

---

## 8. Recommendation

**Do not execute.** Reasons, in order of weight:

1. **The hazard is already gone.** (a) solved the actual problem -- someone deploying
   main against the live `state.db`. Divergence between two branches where only one is
   deployed is untidy, not dangerous.
2. **The cost is front-loaded onto the riskiest step.** The genuine work is section 3's
   content verification of ~79 commits, and the payoff for that work is a branch
   nobody deploys becoming a duplicate of a branch that is deployed.
3. **It spends a grant and a click for no operational benefit**, and the only spelling
   that avoids the grant is the unguarded `branch -f` -- the cheap route is the one
   with no safety net.
4. **It destroys a useful reference point.** main is currently the last state of the
   pre-renumbering schema lineage, which has archaeological value precisely while the
   30-vs-34 split is live.
5. **The divergence is not growing in a way that matters.** Five days, 93 commits, and
   the subsystem that mattered was already proven carried by content.

**If the goal is "stop the two diverging", the cheap and safe version is S3: stop
committing to main.** That costs nothing, needs no grant, and is already almost true --
the only recent commit to main is the abandonment marker itself.

Revisit if any of these change: main becomes a deployment target again; wave2 is
merged to `origin/main` (which would need the three-blobs-over-100MB problem solved
first); or someone needs to cherry-pick *from* main and finds the content genuinely
absent from wave2.
