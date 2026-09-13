from types import SimpleNamespace

import pytest

from agent import account_usage


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, calls, payload):
        self.calls = calls
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        return _FakeResponse(self.payload)


@pytest.fixture
def codex_usage_payload():
    return {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": 21,
                "reset_at": 1779846359,
            },
            "secondary_window": {
                "used_percent": 4,
                "reset_at": 1780230796,
            },
        },
        "credits": {"has_credits": False},
    }


def test_codex_usage_prefers_explicit_live_agent_credentials(monkeypatch, codex_usage_payload):
    calls = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _FakeClient(calls, codex_usage_payload),
    )
    monkeypatch.setattr(
        account_usage,
        "resolve_codex_runtime_credentials",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("legacy auth should not be used")),
    )

    snapshot = account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
    )

    assert snapshot is not None
    assert snapshot.provider == "openai-codex"
    assert snapshot.plan == "Plus"
    assert [w.label for w in snapshot.windows] == ["Session", "Weekly"]
    assert snapshot.windows[0].used_percent == 21
    assert calls[0]["url"] == "https://chatgpt.com/backend-api/wham/usage"
    assert calls[0]["headers"]["Authorization"] == "Bearer live-agent-token"


@pytest.fixture
def kimi_usage_payload():
    # Live shape from GET https://api.kimi.com/coding/v1/usages (verified
    # 2026-08-05): values are STRINGS; top-level `usage` is the weekly window;
    # `limits[]` carry the shorter windows and their `detail` often omits
    # `used` (derive it as limit - remaining).
    return {
        "user": {"membership": {"level": "LEVEL_ADVANCED"}},
        "usage": {
            "limit": "100",
            "used": "70",
            "remaining": "30",
            "resetTime": "2026-08-10T16:59:20.280907Z",
        },
        "limits": [
            {
                "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                "detail": {
                    "limit": "100",
                    "remaining": "40",
                    "resetTime": "2026-08-05T08:59:20.280907Z",
                },
            }
        ],
    }


def test_kimi_usage_maps_session_and_weekly_windows(monkeypatch, kimi_usage_payload):
    calls = []
    monkeypatch.setattr(
        account_usage.httpx, "Client", lambda timeout: _FakeClient(calls, kimi_usage_payload)
    )

    snapshot = account_usage.fetch_account_usage(
        "kimi",
        base_url="https://api.kimi.com/coding",
        api_key="live-kimi-key",
    )

    assert snapshot is not None
    assert snapshot.provider == "kimi"
    assert snapshot.plan == "Advanced"
    # 300-minute window (< 1 day) is the Session; top-level usage is Weekly.
    assert [w.label for w in snapshot.windows] == ["Session", "Weekly"]
    # detail has no `used` → derived from limit - remaining = 100 - 40 = 60.
    assert snapshot.windows[0].used_percent == 60
    # weekly: used=70, limit=100 → 70% (string coercion).
    assert snapshot.windows[1].used_percent == 70


class _FakeStatusResponse(_FakeResponse):
    """A fake response carrying a real HTTP status, for non-2xx shapes."""

    def __init__(self, payload, status_code):
        super().__init__(payload)
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None


class _FakeStatusClient(_FakeClient):
    def __init__(self, calls, payload, status_code):
        super().__init__(calls, payload)
        self.status_code = status_code

    def get(self, url, headers, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        return _FakeStatusResponse(self.payload, self.status_code)


@pytest.fixture
def kimi_exhausted_payload():
    # Live shape from GET https://api.kimi.com/coding/v1/usages on 2026-09-09
    # while the Kimi Code plan's credits were used up: HTTP 429, no usage body.
    return {
        "code": "resource_exhausted",
        "message": "insufficient balance",
        "details": [
            {
                "type": "common.error.v1.ErrorDetail",
                "value": "CHQSGQoFZW4tVVMSEENyZWRpdHMgdXNlZCB1cC4",
                "debug": {
                    "reason": "REASON_QUOTA_EXCEEDED",
                    "localizedMessage": {"locale": "en-US", "message": "Credits used up."},
                },
            }
        ],
    }


def test_kimi_credits_used_up_is_a_100_percent_reading_not_a_failure(
    monkeypatch, kimi_exhausted_payload
):
    """An exhausted Kimi plan answers 429 resource_exhausted instead of usage.

    Before: raise_for_status turned that into a collector failure, the row was
    carried forward as stale and after 24h read "no data for Nh" -- six days of
    it (2026-09-03..09) while the true state was "plan exhausted". The refusal
    IS the reading: 100% of the weekly quota is used.
    """
    calls = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _FakeStatusClient(calls, kimi_exhausted_payload, 429),
    )

    snapshot = account_usage.fetch_account_usage(
        "kimi",
        base_url="https://api.kimi.com/coding",
        api_key="live-kimi-key",
    )

    assert snapshot is not None
    assert snapshot.provider == "kimi"
    assert snapshot.available
    assert [(w.label, w.used_percent) for w in snapshot.windows] == [("Weekly", 100.0)]
    assert snapshot.windows[0].detail == "Credits used up."
    assert "Credits used up." in snapshot.details
    assert len(calls) == 1


def test_kimi_other_429_still_raises(monkeypatch):
    """Only the exhaustion shape is mapped; a plain rate limit is still an error."""
    calls = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _FakeStatusClient(
            calls, {"code": "rate_limited", "message": "slow down"}, 429
        ),
    )
    # The private fetch raises through raise_for_status as before...
    with pytest.raises(RuntimeError, match="HTTP 429"):
        account_usage._fetch_kimi_account_usage(
            base_url="https://api.kimi.com/coding", api_key="live-kimi-key"
        )
    # ...and the public wrapper maps that to its pre-existing "no snapshot"
    # answer, which the collector reports as unavailable. Unchanged behaviour.
    assert (
        account_usage.fetch_account_usage(
            "kimi", base_url="https://api.kimi.com/coding", api_key="live-kimi-key"
        )
        is None
    )


def test_kimi_usage_hits_usages_endpoint_with_bearer(monkeypatch, kimi_usage_payload):
    calls = []
    monkeypatch.setattr(
        account_usage.httpx, "Client", lambda timeout: _FakeClient(calls, kimi_usage_payload)
    )

    account_usage.fetch_account_usage(
        "kimi",
        base_url="https://api.kimi.com/coding",
        api_key="live-kimi-key",
    )

    assert calls[0]["url"] == "https://api.kimi.com/coding/v1/usages"
    assert calls[0]["headers"]["Authorization"] == "Bearer live-kimi-key"


def test_codex_weekly_limit_in_primary_slot_labels_weekly(monkeypatch):
    # When the weekly cap is reached, Codex's /usage puts the 7-day window in
    # primary_window (limit_window_seconds=604800) and nulls secondary_window.
    # The label must come from the window's duration, so a maxed weekly window
    # reads "Weekly" — not "Session" from its slot position.
    payload = {
        "plan_type": "pro",
        "rate_limit": {
            "allowed": False,
            "limit_reached": True,
            "primary_window": {
                "used_percent": 100,
                "limit_window_seconds": 604800,
                "reset_at": 1786159971,
            },
            "secondary_window": None,
        },
        "credits": {"has_credits": False},
    }
    calls = []
    monkeypatch.setattr(
        account_usage.httpx, "Client", lambda timeout: _FakeClient(calls, payload)
    )

    snapshot = account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
    )

    assert snapshot is not None
    assert [w.label for w in snapshot.windows] == ["Weekly"]
    assert snapshot.windows[0].used_percent == 100


def test_codex_labels_windows_by_duration_not_slot(monkeypatch):
    # Labels derive from limit_window_seconds, not slot order: a 5h window is
    # "Session" and a 7d window is "Weekly" wherever Codex places them.
    payload = {
        "plan_type": "pro",
        "rate_limit": {
            "primary_window": {
                "used_percent": 88,
                "limit_window_seconds": 604800,
                "reset_at": 1786159971,
            },
            "secondary_window": {
                "used_percent": 12,
                "limit_window_seconds": 18000,
                "reset_at": 1779846359,
            },
        },
        "credits": {"has_credits": False},
    }
    calls = []
    monkeypatch.setattr(
        account_usage.httpx, "Client", lambda timeout: _FakeClient(calls, payload)
    )

    snapshot = account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
    )

    assert snapshot is not None
    assert [w.label for w in snapshot.windows] == ["Weekly", "Session"]
    assert snapshot.windows[0].used_percent == 88
    assert snapshot.windows[1].used_percent == 12


def test_codex_usage_falls_back_to_native_credential_pool(monkeypatch, codex_usage_payload):
    calls = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _FakeClient(calls, codex_usage_payload),
    )
    # Pool fallback fires only on AuthError (the documented "no creds" mode of
    # the resolver), NOT on arbitrary exceptions — see the transient-error guard
    # test below.
    monkeypatch.setattr(
        account_usage,
        "resolve_codex_runtime_credentials",
        lambda **kwargs: (_ for _ in ()).throw(
            account_usage.AuthError("no singleton auth", provider="openai-codex", code="codex_auth_missing")
        ),
    )

    pool_entry = SimpleNamespace(
        runtime_api_key="pooled-token",
        runtime_base_url="https://chatgpt.com/backend-api/codex",
    )
    pool = SimpleNamespace(select=lambda: pool_entry)

    import agent.credential_pool as credential_pool

    monkeypatch.setattr(credential_pool, "load_pool", lambda provider: pool)

    snapshot = account_usage.fetch_account_usage("openai-codex")

    assert snapshot is not None
    assert snapshot.windows[0].label == "Session"
    assert snapshot.windows[1].label == "Weekly"
    assert calls[0]["url"] == "https://chatgpt.com/backend-api/wham/usage"
    assert calls[0]["headers"]["Authorization"] == "Bearer pooled-token"
    # Pool creds have no account_id concept — the ChatGPT-Account-Id header must
    # be omitted rather than sent stale/wrong.
    assert "ChatGPT-Account-Id" not in calls[0]["headers"]




def test_codex_usage_account_id_read_failure_keeps_singleton_token(monkeypatch, codex_usage_payload):
    """When the resolver succeeds but the separate account_id read raises, the
    working singleton token must still be used (best-effort account_id), NOT
    abandoned in favor of a header-less pool credential."""
    calls = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _FakeClient(calls, codex_usage_payload),
    )
    monkeypatch.setattr(
        account_usage,
        "resolve_codex_runtime_credentials",
        lambda **kwargs: {
            "api_key": "singleton-token",
            "base_url": "https://chatgpt.com/backend-api/codex",
        },
    )
    monkeypatch.setattr(
        account_usage,
        "_read_codex_tokens",
        lambda *a, **k: (_ for _ in ()).throw(
            account_usage.AuthError("partial store", provider="openai-codex", code="codex_auth_invalid_shape")
        ),
    )

    import agent.credential_pool as credential_pool

    monkeypatch.setattr(
        credential_pool,
        "load_pool",
        lambda provider: (_ for _ in ()).throw(AssertionError("pool must not be consulted")),
    )

    snapshot = account_usage.fetch_account_usage("openai-codex")

    assert snapshot is not None
    assert calls[0]["headers"]["Authorization"] == "Bearer singleton-token"
    # account_id read failed → header omitted, but the singleton token is kept.
    assert "ChatGPT-Account-Id" not in calls[0]["headers"]




# ── Banked rate-limit reset credits (`/usage reset`) ─────────────────────────


class _FakeResetClient:
    """GET returns the usage payload; POST returns the consume payload."""

    def __init__(self, calls, usage_payload, consume_payload=None):
        self.calls = calls
        self.usage_payload = usage_payload
        self.consume_payload = consume_payload or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers):
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return _FakeResponse(self.usage_payload)

    def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return _FakeResponse(self.consume_payload)


def _usage_payload_with_resets(primary_used, secondary_used, banked):
    return {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {"used_percent": primary_used, "reset_at": 1779846359},
            "secondary_window": {"used_percent": secondary_used, "reset_at": 1780230796},
        },
        "rate_limit_reset_credits": {"available_count": banked},
        "credits": {"has_credits": False},
    }
















def test_redeem_missing_credentials_reports_unavailable(monkeypatch):
    monkeypatch.setattr(
        account_usage,
        "_resolve_codex_usage_credentials",
        lambda base_url, api_key: (_ for _ in ()).throw(RuntimeError("no creds")),
    )

    result = account_usage.redeem_codex_reset_credit()

    assert result.status == "unavailable"
    assert "hermes auth" in result.message


class _TimeoutRecordingClient(_FakeClient):
    """Records the timeout the fetcher asked httpx for."""

    def __init__(self, calls, payload, timeouts, timeout):
        super().__init__(calls, payload)
        timeouts.append(timeout)


def _record_timeouts(monkeypatch, payload):
    timeouts: list = []
    monkeypatch.setattr(
        account_usage.httpx,
        "Client",
        lambda timeout: _TimeoutRecordingClient([], payload, timeouts, timeout),
    )
    return timeouts


def test_budget_seconds_clamps_the_http_timeout(monkeypatch, codex_usage_payload):
    """The budget must reach httpx, not just the signature.

    Accepting ``budget_seconds`` is what flips
    ``ai_usage.collector._supports_budget`` to True. If the value were then
    dropped on the floor, the collector would believe it had a bounded call
    while the request could still run for the fetcher's full 15s default --
    a worse failure than not accepting it at all, because it reads as fixed.
    """
    timeouts = _record_timeouts(monkeypatch, codex_usage_payload)

    account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
        budget_seconds=2.5,
    )

    assert timeouts == [2.5]


def test_budget_seconds_never_widens_the_default(monkeypatch, codex_usage_payload):
    """A budget larger than the default must not extend the request."""
    timeouts = _record_timeouts(monkeypatch, codex_usage_payload)

    account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
        budget_seconds=900.0,
    )

    assert timeouts == [account_usage._DEFAULT_USAGE_TIMEOUT]


def test_no_budget_keeps_the_fetcher_default(monkeypatch, codex_usage_payload):
    """The CLI and /usage paths pass no budget and must be unaffected."""
    timeouts = _record_timeouts(monkeypatch, codex_usage_payload)

    account_usage.fetch_account_usage(
        "openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="live-agent-token",
    )

    assert timeouts == [account_usage._DEFAULT_USAGE_TIMEOUT]
