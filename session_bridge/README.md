# session_bridge -- branch status

**`main` is ABANDONED for this subsystem as of 2026-09-13.** Do not deploy it, do not
cherry-pick from it, and do not treat it as a fallback when something breaks on the
deployed branch. There is nothing to recover from it, and deploying it would damage
the live database.

The deployed branch is **`codex/wave2-hermes-accepted`**.

This notice lives on both branches, so reading it does not tell you which one you are
on. Check:

```
git -C $HOME/.hermes/agent-src rev-parse --abbrev-ref HEAD
```

## Why main is abandoned and not merely behind

**1. Nothing is stranded on it.** All 14 non-merge main-only commits touching
`session_bridge/` are already on `codex/wave2-hermes-accepted` BY CONTENT -- not by
SHA, so `git cherry`, `git log --cherry-pick` and any SHA-based comparison will
wrongly report them as missing. They were folded in by `8586e305a2` ("Integrate
frozen Hermes 0.21.1 candidate", 2026-09-10) and in places relocated: the schema half
of `9b6e8b38ca` now lives in `hermes_state_bridge_schema.py`, not `hermes_state.py`.
The one genuine gap was that commit's test half, ported as `37f0b4f0ed`. Verified
line by line, 2026-09-13; method and per-commit coverage are on the loops record
named below.

**2. Deploying main would re-migrate a database that is past those migrations.**
This is the part that makes an unmarked main dangerous rather than merely stale:

| | `main` | `codex/wave2-hermes-accepted` | live `~/.hermes/state.db` |
|---|---|---|---|
| `SCHEMA_VERSION` | 34 (`hermes_state.py`) | 30 (`hermes_state_common.py`) | reads 30 |
| `desktop_registry_baselines` | `value_json` | `value_hash` (content-addressed) | `value_hash` |

wave2 RENUMBERED to upstream `SCHEMA_VERSION = 30`, with an offline local33/local34
conversion path in `hermes_state_conversion.py`. The live database therefore reads
**schema_version 30 while already carrying the v34 content-addressed shape**. main's
migrations are keyed on `current_version < 32` and `current_version < 33`
(`hermes_state.py`, around lines 5017 and 5083), so main would read 30, conclude the
database is pre-v32, and re-run the v32 FTS inline-to-external conversion and the v33
block against a database that is past both. The two branches' version numbers are not
on the same scale and must never be compared as if they were.

**3. main is far behind in this subsystem specifically.** 16,202 commits behind
overall, and in `session_bridge/` plus its tests it lacks roughly 5,224 lines that
wave2 has: MCP 2 transport, desktop presentation, the scheduled catalog and handoff
modules, desktop surface discovery, incomplete-registration recovery, the codex
discovery budget, and sidebar convergence. main's remaining unique lines are older
shapes of code wave2 has since rewritten.

## What was deliberately NOT done, and the decision that closed it

main was **not** resynced from wave2, and as of 2026-09-13 that is a CLOSED DECISION
rather than a pending one. The resync was planned in full and then declined. The plan
is `docs/superpowers/plans/2026-09-13-main-resync-from-wave2.md`, on
`codex/wave2-hermes-accepted` -- it was deliberately not landed on main, per the rule
below. Read it before re-proposing a resync, in particular:

- section 3, which measures that `git cherry` reports 92 of 93 main-only commits as
  absent from wave2 **including all 14 that were proven present by content** -- so the
  first tool anyone reaches for here gives the wrong answer; and
- section 4, which records that the natural spelling `git branch -f main <sha>` is
  **not** covered by the destructive-git guard, while `reset --hard` is. The absence
  of a block is not authorization.

**main is FROZEN. Do not commit to it.** That is the whole of the adopted policy
(option S3 in the plan): the two branches stop diverging because nothing new lands on
main -- not because any ref is moved or any history is discarded. Freezing costs
nothing, needs no grant, and keeps main as the last state of the pre-renumbering
schema lineage, which is worth having while the 30-vs-34 split is live.

**The freeze is enforced by a detector, not by trust.** The tag
`main-frozen-20260913` names main's frozen tip, so this reports on it:

```
git -C $HOME/.hermes/agent-src log --oneline main-frozen-20260913..main
```

Empty means the freeze held. Anything else names exactly what landed and when --
report it on the loops record rather than quietly extending it.

**One class of commit to main is permitted: a correction to THIS FILE.** The marker has
to stay accurate to be worth anything, and a detector that fires on its own
documentation fix is a broken detector. If you correct it, move the tag to the new tip
in the same pass -- `git tag -f -a main-frozen-20260913 <new-tip> -m "..."` -- so the
detector keeps reporting the truth rather than a false positive. Everything else --
product code, tests, any other doc -- does not land on main.

Do not run `hermes update` to "fix" this -- it hard-resets local commits. Nothing here
was pushed; `origin/main` is thousands of commits behind and is not a factor.

## Verify before trusting this file

A status note is a snapshot. Re-measure rather than believing it. Every command
below is verified to run **as written in both PowerShell and bash** on this box --
hence `$HOME` rather than `~` (git on Windows does not expand `~`) and git's own
`grep` rather than the external one (PowerShell has no `grep`):

```
git -C $HOME/.hermes/agent-src grep -n "^SCHEMA_VERSION" main -- hermes_state.py
git -C $HOME/.hermes/agent-src grep -n "^SCHEMA_VERSION" codex/wave2-hermes-accepted -- hermes_state_common.py
python -c "import session_bridge; print(session_bridge.__file__)"
python -c "import sqlite3,os; c=sqlite3.connect('file:'+os.path.expanduser('~/.hermes/state.db')+'?mode=ro',uri=True); print(c.execute('select version from schema_version').fetchone()); print([r[1] for r in c.execute('pragma table_info(desktop_registry_baselines)')])"
```

Expected as of 2026-09-13: main 34, wave2 30, `session_bridge.__file__` under
`~/.hermes/agent-src/` (an editable install, so the deployed code IS this working
tree and its checked-out branch), live db `(30,)` with a `value_hash` column and no
`value_json`.

If the two `SCHEMA_VERSION` values now agree, or main has been resynced, or the
deployed branch has changed, **this notice is stale** -- correct it on the loops
record rather than only here, or the next reader gets the old answer.

## Record

- loops: `wave2-main-session-bridge-divergence-20260912`
  (`python ~/.hermes/bin/loops.py check "wave2 divergence"`)
- MemPalace: `session-bridge/wave2-main-session-bridge-divergence-audit-2026-09-13`
- Resync plan (declined): `docs/superpowers/plans/2026-09-13-main-resync-from-wave2.md`
