"""Unknown pricing remains visible beside dashboard cost totals."""

import sqlite3
import sys
import time
import types

import pytest
from hermes_cli.web_routers import analytics


@pytest.mark.parametrize("method", ["_get_usage_analytics", "_get_models_analytics"])
@pytest.mark.parametrize("populated", [False, True])
def test_totals_distinguish_unpriced_usage(monkeypatch, method, populated):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE sessions (
        started_at REAL, model TEXT, billing_provider TEXT, input_tokens INTEGER,
        output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
        reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL,
        api_call_count INTEGER, tool_call_count INTEGER, cost_status TEXT)""")
    if populated:
        for status, cost in [("unknown", 0), ("known", 2)]:
            conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (time.time(), "test-model", "test", 10, 20, 30, 40, 0, cost, 0, 1, 0, status))
    db = types.SimpleNamespace(_conn=conn, close=conn.close)
    monkeypatch.setattr(analytics, "_open_session_db_for_profile", lambda *a, **k: db)
    monkeypatch.setattr(analytics, "_aux_usage_rows", lambda *a: [])
    monkeypatch.setattr(analytics, "_model_capabilities", lambda *a: {})
    insights = types.SimpleNamespace(InsightsEngine=lambda db: types.SimpleNamespace(
        get_usage_breakdown=lambda **kw: {"skills": [], "tools": []}))
    monkeypatch.setitem(sys.modules, "agent.insights", insights)
    totals = getattr(analytics, method)()["totals"]
    assert totals["unpriced_sessions"] == (1 if populated else 0)
    assert totals["unpriced_tokens"] == (100 if populated else 0)
    assert totals["total_estimated_cost"] == (2 if populated else 0)
