"""Locate the 2026-09-08 wave's isolated Node runtime for the desktop probes.

The ``tests/test_upgrade_desktop_*.py`` probes were written for the 0.21.1
integration ceremony (8586e305a2), which provisioned a private Node under
``<checkout>/../runtime-wave01-20260908`` so the desktop toolchain (tsc, vite,
vitest, electron-builder) ran isolated from the host's ``C:\\Program
Files\\nodejs``.  That runtime is a ceremony artifact, not part of the
checkout: it is absent once the wave's evidence tree is pruned, and it is
unreachable from any ``.claude/worktrees/<name>`` checkout, whose parent is
the worktrees directory rather than ``~/.hermes``.

Probes that need it call :func:`wave_node` and skip when it is absent, the
same gate shape as ``_provision()`` in
``tests/test_upgrade_private_python_runtime.py`` -- a missing ceremony
fixture is not a product failure.  The path expression is kept exactly as the
probes spelled it so a host that still holds the runtime resolves it as before.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WAVE_NODE = REPO_ROOT.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"


def wave_node() -> Path:
    """Return the wave's ``node.exe``; skip the calling test when it is absent."""
    if not WAVE_NODE.is_file():
        pytest.skip(f"isolated Wave 1 Node runtime absent: {WAVE_NODE}")
    return WAVE_NODE
