# Scheduled catalog recovery

Claude Desktop's native scheduled-task schema requires `id`, `enabled`,
`filePath`, and numeric `createdAt`. Optional fields accept absence, not JSON
null. A malformed task can make the native loader reject the entire catalog;
the next native task creation can then persist only the newly created task.
Catalog handoff and replication preserve creation timestamps and omit absent
optional values. Handoff preserves the source definition and execution history,
except the old account's `notifySessionId`.

The two operations treat an unportable source task differently, by design.
Replication is a passive sweep over whatever the source happens to hold, so a
task that cannot be replicated is quarantined per task -- recorded as a
`scheduled_catalog` surface conflict with reason `created_at_missing` (or
`prompt_missing`, which takes precedence when both apply) -- and every other
task in the catalog still replicates. Handoff names its tasks explicitly, so it
fails closed on the whole request instead: silently skipping a named task would
report success for a transfer that never happened. Read the conflict rows to
find which task is unportable; a replication run that patches nothing while
reporting conflicts is naming its own blocker, not stalling.

For an explicitly investigated catalog loss after a completed handoff, use
`python -m session_bridge.desktop_scheduled_handoff_cli` with the original
`--source-root-id`, `--target-root-id`, complete repeated `--task-id` set, and
`--recover-committed-run <enable-target-run-id>`. Run `--plan`, review its hashes,
then `--apply --confirm TRANSFER_DESKTOP_SCHEDULED_TASK_OWNER`.

Both operations require Desktop to be provably closed. Recovery requires an
exact committed enable-target receipt, matching current owner state, the entire
original task set missing from the target, intact source definitions and prompt
files, and no enabled old owner. Existing unrelated target tasks are retained.
Apply records pending recovery, backs up the current target outside Hermes,
checks its expected hash before replacement, and verifies sole ownership.
Failures leave pending evidence for the existing monitor. Reopen Desktop and
verify its native task list before claiming recovery; a JSON count alone does
not establish that the native parser accepted the catalog.

Recovery is an explicit operator action, not automatic recreation after every
deletion. The completed handoff receipt is historical evidence and cannot prove
that later user deletions were unintended. The monitor's new-task grace period
can temporarily report zero wanted tasks and is not evidence of native parsing.
