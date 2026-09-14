"""Collection-time warm for the agent stack (``run_agent``).

Call :func:`warm_agent_stack` at MODULE level from any gateway test file whose
tests import ``run_agent`` (usually ``from run_agent import AIAgent``) from
*inside* a helper or a test body.

Why the import has to be forced into collection
-----------------------------------------------
``import run_agent`` pulls the whole agent stack and runs plugin discovery:
~1,570 modules, measured at 7.0s on an idle box and ~25s on a loaded one.

Importing it lazily is right for production -- CLI startup must not pay it --
but in a test it moves the cost out of module import and into whichever test
body touches it first. Collection is NOT covered by pytest's per-test
``--timeout``; a test body is. Under the repo's own ``--timeout=30`` addopts
that makes the first such test a coin flip on host load, and because
pytest-timeout's thread method kills the whole process, the rest of the file
goes unreported: the file surfaces as a bare timeout rather than as one slow
test.

This is the same fix, and the same reasoning, as
``tests/gateway/_feishu_sdk_warm.py`` -- and as the inline warm already in
``tests/gateway/test_compression_concurrent_sessions.py``, which cites
``671b38765`` after the 2026-08-11 gate incident. Paying the identical one-time
cost here, in an untimed phase, is not a new cost: it is the same import
relocated to a place where it cannot fail the file.

Strictly best-effort: it must never decide whether tests run. A file whose
tests genuinely need ``run_agent`` still imports it itself and fails there, in
its own frame, if the module is broken.
"""

import os
import sys
from unittest.mock import patch


def warm_agent_stack(env: "dict[str, str] | None" = None) -> None:
    """Import ``run_agent`` now; never raise.

    ``env`` mirrors whatever ``patch.dict(os.environ, ...)`` the file's own
    deferred import uses, so the module sees an identical environment either
    way. Most callers import it bare and pass nothing; pass the same mapping
    when the in-body import is wrapped in one.
    """
    if "run_agent" in sys.modules:
        # Already loaded, or deliberately stubbed by a test file. Leave it.
        return
    try:
        with patch.dict(os.environ, env or {}):
            import run_agent  # noqa: F401
    except Exception:  # noqa: BLE001 — best-effort warm, never fatal
        pass
