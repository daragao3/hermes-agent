"""``_kill_orphaned_mcp_children`` must not import ``tools.mcp_tool`` when there is
nothing to reap.

cron's post-tick sweep (``cron.scheduler._sweep_mcp_orphans``) calls it on EVERY tick.
Before the fast path, ``_take_reapable_pids`` touched ``_core._lock`` -- an ``_OriginProxy``
attribute -- which executes the whole ``tools.mcp_tool`` module body and pulled in 18
modules just to take a lock and find both ledgers empty, in gateway / cron / test
processes that never speak MCP.

The import cost is the point, but it is not the only reason this matters: that import was
observed faulting the interpreter outright (``Windows fatal exception: access violation``
inside ``importlib._bootstrap_external._compile_bytecode`` while loading
``tools.mcp_tool_transport``, 2 of 100 runs of a cron tick test on a loaded Windows box,
agent-src e99105820d). The fast path removes that code path from every MCP-free tick. It
is NOT a fix for the underlying native fault, which was never root-caused.

The first test runs in a SUBPROCESS on purpose: ``tools.mcp_tool`` is almost certainly
already in ``sys.modules`` by the time this file runs inside the wider suite, so an
in-process assertion would be vacuous.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import sys
import cron.scheduler as sched
sched._sweep_mcp_orphans()
print("IMPORTED" if "tools.mcp_tool" in sys.modules else "NOT_IMPORTED")
print("TRANSPORT" if "tools.mcp_tool_transport" in sys.modules else "NO_TRANSPORT")
"""


def test_mcp_free_tick_sweep_does_not_import_the_mcp_tool_graph():
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stdout}\n{proc.stderr}"
    out = proc.stdout.split()
    assert "NOT_IMPORTED" in out, (
        "a sweep with no stdio children imported tools.mcp_tool; the _take_reapable_pids "
        f"fast path is gone. probe said: {proc.stdout!r}")
    assert "NO_TRANSPORT" in out, (
        "tools.mcp_tool_transport was imported by an MCP-free sweep -- that is the module "
        f"whose bytecode load was observed faulting. probe said: {proc.stdout!r}")


@pytest.fixture
def clean_ledgers():
    """Snapshot/restore the module ledgers so these tests cannot leak into siblings."""
    from tools import mcp_tool_lifecycle as lc
    orphans = set(lc._orphan_stdio_pids)
    active = dict(lc._stdio_pids)
    lc._orphan_stdio_pids.clear()
    lc._stdio_pids.clear()
    try:
        yield lc
    finally:
        lc._orphan_stdio_pids.clear()
        lc._orphan_stdio_pids.update(orphans)
        lc._stdio_pids.clear()
        lc._stdio_pids.update(active)


def _trap_take_reapable(monkeypatch, lc):
    """Replace _take_reapable_pids with a recorder that reaps nothing (so no real kill)."""
    seen = []

    def _fake(include_active, server_name):
        seen.append((include_active, server_name))
        return {}, {}

    monkeypatch.setattr(lc, "_take_reapable_pids", _fake)
    return seen


# --- controls: without these, "always return early" would pass the test above ------------

def test_a_registered_orphan_still_reaches_the_reaper(clean_ledgers, monkeypatch):
    lc = clean_ledgers
    seen = _trap_take_reapable(monkeypatch, lc)
    lc._orphan_stdio_pids.add(4242)

    lc._kill_orphaned_mcp_children()

    assert seen == [(False, None)], (
        "the fast path swallowed a real orphan -- it must only skip when the ledgers are empty")


def test_include_active_still_reaches_the_reaper_for_a_live_child(clean_ledgers, monkeypatch):
    lc = clean_ledgers
    seen = _trap_take_reapable(monkeypatch, lc)
    lc._stdio_pids[4243] = "some-server"

    lc._kill_orphaned_mcp_children(include_active=True)

    assert seen == [(True, None)], "final shutdown must still reap live stdio children"


def test_a_live_child_is_never_killed_by_the_default_sweep(clean_ledgers, monkeypatch):
    """The default sweep deliberately ignores _stdio_pids -- a live session must survive it.

    This asserts on what is SIGNALLED, not on whether _take_reapable_pids was reached,
    so it holds identically with and without the fast path. That is the point: it is a
    control against the fast path starting to reap active children, and a control that
    only passes on the new code would not be one.
    """
    lc = clean_ledgers
    signalled = []
    monkeypatch.setattr(lc, "_signal_mcp_process",
                        lambda pid, sig, owner, pgid, my_pgid: signalled.append(pid))
    lc._stdio_pids[4244] = "some-server"

    lc._kill_orphaned_mcp_children()

    assert signalled == [], "default sweep must never signal an ACTIVE stdio child"
    assert lc._stdio_pids == {4244: "some-server"}, "default sweep must not pop the active ledger"
