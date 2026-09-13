"""``hermes doctor`` — diagnose (and with --fix, repair) a Hermes install.

``run_doctor`` walks ``DOCTOR_CHECKS`` in order; each check prints its own rows and returns a ``Finding``.
Check bodies live in the ``doctor_*`` siblings.
"""

import os
import sys

from hermes_cli.config import get_env_path, get_hermes_home, get_project_root
from hermes_cli.env_loader import load_hermes_dotenv
from hermes_constants import display_hermes_home

PROJECT_ROOT = get_project_root()
HERMES_HOME = get_hermes_home()
_DHH = display_hermes_home()  # user-facing display path (e.g. ~/.hermes or ~/.hermes/profiles/coder)

# Load environment variables from ~/.hermes/.env so API key checks work
_env_path = get_env_path()
load_hermes_dotenv(hermes_home=_env_path.parent, project_env=PROJECT_ROOT / ".env")

from hermes_cli.colors import Colors, color
from hermes_cli.doctor_report import (
    Finding, _section, check_bool, check_info, doctor_check, set_doctor_request,
    warn_on_error)
from hermes_cli.doctor_connectivity import _has_healthy_oauth_fallback_for_apikey_provider, build_probes, run_probes
from hermes_cli.doctor_tools import _safe_which
from hermes_cli.doctor_platform import _python_install_cmd  # noqa: F401 -- patchable module global

from hermes_cli.doctor_config import (
    _check_config_drift,
    _check_config_file,
    _check_env_file,
    _check_mcp_security,
    _check_xai_retirement,
    _check_plugin_compat,
)
from hermes_cli.doctor_platform import (
    _check_certificates,
    _check_command_installation,
    _check_gateway_supervision,
    _check_python_environment,
    _check_required_packages,
    _check_security_advisories,
)
from hermes_cli.doctor_tools import (
    _check_git_and_rg,
    _check_node_and_browser,
    _check_npm_audit,
    _check_terminal_backend,
    _check_tool_availability,
)
from hermes_cli.doctor_state import (
    _check_directory_structure,
    _check_memory_provider,
    _check_profiles,
    _check_skills_hub,
    _check_state_db,
)

_PROVIDER_ENV_HINTS = (
    "DEEPINFRA_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN",
    "OPENAI_BASE_URL", "NOUS_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "KIMI_API_KEY",
    "KIMI_CN_API_KEY", "GMI_API_KEY", "FIREWORKS_API_KEY", "ACTUAL_API_KEY", "ACTUAL_BASE_URL", "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY", "KILOCODE_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "HF_TOKEN",
    "AI_GATEWAY_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_GO_API_KEY", "COMMANDCODE_API_KEY", "XIAOMI_API_KEY",
    "TOKENHUB_API_KEY", "TOKENPLAN_API_KEY",
)


@doctor_check()
def _check_auth_providers(should_fix: bool, f: Finding) -> None:
    """Refresh-free OAuth status snapshot (doctor must never trigger a token refresh)."""
    with warn_on_error("Auth provider status", "(could not check: {e})"):
        from hermes_cli.auth import get_nous_auth_status_local, get_codex_auth_status, get_minimax_oauth_auth_status
        _login_row("Nous Portal auth", get_nous_auth_status_local())
        # Native OAuth is Hermes' own device-code flow; the Codex CLI only imports existing ~/.codex/auth.json
        # tokens, so the hint sits under the Codex row (not as another provider's remedy).
        if not _login_row("OpenAI Codex auth", get_codex_auth_status(), show_error=True) and not _safe_which("codex"):
            check_info("codex CLI not installed (optional — only required to import tokens from an existing Codex CLI login)")
        minimax_status = get_minimax_oauth_auth_status()
        _login_row("MiniMax OAuth", minimax_status, f"(logged in, region={minimax_status.get('region', 'global')})")
    with warn_on_error(""):  # xAI OAuth separately, so an import failure cannot disrupt the rows already printed
        from hermes_cli.auth import get_xai_oauth_auth_status
        _login_row("xAI OAuth", get_xai_oauth_auth_status() or {}, show_error=True)


def _login_row(label: str, status: dict, ok_detail: str = "(logged in)", show_error: bool = False) -> bool:
    """ok/warn row for an OAuth status dict; with show_error, its ``error`` hint prints under a not-logged-in row."""
    logged_in = check_bool(status.get("logged_in"), (label, ok_detail), (label, "(not logged in)"))
    if not logged_in and show_error and status.get("error"):
        check_info(status["error"])
    return logged_in


@doctor_check()
def _check_api_connectivity(should_fix: bool, f: Finding) -> None:
    """Parallel HTTP/SDK probes for every configured provider; results printed in submission order."""
    probes = build_probes()
    # Single status line so users see something happening; ``\r`` clears it once results land.
    print(f"  {color(f'Running {len(probes)} connectivity checks in parallel…', Colors.DIM)}", end="", flush=True)
    results = run_probes(probes)
    print("\r" + " " * 70 + "\r", end="")
    for r in results:
        for glyph, label, detail in r.lines:
            print(f"  {glyph} {label}" + (f" {detail}" if detail else ""))
        if r.issues and not _has_healthy_oauth_fallback_for_apikey_provider(r.label):
            f.issues.extend(r.issues)


# Ordered (section title, check). None title = check prints its own header (or none); order is user-visible.
DOCTOR_CHECKS = (
    ('Security Advisories', _check_security_advisories), ('MCP Server Security', _check_mcp_security),
    ('Python Environment', _check_python_environment), ('SSL / CA Certificates', _check_certificates),
    ('Required Packages', _check_required_packages), ('Configuration Files', _check_env_file),
    (None, _check_config_file), (None, _check_config_drift),
    ('xAI Model Retirement (May 15, 2026)', _check_xai_retirement),
    ('Plugin import paths (removed Sep 14, 2026)', _check_plugin_compat), ('Auth Providers', _check_auth_providers),
    ('Directory Structure', _check_directory_structure), (None, _check_state_db),
    (None, _check_gateway_supervision), (None, _check_command_installation),
    ('External Tools', _check_git_and_rg), (None, _check_terminal_backend), (None, _check_node_and_browser),
    (None, _check_npm_audit), ('API Connectivity', _check_api_connectivity),
    ('Tool Availability', _check_tool_availability), ('Skills Hub', _check_skills_hub),
    ('Memory Provider', _check_memory_provider), (None, _check_profiles),
)


def _ack_advisory(ack_target: str) -> None:
    """`hermes doctor --ack <id>`: persist the ack and return without running diagnostics."""
    from hermes_cli.security_advisories import ADVISORIES, ack_advisory
    valid_ids = {a.id for a in ADVISORIES}
    if ack_target not in valid_ids:
        print(color(f"Unknown advisory ID: {ack_target!r}. Known IDs: {', '.join(sorted(valid_ids)) or '(none)'}", Colors.RED))
        sys.exit(2)
    if ack_advisory(ack_target):
        print(color(f"  ✓ Acknowledged advisory {ack_target}. It will no longer trigger startup banners.", Colors.GREEN))
    else:
        print(color(f"  ✗ Failed to persist ack for {ack_target}. Check ~/.hermes/config.yaml is writable.", Colors.RED))
        sys.exit(1)


def _print_summary(should_fix: bool, total: Finding) -> None:
    print()
    remaining = total.issues + total.manual_issues
    numbered = "".join(f"  {i}. {issue}\n" for i, issue in enumerate(remaining, 1))
    if should_fix and total.fixed > 0:
        print(color("─" * 60, Colors.GREEN))
        print(color(f"  Fixed {total.fixed} issue(s).", Colors.GREEN, Colors.BOLD), end="")
        print(color(f" {len(remaining)} issue(s) require manual intervention.", Colors.YELLOW, Colors.BOLD) if remaining else "")
        print()
        if remaining:
            print(numbered)
    elif remaining:
        print(color("─" * 60, Colors.YELLOW))
        print(color(f"  Found {len(remaining)} issue(s) to address:", Colors.YELLOW, Colors.BOLD))
        print()
        print(numbered)
        if not should_fix:
            print(color("  Tip: run 'hermes doctor --fix' to auto-fix what's possible.", Colors.DIM))
    else:
        print(color("─" * 60, Colors.GREEN))
        print(color("  All checks passed! 🎉", Colors.GREEN, Colors.BOLD))
    print()


def run_doctor(args):
    """Run diagnostic checks."""
    should_fix = getattr(args, 'fix', False)
    # Checks run as check(should_fix) and never see args; the two opt-in ones
    # (--audit, --deep) read their flag from here.
    set_doctor_request(args)
    # Doctor runs from the interactive CLI, so CLI-gated tool checks (e.g. cronjob) see the same context.
    os.environ.setdefault("HERMES_INTERACTIVE", "1")
    if getattr(args, 'ack', None):
        return _ack_advisory(args.ack)
    print()
    for line in ("┌─────────────────────────────────────────────────────────┐",
                 "│                 🩺 Hermes Doctor                        │",
                 "└─────────────────────────────────────────────────────────┘"):
        print(color(line, Colors.CYAN))
    total = Finding()
    for title, check in DOCTOR_CHECKS:
        if title:
            _section(title)
        total.merge(check(should_fix))
    # Opt-in live probes run AFTER all static checks (`--live`: real network calls; bounded + read-only).
    with warn_on_error(""):
        from hermes_cli.doctor_live import maybe_run_live_checks
        maybe_run_live_checks(args, total.manual_issues)
    _print_summary(should_fix, total)


# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
# Names external plugins imported from this module before the Sep 2026 decomposition.
# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
# The whole block is removed by reverting the commit that added it.
from pathlib import Path  # noqa: F401,E402
import importlib.util  # noqa: F401,E402
import shutil  # noqa: F401,E402
import subprocess  # noqa: F401,E402

def check_fail(text: str, detail: str = ""):
    print(f"  {color('✗', Colors.RED)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_ok(text: str, detail: str = ""):
    print(f"  {color('✓', Colors.GREEN)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_warn(text: str, detail: str = ""):
    print(f"  {color('⚠', Colors.YELLOW)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))


_PLUGIN_COMPAT_LAZY = {
    'FTS_STORAGE_VERSION': ('hermes_state_common', 'FTS_STORAGE_VERSION'),
    'OPENROUTER_MODELS_URL': ('hermes_constants', 'OPENROUTER_MODELS_URL'),
    'STATE_DB_SIZE_WARN_BYTES': ('hermes_cli.doctor_state', 'STATE_DB_SIZE_WARN_BYTES'),
    'agent_browser_runnable': ('hermes_constants', 'agent_browser_runnable'),
    'base_url_host_matches': ('utils', 'base_url_host_matches'),
    'check_certificates': ('hermes_cli.doctor_platform', 'check_certificates'),
    'check_macos_full_disk_access': ('hermes_cli.doctor_platform', 'check_macos_full_disk_access'),
    'check_macos_tcc_anchor': ('hermes_cli.doctor_platform', 'check_macos_tcc_anchor'),
    'check_macos_tcc_grants': ('hermes_cli.doctor_platform', 'check_macos_tcc_grants'),
    'collect_deprecated_config_keys': ('hermes_cli.doctor_config', 'collect_deprecated_config_keys'),
    'collect_deprecated_env_vars': ('hermes_cli.doctor_config', 'collect_deprecated_env_vars'),
    'collect_relay_plugin_cutover_findings': ('hermes_cli.doctor_config', 'collect_relay_plugin_cutover_findings'),
    'describe_vercel_auth': ('hermes_cli.vercel_auth', 'describe_vercel_auth'),
    'detect_install_method': ('hermes_cli.config', 'detect_install_method'),
    'is_nix_install_method': ('hermes_cli.config', 'is_nix_install_method'),
    'managed_scope_check': ('hermes_cli.doctor_config', 'managed_scope_check'),
    'recommended_update_command_for_method': ('hermes_cli.config', 'recommended_update_command_for_method'),
    'report_deprecated_config_and_env': ('hermes_cli.doctor_config', 'report_deprecated_config_and_env'),
}


def __getattr__(name):  # PEP 562 — lazy so no import cycles
    target = _PLUGIN_COMPAT_LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    from hermes_cli.plugin_compat import warn_once
    warn_once(__name__, name, *target)
    return getattr(importlib.import_module(target[0]), target[1])
# ---- END PLUGIN-COMPAT ----


# --- opt-in check budgets ---------------------------------------------------------------------

# Wall-clock budget for the state.db health probe. The probe ends in
# ``PRAGMA integrity_check``, a page-by-page verification of the whole
# database: on a 5.1 GB state.db it ran for over 12 minutes and made
# `hermes doctor` never terminate. A diagnostic that cannot answer quickly
# should say so rather than block, so the probe is bounded and a budget hit
# renders a WARN. Raise it (or set 0/invalid to fall back to the default)
# via HERMES_DOCTOR_DB_PROBE_TIMEOUT when you want the exhaustive scan.
_STATE_DB_PROBE_TIMEOUT_ENV = "HERMES_DOCTOR_DB_PROBE_TIMEOUT"

_STATE_DB_PROBE_TIMEOUT_DEFAULT = 5.0


def _state_db_probe_budget() -> float:
    """Return the state.db probe budget in seconds (env-overridable)."""
    raw = os.getenv(_STATE_DB_PROBE_TIMEOUT_ENV, "").strip()
    if not raw:
        return _STATE_DB_PROBE_TIMEOUT_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return _STATE_DB_PROBE_TIMEOUT_DEFAULT
    return value if value > 0 else _STATE_DB_PROBE_TIMEOUT_DEFAULT


# `hermes doctor --deep` additionally runs the FTS5 rank=1 'integrity-check',
# the only probe that detects an index rowid whose messages row is gone
# (external content, schema v32). It is deliberately NOT in the default run.
# Measured 2026-08-11 on a consistent snapshot of the production state.db
# (VACUUM INTO, then the v32 cutover: 4891 MB, 575,962 messages, 1.38 GB of
# indexed text; box CPU-saturated by unrelated work, so these are pessimistic):
#
#     rank=1 FTS integrity-check   70.3s first / 71.5s repeat
#     rank=0 (the weaker form)     27.4s   — detects neither failure mode
#     PRAGMA integrity_check      116.8s   — on this COMPACTED snapshot
#
# 70s against a 5s default budget is not a tuning question. And the failure
# mode it finds is bounded, invisible to searches rather than corrupting them
# (search_messages INNER JOINs messages on the index rowid, so orphans are
# filtered out), and repairable at any later time by 'rebuild' — so it does
# not earn a minute on every `hermes doctor`.
#
# First run ≈ repeat run, because the cost is tokenisation rather than I/O: a
# hot page cache bought nothing. That also means the figure is stable, unlike
# PRAGMA integrity_check — the same scan that took 116.8s compacted is the one
# documented at >12 minutes on the live, fragmented 5.1 GB file. Which is
# exactly why the two get separate budgets below.
_STATE_DB_FTS_PROBE_TIMEOUT_ENV = "HERMES_DOCTOR_FTS_PROBE_TIMEOUT"

_STATE_DB_FTS_PROBE_TIMEOUT_DEFAULT = 300.0


def _state_db_fts_probe_budget() -> float:
    """Return the --deep FTS integrity-check budget in seconds.

    Separate from the general probe budget on purpose: the two checks differ
    by an order of magnitude on the same file (70s vs >12 min), so one shared
    deadline would spend everything on ``PRAGMA integrity_check`` and report
    "unknown" for the check ``--deep`` was invoked to run.
    """
    raw = os.getenv(_STATE_DB_FTS_PROBE_TIMEOUT_ENV, "").strip()
    if not raw:
        return _STATE_DB_FTS_PROBE_TIMEOUT_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return _STATE_DB_FTS_PROBE_TIMEOUT_DEFAULT
    return value if value > 0 else _STATE_DB_FTS_PROBE_TIMEOUT_DEFAULT


# Wall-clock budget for a single `npm audit --json`. This was nominally
# bounded before, by `subprocess.run(..., timeout=30)` — but that does not
# bound the call on Windows: `npm` resolves to `npm.cmd`, so the real work
# runs in a `node.exe` GRANDCHILD which inherits the capture pipes. On
# timeout `subprocess.run` kills only the direct child and then blocks
# re-draining a pipe the surviving grandchild still holds open, so it waits
# out the grandchild regardless of the timeout. Measured: the four audits
# together spent 6m44s as a single silent gap in an ~11 minute `hermes
# doctor`, and swallowed every result. The bound is real now (see
# `_run_npm_audit`), but the audits are also no longer part of a default run:
# 40-120s per target is too slow to finish inside any budget a diagnostic can
# reasonably hold, so paying it on every run bought four "not checked"
# warnings. `hermes doctor --audit` opts in with a budget long enough that
# they actually complete. HERMES_DOCTOR_NPM_AUDIT_TIMEOUT overrides either
# budget (0 or invalid falls back).
_NPM_AUDIT_TIMEOUT_ENV = "HERMES_DOCTOR_NPM_AUDIT_TIMEOUT"

_NPM_AUDIT_TIMEOUT_DEFAULT = 30.0

# `--audit` was asked for explicitly, so the useful failure there is "it took
# ages" rather than "it gave up" — long enough for the slowest measured target
# (122s) with headroom, short enough to still terminate.
_NPM_AUDIT_TIMEOUT_ON_DEMAND = 300.0


def _npm_audit_budget(on_demand: bool = False) -> float:
    """Return the per-target `npm audit` budget in seconds (env-overridable)."""
    default = (
        _NPM_AUDIT_TIMEOUT_ON_DEMAND if on_demand else _NPM_AUDIT_TIMEOUT_DEFAULT
    )
    raw = os.getenv(_NPM_AUDIT_TIMEOUT_ENV, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _run_npm_audit(argv, *, cwd, timeout: float) -> subprocess.CompletedProcess:
    """Run one `npm audit --json`, bounded for real.

    Delegates to ``run_text_capture``, which captures into temp files rather
    than pipes. That is what makes the bound hold when npm's ``node.exe``
    grandchild outlives its parent: with no capture pipe there is no reader
    thread to drain and no handle whose close can block, so the budget does
    not depend on the tree-kill landing. Raises
    :class:`subprocess.TimeoutExpired` like ``subprocess.run`` — but note the
    helper's real bound is ``timeout + ~10s`` on Windows, because it tree-kills
    synchronously before raising and ``taskkill`` on a live ``node.exe`` tree
    measures 8-11s. A timed-out `--audit` run pays that tail once per target.
    """
    from hermes_cli._subprocess_compat import run_text_capture

    return run_text_capture(list(argv), cwd=cwd, timeout=timeout)


def _audit_npm_target(
    npm_bin, npm_dir, label, audit_extra, issues: list[str], *, on_demand: bool = False
) -> None:
    """Audit one npm target and render its result; append any finding to `issues`.

    A budget hit renders a WARN rather than nothing: the audit that motivated
    the bound spent six minutes producing no output at all, because the
    exception was swallowed by a bare `except`. It is not appended to `issues`
    — a diagnostic that could not answer is not a vulnerability finding.
    """
    from hermes_cli.doctor_report import check_ok, check_warn

    budget = _npm_audit_budget(on_demand)
    try:
        # Use resolved absolute path so Windows can execute
        # npm.cmd (CreateProcessW can't run bare .cmd names).
        audit_result = _run_npm_audit(
            [npm_bin, "audit", "--json", *audit_extra],
            cwd=str(npm_dir),
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        check_warn(
            f"{label} deps",
            f"(npm audit exceeded its {budget:.0f}s budget — not checked; "
            f"raise {_NPM_AUDIT_TIMEOUT_ENV} to wait longer)",
        )
        return
    except Exception:
        return

    try:
        import json as _json
        audit_data = _json.loads(audit_result.stdout) if audit_result.stdout.strip() else {}
        vuln_count = audit_data.get("metadata", {}).get("vulnerabilities", {})
        critical = vuln_count.get("critical", 0)
        high = vuln_count.get("high", 0)
        moderate = vuln_count.get("moderate", 0)
        total = critical + high + moderate
        # Does npm believe ANY of these can be fixed by bumping? `fixAvailable`
        # is False, True, or a {name, version, isSemVerMajor} target. A target
        # where nothing is fixable must not be handed a fix command: the
        # WhatsApp bridge's two highs (link-preview-js GHSA-4gp8-rjrq-ch6q and
        # baileys, which only inherits it) are both `fixAvailable: false`, so
        # `npm audit fix` there is a no-op that leaves the warning identical.
        # A partially-fixable set still gets the command — it clears the subset.
        # No `vulnerabilities` block at all (older npm, trimmed payload) means
        # we don't know, and we must not assert a fix we cannot evidence.
        advisories = audit_data.get("vulnerabilities") or {}
        any_fixable = any(
            bool(v.get("fixAvailable"))
            for v in advisories.values()
            if isinstance(v, dict)
        )
        # Determine a scoped fix command for the remediation hint.
        if not any_fixable:
            fix_cmd = None
        elif audit_extra and audit_extra[0] == "--workspace":
            # Detection (`npm audit --workspace <name>`) is read-only and
            # safe, but `npm audit fix --workspace <name>` crashes on
            # current npm with "Cannot read properties of null (reading
            # 'edgesOut')" — an arborist bug with workspace-filtered
            # audit fix. The root-level `npm audit fix` can crash on the
            # same tree with "isDescendantOf", so do not hand the user a
            # manual fix command for these build-tool advisories.
            fix_cmd = None
        elif audit_extra == ["--workspaces=false"]:
            fix_cmd = f"cd {npm_dir} && npm audit fix --workspaces=false"
        else:
            fix_cmd = f"cd {npm_dir} && npm audit fix"
        if total == 0:
            check_ok(f"{label} deps", "(no known vulnerabilities)")
        elif critical > 0 or high > 0:
            if fix_cmd:
                vuln_detail = (
                    f"{critical} critical, {high} high, {moderate} moderate — run: {fix_cmd}"
                )
            elif not any_fixable:
                # Say so explicitly. Silence here reads as a missing hint;
                # "no upstream fix" tells the reader the ball is not in their
                # court — the advisory stands until the dependency ships one,
                # so the answer is a mitigation or an accepted risk, not a bump.
                vuln_detail = (
                    f"{critical} critical, {high} high, {moderate} moderate — "
                    "no upstream fix available (npm reports fixAvailable: false); "
                    "needs a mitigation or an accepted-risk note, not a bump"
                )
            else:
                vuln_detail = (
                    f"{critical} critical, {high} high, {moderate} moderate — "
                    "clears via a lockfile/package bump"
                )
            check_warn(
                f"{label} deps",
                f"({vuln_detail})"
            )
            if audit_extra and audit_extra[0] == "--workspace":
                # Do NOT claim these are build-time-only. The 2026-08-11 triage
                # of this exact output found genuine runtime advisories mixed in
                # with the build tooling: react-router-dom (GHSA-qwww-vcr4-c8h2,
                # ships to the browser) in `web`, and a direct `undici` dep in
                # `ui-tui`. Blanket-labelling the block "build-time" is how they
                # went untriaged. Point at `npm audit --json --workspace <name>`
                # so the reader classifies each advisory instead of dismissing
                # the set. Manual npm remediation may error with a known arborist
                # crash (edgesOut / isDescendantOf) on this monorepo tree — that
                # is an npm bug, not a Hermes one.
                check_info(
                    "  ^ mixed build-time and runtime advisories — triage each with "
                    f"`npm audit --json --workspace {audit_extra[1]}`; remediate by "
                    "bumping the dep/override and re-resolving the lockfile "
                    "(an arborist crash from manual npm remediation is a known npm bug)"
                )
            issues.append(
                f"{label} has {total} npm "
                f"{'vulnerability' if total == 1 else 'vulnerabilities'}"
            )
        else:
            check_ok(
                f"{label} deps",
                f"({moderate} moderate "
                f"{'vulnerability' if moderate == 1 else 'vulnerabilities'})",
            )
    except Exception:
        pass


def _editable_install_cmd(spec: str) -> str:
    """The editable-install command that will actually RUN on this box.

    Delegates to ``install_doctor.reinstall_command``, which picks pip or uv
    by probing the environment instead of hardcoding either. A uv-created
    venv has no pip at all, so a hardcoded ``pip install`` prints a
    remediation that dies on "No module named pip"; hardcoding uv instead
    would fail the same way on a pip-made venv.

    Falls back to the platform hint if ``install_doctor`` cannot be
    imported, so a problem there can never take down this section.
    """
    try:
        from hermes_cli.install_doctor import reinstall_command

        return reinstall_command(spec=spec)
    except Exception:
        return f"{_python_install_cmd()} {spec}"
