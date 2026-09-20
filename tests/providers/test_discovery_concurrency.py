"""``providers._discover_providers`` must be safe for concurrent first callers.

Why this exists
---------------
``_discover_providers`` set its ``_discovered`` flag BEFORE importing the 48 provider
plugins, so a second thread arriving mid-discovery saw the flag, skipped discovery and
returned whatever ``_REGISTRY`` held at that instant -- often nothing.

Nothing exposed that while ``hermes_cli.config`` called ``list_providers()`` at module
scope: discovery ran under importlib's module lock, so only one thread could ever be
inside it. Moving the OPTIONAL_ENV_VARS fill to first read (loops
``hermes-cli-config-import-optional-env-vars-lazy-20260919``) put ``list_providers()``
on the dashboard's first request instead, where eight worker threads reach it at once,
and a loser thread latched a 301-entry env catalog with no ANTHROPIC_API_KEY row.

Subprocess, because discovery is a process-global one-shot: a sibling test that already
imported ``providers`` would leave nothing to race.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_concurrent_first_callers_all_get_the_whole_provider_list():
    code = (
        "from concurrent.futures import ThreadPoolExecutor;"
        "import providers;"
        "pool = ThreadPoolExecutor(max_workers=8);"
        "counts = sorted(set(pool.map(lambda _i: len(providers.list_providers()), range(8))));"
        "print(counts)"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), HERMES_DISABLE_LAZY_INSTALLS="1")
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    counts = [int(n) for n in proc.stdout.strip().strip("[]").split(",") if n.strip()]
    assert len(counts) == 1, (
        "concurrent first callers of list_providers() disagreed on how many providers "
        f"exist -- a loser thread skipped discovery and got a partly-built registry: {counts}")
    assert counts[0] > 1, f"discovery returned {counts[0]} providers"
