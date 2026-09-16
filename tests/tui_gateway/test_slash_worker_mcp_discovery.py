"""Integration coverage for profile-local MCP discovery in slash workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import textwrap
import threading

import pytest
import yaml

_mcp_server_mod = pytest.importorskip("mcp.server")

if not hasattr(_mcp_server_mod, "MCPServer"):
    # `mcp.server.MCPServer` replaced `mcp.server.fastmcp.FastMCP` in mcp 2.0.
    # Skip rather than fail on a FastMCP-era SDK: the probe below is written
    # against the 2.x API, and the pinned version provides it.
    pytest.skip(
        "profile-local MCP discovery probe requires mcp >= 2.0 (MCPServer)",
        allow_module_level=True,
    )


# The repo's default addopts pin a 30s per-test watchdog (--timeout=30). This
# node spends ~13-20s on a cold slash-worker child alone, plus the deliberate
# probe start delay and the discovery wait below, so under sweep load the
# watchdog fired before the assertion could (2026-09-15 twelve-worker sweep,
# run 1). Lift it above RESPONSE_BUDGET_S, the same way
# test_isolated_orphan_activity.py / test_compute_host_turn_protocol.py do.
@pytest.mark.timeout(150)
def test_profile_local_mcp_tool_is_visible_in_slash_worker(tmp_path):
    profile_home = tmp_path / "profile-home"
    profile_home.mkdir()
    marker = "profile-local-61922"
    # Long enough that the default 1.5s discovery bound reliably misses the probe
    # (measured: the un-raised bound answers ~10s before a 6s-delayed server
    # finishes connecting), short enough not to dominate the test.
    PROBE_START_DELAY_S = 5
    server = tmp_path / "mcp_probe.py"
    server.write_text(
        textwrap.dedent(
            f"""
            import time

            # Deliberately SLOW to start (PROBE_START_DELAY_S above): the
            # worker only joins background discovery for ``mcp_discovery_timeout``
            # before it snapshots tools, so a server that is still connecting when
            # ``/tools`` runs is simply absent from the reply. Without this delay a
            # fast box discovers the probe inside the default 1.5s bound and the
            # config key below is never exercised -- a vacuous green.
            time.sleep({PROBE_START_DELAY_S})
            from mcp.server import MCPServer

            mcp = MCPServer("profileprobe")

            @mcp.tool()
            def hermes_61922_profile_probe() -> str:
                return {marker!r}

            if __name__ == "__main__":
                mcp.run(transport="stdio")
            """
        ),
        encoding="utf-8",
    )
    (profile_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                # The slash worker's discovery wait is BOUNDED by this key (default
                # 1.5s, hermes_cli/config_defaults.py): ``wait_for_mcp_discovery``
                # joins the discovery thread for at most that long, then HermesCLI
                # is built and ``/tools`` answers from whatever has registered so
                # far. A cold MCP server child (fresh interpreter + ``mcp`` import)
                # routinely needs longer than that on a loaded box, and the reply
                # then lists every built-in tool but not the probe -- measured
                # 2026-09-15 in 2 of 3 twelve-worker tests/tui_gateway sweeps as
                # "37 tools, probe absent". That is the product's deliberate
                # bounded-startup design (tui_gateway/entry.py, server.py
                # late-refresh), not a discovery defect: a later ``/tools`` reads
                # the live registry and shows the tool. This test asserts
                # profile-local DISCOVERY, so it raises the bound; ``join``
                # returns the instant discovery completes, so this is a readiness
                # gate, not a sleep.
                "mcp_discovery_timeout": 120,
                "mcp_servers": {
                    "profileprobe": {
                        "enabled": True,
                        "command": sys.executable,
                        "args": [str(server)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    for key in list(env):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            env.pop(key)
    env["HERMES_HOME"] = str(profile_home)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["HERMES_SLASH_WATCHDOG_GRACE_S"] = "0"
    env["HERMES_SLASH_WATCHDOG_POLL_S"] = "0.05"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "tui_gateway.slash_worker",
            "--session-key",
            "agent:main:tui:dm:mcp-profile-test",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    output: queue.Queue[str] = queue.Queue()
    errors: list[str] = []
    # A COLD slash worker pays a fresh interpreter plus the whole toolset and
    # MCP-discovery import chain before it can answer anything. Measured on a
    # Windows dev box 2026-09-14: 13.1s / 15.1s / 19.8s for this exact spawn on
    # an otherwise idle machine, so the original 10s budget could not be met
    # here at all and this test was unconditionally red. 120s is this repo's
    # own precedent for a slash-worker child (test_slash_worker_sys_path.py).
    # Nothing here measures latency -- the assertion is that a profile-local
    # MCP tool is DISCOVERED -- so the budget only needs to be safely large.
    RESPONSE_BUDGET_S = 120
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None
        stdout, stderr = proc.stdout, proc.stderr
        threading.Thread(
            target=lambda: output.put(stdout.readline()),
            daemon=True,
        ).start()
        # Drain stderr concurrently: without this the child's own traceback is
        # never seen and a failure here says only "no response", which is what
        # made this red undiagnosable from its own output.
        threading.Thread(
            target=lambda: errors.extend(stderr),
            daemon=True,
        ).start()
        proc.stdin.write(json.dumps({"id": 1, "command": "/tools"}) + "\n")
        proc.stdin.flush()
        try:
            line = output.get(timeout=RESPONSE_BUDGET_S)
        except queue.Empty:
            pytest.fail(
                f"slash worker produced no /tools response within "
                f"{RESPONSE_BUDGET_S}s (rc={proc.poll()}); child stderr:"
                + chr(10) + ("".join(errors[-40:]) or "(empty)")
            )
        response = json.loads(line)
        assert response["ok"] is True, response
        # Include the child's stderr on THIS failure too: the 2026-09-15 sweep
        # reds fell through here with nothing but the tool list to go on.
        assert "mcp__profileprobe__hermes_61922_profile_probe" in response["output"], (
            "profile-local MCP tool absent from /tools reply (rc="
            f"{proc.poll()}); child stderr:" + chr(10)
            + ("".join(errors[-40:]) or "(empty)")
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
