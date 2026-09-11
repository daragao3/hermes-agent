"""Tests for the google_meet node primitive.

Covers protocol helpers, the file-backed registry, the server's
token-and-dispatch machinery, a mocked client, and the CLI plumbing.
We never open a real socket — websockets.serve / websockets.sync.client
are fully mocked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path as Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    yield hermes_home


# ---------------------------------------------------------------------------
# protocol.py
# ---------------------------------------------------------------------------

def test_protocol_encode_decode_roundtrip():
    from plugins.google_meet.node import protocol

    msg = protocol.make_request("ping", "tok", {"x": 1}, req_id="abc")
    raw = protocol.encode(msg)
    out = protocol.decode(raw)
    assert out == msg
    assert out["type"] == "ping"
    assert out["id"] == "abc"
    assert out["token"] == "tok"
    assert out["payload"] == {"x": 1}


# ---------------------------------------------------------------------------
# registry.py
# ---------------------------------------------------------------------------

def test_registry_add_get_roundtrip_persists(tmp_path):
    from plugins.google_meet.node.registry import NodeRegistry

    p = tmp_path / "nodes.json"
    r = NodeRegistry(path=p)
    r.add("mac", "ws://mac.local:18789", "deadbeef")

    # Second instance sees it.
    r2 = NodeRegistry(path=p)
    entry = r2.get("mac")
    assert entry is not None
    assert entry["name"] == "mac"
    assert entry["url"] == "ws://mac.local:18789"
    assert entry["token"] == "deadbeef"
    assert "added_at" in entry


# ---------------------------------------------------------------------------
# server.py — token + dispatch
# ---------------------------------------------------------------------------

def test_server_ensure_token_generates_and_persists(tmp_path):
    from plugins.google_meet.node.server import NodeServer

    p = tmp_path / "tok.json"
    s1 = NodeServer(token_path=p)
    t1 = s1.ensure_token()
    assert isinstance(t1, str) and len(t1) == 32

    # Reuse on a fresh instance.
    s2 = NodeServer(token_path=p)
    t2 = s2.ensure_token()
    assert t1 == t2

    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["token"] == t1
    assert "generated_at" in data


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# client.py
# ---------------------------------------------------------------------------

class _FakeWS:
    """Minimal context-manager stand-in for websockets.sync.client.connect."""

    def __init__(self, reply_builder):
        self._reply_builder = reply_builder
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def send(self, raw):
        self.sent.append(raw)

    def recv(self, timeout=None):
        return self._reply_builder(self.sent[-1])


def _install_fake_ws(monkeypatch, reply_builder):
    fake_ws_holder = {}

    def _connect(url, **kwargs):
        ws = _FakeWS(reply_builder)
        fake_ws_holder["ws"] = ws
        fake_ws_holder["url"] = url
        fake_ws_holder["kwargs"] = kwargs
        return ws

    # Patch the concrete import site inside client._rpc
    import websockets.sync.client as wsc  # type: ignore
    monkeypatch.setattr(wsc, "connect", _connect)
    return fake_ws_holder


def test_client_rpc_sends_correct_envelope_and_parses_response(monkeypatch):
    from plugins.google_meet.node.client import NodeClient
    from plugins.google_meet.node import protocol

    def reply(raw_out):
        req = protocol.decode(raw_out)
        return protocol.encode(protocol.make_response(req["id"], {"ok": True, "echo": req["type"]}))

    holder = _install_fake_ws(monkeypatch, reply)

    c = NodeClient("ws://remote:1", "tok123")
    out = c._rpc("ping", {"hello": 1})
    assert out == {"ok": True, "echo": "ping"}

    sent = json.loads(holder["ws"].sent[0])
    assert sent["type"] == "ping"
    assert sent["token"] == "tok123"
    assert sent["payload"] == {"hello": 1}
    assert sent["id"]  # non-empty
    assert holder["url"] == "ws://remote:1"


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------

def _build_parser():
    from plugins.google_meet.node.cli import register_cli

    parser = argparse.ArgumentParser(prog="meet-node-test")
    register_cli(parser)
    return parser


def test_cli_approve_list_remove(capsys):
    from plugins.google_meet.node.registry import NodeRegistry

    p = _build_parser()

    args = p.parse_args(["approve", "mac", "ws://mac:1", "tok"])
    rc = args.func(args)
    assert rc == 0
    assert NodeRegistry().get("mac") is not None

    args = p.parse_args(["list"])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "mac" in out
    assert "ws://mac:1" in out

    args = p.parse_args(["remove", "mac"])
    rc = args.func(args)
    assert rc == 0
    assert NodeRegistry().get("mac") is None


def test_cli_list_empty(capsys):
    p = _build_parser()
    args = p.parse_args(["list"])
    rc = args.func(args)
    assert rc == 0
    assert "no nodes" in capsys.readouterr().out


def test_cli_remove_missing_returns_nonzero():
    p = _build_parser()
    args = p.parse_args(["remove", "ghost"])
    rc = args.func(args)
    assert rc == 1


def test_cli_status_pings_via_node_client(capsys, monkeypatch):
    from plugins.google_meet.node.registry import NodeRegistry
    from plugins.google_meet.node import cli as node_cli

    NodeRegistry().add("mac", "ws://mac:1", "tok")

    class _FakeClient:
        def __init__(self, url, token):
            assert url == "ws://mac:1"
            assert token == "tok"

        def ping(self):
            return {"type": "pong", "display_name": "hermes-meet-node"}

    monkeypatch.setattr(node_cli, "NodeClient", _FakeClient)

    p = _build_parser()
    args = p.parse_args(["status", "mac"])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["ok"] is True
    assert data["node"] == "mac"


def test_cli_status_unknown_node_fails(capsys):
    p = _build_parser()
    args = p.parse_args(["status", "ghost"])
    rc = args.func(args)
    assert rc == 1


def test_cli_status_reports_client_error(capsys, monkeypatch):
    from plugins.google_meet.node.registry import NodeRegistry
    from plugins.google_meet.node import cli as node_cli

    NodeRegistry().add("mac", "ws://mac:1", "tok")

    class _FakeClient:
        def __init__(self, url, token):
            pass

        def ping(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(node_cli, "NodeClient", _FakeClient)

    p = _build_parser()
    args = p.parse_args(["status", "mac"])
    rc = args.func(args)
    assert rc == 1
    data = json.loads(capsys.readouterr().out.strip())
    assert data["ok"] is False
    assert "connection refused" in data["error"]


# ---------------------------------------------------------------------------
# meet cli.py — the "node module unavailable" fallback
# ---------------------------------------------------------------------------

def _build_meet_parser_with_broken_node_import(monkeypatch):
    """Build the ``hermes meet`` tree with the node module import forced to fail.

    ``sys.modules[name] = None`` makes ``import name`` raise ImportError, which
    is the optional-dependency-missing case the fallback exists to handle.
    """
    import sys

    from plugins.google_meet.cli import register_cli as meet_register_cli

    monkeypatch.setitem(sys.modules, "plugins.google_meet.node.cli", None)
    parser = argparse.ArgumentParser(prog="meet-test")
    meet_register_cli(parser)
    return parser


def test_node_unavailable_fallback_reports_the_error_not_a_nameerror(monkeypatch, capsys):
    """Regression for the F821 NameError at plugins/google_meet/cli.py:97.

    ``except Exception as e:`` compiles to an implicit ``del e`` at the end of
    the block, which clears the closure cell. ``_node_unavailable`` is defined
    inside that block but invoked LATER via argparse dispatch, so referencing
    ``e`` raised NameError — turning the friendly "module unavailable" message
    into the very crash it was written to prevent.
    """
    p = _build_meet_parser_with_broken_node_import(monkeypatch)

    args = p.parse_args(["node"])
    rc = args.func(args)

    assert rc == 1
    out = capsys.readouterr().out
    assert "module unavailable" in out
    # The captured reason must survive into the message, not be swallowed.
    assert "plugins.google_meet.node.cli" in out


def test_node_subparser_still_registered_when_import_fails(monkeypatch):
    """The fallback must keep the subcommand parseable, not drop it."""
    p = _build_meet_parser_with_broken_node_import(monkeypatch)

    args = p.parse_args(["node"])
    assert args.meet_command == "node"
    assert callable(args.func)
