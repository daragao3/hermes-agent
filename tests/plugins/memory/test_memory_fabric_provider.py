"""Tests for the prefetch-only memory-fabric provider (a local HTTP server stands in for the gateway)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from plugins.memory.memory_fabric import MemoryFabricProvider, format_pack

TOKEN = "t" * 40


def _pack(*facts, degraded=False):
    return {"authority": "gbrain", "canonical": [{"fact": f, "entity_slug": "people/diego"} for f in facts],
            "history": [{"excerpt": "history must never be injected"}], "degraded": degraded}


class FakeGateway:
    """Records every tools/call; ``respond(tool, args)`` returns a payload or raises; ``gate`` holds replies."""

    def __init__(self):
        self.calls, self.auth = [], []
        self.gate = threading.Event()
        self.gate.set()
        self.respond = lambda tool, args: _pack(f"{tool} fact")
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                tool, args = req["params"]["name"], req["params"]["arguments"]
                outer.calls.append((tool, args))
                outer.auth.append(self.headers.get("Authorization"))
                outer.gate.wait(10)
                try:
                    result = {"content": [{"type": "text", "text": json.dumps(outer.respond(tool, args))}], "isError": False}
                except Exception as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
                body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def gateway():
    gw = FakeGateway()
    yield gw
    gw.close()


@pytest.fixture(autouse=True)
def _no_env_token(monkeypatch):
    monkeypatch.delenv("MEMORY_FABRIC_TOKEN", raising=False)


def _provider(gateway, tmp_path, **overrides):
    token_file = tmp_path / "local-token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    cfg = {"url": gateway.url, "token_file": str(token_file), "timeout_seconds": 5.0, **overrides}
    p = MemoryFabricProvider(cfg)
    p.initialize("s1", platform="whatsapp", agent_context="primary", hermes_home=str(tmp_path))
    return p


def test_availability_needs_a_token(tmp_path, monkeypatch):
    assert not MemoryFabricProvider({"token_file": str(tmp_path / "missing")}).is_available()
    assert MemoryFabricProvider({}).unavailable_reason()
    monkeypatch.setenv("MEMORY_FABRIC_TOKEN", TOKEN)
    assert MemoryFabricProvider({}).is_available()


def test_first_turn_warms_with_context_then_recalls(gateway, tmp_path):
    p = _provider(gateway, tmp_path)
    first = p.prefetch("how is the job search going", session_id="s1")
    second = p.prefetch("what about Capital One", session_id="s1")
    assert [c[0] for c in gateway.calls] == ["memory_context", "memory_recall"]
    assert gateway.calls[1][1]["query"] == "what about Capital One"
    assert gateway.auth == [f"Bearer {TOKEN}"] * 2
    assert "memory_context fact" in first and "memory_recall fact" in second
    assert "history must never be injected" not in first + second
    assert p.recall_status().count == 1


def test_warmup_can_be_disabled(gateway, tmp_path):
    p = _provider(gateway, tmp_path, warmup=False)
    p.prefetch("one", session_id="s1")
    assert [c[0] for c in gateway.calls] == ["memory_recall"]


def test_degraded_warmup_is_retried_next_turn(gateway, tmp_path):
    gateway.respond = lambda tool, args: _pack("partial", degraded=True)
    p = _provider(gateway, tmp_path)
    p.prefetch("one", session_id="s1")
    p.prefetch("two", session_id="s1")
    assert [c[0] for c in gateway.calls] == ["memory_context", "memory_context"]


def test_slow_call_is_offered_to_the_next_turn_and_never_stacked(gateway, tmp_path):
    gateway.gate.clear()
    p = _provider(gateway, tmp_path, timeout_seconds=0.2)
    assert p.prefetch("first question", session_id="s1") == ""
    assert p.recall_status() is None
    # Still in flight: the next turn must not queue a second call behind it.
    assert p.prefetch("second question", session_id="s1") == ""
    assert len(gateway.calls) == 1
    gateway.gate.set()
    for _ in range(100):
        if not p._inflight:
            break
        threading.Event().wait(0.05)
    gateway.gate.clear()  # the third turn misses its deadline too, so it falls back to the late result
    late = p.prefetch("third question", session_id="s1")
    assert "memory_context fact" in late
    assert p.recall_status().count == 1
    assert p._late == {}  # consumed once
    gateway.gate.set()


def test_on_time_answer_supersedes_a_stale_late_one(gateway, tmp_path):
    p = _provider(gateway, tmp_path)
    p._late["s1"] = (0.0, "## stale", 1)
    assert "memory_context fact" in p.prefetch("question", session_id="s1")
    assert p._late == {}


def test_gateway_failures_are_silent(gateway, tmp_path):
    def boom(tool, args):
        raise RuntimeError("backends_unavailable")
    gateway.respond = boom
    p = _provider(gateway, tmp_path)
    assert p.prefetch("anything", session_id="s1") == ""
    dead = _provider(gateway, tmp_path, url="http://127.0.0.1:9/mcp")
    assert dead.prefetch("anything", session_id="s1") == ""


@pytest.mark.parametrize("kwargs", [{"platform": "cron", "agent_context": "primary"},
                                    {"platform": "cli", "agent_context": "subagent"}])
def test_non_primary_contexts_make_no_calls(gateway, tmp_path, kwargs):
    p = _provider(gateway, tmp_path)
    p.initialize("s1", **kwargs)
    assert p.prefetch("question", session_id="s1") == ""
    assert gateway.calls == []


def test_provider_writes_nothing(gateway, tmp_path):
    p = _provider(gateway, tmp_path)
    assert p.get_tool_schemas() == []
    p.sync_turn("user text", "assistant text", session_id="s1")
    assert gateway.calls == []


def test_format_pack_budget_and_row_shapes():
    payload = {"canonical": [{"fact": "a  b\n c", "entity_slug": "people/x"},
                             {"title": "Page", "chunk": "body text", "slug": "concepts/y"},
                             {"fact": ""}, "junk", {"fact": "z" * 50}]}
    text, count = format_pack(payload, max_chars=200, max_row_chars=20)
    assert count == 3
    assert "- a b c [people/x]" in text and "- Page — body text [concepts/y]" in text
    assert "z" * 19 + "…" in text
    assert format_pack({"canonical": []}, max_chars=100, max_row_chars=10) == ("", 0)
    assert format_pack({"canonical": [{"fact": "x" * 30}]}, max_chars=10, max_row_chars=100) == ("", 0)
