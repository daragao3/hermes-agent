from types import SimpleNamespace

from agent.usage_pricing import (
    CanonicalUsage,
    estimate_usage_cost,
    get_pricing_entry,
    normalize_usage,
)


def test_normalize_usage_anthropic_keeps_cache_buckets_separate():
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=500,
        cache_read_input_tokens=2000,
        cache_creation_input_tokens=400,
    )

    normalized = normalize_usage(usage, provider="anthropic", api_mode="anthropic_messages")

    assert normalized.input_tokens == 1000
    assert normalized.output_tokens == 500
    assert normalized.cache_read_tokens == 2000
    assert normalized.cache_write_tokens == 400
    assert normalized.prompt_tokens == 3400


def test_normalize_usage_openai_subtracts_cached_prompt_tokens():
    usage = SimpleNamespace(
        prompt_tokens=3000,
        completion_tokens=700,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1800),
    )

    normalized = normalize_usage(usage, provider="openai", api_mode="chat_completions")

    assert normalized.input_tokens == 1200
    assert normalized.cache_read_tokens == 1800
    assert normalized.output_tokens == 700


def test_normalize_usage_reads_deepseek_native_cache_hit_tokens():
    """DeepSeek's native API (api.deepseek.com) reports context-cache hits as
    top-level prompt_cache_hit_tokens / prompt_cache_miss_tokens (with
    prompt_tokens = hit + miss), not OpenAI's nested
    prompt_tokens_details.cached_tokens. Before this fix, direct DeepSeek
    sessions always normalized to cache_read_tokens=0 — cache hits were
    invisible in accounting and billed at the full input rate (#61871)."""
    usage = SimpleNamespace(
        prompt_tokens=2000,
        completion_tokens=400,
        prompt_cache_hit_tokens=1500,
        prompt_cache_miss_tokens=500,
    )

    normalized = normalize_usage(usage, provider="deepseek", api_mode="chat_completions")

    assert normalized.cache_read_tokens == 1500
    # prompt_tokens includes cached; input = 2000 - 1500 = the miss bucket
    assert normalized.input_tokens == 500
    assert normalized.output_tokens == 400


def test_normalize_usage_nested_details_win_over_deepseek_top_level():
    """When a proxy forwards both shapes, the OpenAI nested value wins and
    the DeepSeek top-level field is not double-read."""
    usage = SimpleNamespace(
        prompt_tokens=2000,
        completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=900),
        prompt_cache_hit_tokens=1500,
    )

    normalized = normalize_usage(usage, provider="deepseek", api_mode="chat_completions")

    assert normalized.cache_read_tokens == 900
    assert normalized.input_tokens == 1100


def test_normalize_usage_openai_reads_top_level_anthropic_cache_fields():
    """Some OpenAI-compatible proxies (OpenRouter, Cline) expose
    Anthropic-style cache token counts at the top level of the usage object when
    routing Claude models, instead of nesting them in prompt_tokens_details.

    Regression guard for the bug fixed in cline/cline#10266 — before this fix,
    the chat-completions branch of normalize_usage() only read
    prompt_tokens_details.cache_write_tokens and completely missed the
    cache_creation_input_tokens case, so cache writes showed as 0 and reflected
    inputTokens were overstated by the cache-write amount.
    """
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=500),
        cache_creation_input_tokens=300,
    )

    normalized = normalize_usage(usage, provider="openrouter", api_mode="chat_completions")

    # Expected: cache read from prompt_tokens_details.cached_tokens (preferred),
    # cache write from top-level cache_creation_input_tokens (fallback).
    assert normalized.cache_read_tokens == 500
    assert normalized.cache_write_tokens == 300
    # input_tokens = prompt_total - cache_read - cache_write = 1000 - 500 - 300 = 200
    assert normalized.input_tokens == 200
    assert normalized.output_tokens == 200


def test_normalize_usage_openai_reads_top_level_cache_read_when_details_missing():
    """Some proxies expose only top-level Anthropic-style fields with no
    prompt_tokens_details object. Regression guard for cline/cline#10266.
    """
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        cache_read_input_tokens=500,
        cache_creation_input_tokens=300,
    )

    normalized = normalize_usage(usage, provider="openrouter", api_mode="chat_completions")

    assert normalized.cache_read_tokens == 500
    assert normalized.cache_write_tokens == 300
    assert normalized.input_tokens == 200


def test_normalize_usage_openai_prefers_prompt_tokens_details_over_top_level():
    """When both prompt_tokens_details and top-level Anthropic fields are
    present, we prefer the OpenAI-standard nested fields. Top-level Anthropic
    fields are only a fallback when the nested ones are absent/zero.
    """
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=600, cache_write_tokens=150),
        # Intentionally different values — proving we ignore these when details exist.
        cache_read_input_tokens=999,
        cache_creation_input_tokens=999,
    )

    normalized = normalize_usage(usage, provider="openrouter", api_mode="chat_completions")

    assert normalized.cache_read_tokens == 600
    assert normalized.cache_write_tokens == 150


def test_openrouter_models_api_pricing_is_converted_from_per_token_to_per_million(monkeypatch):
    monkeypatch.setattr(
        "agent.usage_pricing.fetch_model_metadata",
        lambda: {
            "anthropic/claude-opus-4.6": {
                "pricing": {
                    "prompt": "0.000005",
                    "completion": "0.000025",
                    "input_cache_read": "0.0000005",
                    "input_cache_write": "0.00000625",
                }
            }
        },
    )

    entry = get_pricing_entry(
        "anthropic/claude-opus-4.6",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
    )

    assert float(entry.input_cost_per_million) == 5.0
    assert float(entry.output_cost_per_million) == 25.0
    assert float(entry.cache_read_cost_per_million) == 0.5
    assert float(entry.cache_write_cost_per_million) == 6.25


def test_estimate_usage_cost_marks_subscription_routes_included():
    result = estimate_usage_cost(
        "gpt-5.3-codex",
        CanonicalUsage(input_tokens=1000, output_tokens=500),
        provider="openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
    )

    assert result.status == "included"
    assert float(result.amount_usd) == 0.0


def test_ignore_subscription_prices_a_codex_route_at_the_vendor_list_rate():
    """What the same call would have cost had it been bought from OpenAI.

    Without this, a subscription workload reports as free and beats every
    metered alternative in a cost comparison by construction, rather than on
    the merits.
    """
    usage = CanonicalUsage(input_tokens=1_000_000, output_tokens=100_000)

    included = estimate_usage_cost("gpt-5.6-sol", usage, provider="openai-codex")
    equivalent = estimate_usage_cost(
        "gpt-5.6-sol", usage, provider="openai-codex", ignore_subscription=True
    )
    direct = estimate_usage_cost("gpt-5.6-sol", usage, provider="openai")

    assert float(included.amount_usd) == 0.0
    assert equivalent.amount_usd == direct.amount_usd
    assert equivalent.amount_usd > 0


def test_ignore_subscription_leaves_metered_routes_untouched():
    usage = CanonicalUsage(input_tokens=1_000_000, output_tokens=100_000)
    assert estimate_usage_cost(
        "deepseek-v4-pro", usage, provider="deepseek", ignore_subscription=True
    ).amount_usd == estimate_usage_cost(
        "deepseek-v4-pro", usage, provider="deepseek"
    ).amount_usd


def test_estimate_usage_cost_refuses_cache_pricing_without_official_cache_rate(monkeypatch):
    monkeypatch.setattr(
        "agent.usage_pricing.fetch_model_metadata",
        lambda: {
            "google/gemini-2.5-pro": {
                "pricing": {
                    "prompt": "0.00000125",
                    "completion": "0.00001",
                }
            }
        },
    )

    result = estimate_usage_cost(
        "google/gemini-2.5-pro",
        CanonicalUsage(input_tokens=1000, output_tokens=500, cache_read_tokens=100),
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
    )

    assert result.status == "unknown"


def test_custom_endpoint_models_api_pricing_is_supported(monkeypatch):
    monkeypatch.setattr(
        "agent.usage_pricing.fetch_endpoint_model_metadata",
        lambda base_url, api_key=None: {
            "zai-org/GLM-5-TEE": {
                "pricing": {
                    "prompt": "0.0000005",
                    "completion": "0.000002",
                }
            }
        },
    )

    entry = get_pricing_entry(
        "zai-org/GLM-5-TEE",
        provider="custom",
        base_url="https://llm.chutes.ai/v1",
        api_key="test-key",
    )

    assert float(entry.input_cost_per_million) == 0.5
    assert float(entry.output_cost_per_million) == 2.0


def test_nous_portal_pricing_preserves_vendor_prefixed_model_ids(monkeypatch):
    seen = {}

    def _fake_fetch_endpoint_model_metadata(base_url, api_key=None):
        seen["base_url"] = base_url
        return {
            "openai/gpt-5.5-pro": {
                "pricing": {
                    "prompt": "0.000025",
                    "completion": "0.000125",
                }
            }
        }

    monkeypatch.setattr(
        "agent.usage_pricing.fetch_endpoint_model_metadata",
        _fake_fetch_endpoint_model_metadata,
    )

    entry = get_pricing_entry("openai/gpt-5.5-pro", provider="nous")

    assert seen["base_url"] == "https://inference-api.nousresearch.com/v1"
    assert float(entry.input_cost_per_million) == 25.0
    assert float(entry.output_cost_per_million) == 125.0


def test_deepseek_v4_pro_pricing_entry_exists():
    """Regression test: deepseek-v4-pro must have a pricing entry.

    Before this fix, deepseek-v4-pro sessions showed as unknown cost
    in hermes insights because the _OFFICIAL_DOCS_PRICING table had no
    entry for that model.  See #24218.  Rates track the 2026-07 price cut
    ($1.74/$3.48 → $0.435/$0.87).
    """
    entry = get_pricing_entry(
        "deepseek-v4-pro",
        provider="deepseek",
    )

    assert entry is not None
    assert entry.input_cost_per_million is not None
    assert entry.output_cost_per_million is not None
    assert float(entry.input_cost_per_million) == 0.435
    assert float(entry.output_cost_per_million) == 0.87
    assert float(entry.cache_read_cost_per_million) == 0.003625


def test_deepseek_v4_pro_estimate_usage_cost():
    """Ensure deepseek-v4-pro sessions get a dollar estimate, not unknown."""
    result = estimate_usage_cost(
        "deepseek-v4-pro",
        CanonicalUsage(input_tokens=1000000, output_tokens=500000),
        provider="deepseek",
    )

    assert result.status == "estimated"
    assert result.amount_usd is not None
    # 1M input × $0.435/M + 500K output × $0.87/M = $0.435 + $0.435 = $0.87
    assert float(result.amount_usd) == 0.87


def test_deepseek_deprecated_aliases_price_as_v4_flash():
    """Invariant: deepseek-chat / deepseek-reasoner are deprecated aliases for
    deepseek-v4-flash's non-thinking / thinking modes (deprecation 2026-07-24)
    — they must bill at identical rates to the flash entry, or sessions on the
    legacy names over/under-report cost."""
    flash = get_pricing_entry("deepseek-v4-flash", provider="deepseek")
    assert flash is not None
    for alias in ("deepseek-chat", "deepseek-reasoner"):
        entry = get_pricing_entry(alias, provider="deepseek")
        assert entry is not None, alias
        assert entry.input_cost_per_million == flash.input_cost_per_million, alias
        assert entry.output_cost_per_million == flash.output_cost_per_million, alias
        assert (
            entry.cache_read_cost_per_million == flash.cache_read_cost_per_million
        ), alias


def test_deepseek_rows_all_carry_cache_read_pricing():
    """Invariant: DeepSeek publishes a cache-hit rate for every current model;
    every deepseek snapshot row must carry cache_read < input so cached
    sessions estimate correctly instead of billing reads at full price."""
    from agent.usage_pricing import _OFFICIAL_DOCS_PRICING

    ds_rows = [k for k in _OFFICIAL_DOCS_PRICING if k[0] == "deepseek"]
    assert ds_rows, "expected at least one deepseek pricing row"
    for key in ds_rows:
        entry = _OFFICIAL_DOCS_PRICING[key]
        assert entry.cache_read_cost_per_million is not None, key
        assert entry.cache_read_cost_per_million < entry.input_cost_per_million, key


def test_bedrock_claude_rows_all_carry_cache_pricing():
    """Invariant: every Bedrock Claude pricing row must carry cache-read AND
    cache-write rates, otherwise a cached session prices as ``unknown``.

    Bedrock Claude routes through the AnthropicBedrock SDK and injects
    cache_control, so cached tokens are always reported — the pricing layer
    must be able to value them.  See #50295.
    """
    from agent.usage_pricing import _OFFICIAL_DOCS_PRICING

    claude_rows = [
        (prov, model)
        for (prov, model) in _OFFICIAL_DOCS_PRICING
        if prov == "bedrock" and "claude" in model
    ]
    assert claude_rows, "expected at least one bedrock Claude pricing row"
    for key in claude_rows:
        entry = _OFFICIAL_DOCS_PRICING[key]
        assert entry.input_cost_per_million is not None, key
        assert entry.cache_read_cost_per_million is not None, key
        assert entry.cache_write_cost_per_million is not None, key
        # Cache reads are cheaper than fresh input; cache writes cost more.
        assert entry.cache_read_cost_per_million < entry.input_cost_per_million, key
        assert entry.cache_write_cost_per_million > entry.input_cost_per_million, key


def test_bedrock_current_gen_claude_rows_resolve():
    """Current-gen Claude models (Opus 4.8/4.7, Sonnet 5) must have Bedrock
    pricing rows so cached sessions report a dollar cost, not ``unknown``.
    Assert each resolves via the bare id and a cross-region inference profile
    (us./global. prefix), that every id for a given model resolves to the same
    entry, and that the row carries the cache fields a Bedrock Claude session
    needs.

    (Version-suffixed IDs like ``...-v1:0`` are covered separately by the
    normalizer test in the suffix-strip change; this test intentionally sticks
    to id shapes that resolve on ``main`` so it is independent of that PR.)
    """
    url = "https://bedrock-runtime.us-east-1.amazonaws.com"
    for bare in (
        "anthropic.claude-opus-4-8",
        "anthropic.claude-opus-4-7",
        "anthropic.claude-sonnet-5",
    ):
        ref = get_pricing_entry(bare, provider="bedrock", base_url=url)
        assert ref is not None, bare
        assert ref.input_cost_per_million is not None, bare
        assert ref.output_cost_per_million is not None, bare
        # Output costs more than input across the Claude line; sanity-check the
        # row isn't malformed (input < output).
        assert ref.output_cost_per_million > ref.input_cost_per_million, bare
        # Cache fields present so cached sessions price correctly (the #50295
        # symptom was unknown cost on cached Bedrock Claude sessions).
        assert ref.cache_read_cost_per_million is not None, bare
        assert ref.cache_write_cost_per_million is not None, bare
        # Cross-region inference profiles resolve to the same entry.
        for mid in (f"us.{bare}", f"global.{bare}"):
            entry = get_pricing_entry(mid, provider="bedrock", base_url=url)
            assert entry is not None, mid
            assert entry.input_cost_per_million == ref.input_cost_per_million, mid
            assert entry.output_cost_per_million == ref.output_cost_per_million, mid


def test_bedrock_cross_region_profile_prefix_resolves_to_pricing():
    """Cross-region inference profiles must resolve to the same pricing entry
    as the bare foundation-model id.  Without prefix normalization a scoped
    ``<region>.anthropic.claude-*`` session prices as unknown.

    Asia-Pacific (``apac.``) and Australia (``au.``) are included because AWS
    uses the full ``apac.`` prefix, not ``ap.`` — a bare ``ap.`` never matches
    an ``apac.*`` id, so those geographies previously priced as unknown.
    """
    bedrock_url = "https://bedrock-runtime.us-east-1.amazonaws.com"
    bare = get_pricing_entry(
        "anthropic.claude-sonnet-4-5", provider="bedrock", base_url=bedrock_url
    )
    assert bare is not None
    for prefix in ("us.", "global.", "eu.", "apac.", "au."):
        scoped = get_pricing_entry(
            f"{prefix}anthropic.claude-sonnet-4-5",
            provider="bedrock",
            base_url=bedrock_url,
        )
        assert scoped is not None, prefix
        assert scoped.input_cost_per_million == bare.input_cost_per_million
        assert scoped.cache_read_cost_per_million == bare.cache_read_cost_per_million


def test_bedrock_versioned_inference_profile_resolves_to_bare_pricing():
    """Bedrock profile IDs may include the provider's dated version suffix.

    The pricing table intentionally uses shorter model-family IDs, so the
    lookup needs a longest-prefix fallback after stripping the region scope.
    """
    bare = get_pricing_entry("anthropic.claude-sonnet-4-6", provider="bedrock")
    assert bare is not None

    for model in (
        "us.anthropic.claude-sonnet-4-6-20250514-v1:0",
        "global.anthropic.claude-sonnet-4-6-20250514-v1:0",
    ):
        scoped = get_pricing_entry(model, provider="bedrock")
        assert scoped is not None, model
        assert scoped.input_cost_per_million == bare.input_cost_per_million
        assert scoped.output_cost_per_million == bare.output_cost_per_million
        assert scoped.cache_read_cost_per_million == bare.cache_read_cost_per_million
        assert scoped.cache_write_cost_per_million == bare.cache_write_cost_per_million


def test_bedrock_pricing_supports_less_common_inference_profile_prefixes():
    """AWS also exposes profile scopes beyond us./global./eu.; those should
    not silently fall through to unknown pricing.
    """
    bare = get_pricing_entry("anthropic.claude-haiku-4-5", provider="bedrock")
    entry = get_pricing_entry(
        "apac.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock",
    )

    assert bare is not None
    assert entry is not None
    for field in (
        "input_cost_per_million",
        "output_cost_per_million",
        "cache_read_cost_per_million",
        "cache_write_cost_per_million",
    ):
        assert getattr(entry, field) == getattr(bare, field)


def test_bedrock_unknown_model_continuation_does_not_use_base_pricing():
    """Unrecognized Bedrock SKUs must remain unknown rather than inheriting a
    similarly named model family's price.
    """
    assert (
        get_pricing_entry(
            "anthropic.claude-sonnet-4-6-experimental",
            provider="bedrock",
        )
        is None
    )


def test_bedrock_claude_cached_session_estimates_cost_not_unknown():
    """A Bedrock Claude session with cache hits must produce a dollar estimate,
    not ``unknown`` — the user-visible symptom in #50295.
    """
    bedrock_url = "https://bedrock-runtime.us-east-1.amazonaws.com"
    usage = SimpleNamespace(
        input_tokens=55,
        output_tokens=7113,
        cache_read_input_tokens=1369379,
        cache_creation_input_tokens=42135,
    )
    canonical = normalize_usage(usage, provider="bedrock", api_mode="anthropic_messages")
    assert canonical.cache_read_tokens == 1369379
    assert canonical.cache_write_tokens == 42135

    result = estimate_usage_cost(
        "us.anthropic.claude-opus-4-6",
        canonical,
        provider="bedrock",
        base_url=bedrock_url,
    )
    assert result.status == "estimated"
    assert result.amount_usd is not None

def test_fireworks_kimi_k2p6_resolves_with_full_model_path():
    """Fireworks model ids look like accounts/fireworks/models/<name>;
    the routing layer must strip the prefix so the dict lookup succeeds."""
    entry = get_pricing_entry(
        "accounts/fireworks/models/kimi-k2p6",
        provider="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
    )

    assert entry is not None
    assert float(entry.input_cost_per_million) == 0.95
    assert float(entry.output_cost_per_million) == 4.00
    assert float(entry.cache_read_cost_per_million) == 0.16
    assert entry.source == "official_docs_snapshot"


def test_fireworks_base_url_host_match_alone_routes_to_pricing():
    """Provider not explicitly passed; routing infers fireworks from the host."""
    entry = get_pricing_entry(
        "accounts/fireworks/models/deepseek-v4-pro",
        base_url="https://api.fireworks.ai/inference/v1",
    )

    assert entry is not None
    assert float(entry.input_cost_per_million) == 1.74
    assert float(entry.output_cost_per_million) == 3.48


def test_fireworks_qwen3p7_plus_estimate_usage_cost():
    """End-to-end: Fireworks Qwen3.7-Plus sessions report a dollar estimate."""
    result = estimate_usage_cost(
        "accounts/fireworks/models/qwen3p7-plus",
        CanonicalUsage(input_tokens=1_000_000, output_tokens=500_000),
        provider="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
    )

    assert result.status == "estimated"
    assert result.amount_usd is not None
    # 1M input × $0.40/M + 500K output × $1.60/M = $0.40 + $0.80 = $1.20
    assert float(result.amount_usd) == 1.20


def test_fireworks_router_fast_tier_prices_distinctly():
    """Fast serving tiers live under accounts/fireworks/routers/<name>-fast and
    bill at higher rates than the standard model — the routing layer's
    rsplit("/", 1) must land on the distinct fast-tier entry."""
    standard = get_pricing_entry(
        "accounts/fireworks/models/kimi-k2p6",
        provider="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
    )
    fast = get_pricing_entry(
        "accounts/fireworks/routers/kimi-k2p6-fast",
        provider="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
    )
    assert standard is not None and fast is not None
    assert fast.input_cost_per_million > standard.input_cost_per_million
    assert fast.output_cost_per_million > standard.output_cost_per_million


def test_fireworks_plugin_fallback_models_all_have_pricing():
    """Invariant: every model in the Fireworks provider plugin's
    fallback_models (the picker's curated safety net) must resolve to a
    pricing entry — otherwise the default picker choices bill as unknown."""
    from providers import get_provider_profile

    profile = get_provider_profile("fireworks")
    assert profile is not None
    for mid in profile.fallback_models:
        entry = get_pricing_entry(
            mid,
            provider="fireworks",
            base_url="https://api.fireworks.ai/inference/v1",
        )
        assert entry is not None, f"no pricing entry for fallback model {mid}"
        assert entry.input_cost_per_million is not None, mid


def test_fireworks_rows_all_carry_cache_read_pricing():
    """Invariant: Fireworks publishes cached-input rates for every serverless
    model, and Hermes prompt caching is active on Fireworks sessions — every
    snapshot row must carry a cache_read rate cheaper than fresh input."""
    from agent.usage_pricing import _OFFICIAL_DOCS_PRICING

    fw_rows = [k for k in _OFFICIAL_DOCS_PRICING if k[0] == "fireworks"]
    assert fw_rows, "expected at least one fireworks pricing row"
    for key in fw_rows:
        entry = _OFFICIAL_DOCS_PRICING[key]
        assert entry.cache_read_cost_per_million is not None, key
        assert entry.cache_read_cost_per_million < entry.input_cost_per_million, key


def test_deepseek_v4_flash_pricing_entry_exists():
    """Regression test: deepseek-v4-flash must have a pricing entry.

    Before this fix, deepseek-v4-flash sessions showed $0.00 / cost_source
    "none" because the _OFFICIAL_DOCS_PRICING table had an entry for
    deepseek-v4-pro but not the (newer) flash model.  DeepSeek's /models
    endpoint returns no pricing, so the official-docs snapshot is the only
    source for direct-provider routes.
    """
    entry = get_pricing_entry(
        "deepseek-v4-flash",
        provider="deepseek",
    )

    assert entry is not None
    assert float(entry.input_cost_per_million) == 0.14
    assert float(entry.output_cost_per_million) == 0.28
    assert float(entry.cache_read_cost_per_million) == 0.0028


def test_deepseek_v4_flash_estimate_usage_cost():
    """Ensure deepseek-v4-flash sessions get a dollar estimate, not $0/none."""
    result = estimate_usage_cost(
        "deepseek-v4-flash",
        CanonicalUsage(input_tokens=1000000, output_tokens=500000),
        provider="deepseek",
    )

    assert result.status == "estimated"
    assert result.amount_usd is not None
    # 1M input × $0.14/M + 500K output × $0.28/M = $0.14 + $0.14 = $0.28
    assert float(result.amount_usd) == 0.28


# --- Gemini official-docs snapshot (reconciled 2026-09-04) -------------------


def _gemini_cost(model, provider=None, base_url=None):
    return estimate_usage_cost(
        model,
        CanonicalUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        provider=provider,
        base_url=base_url,
    )


def test_gemini_2_5_flash_matches_googles_published_rate():
    """Regression: this entry sat at $0.15/$0.60 against a published $0.30/$2.50.

    A 2x input / 4.2x output UNDER-report, stamped google-pricing-2026-03-16
    and sourced from the retired ai.google.dev/pricing page.
    """
    result = _gemini_cost("gemini-2.5-flash", provider="google")
    assert result.status == "estimated"
    assert float(result.amount_usd) == 2.80  # 1M x 0.30 + 1M x 2.50


def test_gemini_pricing_keys_are_reachable_from_every_google_route():
    """Regression: the route said "gemini" while the keys are ("google", ...).

    Vertex and bare "gemini-*" model names therefore missed every Gemini key
    and came back cost=None / status="unknown" -- priced at nothing.
    """
    routes = [
        {"provider": "google"},
        {"provider": "gemini"},
        {"provider": "vertex"},
        {"base_url": "https://aiplatform.googleapis.com/v1"},
        {"base_url": "https://generativelanguage.googleapis.com/v1beta"},
    ]
    # NOT covered, deliberately: a bare "gemini-*" with neither provider nor
    # base_url still resolves to provider "unknown" and goes unpriced. That is
    # pre-existing and vendor-neutral -- this module never infers a vendor from
    # a model name (only from an explicit "google/" prefix) -- so fixing it is a
    # design decision for the whole table, not part of this reconciliation.
    for kwargs in routes:
        result = _gemini_cost("gemini-2.5-flash", **kwargs)
        assert result.status == "estimated", f"unpriced via {kwargs}"
        assert float(result.amount_usd) == 2.80, f"wrong rate via {kwargs}"
    # ...including the "google/" vendor prefix the OpenAI-compat endpoint wants.
    prefixed = _gemini_cost("google/gemini-2.5-flash", provider="vertex")
    assert float(prefixed.amount_usd) == 2.80


def test_current_gemini_generations_are_priced_not_unknown():
    expected = {
        "gemini-3.8-flash": 9.00,   # 1.50 + 7.50 (post-promo; promo is 0.75/3.75)
        "gemini-3.7-flash": 9.00,
        "gemini-3.6-flash": 9.00,
        "gemini-3.5-flash": 10.50,  # 1.50 + 9.00
        "gemini-3.5-flash-lite": 2.80,
        "gemini-3.1-flash-lite": 1.75,
        "gemini-3.1-pro-preview": 14.00,
        "gemini-2.5-pro": 11.25,
        "gemini-2.5-flash-lite": 0.50,
    }
    for model, total in expected.items():
        result = _gemini_cost(model, provider="google")
        assert result.status == "estimated", f"{model} is unpriced"
        assert float(result.amount_usd) == total, model


def test_gemini_entries_carry_the_reconciliation_stamp():
    # 2.0-flash is exempt: Google removed it from the pricing page, so it keeps
    # its original stamp rather than borrowing a check that never happened.
    entry = get_pricing_entry("gemini-2.5-flash", provider="google")
    assert entry.pricing_version == "google-pricing-2026-09-04"
    assert entry.source_url == "https://ai.google.dev/gemini-api/docs/pricing"


# --- Vendor inference from a bare model name: deliberately REFUSED ----------


def _cost(model, **kwargs):
    return estimate_usage_cost(
        model,
        CanonicalUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        **kwargs,
    )


def test_bare_model_name_is_never_vendor_inferred():
    """A bare model name with no provider and no base_url must stay unpriced.

    Guards a deliberate refusal, not an oversight -- see the
    ``resolve_billing_route`` docstring. Adding a stem->vendor table looks like
    a one-liner and is the change this test exists to stop: the pricing table
    already sells these stems under several vendors at different prices, so any
    such table must GUESS, and guessing cheap under-reports silently. "unknown"
    is a signal a caller can act on; a wrong number is not.

    Measured 2026-09-04 across both live state.db files: of 869 token-bearing
    sessions, zero arrived here without a provider or base_url, so inference
    would have recovered nothing while introducing that risk.
    """
    for model in (
        "gemini-2.5-flash",   # ("google", ...) exists
        "claude-opus-4-7",    # ("anthropic", ...) exists
        "gpt-5.6-sol",        # ("openai", ...) AND ("fireworks", ...) exist
        "deepseek-v4-pro",    # ("deepseek", ...) AND ("fireworks", ...) exist
        "minimax-m2.7",       # three vendors
        "kimi-k3",            # ("moonshot", ...) exists
    ):
        result = _cost(model)
        assert result.status == "unknown", f"{model} was vendor-inferred"
        assert result.amount_usd is None, f"{model} was vendor-inferred"

    # The explicit signals still work -- this is a refusal to GUESS, not a
    # refusal to price.
    assert _cost("gemini-2.5-flash", provider="google").status == "estimated"
    assert _cost("google/gemini-2.5-flash").status == "estimated"


def test_colliding_stems_price_differently_per_vendor():
    """The evidence behind the refusal above; fails if a collision is removed.

    If these ever converge, the argument in ``resolve_billing_route``'s
    docstring weakens and the decision deserves re-litigating -- rather than a
    stale comment nobody rechecks.
    """
    cheap = get_pricing_entry("deepseek-v4-pro", provider="deepseek")
    dear = get_pricing_entry("deepseek-v4-pro", provider="fireworks")
    assert cheap.input_cost_per_million != dear.input_cost_per_million
    assert dear.input_cost_per_million > cheap.input_cost_per_million


# --- Kimi Coding Plan is a subscription, not an unpriced route --------------


def test_kimi_coding_plan_is_included_not_unknown():
    """Regression: every Coding Plan call priced as unknown/None.

    Measured 2026-09-04 before the fix: 244,412 tokens across 20
    activity-telemetry rows and 23 sessions carried a NULL cost, which the
    analytics total then read as $0 of spend. The plan bills a flat monthly
    subscription with a refreshing quota -- ``/coding/v1/usages`` returns
    limit/used/remaining counts, never dollars -- so $0 is the true recorded
    cost, and "included" says so where "unknown" did not.
    """
    for model in ("kimi-for-coding", "kimi-k3", "k3"):
        for kwargs in (
            {"provider": "kimi-coding"},
            {"provider": "kimi-coding", "base_url": "https://api.kimi.com/coding"},
            {"provider": "kimi-coding-cn"},
        ):
            result = _cost(model, **kwargs)
            assert result.status == "included", f"{model} via {kwargs}"
            assert float(result.amount_usd) == 0.0, f"{model} via {kwargs}"


def test_kimi_coding_plan_has_an_api_equivalent_at_list_price():
    """ignore_subscription must reach Moonshot's published rates.

    Without an underlying vendor a subscription workload reads as free and
    wins every cost comparison by construction, which is what
    ``_SUBSCRIPTION_UNDERLYING_PROVIDER`` exists to prevent.
    """
    result = _cost(
        "kimi-for-coding",
        provider="kimi-coding",
        base_url="https://api.kimi.com/coding",
        ignore_subscription=True,
    )
    assert result.status == "estimated"
    # 1M x $3.00 + 1M x $15.00 -- the K3 rate.
    assert float(result.amount_usd) == 18.00


def test_moonshot_pay_as_you_go_rates_match_published_prices():
    """The Kimi Open Platform is a separate surface from the Coding Plan."""
    expected = {
        "kimi-k3": 18.00,                    # 3.00 + 15.00
        "kimi-k2.7-code": 4.95,              # 0.95 + 4.00
        "kimi-k2.7-code-highspeed": 9.90,    # 1.90 + 8.00
        "kimi-k2.6": 4.95,                   # 0.95 + 4.00
    }
    for model, total in expected.items():
        result = _cost(model, provider="moonshot")
        assert result.status == "estimated", f"{model} is unpriced"
        assert float(result.amount_usd) == total, model

    entry = get_pricing_entry("kimi-k3", provider="moonshot")
    assert entry.pricing_version == "moonshot-pricing-2026-09-04"
    assert entry.cache_read_cost_per_million is not None
