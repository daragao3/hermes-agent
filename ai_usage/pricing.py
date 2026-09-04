from __future__ import annotations

# Rate cards for log-billed, pay-as-you-go providers whose spend is ESTIMATED
# from token counts (state.db's estimated_cost_usd column is unpopulated — all
# rows read $0 — so the tray can't trust it and prices tokens itself).
#
# Gemini API list pricing, USD per 1,000,000 tokens, STANDARD tier only:
#   - prompts <=200k tokens (the >200k long-context tier costs ~2x in / 1.5x
#     out on Pro models; ignored here -- this is a running estimate, not a bill);
#   - batch/flex half-price and the priority-tier surcharge ignored likewise;
#   - text/image/video input rates (audio input is dearer on several families;
#     the deliberately-high fallbacks below absorb that).
# As of 2026-09-04, reconciled against ai.google.dev/gemini-api/docs/pricing
# (sources recorded in the spend-mode memory note). Ordered most-specific ->
# least; the FIRST needle found in the lowercased model name wins, so
# generation+tier entries must precede the bare-tier fallbacks, and
# "flash-lite" must precede "flash" (the latter is a substring of the former)
# at BOTH levels -- "3.5-flash-lite" before "3.5-flash" as well.
#
# The 3.8/3.7/3.6-flash standard price is promotionally $0.75/$3.75 through
# 2026-12-31 and reverts to the $1.50/$7.50 booked here on 2027-01-01. The
# post-promo figure is kept deliberately: it needs no edit at the new year, and
# it errs HIGH, which is the only direction this card is allowed to err in.
GEMINI_PRICING: list[tuple[str, float, float]] = [
    ("3.8-flash", 1.50, 7.50),
    ("3.7-flash", 1.50, 7.50),
    ("3.6-flash", 1.50, 7.50),
    ("3.5-flash-lite", 0.30, 2.50),
    ("3.5-flash", 1.50, 9.00),
    ("3.1-flash-lite", 0.25, 1.50),
    ("3.1-pro", 2.00, 12.00),
    ("2.5-pro", 1.25, 10.00),
    ("2.5-flash-lite", 0.10, 0.40),
    ("2.5-flash", 0.30, 2.50),
    # generation-agnostic tier fallbacks (flash-lite before flash before pro).
    # Pinned to the DEAREST LIVE family in each tier -- not merely the newest
    # generation -- so a versionless model string ("gemini-flash-latest",
    # "gemini-pro") can never be priced below whatever it actually resolved to.
    # flash-lite = 3.5-flash-lite; flash = 3.5-flash / Omni Flash, whose $9.00
    # output exceeds the newer 3.8 flagship's $7.50; pro = 3.1-pro.
    ("flash-lite", 0.30, 2.50),
    ("flash", 1.50, 9.00),
    ("pro", 2.00, 12.00),
]

# Unknown Gemini model -> current top Pro-tier rates (3.1-pro): deliberately the
# priciest common tier so an unrecognized model never silently UNDER-reports.
GEMINI_DEFAULT: tuple[float, float] = (2.00, 12.00)


def gemini_rate(model: str) -> tuple[float, float]:
    """(input, output) $ per 1M tokens for a Gemini model name, by substring."""
    m = str(model or "").lower()
    for needle, in_rate, out_rate in GEMINI_PRICING:
        if needle in m:
            return in_rate, out_rate
    return GEMINI_DEFAULT


def cost_usd(key: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated $ for a provider/model/token-count triple.

    Dispatches on the canonical provider key. Only ``gemini`` has a rate card
    today; any other key returns 0.0 (spend mode is Gemini-only for now).
    """
    if key == "gemini":
        in_rate, out_rate = gemini_rate(model)
        return (int(input_tokens) * in_rate + int(output_tokens) * out_rate) / 1_000_000.0
    return 0.0
