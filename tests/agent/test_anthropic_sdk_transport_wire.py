"""Real SDK transport preserves cached request bodies and per-request credentials."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.parametrize("rotating", [False, True])
def test_sdk_transport_preserves_cache_body_and_auth(rotating):
    from agent.anthropic_adapter import build_anthropic_client

    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((dict(self.headers), body))
            data = json.dumps({
                "id": "msg_fixture", "type": "message", "role": "assistant",
                "model": "fixture", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tokens = iter(["fixture-one", "fixture-two"])
    credential = (lambda: next(tokens)) if rotating else "sk-ant-api-fixture"
    client = None
    try:
        client = build_anthropic_client(credential, f"http://127.0.0.1:{server.server_port}", timeout=7)
        if rotating:
            assert client._client.follow_redirects is False
        body = dict(model="fixture", max_tokens=8,
                    system=[{"type": "text", "text": "stable prefix", "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": "fixture"}])
        for _ in range(2):
            assert client.messages.create(**body).content[0].text == "ok"
        assert received[0][1] == received[1][1] == body
        assert client.timeout.read == 7 and client.timeout.connect == 10
        headers = [{k.lower(): v for k, v in item[0].items()} for item in received]
        if rotating:
            assert [h["authorization"] for h in headers] == ["Bearer fixture-one", "Bearer fixture-two"]
            assert all("x-api-key" not in h for h in headers)
        else:
            assert all(h["x-api-key"] == credential for h in headers)
    finally:
        if client is not None:
            client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
