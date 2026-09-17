"""How to spawn :file:`_mock_lsp_server.py` so its stdout EOF actually reaches the client.

``sys.executable`` is the wrong interpreter for this on Windows. There a venv's
``Scripts\\python.exe`` is a launcher stub that spawns the real interpreter as a
CHILD and waits for it (two PIDs -- the same trap
``hermes_cli.windows_ssh_runtime._resolve_direct_interpreter`` documents). The
stub inherits the client's stdout pipe and holds its copy open, so when the
mock's ``clean_eof`` script does ``os.close(sys.stdout.fileno())`` the pipe
stays open until the stub itself exits: the reader never sees EOF and the
"reader failure retires the client" tests time out. Measured 2026-09-16 on the
uv-managed 3.12 venv: base interpreter -> EOF in 0.12 s; venv launcher -> no
EOF within 4 s while the child slept.

The mock server is stdlib-only, so the base interpreter runs it everywhere; on
POSIX a venv's ``python`` is a symlink to that same binary, so this is a no-op
there.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MOCK_SERVER = str(Path(__file__).parent / "_mock_lsp_server.py")

_base = getattr(sys, "_base_executable", None)
MOCK_PYTHON = _base if _base and os.path.isfile(_base) else sys.executable


def mock_server_command() -> list[str]:
    """argv that runs the mock LSP server in a process that OWNS its stdout pipe."""
    return [MOCK_PYTHON, MOCK_SERVER]
