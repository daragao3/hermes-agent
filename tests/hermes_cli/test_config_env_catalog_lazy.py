"""``hermes_cli.config`` must not build the OPTIONAL_ENV_VARS catalog at import.

Why this exists
---------------
``config.py`` used to end with two module-scope calls, ``_inject_profile_env_vars()``
and ``_inject_platform_plugin_env_vars()``, that mutated ``OPTIONAL_ENV_VARS`` at
import. The first reaches ``providers.list_providers()``, whose discovery imports
every ``providers/*`` module (48 of them); the second parses the 22 bundled
``plugins/platforms/*/plugin.yaml`` manifests. Every process touching
``hermes_cli.config`` paid it -- every ``python -m hermes_cli.main <anything>``
spawn, every gateway/worker start, every test process -- including the whole
``kanban`` and ``plugins`` command families, which never read this table.
Measured on an idle box: ~1.16 s median for ``import hermes_cli.config``, of which
~0.5 s was the provider half alone; under load it was 6.9 s of a 9.3 s import
(loops ``hermes-cli-config-import-optional-env-vars-lazy-20260919``).

The catalog is now a ``_EnvVarCatalog``: the 154 hand-written entries are built at
import, the 178 injected ones are filled in on the FIRST READ. The danger in that
trade is a reader observing a short catalog through a path the subclass does not
cover -- ``hermes config`` or the dashboard Keys page silently losing
``ANTHROPIC_API_KEY`` -- so ``test_every_read_path_populates_first`` walks every
read operation CPython can route to a dict, including the ones that go through C
(``dict(c)``, ``{**c}``, ``json.dumps(c)``, ``f(**c)``).

The import assertions run in SUBPROCESSES on purpose: ``sys.modules`` is
process-global and the catalog is a module-global singleton, so a sibling test
that legitimately imported ``providers`` or read the catalog would mask a
regression here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Two entries that only exist because an injector ran: the first comes from a
# providers/ profile, the second from plugins/platforms/whatsapp/plugin.yaml.
# Neither is in the hand-written literal in config_defaults.py.
PROVIDER_INJECTED = "ANTHROPIC_API_KEY"
PLATFORM_INJECTED = "WHATSAPP_ENABLED"


def _run(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), HERMES_DISABLE_LAZY_INSTALLS="1")
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


# ---------------------------------------------------------------- import cost


def test_importing_config_does_not_import_the_providers_package():
    out = _run(
        "import sys; import hermes_cli.config; print('providers' in sys.modules)"
    ).stdout.strip()
    assert out == "False", (
        "importing hermes_cli.config imported the providers package -- provider "
        "discovery (48 modules) is back on every CLI spawn's startup path"
    )


def test_importing_config_leaves_the_catalog_uninjected_until_a_read():
    """The raw dict is short at import and complete after one read.

    ``dict.__len__``/``dict.__contains__`` are called unbound on purpose: that is
    the only way to look at the table without tripping the lazy fill we are
    measuring.
    """
    out = _run(
        "import hermes_cli.config as c;"
        "cat = c.OPTIONAL_ENV_VARS;"
        "raw = dict.__len__(cat);"
        "raw_has = dict.__contains__(cat, %r);"
        "full = len(cat);"
        "print(raw, raw_has, full, %r in cat)" % (PROVIDER_INJECTED, PLATFORM_INJECTED)
    ).stdout.split()
    raw, raw_has, full, full_has = int(out[0]), out[1], int(out[2]), out[3]
    assert raw_has == "False", (
        f"{PROVIDER_INJECTED} was already in the catalog at import time -- the "
        "provider injector still runs at module scope"
    )
    assert raw < full, (
        f"the catalog held all {raw} entries before the first read -- nothing is "
        "being deferred"
    )
    assert full_has == "True", (
        f"{PLATFORM_INJECTED} is missing after a read -- the platform-plugin "
        "injector never ran"
    )


def test_reading_the_catalog_through_config_defaults_alone_still_injects():
    """A caller that never imports ``hermes_cli.config`` must still see the full
    table: the catalog pulls in its own injectors on first read."""
    out = _run(
        "import hermes_cli.config_defaults as d;"
        "print(%r in d.OPTIONAL_ENV_VARS, %r in d.OPTIONAL_ENV_VARS)"
        % (PROVIDER_INJECTED, PLATFORM_INJECTED)
    ).stdout.split()
    assert out == ["True", "True"], (
        "reading OPTIONAL_ENV_VARS straight from config_defaults returned the "
        f"hand-written table only: {out}"
    )


# ------------------------------------------------------- read-path completeness


def _fresh():
    """A catalog with one hand-written entry and a populator that adds one more."""
    from hermes_cli.config_defaults import _EnvVarCatalog

    calls = []
    catalog = _EnvVarCatalog({"HAND": {"description": "hand-written"}})

    def _populate(target):
        calls.append(1)
        target["INJECTED"] = {"description": "injected"}

    catalog.set_populator(_populate)
    return catalog, calls


READ_OPS = {
    "getitem": lambda c: c["HAND"],
    "contains": lambda c: "HAND" in c,
    "len": len,
    "bool": bool,
    "iter": lambda c: list(iter(c)),
    "sorted": sorted,
    "reversed": lambda c: list(reversed(c)),
    "keys": lambda c: list(c.keys()),
    "values": lambda c: list(c.values()),
    "items": lambda c: list(c.items()),
    "get": lambda c: c.get("HAND"),
    "copy": lambda c: c.copy(),
    "dict(c)": dict,
    "{**c}": lambda c: {**c},
    "f(**c)": lambda c: (lambda **kw: kw)(**c),
    "other.update(c)": lambda c: {}.update(c),
    "repr": repr,
    "eq": lambda c: c == {},
    "ne": lambda c: c != {},
    "or": lambda c: c | {},
    "json.dumps": json.dumps,
    "pop": lambda c: c.pop("HAND", None),
    "popitem": lambda c: c.popitem(),
    "setdefault": lambda c: c.setdefault("HAND", None),
    "delitem": lambda c: c.__delitem__("HAND"),
    "clear": lambda c: c.clear(),
}


@pytest.mark.parametrize("op_name", sorted(READ_OPS))
def test_every_read_path_populates_first(op_name):
    catalog, calls = _fresh()
    assert calls == [], "constructing the catalog must not populate it"
    READ_OPS[op_name](catalog)
    assert calls == [1], (
        f"reading the catalog via {op_name} did not run the populator -- a caller "
        "using that path would observe the hand-written entries only"
    )


@pytest.mark.parametrize(
    "op_name", ["dict(c)", "{**c}", "f(**c)", "json.dumps", "items", "keys", "copy"])
def test_bulk_read_paths_return_the_injected_entries(op_name):
    """Populating is not enough: the value the caller gets back must carry the
    injected entries too, not a snapshot taken before the fill."""
    catalog, _ = _fresh()
    result = READ_OPS[op_name](catalog)
    text = result if isinstance(result, str) else repr(list(result))
    assert "INJECTED" in text, (
        f"{op_name} returned a view built before the populator ran: {text}")


# ------------------------------------------------------------- fill semantics


def test_the_populator_runs_once_no_matter_how_many_reads():
    catalog, calls = _fresh()
    for _ in range(3):
        len(catalog)
        "HAND" in catalog
        list(catalog.items())
    assert calls == [1], f"the populator ran {len(calls)} times"


def test_writing_to_the_catalog_does_not_populate_it():
    """The injectors fill the table through ``__setitem__``; if writes populated,
    the first injected entry would re-enter the fill."""
    catalog, calls = _fresh()
    catalog["NEW"] = {"description": "new"}
    catalog.update({"NEWER": {"description": "newer"}})
    assert calls == [], "a plain write triggered the lazy fill"


def test_an_entry_written_before_the_first_read_survives_the_fill():
    """Back-compat the eager version got for free: a name already in the table wins
    over the injected one (both injectors skip names already present). With the fill
    deferred, a caller can now seed an entry BEFORE the injectors have run, so this
    pins the real injectors, not a stand-in populator.

    Subprocess: it writes to the module-global catalog."""
    out = _run(
        "import hermes_cli.config as c;"
        "c.OPTIONAL_ENV_VARS[%r] = {'description': 'seeded'};"
        "print(c.OPTIONAL_ENV_VARS[%r]['description'])" % (PROVIDER_INJECTED, PROVIDER_INJECTED)
    ).stdout.strip()
    assert out == "seeded", (
        f"the fill clobbered an entry seeded before the first read: {out!r}")


def test_a_populator_that_cannot_run_yet_is_retried_on_the_next_read():
    """A read that lands mid-import of hermes_cli.config must not latch a short
    catalog forever."""
    from hermes_cli.config_defaults import _EnvVarCatalog

    attempts = []
    catalog = _EnvVarCatalog({"HAND": {}})

    def _populate(target):
        attempts.append(1)
        if len(attempts) == 1:
            raise ImportError("hermes_cli.config is only half-imported")
        target["INJECTED"] = {}

    catalog.set_populator(_populate)
    assert "INJECTED" not in catalog
    assert "INJECTED" in catalog, "the failed fill was latched instead of retried"
    assert len(attempts) == 2


def test_a_read_from_inside_the_populator_does_not_recurse():
    from hermes_cli.config_defaults import _EnvVarCatalog

    calls = []
    catalog = _EnvVarCatalog({"HAND": {}})

    def _populate(target):
        calls.append(1)
        if "HAND" not in target:  # the real injectors do exactly this
            raise AssertionError("unreachable")
        target["INJECTED"] = {}

    catalog.set_populator(_populate)
    assert "INJECTED" in catalog
    assert calls == [1]


# ------------------------------------------------------- concurrency / deadlock


def test_a_second_thread_can_read_while_the_fill_is_running():
    """The fill must NOT hold a lock across the populator.

    The populator imports: `from providers import list_providers` walks 48 modules, so
    it takes importlib's per-module locks. Meanwhile tools/environments/local_env_policy.py
    reads this catalog AT MODULE SCOPE (line ~82, _build_provider_env_blocklist), so a
    thread can legitimately want the catalog while already holding an import lock. Hold a
    catalog-wide lock across the fill and those two orders invert into a hang -- the worst
    failure mode there is. A second thread therefore has to get through a read while a fill
    is in flight, even if that costs it a duplicate fill.
    """
    from hermes_cli.config_defaults import _EnvVarCatalog

    in_populator = threading.Event()
    release_populator = threading.Event()
    reads = []
    catalog = _EnvVarCatalog({"HAND": {"description": "hand-written"}})

    def _populate(target):
        if in_populator.is_set():
            target["INJECTED"] = {"description": "injected"}  # the reader's own fill
            return
        in_populator.set()
        release_populator.wait(30)  # stands in for `from providers import ...`
        target["INJECTED"] = {"description": "injected"}

    catalog.set_populator(_populate)

    filler = threading.Thread(target=lambda: len(catalog), daemon=True)
    filler.start()
    assert in_populator.wait(30), "the fill never started"

    reader = threading.Thread(target=lambda: reads.append("INJECTED" in catalog), daemon=True)
    reader.start()
    reader.join(10)
    reader_blocked = reader.is_alive()

    release_populator.set()
    filler.join(30)
    reader.join(30)

    assert not reader_blocked, (
        "a read from a second thread blocked behind the in-flight fill -- the catalog is "
        "holding a lock across the populator's imports, which deadlocks against any module "
        "that reads OPTIONAL_ENV_VARS at import scope")
    assert reads == [True], f"the second thread read a short catalog: {reads}"


def test_concurrent_first_reads_never_see_a_short_catalog():
    """Eight threads racing the very first read, as the dashboard's first page load does.
    Every one of them must observe the injected entries -- none may return the
    hand-written half because another thread's fill was still in flight."""
    out = _run(
        "from concurrent.futures import ThreadPoolExecutor;"
        "import hermes_cli.config as c;"
        "cat = c.OPTIONAL_ENV_VARS;"
        "probe = lambda _i: (%r in cat, %r in cat, len(cat));"
        "pool = ThreadPoolExecutor(max_workers=8);"
        "rows = list(pool.map(probe, range(8)));"
        "print(sorted(set(rows)))" % (PROVIDER_INJECTED, PLATFORM_INJECTED)
    ).stdout.strip()
    # set() collapses agreeing threads, so one row means all eight agreed.
    assert re.fullmatch(r"\[\(True, True, \d+\)\]", out), (
        "the eight concurrent first readers did not all see one full catalog "
        f"(each row is provider-entry, platform-entry, len): {out}")


# ------------------------------------------------------------- real wiring


def test_the_live_catalog_carries_both_injectors_entries():
    from hermes_cli.config import OPTIONAL_ENV_VARS

    assert PROVIDER_INJECTED in OPTIONAL_ENV_VARS, (
        "the provider-profile injector did not run on first read")
    assert PLATFORM_INJECTED in OPTIONAL_ENV_VARS, (
        "the platform-plugin injector did not run on first read")


def test_the_catalog_copies_and_pickles_as_a_plain_dict():
    """It stood in for a plain dict for years, so copy/deepcopy/pickle have to keep
    working -- and hand back the filled table, not a lazy shell carrying an
    unpicklable fill hook and lock."""
    import copy
    import pickle

    from hermes_cli.config import OPTIONAL_ENV_VARS

    for name, fn in (("copy.copy", copy.copy), ("copy.deepcopy", copy.deepcopy),
                     ("pickle round-trip", lambda d: pickle.loads(pickle.dumps(d)))):
        out = fn(OPTIONAL_ENV_VARS)
        assert type(out) is dict, (
            f"{name} returned a {type(out).__name__}, not the plain dict callers got "
            "before the catalog went lazy")
        assert PROVIDER_INJECTED in out, f"{name} dropped the injected entries"


def test_config_and_config_defaults_share_one_catalog_object():
    """Readers import the name by value from either module; if the fill produced a
    second object they would diverge."""
    from hermes_cli import config, config_defaults

    assert config.OPTIONAL_ENV_VARS is config_defaults.OPTIONAL_ENV_VARS
