from __future__ import annotations

from datetime import datetime, timezone

# Canonical provider grid order for the tray. (key, display label, mode)
# mode ∈ {budget (rolling %-windows), tokens (log-summed counts),
#         balance (pay-as-you-go outstanding-$),
#         spend (month-to-date estimated-$ from token counts × rate card)}.
PROVIDERS: list[tuple[str, str, str]] = [
    ("anthropic", "Claude", "budget"),
    ("anthropic2", "Claude 2", "budget"),
    ("openai-codex", "Codex", "budget"),
    ("kimi", "Kimi K3", "budget"),
    # DeepSeek is deliberately ABSENT (retired 2026-09-13). DeepSeek models are
    # served through the OpenCode Go subscription (the "opencode-go" row below),
    # not through a direct api.deepseek.com account. The direct account's
    # prepaid balance is $0 and is not a path anything routes through, so
    # watching it only produced a permanent "DeepSeek balance chain_exhausted"
    # page every poll. The balance-mode machinery (ai_usage/balance.py, the
    # "balance" branch in collector.py / quota_signal.py) and
    # agent.account_usage._fetch_deepseek_account_usage are kept generic and
    # intact for any future prepaid provider; only this grid row is gone.
    # Gemini: quantitative % scraped from AI Studio's own apikey-page RPCs
    # (BatchGetProjectUsageLimits carries month-to-date spend vs budget) via
    # agent/gemini_session.py over CDP -- see that module's docstring.
    ("gemini", "Gemini", "budget"),
    ("xai", "Grok", "budget"),
    ("opencode-go", "OpenCode Go", "budget"),
]

# Maps AccountUsageWindow.label (emitted by agent/account_usage.py fetchers)
# to (canonical window id, tray display label).
WINDOW_LABEL_TO_ID: dict[str, tuple[str, str]] = {
    # Anthropic (_fetch_anthropic_account_usage)
    "Current session": ("5h", "5h"),
    "Current week": ("wk", "Weekly"),
    "Opus week": ("wk_opus", "Weekly · Opus"),
    "Sonnet week": ("wk_sonnet", "Weekly · Sonnet"),
    # Codex (_fetch_codex_account_usage)
    "Session": ("5h", "Session"),
    "Weekly": ("wk", "Weekly"),
    # OpenCode Go (_fetch_opencode_go_account_usage) and Gemini
    # (_fetch_gemini_account_usage, monthly budget %)
    "Rolling": ("5h", "Rolling"),
    "Monthly": ("mo", "Monthly"),
    # Grok (_fetch_grok_account_usage, via agent/grok_session.py CDP scrape)
    "Grok window": ("5h", "Grok"),
}

# state.db billing_provider substrings that map to a canonical tokens-mode key.
# Best-effort; extend as new routes appear. Verified live values today:
# only "openai-codex" and "anthropic" present, so these start empty.
BILLING_PROVIDER_ALIASES: dict[str, list[str]] = {
    "kimi": ["kimi", "moonshot"],
    "gemini": ["gemini", "google", "generativelanguage"],
    "xai": ["xai", "grok"],
}

# (window id, tray display label, window length in seconds)
TOKEN_WINDOWS: list[tuple[str, str, int]] = [
    ("5h", "5h", 5 * 3600),
    ("24h", "Today", 24 * 3600),
    ("7d", "Week", 7 * 86400),
]


def iso(dt: datetime) -> str:
    """UTC ISO-8601 with a trailing Z, second precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
