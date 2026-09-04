from ai_usage.pricing import GEMINI_DEFAULT, GEMINI_PRICING, cost_usd, gemini_rate


def test_generation_and_tier_specific_rates_win():
    assert gemini_rate("gemini-2.5-pro") == (1.25, 10.00)
    assert gemini_rate("gemini-2.5-flash") == (0.30, 2.50)
    assert gemini_rate("gemini-2.5-flash-lite") == (0.10, 0.40)
    assert gemini_rate("gemini-3.1-pro") == (2.00, 12.00)
    assert gemini_rate("gemini-3.6-flash") == (1.50, 7.50)


def test_gemini_3_x_generations_added_2026_09_04():
    # Families Google published after the 2026-08-05 card was written; each
    # previously fell through to a bare-tier fallback.
    assert gemini_rate("gemini-3.8-flash") == (1.50, 7.50)
    assert gemini_rate("gemini-3.7-flash") == (1.50, 7.50)
    assert gemini_rate("gemini-3.5-flash") == (1.50, 9.00)
    assert gemini_rate("gemini-3.5-flash-lite") == (0.30, 2.50)
    assert gemini_rate("gemini-3.1-flash-lite") == (0.25, 1.50)


def test_flash_lite_precedes_flash_substring():
    # "flash" is a substring of "flash-lite"; the lite rate must still win.
    assert gemini_rate("some-future-flash-lite") == (0.30, 2.50)
    # ...and at the generation level too: "3.5-flash" must not eat
    # "gemini-3.5-flash-lite".
    assert gemini_rate("gemini-3.5-flash-lite") != gemini_rate("gemini-3.5-flash")
    # bare "flash" fallback tracks the dearest live flash family (3.5-flash /
    # Omni Flash at $9.00 out, above the newer 3.8 flagship's $7.50).
    assert gemini_rate("some-future-flash") == (1.50, 9.00)


def test_bare_tier_fallback_is_never_cheaper_than_a_known_model_in_that_tier():
    """The invariant the 2026-08-05 card violated for a month.

    Bare "flash-lite" sat at the 2.5 rate (0.10/0.40) while 3.5-flash-lite
    (0.30/2.50) was already in the same list, so "gemini-flash-lite-latest"
    under-reported by 3x in / 6.25x out. A fallback must dominate every
    explicit entry it could stand in for.
    """
    rates = dict((needle, (i, o)) for needle, i, o in GEMINI_PRICING)
    tiers = {
        "flash-lite": [n for n in rates if n.endswith("flash-lite")],
        "flash": [n for n in rates if n.endswith("flash")],
        "pro": [n for n in rates if n.endswith("pro")],
    }
    for bare, members in tiers.items():
        fb_in, fb_out = rates[bare]
        for needle in members:
            in_rate, out_rate = rates[needle]
            assert fb_in >= in_rate, f"bare {bare!r} under-reports input vs {needle!r}"
            assert fb_out >= out_rate, f"bare {bare!r} under-reports output vs {needle!r}"


def test_default_dominates_every_bare_tier_fallback():
    # An unrecognized model must never be cheaper than a recognized one.
    for bare in ("flash-lite", "flash", "pro"):
        in_rate, out_rate = gemini_rate(f"gemini-{bare}-latest")
        assert GEMINI_DEFAULT[0] >= in_rate
        assert GEMINI_DEFAULT[1] >= out_rate


def test_model_prefixes_and_case_are_tolerated():
    assert gemini_rate("models/Gemini-2.5-Flash") == (0.30, 2.50)


def test_unknown_gemini_model_falls_back_to_pro_tier():
    # Deliberately the priciest common tier (current top gen, 3.1-pro) — never
    # under-report.
    assert gemini_rate("gemini-experimental-xyz") == (2.00, 12.00)
    assert gemini_rate("") == (2.00, 12.00)


def test_cost_usd_prices_input_and_output_separately():
    # 0.2M input @ $1.25 + 0.1M output @ $10.00 = 0.25 + 1.00 = $1.25
    assert cost_usd("gemini", "gemini-2.5-pro", 200_000, 100_000) == 1.25
    # 1M in + 1M out on Flash = 0.30 + 2.50 = $2.80
    assert round(cost_usd("gemini", "gemini-2.5-flash", 1_000_000, 1_000_000), 2) == 2.80


def test_cost_usd_is_zero_for_non_gemini_keys():
    assert cost_usd("xai", "grok-4", 1_000_000, 1_000_000) == 0.0
