"""Memory Fabric provider — READ-ONLY per-turn recall through the local memory-fabric gateway.

Implements only :meth:`prefetch`: the first turn of a session warms with ``memory_context``
(default entities + GBrain context pack), later turns call ``memory_recall`` for the turn's
query. GBrain stays canonical and MemPalace historical; this provider never writes — no
``sync_turn``, no tools, no transcript capture (promotion goes through the gateway's review
queue, never through a turn hook).

Transport: the gateway's stateless streamable-HTTP MCP endpoint (default
``http://127.0.0.1:7492/mcp``) with a static bearer token, resolved from ``MEMORY_FABRIC_TOKEN``
or ``plugins.memory_fabric.token_file`` in config.yaml. Proxies are bypassed: it is loopback.

Latency: a recall is ~2 s on a quiet box and 40-80 s on a saturated one, while the manager
bounds prefetch at 8 s on the turn's critical path. So each call waits at most
``timeout_seconds``; a call that misses the deadline keeps running in a daemon thread and its
result is offered to the NEXT turn (while younger than ``late_ttl_seconds``) instead of being lost.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.memory_provider import MemoryProvider, RecallStatus
from hermes_cli.config import cfg_get

logger = logging.getLogger(__name__)

PROVIDER_NAME = "memory_fabric"
TOKEN_ENV = "MEMORY_FABRIC_TOKEN"
DEFAULTS: Dict[str, Any] = {
    "url": "http://127.0.0.1:7492/mcp",
    "warmup": True,  # False: skip the first-turn memory_context (default-entity profile) and only recall
    "token_file": "",
    "timeout_seconds": 6.0,  # < the manager's 8 s external prefetch bound
    "call_timeout_seconds": 90.0,  # background ceiling for a call that missed the turn
    "late_ttl_seconds": 600.0,
    "budget_tokens": 1500,
    "limit": 8,
    "max_chars": 4000,
    "max_row_chars": 400,
    "skip_platforms": ["cron"],
}
# Non-primary agents (cron jobs, subagents, flush agents) get no recall: high volume, no user.
_SKIP_CONTEXTS = frozenset({"cron", "flush", "subagent"})
_WS = re.compile(r"\s+")


def _load_plugin_config() -> dict:
    try:
        from hermes_cli.config import load_config_readonly  # managed-scope overlay + ${VAR} expansion
        return cfg_get(load_config_readonly(), "plugins", PROVIDER_NAME, default={}) or {}
    except Exception:
        return {}


class GatewayError(RuntimeError):
    """The gateway answered, but not with a usable tool result."""


def call_gateway(url: str, token: str, tool: str, arguments: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """One stateless MCP ``tools/call``; returns the tool's decoded JSON payload."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        envelope = json.loads(resp.read().decode("utf-8"))
    if "error" in envelope:
        raise GatewayError(f"{tool}: {envelope['error']}")
    result = envelope.get("result") or {}
    text = next((c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text"), "")
    if result.get("isError"):
        raise GatewayError(f"{tool}: {text[:200]}")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise GatewayError(f"{tool}: non-JSON tool result") from exc
    if not isinstance(payload, dict):
        raise GatewayError(f"{tool}: unexpected result type {type(payload).__name__}")
    return payload


def format_pack(payload: Dict[str, Any], *, max_chars: int, max_row_chars: int) -> Tuple[str, int]:
    """Render a gateway pack's canonical rows as a bullet list; ``("", 0)`` when empty.
    History rows are ignored: only canonical (GBrain) state is injected."""
    lines: List[str] = []
    used = 0
    for row in payload.get("canonical") or []:
        if not isinstance(row, dict):
            continue
        text = row.get("fact") or " — ".join(
            str(p) for p in (row.get("title"), row.get("chunk") or row.get("excerpt") or row.get("summary")) if p)
        text = _WS.sub(" ", str(text or "")).strip()
        if not text:
            continue
        if len(text) > max_row_chars:
            text = text[: max_row_chars - 1].rstrip() + "…"
        source = row.get("entity_slug") or row.get("slug")
        line = f"- {text}" + (f" [{source}]" if source else "")
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return "", 0
    return "## Memory Fabric (GBrain canonical facts)\n" + "\n".join(lines), len(lines)


class MemoryFabricProvider(MemoryProvider):
    """Prefetch-only provider over the memory-fabric gateway."""

    def __init__(self, config: Optional[dict] = None):
        self._config = {**DEFAULTS, **(config or {})}
        self._enabled = True
        self._lock = threading.Lock()
        self._warmed: set = set()  # session ids whose memory_context warm-up succeeded
        self._inflight: Dict[str, threading.Thread] = {}
        self._late: Dict[str, Tuple[float, str, int]] = {}
        self._status: Optional[RecallStatus] = None

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    # -- config -------------------------------------------------------------

    def _token(self) -> str:
        token = ""
        try:
            from agent.secret_scope import get_secret
            token = get_secret(TOKEN_ENV) or ""
        except Exception:
            token = os.environ.get(TOKEN_ENV, "")
        if token.strip():
            return token.strip()
        token_file = str(self._config.get("token_file") or "").strip()
        if token_file:
            try:
                return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def is_available(self) -> bool:
        return bool(self._config.get("url")) and bool(self._token())

    def unavailable_reason(self) -> str:
        return (f"set {TOKEN_ENV} or plugins.{PROVIDER_NAME}.token_file (the memory-fabric "
                "gateway's bearer token file, e.g. C:/AI/memory-fabric/state/local-token)")

    def initialize(self, session_id: str, **kwargs) -> None:
        platform = str(kwargs.get("platform") or "")
        skip = set(self._config.get("skip_platforms") or [])
        self._enabled = kwargs.get("agent_context", "") not in _SKIP_CONTEXTS and platform not in skip
        if not self._enabled:
            logger.debug("memory_fabric prefetch disabled (platform=%s, agent_context=%s)",
                         platform, kwargs.get("agent_context"))

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    # -- recall -------------------------------------------------------------

    def recall_status(self) -> Optional[RecallStatus]:
        return self._status

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._status = None
        if not self._enabled or not (query or "").strip():
            return ""
        with self._lock:
            busy = session_id in self._inflight
            warm = session_id in self._warmed
        if busy:  # a previous call is still running; never stack a second one behind it
            return self._take_late(session_id)
        tool, args = self._request(query, warm)
        box: Dict[str, Any] = {}
        done = threading.Event()
        worker = threading.Thread(target=self._run, args=(session_id, tool, args, box, done),
                                  name=f"memory-fabric-{tool}", daemon=True)
        with self._lock:
            self._inflight[session_id] = worker
        worker.start()
        done.wait(float(self._config["timeout_seconds"]))
        with self._lock:  # decide under the lock: the worker may finish between wait() and here
            text, count = box.get("text", ""), box.get("count", 0)
            if "text" not in box:
                box["late"] = True  # still running (or failed): _run stashes a result for the next turn
            elif text:
                self._late.pop(session_id, None)  # a fresh answer supersedes an older late one
        if not text:
            return self._take_late(session_id)
        self._status = RecallStatus(provider_label="Memory Fabric", count=count)
        return text

    def _request(self, query: str, warm: bool) -> Tuple[str, Dict[str, Any]]:
        budget = int(self._config["budget_tokens"])
        q = query.strip()[:1000]
        if not warm and self._config.get("warmup", True):
            return "memory_context", {"query": q, "budget_tokens": budget}
        return "memory_recall", {"query": q, "budget_tokens": budget, "limit": int(self._config["limit"])}

    def _run(self, session_id: str, tool: str, args: Dict[str, Any], box: Dict[str, Any], done: threading.Event) -> None:
        try:
            token = self._token()
            payload = call_gateway(str(self._config["url"]), token, tool, args,
                                   float(self._config["call_timeout_seconds"]))
            text, count = format_pack(payload, max_chars=int(self._config["max_chars"]),
                                      max_row_chars=int(self._config["max_row_chars"]))
            with self._lock:
                if tool == "memory_context" and not payload.get("degraded"):
                    self._warmed.add(session_id)
                box["text"], box["count"] = text, count
                if box.get("late") and text:
                    self._late[session_id] = (time.monotonic(), text, count)
        except Exception as exc:
            logger.debug("memory_fabric %s failed (non-fatal): %s", tool, exc)
        finally:
            with self._lock:
                self._inflight.pop(session_id, None)
            done.set()

    def _take_late(self, session_id: str) -> str:
        """Consume a result that arrived after its own turn's deadline, if still fresh."""
        with self._lock:
            entry = self._late.pop(session_id, None)
        if not entry:
            return ""
        stamp, text, count = entry
        if time.monotonic() - stamp > float(self._config["late_ttl_seconds"]):
            return ""
        self._status = RecallStatus(provider_label="Memory Fabric", count=count)
        return text

    def on_session_switch(self, new_session_id: str, *, parent_session_id: str = "", reset: bool = False,
                          rewound: bool = False, **kwargs) -> None:
        if reset:
            with self._lock:
                self._warmed.discard(new_session_id)
                self._late.pop(new_session_id, None)

    def shutdown(self) -> None:
        with self._lock:
            self._late.clear()


def register(ctx) -> None:
    """Register the memory-fabric provider with the plugin system."""
    ctx.register_memory_provider(MemoryFabricProvider(config=_load_plugin_config()))
