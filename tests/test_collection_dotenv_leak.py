"""Collection must not inject the host's live ``~/.hermes/.env`` into os.environ.

Two test modules did this, by different mechanisms, and a full-tree audit hook
found both:

* ``tests/integration/test_modal_terminal.py`` called a bare ``load_dotenv()``
  at MODULE level. ``find_dotenv()`` walks up from the calling file, and this
  checkout lives at ``~/.hermes/agent-src``, so the walk reached the live
  ``~/.hermes/.env``; ``set_as_environment_variables()`` then copied the host's
  production credentials into ``os.environ``.
* ``tests/run_agent/test_sequential_chats_live.py`` hand-rolled the same thing
  in a ``_load_user_env()`` called unconditionally at module scope, reading
  ``Path.home()/".hermes"/".env"`` and ``os.environ.setdefault``-ing every key.
  It is now gated on ``HERMES_LIVE_TESTS``.

Three properties made that worse than it looks, and they are why this guard is
behavioural rather than a grep:

* It ran at **collection**, before any autouse fixture existed to scrub it.
* Every test in that file is deselected by the default ``-m "not integration"``,
  so it fired on runs that never intended to touch the module at all --
  deselection skips execution, not import.
* The leaked names (``LANGFUSE_*``, ``OTEL_EXPORTER_OTLP_*``) are not
  credential-shaped enough for ``_hermetic_environment``'s scrub and are not in
  ``_HERMES_BEHAVIORAL_VARS``, so they survived into every subsequent test.

Same class as the ``obs/otel_tracing._load_env_once`` leak fixed in
``24e0a44868``; these re-opened it from the test side.

KNOWN AND DELIBERATELY NOT ASSERTED HERE: ``mini_swe_runner.py:40`` -- PRODUCT
code, not a test -- also calls a bare ``load_dotenv()`` at module scope, so
importing it leaks the same way. Fixing that is a production change (the same
audit that fixed ``_load_env_once`` found the leak was load-bearing for the live
gateway and needed 16 keys mirrored into ``profiles/main/.env`` first), so this
guard is deliberately scoped to the two TEST modules rather than asserting a
tree-wide property it would fail on today.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIVE_ENV = Path(os.path.expanduser("~")) / ".hermes" / ".env"

# A conftest-scrubbed name would pass this guard for the wrong reason, so probe
# on names the hermetic fixture deliberately leaves alone.
_PROBE_NAMES = ("LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "OTEL_EXPORTER_OTLP_ENDPOINT")

_PROBE_TEMPLATE = """
import json, os, sys

NAMES = __NAMES__


def pytest_collection_finish(session):
    sys.stdout.write("PROBE" + json.dumps({n: (n in os.environ) for n in NAMES}) + chr(10))
"""


def _live_env_names() -> set[str]:
    if not LIVE_ENV.is_file():
        return set()
    names = set()
    for line in LIVE_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return names


@pytest.mark.parametrize("target", [
    "tests/integration/test_modal_terminal.py",
    "tests/run_agent/test_sequential_chats_live.py",
])
def test_collecting_a_module_does_not_import_the_live_dotenv(tmp_path, target):
    """Collect the module in a child pytest and read that child's environment.

    Textual assertions ("no bare ``load_dotenv()``") go quiet the moment someone
    reintroduces the leak through a different call -- and in fact the two known
    cases used *different* calls, one ``load_dotenv()`` and one hand-rolled
    reader. So this drives the real collection instead of grepping.
    """
    present = _live_env_names() & set(_PROBE_NAMES)
    if not present:
        pytest.skip(
            "this host's ~/.hermes/.env defines none of the probe names, so a "
            "leak here would be undetectable -- the guard would pass vacuously"
        )

    plugin = tmp_path / "collect_env_probe.py"
    plugin.write_text(
        _PROBE_TEMPLATE.replace("__NAMES__", json.dumps(list(_PROBE_NAMES))),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    # The parent process may already be contaminated; start the child clean.
    for name in _PROBE_NAMES:
        env.pop(name, None)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", target,
         "--collect-only", "-q", "-p", "no:randomly", "-p", "collect_env_probe"],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )

    line = next((ln for ln in result.stdout.splitlines() if ln.startswith("PROBE")), None)
    assert line is not None, (
        "the probe plugin never reported; collection failed?\n"
        f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
    )
    seen = json.loads(line[len("PROBE"):])
    leaked = sorted(n for n in present if seen.get(n))
    assert not leaked, (
        f"collecting {target} injected {leaked} from the live {LIVE_ENV} into "
        "the test process environment. Either give load_dotenv() an explicit "
        "repo-scoped path -- a bare call walks up into ~/.hermes because the "
        "checkout lives inside it -- or gate the read behind the flag that "
        "makes the module's tests actually run."
    )
