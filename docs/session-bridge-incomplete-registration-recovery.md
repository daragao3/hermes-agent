# Exact incomplete Claude registration recovery

`claude-visibility-resume-incomplete` is an operator-only recovery for one terminal
`bridge_conflict` whose exact native transcript contains only the authenticated
original registration prompt. It never creates another UUID or deletes transcript
records. It reserves one additional paid attempt using the existing recovery ledger,
checks native evidence again, and starts an interactive `--resume` of the reserved UUID.

From the deployed checkout in PowerShell, set `HERMES_HOME` to the store's actual
home and inspect the exact job first:

```powershell
$env:HERMES_HOME = 'C:/Users/diego/.hermes'
& .venv/Scripts/python.exe -c 'from session_bridge.cli import main; raise SystemExit(main())' claude-visibility-resume-incomplete --job-id <job-id> --reserved-claude-uuid <uuid> --dry-run
```

Replace `--dry-run` with `--apply` only for the operator-authorized recovery. Apply
retains the normal Claude version, authentication, startup, budget, and lease checks.
The failed job itself is not leased or marked visible until native proof exists.
Success requires the exact recovery prompt and an actual `REGISTERED` assistant
reply. The exact native resume bookkeeping pair may precede that prompt; unrelated
user turns, different bookkeeping text, tool calls, and provider-limit replies fail
validation. Signed identity, UUID, title, cwd, and unique transcript checks still apply.

The call-start checkpoint enforces one call atomically, even after lease expiry.
After any started call, repeating `--apply` cannot initiate another native call.
If a completed transcript survives a commit crash, the command can reconcile it
without another call. A failure before the checkpoint leaves only an expiring
recovery lease; after expiry the unused paid reservation can be reclaimed. Do not
delete usage rows, change UUIDs, clear checkpoints, dismiss the failure to obtain a
green health result, or copy signed prompts into probe sessions.

## Current operational blocker — 2026-09-12

Job `claude-visibility-job:aba0f323f486eb14f9029a75c67777a33931c31804d9a97c201e4df1e0b512a9`,
UUID `057fe73b-35c8-51e2-b0a1-384e21b1dd49`, consumed its single authorized recovery
call at 18:09 UTC. Its native transcript records the recovery prompt followed by:

> You've hit your weekly limit · resets Sep 14, 4am (America/New_York)

That reported reset is **2026-09-14 at 04:00 America/New_York (08:00 UTC)**. No
`REGISTERED` reply was produced. The job remains `claude_failed`, attempts=2, with
its original `bridge_conflict` and no main-job lease. The recovery row retains
the call-start checkpoint and is in `retry`; that ledger label does **not** grant
permission for another native call.

Resolve or wait out the Claude account quota first. Recheck native account status
and the exact transcript after the reported reset. If no completed registration
appears, another paid attempt needs a separately reviewed, guarded recovery
disposition preserving this UUID, transcript, and attempt history. The current
one-call command deliberately refuses that second launch. Do not rerun apply to
obtain diagnostics: the existing native transcript already contains the cause.
