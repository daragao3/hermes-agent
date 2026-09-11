"""DeepInfra provider profile (chat surface; image-gen/TTS/STT are wired via
their own plugin subsystems)."""

import logging

from providers import register_provider
from providers.base import ProviderProfile


logger = logging.getLogger(__name__)

_VISION_MODEL_PREFERENCE = (
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
)

_last_reported_vision_model = None

def _report_vision_model(model_id, eligible_count, from_preference):
    """Log the discovered vision default once, and again only if it changes."""
    global _last_reported_vision_model
    if model_id == _last_reported_vision_model:
        return
    _last_reported_vision_model = model_id
    logger.info(
        "DeepInfra vision default: %s (%s; %d vision-capable chat model%s "
        "in catalog)",
        model_id,
        "preferred" if from_preference
        else "NOT in preference list -- fell back to catalog order",
        eligible_count,
        "" if eligible_count == 1 else "s",
    )

class _DeepInfraProfile(ProviderProfile):
    """DeepInfra profile with live vision-default discovery, so shared vision
    resolution in ``agent/auxiliary_client.py`` stays provider-agnostic."""

    def default_vision_model(self):  # type: ignore[override]
        """Preferred vision-capable *chat* model from the live catalog, or None.

        Selection is preference-ordered, not catalog-ordered: the first entry
        of :data:`_VISION_MODEL_PREFERENCE` that the catalog actually offers
        wins, and catalog order is only the fallback. See that tuple for why.

        Key-gated so a box without a DeepInfra credential never pays the
        catalog round-trip. Requires the ``chat`` surface tag (not just the
        ``vision`` capability) so an image-gen/edit model that merely carries
        a ``vision`` tag can't be picked as a chat-completions vision backend.

        Outside multiplexing, the gate asks the client credential resolver
        (``resolve_api_key_provider_credentials``). An active secret scope or
        multiplexed process instead uses ``get_secret`` so a sibling profile's
        process environment or credential pool cannot unlock discovery.

        That matters because ``os.environ`` is **not reliably populated**
        from where Hermes actually stores credentials (``~/.hermes/.env``
        and the auth pool). ``.env`` reaches the environment only via an
        explicit sync in ``hermes_cli.config``, which not every entry point
        calls -- so the answer depended on WHICH PROCESS asked. Measured
        2026-08-25 in a plain ``import agent.auxiliary_client``:
        ``get_env_value("DEEPSEEK_API_KEY")`` truthy,
        ``os.environ.get("DEEPSEEK_API_KEY")`` None.

        Process-dependent is worse than uniformly broken. The old gate could
        pass inside a long-lived gateway that had run the sync and fail in
        ``hermes setup`` moments later, so a correctly-installed DeepInfra
        key returned None here, the vision chain logged "catalog
        unreachable", and vision stayed dead while blaming the network --
        intermittently, which is the hardest shape to diagnose. Asking the
        credential resolver removes the dependency entirely.
        """
        try:
            from hermes_cli.auth import resolve_api_key_provider_credentials
            from agent.secret_scope import current_secret_scope, get_secret, is_multiplex_active
            if current_secret_scope() is not None or is_multiplex_active():
                api_key = str(get_secret("DEEPINFRA_API_KEY") or "").strip()
            else:
                creds = resolve_api_key_provider_credentials("deepinfra")
                api_key = str(creds.get("api_key") or "").strip()
        except Exception:
            # Never let credential resolution break model discovery; treat an
            # unresolvable credential as "no key" and skip the round-trip.
            return None
        if not api_key:
            return None
        try:
            from hermes_cli.models import _fetch_deepinfra_models_by_tag
            items = _fetch_deepinfra_models_by_tag("chat")
        except Exception:
            return None

        eligible = []
        for item in items or []:
            metadata = item.get("metadata") or {}
            tags = metadata.get("tags") if isinstance(metadata, dict) else None
            if isinstance(tags, list) and "vision" in tags:
                model_id = item.get("id")
                if model_id:
                    eligible.append(model_id)
        if not eligible:
            return None

        # Match case-insensitively but return the catalog's own spelling --
        # that string is sent to the API, so it must be the id DeepInfra
        # published, not the one written in the preference tuple.
        by_lower = {str(m).lower(): m for m in eligible}
        chosen = None
        for preferred in _VISION_MODEL_PREFERENCE:
            chosen = by_lower.get(preferred.lower())
            if chosen:
                break
        from_preference = chosen is not None
        if chosen is None:
            # Every preferred id has been retired or renamed upstream. Fall
            # back to catalog order rather than returning None: a working but
            # unpreferred vision backend beats no vision at all, and the log
            # line below says which case this was.
            chosen = eligible[0]

        _report_vision_model(chosen, len(eligible), from_preference)
        return chosen


deepinfra = _DeepInfraProfile(
    name="deepinfra", aliases=("deep-infra", "deepinfra-ai"), display_name="DeepInfra",
    description="DeepInfra — 100+ open models, pay-per-use", signup_url="https://deepinfra.com/dash/api_keys",
    env_vars=("DEEPINFRA_API_KEY", "DEEPINFRA_BASE_URL"), base_url="https://api.deepinfra.com/v1/openai",
    auth_type="api_key",
    default_max_tokens=None,  # DeepInfra applies its documented per-model limit
    # The only hardcoded DeepInfra model: aux resolution is synchronous, so it
    # can't wait on a catalog round-trip. Everything else is discovered live.
    default_aux_model="deepseek-ai/DeepSeek-V4-Flash",
    # Empty on purpose: the live catalog is the source of truth; an empty picker
    # beats silently routing to a retired model.
    fallback_models=(),
)

register_provider(deepinfra)
