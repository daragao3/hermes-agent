from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from agent.anthropic_credentials import (
    _is_oauth_token,
    refresh_anthropic_oauth_pure,
    resolve_anthropic_token,
)

def _read_codex_tokens():
    from hermes_cli.auth import _read_codex_tokens as read
    return read()


def resolve_codex_runtime_credentials(*args: Any, **kwargs: Any):
    from hermes_cli.auth import resolve_codex_runtime_credentials as resolve
    return resolve(*args, **kwargs)


def resolve_runtime_provider(*args: Any, **kwargs: Any):
    """Load provider/model catalogs only when usage actually needs credentials."""
    from hermes_cli.runtime_provider import resolve_runtime_provider as resolve

    return resolve(*args, **kwargs)

if TYPE_CHECKING:
    from typing import TypeGuard

logger = logging.getLogger(__name__)

_DEPLETED_LINE = "Status: access depleted — top up to restore"


# ---------------------------------------------------------------------------
# Lazy httpx
# ---------------------------------------------------------------------------
#
# This module used to carry ``import httpx`` at module scope, which silently
# undid the identical work already done in ``hermes_cli.auth`` (see the long
# note there): httpx 0.28.1's ``__init__`` runs ``from ._main import main``,
# dragging in click, rich and pygments for a CLI nothing here uses.
#
# MEASURED on this box 2026-08-20, and this is why it mattered:
#   ``import httpx``          7.56 s      ``import httpx._client``   4.91 s
# so the CLI subtree alone was ~2.65 s, and ``import ai_usage.__main__`` spent
# 3.67 s of its 5.02 s total inside httpx -- 73%, paid at MODULE SCOPE on every
# single run of the 5-minutely AIUsageCollector task.
#
# THE FAILURE THIS CAUSED: that task runs at Priority 7 = BELOW_NORMAL, which is
# inherited by the child. The same import measured 15.54 s at Normal against
# 475.12 s at BelowNormal (30.6x) -- longer than the task's own PT6M
# ExecutionTimeLimit, so it was killed DURING IMPORT, 145 times in 7 days.
# ``main()`` never ran, no fetch was attempted, and ``collect()``'s 90 s
# cooperative deadline never got the chance to engage and carry values forward.
# Deferring the cost past module scope is what lets ``collect()`` start, so a
# slow run now degrades to carry-forward instead of producing nothing at all.
#
# NO ``TYPE_CHECKING`` import here, unlike hermes_cli/auth.py: that module has
# seven annotation-only ``client: httpx.Client`` parameters that need the name
# for type checkers. This module has none -- all six uses are runtime calls
# inside functions that bind ``httpx`` locally -- so a TYPE_CHECKING import
# would be dead weight and ruff's F401 rejects it.
#
# WHY THROUGH THE MODULE GLOBAL rather than a plain function-local import:
# tests/agent/test_account_usage.py patches through the module attribute
# (``monkeypatch.setattr(account_usage.httpx, "Client", ...)``, 10 sites). A
# function-local import would fetch the real httpx and silently ignore that,
# turning a mocked test into a live network call. ``__getattr__`` below serves
# the attribute access by importing the real module and caching it here, so
# those tests patch exactly the object they always did.
#
# Regression test: tests/agent/test_account_usage_import_cost.py
# Mirrors: hermes_cli/auth.py (same pattern, same reason).


def _ensure_httpx():
    """Return the module-global ``httpx``, importing it on first use.

    Reads ``globals()`` rather than importing directly, so a test that has
    replaced ``agent.account_usage.httpx`` wholesale gets its replacement back.
    """
    module = globals().get("httpx")
    if module is None:
        import httpx as module

        globals()["httpx"] = module
    return module


# ---------------------------------------------------------------------------
# Cooperative budget
#
# ``ai_usage.collector.collect()`` documents a ``deadline_seconds`` bound (90s
# by default) and hands each provider the time it has left -- but only when the
# fetcher it was given declares ``budget_seconds`` (see
# ``ai_usage.collector._supports_budget``). Until 2026-08-20 this function did
# not, so ``_supports_budget`` returned False and the deadline was evaluated
# only BETWEEN providers: a single hung request could overrun it by any amount.
# The collector's own tests missed it because their fakes DO accept the budget.
#
# Accepting the parameter is not enough on its own -- that would flip
# ``_supports_budget`` to True while the bound stayed fictional. So the budget
# is clamped onto the per-request httpx timeout of every fetcher below.
_DEFAULT_USAGE_TIMEOUT = 15.0
_OPENROUTER_USAGE_TIMEOUT = 10.0

# Floor for a clamped timeout. collect() skips a provider outright once the
# budget is gone, so a value this small only shows up when a caller passes a
# near-zero budget by hand; it keeps httpx from receiving 0 or a negative.
_MIN_USAGE_TIMEOUT = 0.1


def _budgeted_timeout(default: float, budget_seconds: Optional[float]) -> float:
    """Clamp a per-request timeout down to the caller's remaining budget.

    ``None`` means "no budget in force" -- the fetcher's own default stands,
    which is what the CLI and /usage paths get.
    """
    if budget_seconds is None:
        return default
    try:
        budget = float(budget_seconds)
    except (TypeError, ValueError):
        return default
    return max(_MIN_USAGE_TIMEOUT, min(default, budget))


def __getattr__(name: str):
    """Resolve ``agent.account_usage.httpx`` on first attribute access (PEP 562).

    Keeps the module attribute that ``import httpx`` used to provide, without
    paying for it at import time.
    """
    if name == "httpx":
        return _ensure_httpx()
    if name == "AuthError":
        from hermes_cli.auth import AuthError
        return AuthError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AccountUsageWindow:
    label: str
    used_percent: Optional[float] = None
    reset_at: Optional[datetime] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class AccountUsageSnapshot:
    provider: str
    source: str
    fetched_at: datetime
    title: str = "Account limits"
    plan: Optional[str] = None
    windows: tuple[AccountUsageWindow, ...] = ()
    details: tuple[str, ...] = ()
    unavailable_reason: Optional[str] = None
    # Pay-as-you-go providers (DeepSeek) report a single outstanding-$ balance
    # instead of rolling %-windows. None for subscription/quota providers.
    balance_usd: Optional[float] = None
    balance_currency: Optional[str] = None
    # Which account the credential actually belongs to. Populated for the
    # Anthropic providers from GET /api/oauth/usage's sibling profile endpoint
    # so the collector can tell two DISTINCT subscriptions apart from two
    # tokens minted against the SAME one (see _flag_duplicate_accounts).
    account_uuid: Optional[str] = None
    account_email: Optional[str] = None

    @property
    def available(self) -> bool:
        return (
            bool(self.windows or self.details or self.balance_usd is not None)
            and not self.unavailable_reason
        )


def _snapshot(provider: str, source: str, windows: list, details: list, **kw: Any) -> AccountUsageSnapshot:
    return AccountUsageSnapshot(provider=provider, source=source, fetched_at=_utc_now(), windows=tuple(windows), details=tuple(details), **kw)


def _title_case_slug(value: Optional[str]) -> Optional[str]:
    cleaned = str(value or "").strip()
    return cleaned.replace("_", " ").replace("-", " ").title() if cleaned else None


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str) or not (text := value.strip()):
        return None
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_reset(dt: Optional[datetime]) -> str:
    if not dt:
        return "unknown"
    stamp = dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    total_seconds = int((dt - _utc_now()).total_seconds())
    if total_seconds <= 0:
        return f"now ({stamp})"
    hours, rem = divmod(total_seconds, 3600)
    minutes = rem // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"in {days}d {hours}h ({stamp})"
    return f"in {hours}h {minutes}m ({stamp})" if hours else f"in {minutes}m ({stamp})"


def render_account_usage_lines(snapshot: Optional[AccountUsageSnapshot], *, markdown: bool = False) -> list[str]:
    if not snapshot:
        return []
    bold = "**" if markdown else ""
    plan = f" ({snapshot.plan})" if snapshot.plan else ""
    lines = [f"📈 {bold}{snapshot.title}{bold}", f"Provider: {snapshot.provider}{plan}"]
    for window in snapshot.windows:
        if window.used_percent is None:
            base = f"{window.label}: unavailable"
        else:
            used = float(window.used_percent)
            base = f"{window.label}: {max(0, round(100 - used))}% remaining ({max(0, round(used))}% used)"
        if window.reset_at:
            base += f" • resets {_format_reset(window.reset_at)}"
        elif window.detail:
            base += f" • {window.detail}"
        lines.append(base)
    lines.extend(snapshot.details)
    if snapshot.unavailable_reason:
        lines.append(f"Unavailable: {snapshot.unavailable_reason}")
    return lines


def _fmt_usd(d: float) -> str:
    return f"${d:,.2f}"


def _is_num(v: Any) -> TypeGuard[float]:
    return isinstance(v, (int, float))


def _is_finite_num(v: Any) -> TypeGuard[float]:
    """True iff v is a real number (int/float, not bool, not NaN/Inf); TypeGuard so callers can do arithmetic."""
    return _is_num(v) and not isinstance(v, bool) and math.isfinite(v)


def _nous_snapshot(windows: list, details: list, tail: list, *, source: str, plan: Optional[str] = None) -> Optional[AccountUsageSnapshot]:
    """Nous snapshot with *tail* lines appended, or None when there is nothing to show."""
    if not windows and not details:
        return None
    return _snapshot("nous", source, windows, details + tail, title="Nous credits", plan=plan)


def build_nous_credits_snapshot(account_info) -> Optional[AccountUsageSnapshot]:
    """NousPortalAccountInfo → /usage snapshot: dollar magnitudes + renewal date + portal CTA, plus a ``% used``
    gauge when the portal supplies ``monthly_credits``. Fail-open → None."""
    try:
        from hermes_cli.nous_account import nous_portal_topup_url
        if account_info is None or not getattr(account_info, "logged_in", False):
            return None
        access = getattr(account_info, "paid_service_access_info", None)
        sub = getattr(account_info, "subscription", None)
        windows: list[AccountUsageWindow] = []
        details: list[str] = []
        # Gauge needs a positive cap AND a finite remaining <= cap (numeric fields, NOT a server *_usd); used =
        # cap - remaining clamped [0,100] so debt reads 100%. NaN/Inf (json.loads accepts bare NaN → "$nan") and
        # remaining > cap (rollover makes the cap a meaningless denominator) fall back to the magnitudes lines.
        if sub is not None:
            cap = getattr(sub, "monthly_credits", None)
            sub_remaining = getattr(sub, "credits_remaining", None)
            if _is_finite_num(cap) and cap > 0 and _is_finite_num(sub_remaining) and sub_remaining <= cap:
                windows.append(AccountUsageWindow(
                    label="Subscription", used_percent=max(0.0, min(100.0, (cap - sub_remaining) / cap * 100.0)),
                    detail=f"{_fmt_usd(sub_remaining)} of {_fmt_usd(cap)} left",
                ))
        if access is not None:
            for attr, label in (("subscription_credits_remaining", "Subscription credits"),
                                ("purchased_credits_remaining", "Top-up credits"), ("total_usable_credits", "Total usable")):
                value = getattr(access, attr, None)
                if _is_finite_num(value):
                    details.append(f"{label}: {_fmt_usd(value)}")
        if sub is not None:
            rollover = getattr(sub, "rollover_credits", None)
            if _is_finite_num(rollover) and rollover > 0:
                details.append(f"Rollover: {_fmt_usd(rollover)}")
            period_end = getattr(sub, "current_period_end", None)
            if period_end:
                details.append(f"Renews: {period_end}")
        if getattr(account_info, "paid_service_access", None) is False:
            details.append(_DEPLETED_LINE)
        return _nous_snapshot(windows, details, [f"Top up: {nous_portal_topup_url(account_info)}", "(or run /topup)"],
                              source="portal-account", plan=getattr(sub, "plan", None) if sub is not None else None)
    except (AttributeError, TypeError):
        return None


def _nous_logged_in() -> bool:
    """Cheap local auth-state check: a Nous access token is present. Fail-open False."""
    try:
        from hermes_cli.auth import get_provider_auth_state
        tok = (get_provider_auth_state("nous") or {}).get("access_token")
        return isinstance(tok, str) and bool(tok.strip())
    except Exception:
        return False


def _fetch_portal_account(timeout: float):
    """Wall-clock-bounded fresh portal account fetch (raises on any failure/timeout)."""
    import concurrent.futures
    from hermes_cli.nous_account import get_nous_portal_account_info
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(get_nous_portal_account_info, force_fresh=True).result(timeout=timeout)


def nous_credits_lines(*, markdown: bool = False, timeout: float = 10.0) -> list[str]:
    """Rendered Nous-credits /usage lines, or [] when there's nothing to show. Independent of any live agent
    (logged-in gate, then a bounded portal fetch); shared by CLI ``_show_usage`` and the TUI ``session.usage`` RPC.
    Fail-open: any hiccup or timeout → []. HERMES_DEV_CREDITS_FIXTURE renders from the fixture instead of the portal."""
    try:
        from agent.credits_tracker import dev_fixture_credits_state
        fixture = dev_fixture_credits_state()
    except Exception:
        fixture = None
    if fixture is not None:
        return render_account_usage_lines(_snapshot_from_credits_state(fixture), markdown=markdown)
    if not _nous_logged_in():
        return []
    try:
        snapshot = build_nous_credits_snapshot(_fetch_portal_account(timeout))
        return render_account_usage_lines(snapshot, markdown=markdown)
    except Exception:
        # Fail-open; breadcrumb so a dead /usage credits block is diagnosable.
        logger.debug("credits ▸ /usage portal fetch/render failed (fail-open)", exc_info=True)
        return []


def _snapshot_from_credits_state(state) -> Optional[AccountUsageSnapshot]:
    """Header-shaped CreditsState (dev fixture) → /usage snapshot, same shape as the portal path. *_usd strings
    are display-only; the % comes from CreditsState.used_fraction. Fail-open → None."""
    try:
        if state is None:
            return None
        windows: list[AccountUsageWindow] = []
        details: list[str] = []
        uf = getattr(state, "used_fraction", None)
        sub_usd = getattr(state, "subscription_usd", None)
        cap_usd = getattr(state, "subscription_limit_usd", None)
        if _is_num(uf) and math.isfinite(uf):
            windows.append(AccountUsageWindow(
                label="Subscription", used_percent=max(0.0, min(100.0, uf * 100.0)),
                detail=f"${sub_usd} of ${cap_usd} left" if sub_usd and cap_usd else None,
            ))
        for value, label in ((sub_usd, "Subscription credits"), (getattr(state, "purchased_usd", None), "Top-up credits"),
                             (getattr(state, "remaining_usd", None), "Total usable")):
            if value:
                details.append(f"{label}: ${value}")
        if getattr(state, "paid_access", True) is False:
            details.append(_DEPLETED_LINE)
        return _nous_snapshot(windows, details, ["(dev fixture — HERMES_DEV_CREDITS_FIXTURE)"], source="dev-fixture")
    except (AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class CreditsView:
    """Surface-agnostic ``/topup`` balance view: one portal fetch, consumed identically by every money surface.
    Fail-open: not logged in / portal unreachable → ``logged_in`` False, ``topup_url`` None."""

    logged_in: bool
    balance_lines: tuple[str, ...] = ()
    identity_line: Optional[str] = None
    topup_url: Optional[str] = None
    depleted: bool = False


def build_credits_view(*, markdown: bool = False, timeout: float = 10.0) -> CreditsView:
    """/topup view: balance block + identity line + top-up URL. Reuses the /usage fetch + snapshot so numbers
    match; the balance block drops the trailing top-up/hint lines (/topup has its own affordance).
    Fail-open → ``CreditsView(logged_in=False)``."""
    not_logged_in = CreditsView(logged_in=False)
    if not _nous_logged_in():
        return not_logged_in
    try:
        account = _fetch_portal_account(timeout)
    except Exception:
        logger.debug("credits ▸ /topup portal fetch failed (fail-open)", exc_info=True)
        return not_logged_in
    if account is None or not getattr(account, "logged_in", False):
        return not_logged_in
    from hermes_cli.nous_account import nous_portal_topup_url
    balance_lines = [
        line
        for line in render_account_usage_lines(build_nous_credits_snapshot(account), markdown=markdown)
        if not line.lstrip().startswith(("Top up:", "(or run"))
    ]
    who = [str(v) for v in (getattr(account, "email", None),) if v]
    org_name = getattr(account, "org_name", None)
    if org_name:
        who.append(f"org {org_name}")
    return CreditsView(
        logged_in=True, balance_lines=tuple(balance_lines),
        identity_line=("Topping up as " + " / ".join(who)) if who else None, topup_url=nous_portal_topup_url(account),
        depleted=getattr(account, "paid_service_access", None) is False,
    )


def _codex_backend_urls(base_url: str) -> tuple[str, str, str]:
    """Codex backend endpoints (usage, reset-credits list, consume). Mirrors the Codex CLI's PathStyle
    split: ``/backend-api`` bases use the ChatGPT ``/wham/`` paths; everything else ``/api/codex/``."""
    normalized = (base_url or "").strip().rstrip("/") or "https://chatgpt.com/backend-api/codex"
    normalized = normalized.removesuffix("/codex")
    prefix = normalized + ("/wham" if "/backend-api" in normalized else "/api/codex")
    return (prefix + "/usage", prefix + "/rate-limit-reset-credits", prefix + "/rate-limit-reset-credits/consume")


def _resolve_codex_usage_credentials(
    base_url: Optional[str], api_key: Optional[str],
) -> tuple[str, str, Optional[str]]:
    """Codex quota credentials: explicit live-agent creds → native runtime resolver (itself pool-aware) → direct
    pool select. Native OAuth stores device-code logins in the pool, so the singleton store alone is not enough."""
    from hermes_cli.auth import AuthError

    explicit_key = str(api_key or "").strip()
    if explicit_key:
        return explicit_key, str(base_url or "").strip(), None
    # Only AuthError is caught so tier 3 can run: a broad except would mask a transient refresh/network failure
    # and hand back a DIFFERENT pool account's usage; such errors must propagate to the fail-open outer guard.
    # account_id is best-effort: a partial singleton store must not sink a usable credential.
    try:
        # Tier 2: the native runtime resolver. It ALREADY falls back to the credential pool when the
        # singleton is empty (see ``resolve_codex_runtime_credentials`` — issue #32992), so in a pool-only
        # setup this returns a usable ``source="credential_pool"`` token. A refresh/network error must
        # propagate — the outer ``fetch_account_usage`` guard fails open (shows nothing this turn) rather
        # than reporting the wrong account.
        creds = resolve_codex_runtime_credentials(refresh_if_expiring=True)
        account_id: Optional[str] = None
        try:
            tokens = _read_codex_tokens().get("tokens") or {}
            account_id = str(tokens.get("account_id", "") or "").strip() or None
        except AuthError:
            # Pool-only creds carry no singleton account_id; header is optional.
            logger.debug("codex ▸ /usage account_id read failed (best-effort)", exc_info=True)
        return creds["api_key"], str(creds.get("base_url", "") or "").strip(), account_id
    except AuthError:
        logger.debug("codex ▸ /usage runtime resolver returned no creds; trying pool", exc_info=True)
    # Tier 3: pool credentials have no account_id concept → header omitted.
    from agent.credential_pool import load_pool
    entry = load_pool("openai-codex").select()
    if entry is None:
        raise RuntimeError("No available openai-codex credential in credential pool")
    return entry.runtime_api_key, str(entry.runtime_base_url or base_url or "").strip(), None


# A day, in seconds — the split between Codex's 5h "Session" window and its
# 7-day "Weekly" window. Codex reorders these across slots (when the weekly cap
# is reached it moves the 7-day window into primary_window and nulls
# secondary_window), so the label must come from the window's own duration, not
# its slot position.
_CODEX_SESSION_MAX_SECONDS = 86400


def _codex_window_label(window: dict, fallback_label: str) -> str:
    secs = window.get("limit_window_seconds")
    if isinstance(secs, (int, float)):
        return "Session" if secs < _CODEX_SESSION_MAX_SECONDS else "Weekly"
    return fallback_label


def _codex_banked_resets(payload: dict) -> int:
    raw = (payload.get("rate_limit_reset_credits") or {}).get("available_count")
    return int(raw) if _is_num(raw) else 0


def _codex_headers(token: str, account_id: Optional[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "codex-cli",
            **({"ChatGPT-Account-Id": account_id} if account_id else {})}


def _get_json(url: str, headers: dict[str, str], *, timeout: float) -> dict:
    with _ensure_httpx().Client(timeout=timeout) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
    return response.json() or {}


def _usage_windows(
    source: dict, mapping: tuple[tuple[str, str], ...], used_key: str, reset_key: str, *, fraction: bool = False
) -> list[AccountUsageWindow]:
    """Build windows from ``source[key][used_key]``; ``fraction`` scales values <= 1 to percent."""
    windows: list[AccountUsageWindow] = []
    for key, label in mapping:
        window = source.get(key) or {}
        used = window.get(used_key)
        if used is None:
            continue
        used = float(used)
        if fraction and used <= 1:
            used *= 100
        windows.append(AccountUsageWindow(label=label, used_percent=used, reset_at=_parse_dt(window.get(reset_key))))
    return windows


def _plural(count: int) -> str:
    return "s" if count != 1 else ""


def _fetch_codex_account_usage(
    base_url: Optional[str] = None, api_key: Optional[str] = None,
    *, timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    token, resolved_base_url, account_id = _resolve_codex_usage_credentials(base_url, api_key)
    payload = _get_json(_codex_backend_urls(resolved_base_url)[0], _codex_headers(token, account_id), timeout=timeout)
    rate_limit = payload.get("rate_limit") or {}
    mapping = tuple((key, _codex_window_label(rate_limit.get(key) or {}, label))
                    for key, label in (("primary_window", "Session"), ("secondary_window", "Weekly")))
    windows = _usage_windows(rate_limit, mapping, "used_percent", "reset_at")
    details: list[str] = []
    count = _codex_banked_resets(payload)
    if count > 0:
        details.append(f"You have {count} reset{_plural(count)} banked - use /usage reset to activate")
    credits, balance = payload.get("credits") or {}, (payload.get("credits") or {}).get("balance")
    if credits.get("has_credits") and _is_num(balance):
        details.append(f"Credits balance: ${float(balance):.2f}")
    elif credits.get("has_credits") and credits.get("unlimited"):
        details.append("Credits balance: unlimited")
    return _snapshot("openai-codex", "usage_api", windows, details, plan=_title_case_slug(payload.get("plan_type")))


@dataclass(frozen=True)
class CodexResetRedeemResult:
    """Outcome of a `/usage reset` attempt against the Codex backend."""

    status: str  # reset|nothing_to_reset|no_credit|already_redeemed|not_exhausted|no_credits_banked|unavailable
    message: str
    available_count: int = 0
    windows_reset: int = 0

    @property
    def redeemed(self) -> bool:
        return self.status == "reset"


# Client-side guard: a window only counts as exhausted when fully used; below this, redeeming a banked reset
# wastes most of its value → block, point at --force.
_CODEX_WINDOW_EXHAUSTED_PERCENT = 100.0


def _unavailable(message: str) -> CodexResetRedeemResult:
    return CodexResetRedeemResult(status="unavailable", message=message)


def _codex_reset_guard(payload: dict, available: int, force: bool) -> Optional[CodexResetRedeemResult]:
    """Refuse a redemption that would be wasted (no banked credits, or no window fully used and not ``force``)."""
    if available <= 0:
        return CodexResetRedeemResult(status="no_credits_banked", message="No banked reset credits on this account — nothing to redeem.")
    rate_limit = payload.get("rate_limit") or {}
    used_pcts = [float(u) for u in ((rate_limit.get(k) or {}).get("used_percent") for k in ("primary_window", "secondary_window"))
                 if _is_num(u)]
    worst_used: Optional[float] = max(0.0, *used_pcts) if used_pcts else None
    if force or (worst_used is not None and worst_used >= _CODEX_WINDOW_EXHAUSTED_PERCENT):
        return None
    usage_note = (f"your busiest window is only {worst_used:.0f}% used" if worst_used is not None
                  else "your current usage could not be confirmed as exhausted")
    return CodexResetRedeemResult(
        status="not_exhausted", available_count=available,
        message=(f"⚠️ Not redeeming: {usage_note}. A banked reset restores your FULL 5h + weekly limits, so spending it "
                 f"now would waste most of it. You have {available} reset{_plural(available)} banked. "
                 f"Use `/usage reset --force` to redeem anyway."),
    )


def _codex_reset_outcome(body: dict, available: int) -> CodexResetRedeemResult:
    """Map the consume response ``code`` to a result (``reset`` also lifts persisted pool cooldowns)."""
    code = str(body.get("code", "") or "").strip().lower()
    remaining = max(0, available - 1)
    outcomes: dict[str, tuple[str, int]] = {
        "reset": (f"✅ Reset redeemed — your usage limits have been reset. {remaining} banked reset{_plural(remaining)} remaining.",
                  remaining),
        "nothing_to_reset": ("Backend reports nothing to reset — your limits aren't exhausted. The credit was NOT spent.", available),
        "no_credit": ("Backend reports no available reset credit on this account.", 0),
        "already_redeemed": ("This redemption was already processed — no additional credit was spent.", remaining),
    }
    if code not in outcomes:
        return _unavailable(f"Unexpected response from the Codex backend: {body!r}")
    windows_reset = 0
    if code == "reset":
        # Quota is restored upstream — lift persisted pool cooldowns so the credential isn't frozen behind a
        # stale ``last_error_reset_at``.
        try:
            from hermes_cli.auth import clear_codex_pool_quota_cooldowns
            clear_codex_pool_quota_cooldowns()
        except Exception:
            logger.debug("Failed to clear Codex pool cooldowns after reset redemption", exc_info=True)
        raw = body.get("windows_reset")
        windows_reset = int(raw) if _is_num(raw) else 0
    message, count = outcomes[code]
    return CodexResetRedeemResult(status=code, message=message, available_count=count, windows_reset=windows_reset)


def redeem_codex_reset_credit(
    *, base_url: Optional[str] = None, api_key: Optional[str] = None, force: bool = False,
) -> CodexResetRedeemResult:
    """Redeem one banked Codex rate-limit reset credit (`/usage reset`), mirroring the Codex CLI picker: GET usage →
    guard (a reset restores the WHOLE 5h + weekly allowance, and the backend's own ``nothing_to_reset`` guard is
    less clear) → POST consume with a fresh UUID ``redeem_request_id`` and no ``credit_id`` (the backend picks the
    next credit). Never raises: every failure returns a result."""
    import uuid

    httpx = _ensure_httpx()
    try:
        token, resolved_base_url, account_id = _resolve_codex_usage_credentials(base_url, api_key)
    except Exception:
        return _unavailable("No Codex credentials available. Run `hermes auth` to sign in with your ChatGPT account.")
    usage_url, _credits_url, consume_url = _codex_backend_urls(resolved_base_url)
    headers = _codex_headers(token, account_id)
    try:
        with httpx.Client(timeout=15.0) as client:
            usage_resp = client.get(usage_url, headers=headers)
            usage_resp.raise_for_status()
            payload = usage_resp.json() or {}
            available = _codex_banked_resets(payload)
            refused = _codex_reset_guard(payload, available, force)
            if refused is not None:
                return refused
            consume_resp = client.post(
                consume_url, headers={**headers, "Content-Type": "application/json"},
                json={"redeem_request_id": str(uuid.uuid4())},
            )
            consume_resp.raise_for_status()
            body = consume_resp.json() or {}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            return _unavailable(f"Codex backend rejected the request (HTTP {code}). Reset credits require ChatGPT-account "
                                "(OAuth) auth — run `hermes auth` and sign in with your ChatGPT account.")
        return _unavailable(f"Codex backend error (HTTP {code}) — try again shortly.")
    except Exception as exc:
        return _unavailable(f"Could not reach the Codex backend: {exc}")
    return _codex_reset_outcome(body, available)


def _fetch_anthropic_account_identity(
    client: Any, headers: dict
) -> tuple[Optional[str], Optional[str]]:
    """Resolve which account an OAuth token belongs to (uuid, email).

    ``/api/oauth/profile`` is the sibling of the usage endpoint and needs the
    same ``user:profile`` scope, so a token that can read usage can always read
    this. Best-effort: any failure returns ``(None, None)`` rather than losing
    the usage numbers we already fetched successfully.

    Exists so the collector can distinguish two DISTINCT subscriptions from two
    tokens minted against the SAME account -- the 2026-08-23 defect where the
    tray's "Claude" and "Claude 2" rows both reported the SAME account email
    (identical percentages) because the isolated ~/.claude-anthropic2 login
    landed on the already-signed-in browser account. Which address it was does
    not matter to the mechanism and is not recorded here: this file is tracked.
    """
    try:
        response = client.get(
            "https://api.anthropic.com/api/oauth/profile", headers=headers
        )
        response.raise_for_status()
        account = (response.json() or {}).get("account") or {}
    except Exception as exc:  # noqa: BLE001 - identity is advisory, never fatal
        logger.debug("anthropic profile lookup failed: %s", exc)
        return None, None
    uuid = str(account.get("uuid") or "").strip() or None
    email = str(account.get("email") or "").strip() or None
    return uuid, email


def _fetch_anthropic_usage_with_token(
    token: str,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
    provider: str = "anthropic",
) -> Optional[AccountUsageSnapshot]:
    """Query GET /api/oauth/usage with one explicit OAuth token.

    Shared by ``_fetch_anthropic_account_usage`` (primary account via
    ``resolve_anthropic_token()``) and ``_fetch_anthropic2_account_usage``
    (second subscription via its isolated login profile). NOTE: the token
    must carry the ``user:profile`` scope -- a full ``claude auth login``
    OAuth credential does. ``claude setup-token`` tokens are deliberately
    inference-only and get 403 ``permission_error`` here (verified live
    2026-08-23), so they are NOT a valid credential source for usage.
    """
    httpx = _ensure_httpx()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/2.1.0",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get("https://api.anthropic.com/api/oauth/usage", headers=headers)
        response.raise_for_status()
        account_uuid, account_email = _fetch_anthropic_account_identity(client, headers)
    payload = response.json() or {}
    windows = _usage_windows(
        payload, (("five_hour", "Current session"), ("seven_day", "Current week"),
                  ("seven_day_opus", "Opus week"), ("seven_day_sonnet", "Sonnet week")),
        "utilization", "resets_at", fraction=True,
    )
    details: list[str] = []
    extra = payload.get("extra_usage") or {}
    if extra.get("is_enabled"):
        used_credits = extra.get("used_credits")
        monthly_limit = extra.get("monthly_limit")
        currency = extra.get("currency") or "USD"
        if isinstance(used_credits, (int, float)) and isinstance(monthly_limit, (int, float)):
            details.append(
                f"Extra usage: {used_credits:.2f} / {monthly_limit:.2f} {currency}"
            )
    return AccountUsageSnapshot(
        provider=provider,
        source="oauth_usage_api",
        fetched_at=_utc_now(),
        windows=tuple(windows),
        details=tuple(details),
        account_uuid=account_uuid,
        account_email=account_email,
    )


def _fetch_anthropic_account_usage(
    *, timeout: float = _DEFAULT_USAGE_TIMEOUT
) -> Optional[AccountUsageSnapshot]:
    """Primary subscription's usage.

    Prefers the PINNED isolated profile ``~/.claude-anthropic1`` when it
    exists. ``resolve_anthropic_token()`` ultimately reads ``~/.claude``, which
    follows whichever account the desktop app is signed into -- so this row
    used to change subject on every account switch. On 2026-08-23 14:18 the
    primary flipped to the second subscription's account and this row silently
    became a duplicate of "Claude 2". Pinning fixes the subject; the fallback
    keeps the row working on a box that has never created the profile.
    """
    if _read_anthropic1_credentials() is not None:
        return _fetch_pinned_profile_usage(
            "anthropic",
            read=lambda: _read_anthropic1_credentials(),
            write=lambda *a, **kw: _write_anthropic1_credentials(*a, **kw),
            timeout=timeout,
        )
    token = (resolve_anthropic_token() or "").strip()
    if not token:
        return None
    if not _is_oauth_token(token):
        return AccountUsageSnapshot(
            provider="anthropic",
            source="oauth_usage_api",
            fetched_at=_utc_now(),
            unavailable_reason="Anthropic account limits are only available for OAuth-backed Claude accounts.",
        )
    return _fetch_anthropic_usage_with_token(token, timeout=timeout)


# Isolated login profiles, one per tracked subscription. ~/.claude is NOT used
# for either row's identity: it follows whichever account the desktop app is
# signed into, so a row sourced from it changes subject on every account switch.
_ANTHROPIC1_CONFIG_DIR = Path.home() / ".claude-anthropic1"
_ANTHROPIC2_CONFIG_DIR = Path.home() / ".claude-anthropic2"


def _read_anthropic1_credentials(
    config_dir: Optional[Path] = None,
) -> Optional[dict]:
    """OAuth credentials for the PRIMARY subscription's pinned profile."""
    return _read_profile_credentials(config_dir or _ANTHROPIC1_CONFIG_DIR)


def _write_anthropic1_credentials(
    access_token: str,
    refresh_token: str,
    expires_at_ms: int,
    *,
    scopes: Optional[list] = None,
) -> None:
    _write_profile_credentials(
        _ANTHROPIC1_CONFIG_DIR,
        access_token,
        refresh_token,
        expires_at_ms,
        scopes=scopes,
    )


def _read_anthropic2_credentials(
    config_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Read OAuth credentials from the isolated anthropic2 Claude Code profile.

    The second subscription logs in once via ``CLAUDE_CONFIG_DIR``-isolated
    ``claude auth login``, which writes the same ``.credentials.json`` shape as
    the primary profile -- full OAuth scopes including ``user:profile`` (which
    ``claude setup-token`` tokens lack and which /api/oauth/usage requires).

    Returns {accessToken, refreshToken, expiresAt, scopes} or None.
    """
    return _read_profile_credentials(config_dir or _ANTHROPIC2_CONFIG_DIR)


def _read_profile_credentials(config_dir: Path) -> Optional[dict]:
    """Read an isolated Claude Code profile's OAuth block, or None.

    Returns {accessToken, refreshToken, expiresAt, scopes}. A missing or
    unreadable profile is None (unconfigured row), never an exception.
    """
    cred_path = config_dir / ".credentials.json"
    try:
        data = json.loads(cred_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    if not str(oauth.get("accessToken", "") or "").strip():
        return None
    return oauth


def _fetch_pinned_profile_usage(
    provider: str,
    *,
    read: Callable[[], Optional[dict]],
    write: Callable[..., None],
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    """Usage for one Anthropic account PINNED to an isolated login profile.

    Credential source: an isolated ``CLAUDE_CONFIG_DIR`` profile's
    ``.credentials.json`` (one-time ``claude /login``), NOT an env token --
    `claude setup-token` tokens are inference-only and get 403 on the usage
    endpoint (verified live 2026-08-23). Missing profile → None, so the row
    degrades to unconfigured rather than erroring every cycle.

    Pinning is the point: ``~/.claude`` follows whichever account the desktop
    app is currently signed into, so a row sourced from it silently changes
    subject on every account switch (observed 2026-08-23 14:18, when the
    primary flipped to the second subscription's account and collapsed onto
    the "Claude 2" row). An isolated profile keeps one row on one account.

    Expired access tokens are refreshed in place with the profile's own
    refresh token. Refresh tokens are SINGLE-USE rotating: a successful
    refresh invalidates the old one, so the new pair is written back to the
    profile file immediately -- losing it would force a manual re-login.
    """
    creds = read()
    if creds is None:
        return None

    token = str(creds.get("accessToken") or "").strip()
    if not _is_oauth_token(token):
        return AccountUsageSnapshot(
            provider=provider,
            source="oauth_usage_api",
            fetched_at=_utc_now(),
            unavailable_reason="Isolated profile credential is not an OAuth token; re-run the one-time `claude auth login` for this account.",
        )

    expires_at_ms = int(creds.get("expiresAt") or 0)
    now_ms = int(time.time() * 1000)
    if now_ms >= (expires_at_ms - 60_000):
        # Access token expired (or expiry unknown/zero): try a refresh before
        # giving up. Mirrors anthropic_adapter.is_claude_code_token_valid's
        # 60s clock-skew buffer.
        refresh_token = str(creds.get("refreshToken") or "").strip()
        if not refresh_token:
            return AccountUsageSnapshot(
                provider=provider,
                source="oauth_usage_api",
                fetched_at=_utc_now(),
                unavailable_reason="Access token expired and the isolated profile holds no refresh token; re-run the one-time `claude auth login`.",
            )
        try:
            refreshed = refresh_anthropic_oauth_pure(refresh_token)
        except Exception as exc:
            logger.debug("%s token refresh failed: %s", provider, exc)
            return AccountUsageSnapshot(
                provider=provider,
                source="oauth_usage_api",
                fetched_at=_utc_now(),
                unavailable_reason="Token refresh failed (refresh token may have been rotated elsewhere); re-run the one-time `claude auth login`.",
            )
        token = str(refreshed["access_token"]).strip()
        # Persist the rotated pair FIRST — single-use refresh tokens die with
        # the POST, so a crash between refresh and write would strand the
        # profile. Scopes are preserved from the existing file when the
        # response omits them (Claude Code gates on user:inference there).
        write(
            refreshed["access_token"],
            refreshed["refresh_token"],
            refreshed["expires_at_ms"],
            scopes=creds.get("scopes"),
        )

    return _fetch_anthropic_usage_with_token(token, timeout=timeout, provider=provider)


def _fetch_anthropic2_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    """Second Anthropic subscription, pinned to ``~/.claude-anthropic2``."""
    del base_url  # dispatcher passes it; this fetcher has no alternate host
    # Late-bound through the module globals so tests can monkeypatch either.
    return _fetch_pinned_profile_usage(
        "anthropic2",
        read=lambda: _read_anthropic2_credentials(),
        write=lambda *a, **kw: _write_anthropic2_credentials(*a, **kw),
        timeout=timeout,
    )


def _write_anthropic2_credentials(
    access_token: str,
    refresh_token: str,
    expires_at_ms: int,
    *,
    scopes: Optional[list] = None,
) -> None:
    """Write the rotated OAuth pair back to the isolated profile.

    Atomic temp-file + rename, 0600-equivalent via os.open flags, mirroring
    anthropic_adapter._write_claude_code_credentials but against the isolated
    config dir. Existing non-oauth top-level fields are preserved.
    """
    _write_profile_credentials(
        _ANTHROPIC2_CONFIG_DIR,
        access_token,
        refresh_token,
        expires_at_ms,
        scopes=scopes,
    )


def _write_profile_credentials(
    config_dir: Path,
    access_token: str,
    refresh_token: str,
    expires_at_ms: int,
    *,
    scopes: Optional[list] = None,
) -> None:
    """Atomically write a rotated OAuth pair into an isolated profile."""
    cred_path = config_dir / ".credentials.json"
    existing: dict = {}
    try:
        if cred_path.exists():
            existing = json.loads(cred_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        existing = {}

    oauth_data: dict = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    if scopes is not None:
        oauth_data["scopes"] = scopes
    elif "claudeAiOauth" in existing and "scopes" in existing["claudeAiOauth"]:
        oauth_data["scopes"] = existing["claudeAiOauth"]["scopes"]
    existing["claudeAiOauth"] = oauth_data

    payload = json.dumps(existing, indent=2)
    config_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = cred_path.with_suffix(".json.tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(str(tmp_path), str(cred_path))
    except Exception:
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
        raise


def _fetch_opencode_go_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    """OpenCode Go rolling/weekly/monthly % from GET /zen/go/v1/usage.

    Undocumented but official endpoint (source of truth: oc-src
    packages/console/app/src/routes/zen/go/v1/usage.ts). Live shape:
      {"usage":{"rolling":{"status":"ok","percent":12,"resetsAt":"...Z"},
                "weekly":{...}, "monthly":{...}}}
    Cloudflare fronts opencode.ai and 1010s the default python UA; a plain
    product UA passes.
    """
    key = str(api_key or os.environ.get("OPENCODE_GO_API_KEY", "") or "").strip()
    if not key:
        return None
    url = (str(base_url or "").strip() or "https://opencode.ai").rstrip("/")
    httpx = _ensure_httpx()
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        # NOT httpx's default python UA -- Cloudflare 1010s it (verified live).
        "User-Agent": "opencode/1.0",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(f"{url}/zen/go/v1/usage", headers=headers)
        response.raise_for_status()
    payload = response.json() or {}
    windows: list[AccountUsageWindow] = []
    for name, label in (("rolling", "Rolling"), ("weekly", "Weekly"), ("monthly", "Monthly")):
        entry = (payload.get("usage") or {}).get(name) or {}
        percent = entry.get("percent")
        if percent is None:
            continue
        windows.append(
            AccountUsageWindow(
                label=label,
                used_percent=float(percent),
                reset_at=_parse_dt(entry.get("resetsAt")),
            )
        )
    return AccountUsageSnapshot(
        provider="opencode-go",
        source="usage_api",
        fetched_at=_utc_now(),
        windows=tuple(windows),
    )


def _fetch_gemini_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
    budget_seconds: Optional[float] = None,
) -> Optional[AccountUsageSnapshot]:
    """Gemini budget usage scraped from AI Studio's apikey page over CDP.

    Google exposes no usage API for Gemini API billing, but AI Studio's own
    "API keys" page calls internal MakerSuiteService RPCs whose responses
    carry month-to-date spend vs the account budget (verified 2026-08-23:
    BatchGetProjectUsageLimits -> [["USD",null,<micros>],["USD","<budget>"]]).
    agent/gemini_session.py drives an existing aistudio.google.com tab over
    CDP (:9222) and reads those response bodies passively -- no replay, no
    cookie decryption. Browser down / logged out / shape changed -> None ->
    the row shows no data instead of erroring every cycle.

    ``budget_seconds`` threads through so the scraper may spend one backoff +
    settle window on a fresh-tab retry when the collector can afford it.
    """
    try:
        from agent.gemini_session import fetch_gemini_budget_usage
    except ImportError:
        return None
    result = fetch_gemini_budget_usage(
        timeout=timeout, budget_seconds=budget_seconds
    )
    if not result:
        return None
    used_pct, budget_usd = result
    return AccountUsageSnapshot(
        provider="gemini",
        source="web_scrape",
        fetched_at=_utc_now(),
        windows=(
            AccountUsageWindow(
                label="Monthly",
                used_percent=max(0.0, min(100.0, float(used_pct))),
                detail=f"${budget_usd:.0f} budget" if budget_usd else None,
            ),
        ),
    )


def _fetch_grok_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    """Grok rate-limit window scraped from grok.com's own web session.

    api.x.ai exposes no usage endpoint and the XAI_API_KEY on this box is
    team_blocked, so the only automated source is the same POST /rest/
    rate-limits call grok.com's web app makes -- which needs that tab's
    session cookies. We therefore run the fetch INSIDE a logged-in grok.com
    tab over CDP (:9222), so Chrome attaches its own cookies; nothing here
    reads or decrypts cookie files. Not logged in / Chrome down -> None ->
    the row shows no data instead of erroring every cycle.
    """
    try:
        from agent.grok_session import fetch_grok_rate_limits
    except ImportError:
        return None
    result = fetch_grok_rate_limits(base_url=base_url, timeout=timeout)
    if not result:
        return None
    remaining, total, reset_at = result
    if total <= 0:
        return None
    used_pct = max(0.0, min(100.0, 100.0 * (1.0 - float(remaining) / float(total))))
    return AccountUsageSnapshot(
        provider="xai",
        source="web_scrape",
        fetched_at=_utc_now(),
        windows=(
            AccountUsageWindow(
                label="Grok window",
                used_percent=used_pct,
                reset_at=reset_at,
            ),
        ),
    )


def _fetch_openrouter_account_usage(
    base_url: Optional[str],
    api_key: Optional[str],
    *,
    timeout: float = _OPENROUTER_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    httpx = _ensure_httpx()
    runtime = resolve_runtime_provider(
        requested="openrouter",
        explicit_base_url=base_url,
        explicit_api_key=api_key,
    )
    token = str(runtime.get("api_key", "") or "").strip()
    if not token:
        return None
    normalized = str(runtime.get("base_url", "") or "").rstrip("/")
    credits_url = f"{normalized}/credits"
    key_url = f"{normalized}/key"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    started = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        credits_resp = client.get(credits_url, headers=headers)
        credits_resp.raise_for_status()
        credits = (credits_resp.json() or {}).get("data") or {}
        try:
            # The budget covers BOTH calls, so the key call only gets what the
            # credits call left. Overrunning here is the failure this clamp
            # exists to prevent; the balance is already in hand, and key_data
            # is optional -- an empty one just omits the quota window below.
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("usage budget spent on the credits call")
            key_resp = client.get(key_url, headers=headers, timeout=remaining)
            key_resp.raise_for_status()
            key_data = (key_resp.json() or {}).get("data") or {}
        except Exception:
            key_data = {}
    balance = float(credits.get("total_credits") or 0.0) - float(credits.get("total_usage") or 0.0)
    details = [f"Credits balance: ${max(0.0, balance):.2f}"]
    windows: list[AccountUsageWindow] = []
    limit, limit_remaining, usage = key_data.get("limit"), key_data.get("limit_remaining"), key_data.get("usage")
    limit_reset = str(key_data.get("limit_reset") or "").strip()
    if _is_num(limit) and float(limit) > 0 and _is_num(limit_remaining) and 0 <= float(limit_remaining) <= float(limit):
        limit_value, remaining_value = float(limit), float(limit_remaining)
        detail_parts = [f"${remaining_value:.2f} of ${limit_value:.2f} remaining", *([f"resets {limit_reset}"] if limit_reset else [])]
        windows.append(AccountUsageWindow(label="API key quota", used_percent=((limit_value - remaining_value) / limit_value) * 100,
                                          detail=" • ".join(detail_parts)))
    if _is_num(usage):
        usage_parts = [f"API key usage: ${float(usage):.2f} total"]
        for key, label in (("usage_daily", "today"), ("usage_weekly", "this week"), ("usage_monthly", "this month")):
            value = key_data.get(key)
            if _is_num(value) and float(value) > 0:
                usage_parts.append(f"${float(value):.2f} {label}")
        details.append(" • ".join(usage_parts))
    return _snapshot("openrouter", "credits_api", windows, details)


def _kimi_usage_url(base_url: Optional[str]) -> str:
    base = str(base_url or "https://api.kimi.com/coding").strip().rstrip("/")
    return f"{base}/usages" if base.endswith("/v1") else f"{base}/v1/usages"


def _resolve_kimi_usage_credentials(
    base_url: Optional[str],
    api_key: Optional[str],
) -> tuple[str, str]:
    """Resolve Kimi Code quota credentials: explicit → env → credential pool.

    Kimi Code has no OAuth singleton; the collector runs headless, so fall
    back to ``KIMI_API_KEY`` and finally the ``kimi-coding`` credential pool
    (auth.json) the way the Codex resolver falls back to its pool.
    """
    explicit = str(api_key or "").strip()
    if explicit:
        return explicit, str(base_url or "").strip()
    env_key = str(os.environ.get("KIMI_API_KEY", "") or "").strip()
    if env_key:
        return env_key, str(base_url or "").strip()
    from agent.credential_pool import load_pool

    pool = load_pool("kimi-coding")
    entry = pool.select()
    if entry is None:
        raise RuntimeError("No available kimi-coding credential in credential pool")
    return entry.runtime_api_key, str(entry.runtime_base_url or base_url or "").strip()


def _kimi_int(value: Any) -> Optional[int]:
    # /coding/v1/usages returns quota counts as strings ("100", "70").
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _kimi_window_seconds(window: Any) -> Optional[int]:
    if not isinstance(window, dict):
        return None
    duration = _kimi_int(window.get("duration"))
    if not duration or duration <= 0:
        return None
    unit = str(window.get("timeUnit") or window.get("time_unit") or "").upper()
    if "HOUR" in unit:
        return duration * 3600
    if "MINUTE" in unit:
        return duration * 60
    if "DAY" in unit:
        return duration * 86400
    if "SECOND" in unit:
        return duration
    return None


def _kimi_window(record: Any, *, label: str) -> Optional[AccountUsageWindow]:
    if not isinstance(record, dict):
        return None
    limit = _kimi_int(record.get("limit"))
    used = _kimi_int(record.get("used"))
    if used is None:
        remaining = _kimi_int(record.get("remaining"))
        if limit is not None and remaining is not None:
            used = limit - remaining
    if not limit or used is None:
        return None
    used_percent = round(max(0, min(used, limit)) / limit * 100)
    return AccountUsageWindow(
        label=label,
        used_percent=used_percent,
        reset_at=_parse_dt(record.get("resetTime")),
    )


def _kimi_plan(payload: dict) -> Optional[str]:
    level = ((payload.get("user") or {}).get("membership") or {}).get("level")
    text = str(level or "").strip()
    if text.upper().startswith("LEVEL_"):
        text = text[len("LEVEL_") :]
    return _title_case_slug(text)


_KIMI_EXHAUSTED_CODES = frozenset({"resource_exhausted"})
_KIMI_EXHAUSTED_REASONS = frozenset({"REASON_QUOTA_EXCEEDED"})


def _kimi_exhausted_snapshot(response: Any) -> Optional[AccountUsageSnapshot]:
    """Turn Kimi's "credits used up" refusal into a real 100%-used reading.

    When the Kimi Code plan's credits are exhausted, GET /coding/v1/usages does
    NOT return the usage payload -- it answers HTTP 429 with
    ``{"code": "resource_exhausted", "message": "insufficient balance",
    "details": [{"debug": {"reason": "REASON_QUOTA_EXCEEDED",
    "localizedMessage": {"message": "Credits used up."}}}]}``
    (measured live 2026-09-09). ``raise_for_status`` turned that into a
    collector failure, the collector carried the last good row forward as
    ``stale``, and after the 24h carry bound the panel read "no data for
    142h" -- for SIX DAYS (2026-09-03..09) while the true state was simply
    "plan exhausted". That refusal IS the usage reading: 100% of the weekly
    quota is used. Report it that way, so the row renders "wk 100%" exactly
    like the other exhausted subscription rows, and never decays to stale.

    Only the exhaustion shape is mapped. Any other 429 (a genuine rate
    limit) and every other non-2xx status still raise through
    ``raise_for_status`` as before.
    """

    if getattr(response, "status_code", None) != 429:
        return None
    try:
        payload = response.json() or {}
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    code = str(payload.get("code") or "").strip().lower()
    reason = ""
    message = str(payload.get("message") or "").strip()
    for item in payload.get("details") or []:
        if not isinstance(item, dict):
            continue
        debug = item.get("debug") if isinstance(item.get("debug"), dict) else {}
        reason = str(debug.get("reason") or "").strip().upper() or reason
        localized = debug.get("localizedMessage")
        if isinstance(localized, dict) and localized.get("message"):
            message = str(localized["message"]).strip()
    if code not in _KIMI_EXHAUSTED_CODES and reason not in _KIMI_EXHAUSTED_REASONS:
        return None
    return AccountUsageSnapshot(
        provider="kimi",
        source="usages_api",
        fetched_at=_utc_now(),
        windows=(
            AccountUsageWindow(
                label="Weekly",
                used_percent=100.0,
                detail=message or "Credits used up.",
            ),
        ),
        details=(message or "Credits used up.",),
    )


def _fetch_kimi_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    httpx = _ensure_httpx()
    token, resolved_base_url = _resolve_kimi_usage_credentials(base_url, api_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "kimi-code",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(_kimi_usage_url(resolved_base_url), headers=headers)
        exhausted = _kimi_exhausted_snapshot(response)
        if exhausted is not None:
            return exhausted
        response.raise_for_status()
    payload = response.json() or {}

    windows: list[AccountUsageWindow] = []
    # Shorter rolling windows (5h "Session") live in limits[]; a >=1-day window
    # would read "Weekly" — the label comes from the window's own duration.
    for item in payload.get("limits") or []:
        if not isinstance(item, dict):
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else item
        secs = _kimi_window_seconds(item.get("window"))
        label = "Weekly" if (secs is not None and secs >= _CODEX_SESSION_MAX_SECONDS) else "Session"
        window = _kimi_window(detail, label=label)
        if window is not None:
            windows.append(window)
    # Top-level `usage` is the weekly window.
    weekly = _kimi_window(payload.get("usage"), label="Weekly")
    if weekly is not None:
        windows.append(weekly)

    if not windows:
        return None
    return AccountUsageSnapshot(
        provider="kimi",
        source="usages_api",
        fetched_at=_utc_now(),
        plan=_kimi_plan(payload),
        windows=tuple(windows),
    )


def _deepseek_balance_url(base_url: Optional[str]) -> str:
    """DeepSeek balance lives at the API ROOT (/user/balance), not under /v1."""
    base = str(base_url or "https://api.deepseek.com").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/user/balance"


def _resolve_deepseek_balance_credentials(
    base_url: Optional[str],
    api_key: Optional[str],
) -> tuple[str, str]:
    """Resolve DeepSeek key: explicit → DEEPSEEK_API_KEY env → credential pool.

    DeepSeek is a direct (non-OAuth) provider; the collector runner loads
    ``profiles/main/.env`` so ``DEEPSEEK_API_KEY`` is normally present.
    """
    explicit = str(api_key or "").strip()
    if explicit:
        return explicit, str(base_url or "").strip()
    env_key = str(os.environ.get("DEEPSEEK_API_KEY", "") or "").strip()
    if env_key:
        return env_key, str(base_url or "").strip()
    from agent.credential_pool import load_pool

    pool = load_pool("deepseek")
    entry = pool.select()
    if entry is None:
        raise RuntimeError("No available deepseek credential in credential pool")
    return entry.runtime_api_key, str(entry.runtime_base_url or base_url or "").strip()


def _fetch_deepseek_account_usage(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    timeout: float = _DEFAULT_USAGE_TIMEOUT,
) -> Optional[AccountUsageSnapshot]:
    """DeepSeek pay-as-you-go balance from GET /user/balance.

    Live shape (2026-08-05):
      {"is_available": true,
       "balance_infos": [{"currency":"USD","total_balance":"9.74", ...}]}
    ``total_balance`` (a string) is the outstanding-$ figure the tray shows.
    """
    httpx = _ensure_httpx()
    token, resolved_base_url = _resolve_deepseek_balance_credentials(base_url, api_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "hermes-usage-collector",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(_deepseek_balance_url(resolved_base_url), headers=headers)
        response.raise_for_status()
    payload = response.json() or {}

    infos = payload.get("balance_infos") or []
    chosen: Optional[dict] = None
    for info in infos:
        if isinstance(info, dict) and str(info.get("currency") or "").upper() == "USD":
            chosen = info
            break
    if chosen is None and infos and isinstance(infos[0], dict):
        chosen = infos[0]  # fall back to the first row if no USD line
    if chosen is None:
        return None

    try:
        balance = float(str(chosen.get("total_balance")).strip())
    except (TypeError, ValueError):
        return None

    return AccountUsageSnapshot(
        provider="deepseek",
        source="balance_api",
        fetched_at=_utc_now(),
        balance_usd=balance,
        balance_currency=str(chosen.get("currency") or "USD"),
    )


# Names are resolved at call time so existing provider test/extension overrides remain effective.
_USAGE_FETCHERS: dict[str, str] = {
    "openai-codex": "_fetch_codex_account_usage",
    "anthropic": "_fetch_anthropic_account_usage",
    "anthropic2": "_fetch_anthropic2_account_usage",
    "openrouter": "_fetch_openrouter_account_usage",
    "kimi": "_fetch_kimi_account_usage",
    "deepseek": "_fetch_deepseek_account_usage",
    "opencode-go": "_fetch_opencode_go_account_usage",
    "xai": "_fetch_grok_account_usage",
    "gemini": "_fetch_gemini_account_usage",
}


def fetch_account_usage(
    provider: Optional[str], *, base_url: Optional[str] = None,
    api_key: Optional[str] = None, budget_seconds: Optional[float] = None,
) -> Optional[AccountUsageSnapshot]:
    """Fetch usage with the collector's remaining cooperative request budget."""
    normalized = str(provider or "").strip().lower()
    name = _USAGE_FETCHERS.get(normalized)
    if name is None:
        return None
    default = _OPENROUTER_USAGE_TIMEOUT if normalized == "openrouter" else _DEFAULT_USAGE_TIMEOUT
    kwargs: dict[str, Any] = {"timeout": _budgeted_timeout(default, budget_seconds)}
    if normalized != "anthropic":
        kwargs.update(base_url=base_url, api_key=api_key)
    if normalized == "gemini":
        kwargs["budget_seconds"] = budget_seconds
    try:
        return globals()[name](**kwargs)
    except Exception:
        return None
