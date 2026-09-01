# Which HERMES_HOME does each service use?

> **Audience:** Operators and contributors touching `session_bridge`, the gateway, or cron
> **Source files:** `hermes_constants.py` (`get_hermes_home`, `get_default_hermes_root`), `session_bridge/config.py`, `~/.hermes/session-bridge/launch-session-bridge.ps1`, `~/laptop-start.ps1`
> **Related:** [Profile-Based Routing](../profile-routing.md) (a *different* concept — inbound message routing, not filesystem scoping)

## The one-sentence version

**`session_bridge` is ROOT-scoped. The gateway is PROFILE-scoped.** They are two
long-lived services running on two different `HERMES_HOME` values on the same box, and
that is deliberate — not a misconfiguration to "fix" by making them agree.

## Why this trips people up

`hermes_constants.get_hermes_home()` resolves, in order: a context-local override → the
`HERMES_HOME` env var → the platform default (`~/.hermes`). It is used by ~30 modules at
import time, so it cannot raise.

When `HERMES_HOME` is unset while `~/.hermes/active_profile` names a non-default profile,
it emits a one-shot stderr warning telling you the spawner should pass `HERMES_HOME`
explicitly (issue #18594). **That advice is correct in general and wrong for
`session_bridge` specifically.** Passing the obvious value — the active profile — points
`session_bridge` at a config and a `state.db` that no running bridge reads.

## Who pins what

| Process | `HERMES_HOME` | Pinned by |
|---|---|---|
| Session bridge service | `~/.hermes` (the **root**) | `launch-session-bridge.ps1` (hardcoded, passed to the child's environment) |
| Gateway | `~/.hermes/profiles/main` | `laptop-start.ps1` (set across the launch, restored after) |
| Cron-spawned scripts | the job's profile | `cron/scheduler.py` |
| A bare `python -m session_bridge.cli ...` | **unset → falls back to the root** | nothing — and for `session_bridge` that fallback is the *correct* answer |

`get_default_hermes_root()` is the helper that answers "what is the root?" from any of
these: a profile home (`<root>/profiles/<name>`) resolves to `<root>`, while a home
outside `~/.hermes` (Docker, `/opt/data`) *is* its own root and is returned unchanged.

## The failure this caused

Measured 2026-09-01. The root `config.yaml` carried the sidebar lane's retirement
(`session_bridge.sidebar.enabled: false`). `profiles/main/config.yaml` still said `true` —
the retirement was never mirrored there — and pointed at a different, much smaller
`state.db`.

Running the same command under each home gave two different answers:

| `HERMES_HOME` | counts | `enabled` | broker thread |
|---|---|---|---|
| unset → root | 517 pending / 9 retry / 20 visible | `false` (retired) | `01a05a84…` |
| `profiles/main` | all zero | `true` (active) | `019f9b71…` |

The root's answer matched the live service. The profile's answer was a phantom: a retired
lane reported as **active and healthy with zero rows** — green but blind, the same failure
class the `optional_feature_disabled` evidence work eliminated on every other surface that
same day.

This stayed latent only because every reader of `sidebar.enabled` lives inside
`session_bridge/` (`config.py`, `coordinator.py`, `cli.py`, `health.py`, `mcp_server.py`)
and every such process is launched root-scoped. Nothing on the gateway side reads it.

## The guard

`session_bridge/config.py` now warns when a `session_bridge` config load resolves a home
that **disagrees with the root** about `sidebar.enabled`. It:

- **warns only** — it does not raise (that would brick callers over a file they may not
  own) and does not override the resolved value (that would hide a real misconfiguration);
- fires **once** per process, straight to stderr, matching
  `hermes_constants._warn_profile_fallback_once` — config load happens before logging is
  configured at several call sites;
- reads the root `config.yaml` **directly** rather than through
  `hermes_cli.config.load_config`, because that helper merges built-in defaults and
  substitutes the whole default config on a parse error. Going through it would turn an
  *absent* or *unparseable* root key into a real `False` and raise a false alarm against a
  config that never stated an opinion.

Tests: `tests/session_bridge/test_root_scope_divergence.py`.

## If you see the warning

1. Doing `session_bridge` work by hand? **Unset `HERMES_HOME`.** The fallback to the root
   is what the service uses.
2. Otherwise the two configs have genuinely drifted — reconcile the profile's
   `config.yaml` with the root's. The root is authoritative for `session_bridge`.

Do **not** silence it by making `session_bridge` follow the active profile. That inverts
the design and points the service at the wrong `state.db`.
