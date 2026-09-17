"""Boot-time daemon threads must be retired on EVERY ``start_gateway`` exit.

Companion to ``test_early_boot_heartbeat_binding.py``. That file fixed the
early-boot heartbeat and the nous auth keepalive; the same defect survives in
two more threads started by ``start_gateway``, both of which re-resolve
``HERMES_HOME`` on every tick:

* ``_run_planned_stop_watcher`` — started ~70 lines BEFORE
  ``await runner.start()``, but ``_planned_stop_watcher_stop.set()`` sits at the
  very bottom of the function. Both the ``if not success:`` return and the
  ``if runner.should_exit_with_failure:`` return skip it, so a failed start
  leaks a 0.5s poll loop for the life of the process. It calls
  ``planned_stop_marker_targets_self()``, which re-resolves the marker path and
  *unlinks* stale/malformed markers.

* ``_start_gateway_housekeeping`` — shares ``cron_stop``, which is only set
  after the ``should_exit_with_failure`` return. Its hourly chore calls
  ``cleanup_image_cache()``, which resolves ``get_image_cache_dir()`` live and
  ``unlink()``s every file older than 24h. A leaked housekeeping thread whose
  env has been restored deletes real ``~/.hermes/image_cache`` entries.

The discriminator for this bug class is NOT "is it a daemon" — daemon-ness only
governs interpreter exit, which is irrelevant inside a long pytest session
where the next tick lands minutes earlier. It is: *an unbounded poll loop whose
stop is not reachable from every return, including the raising one.*

See GBrain ``concepts/import-time-hermes-home-snapshot-bug``.

2026-09-17: the upstream 0.21.1 body of ``start_gateway`` retires both threads
from ONE outer ``finally`` (``_planned_stop_watcher_stop.set()`` and
``_stop_gateway_cron_resources(...)``, which sets ``cron_stop``) instead of a
``.set()`` beside each return. That is the stronger shape of the same
property, and the old text-slice assertions read it as a regression every
night. The checks below assert the PROPERTY over the function's AST: every
``return`` (and every ``raise SystemExit``) is inside the ``try`` whose
``finally`` retires the threads, and that ``finally`` names both stops.
"""

import ast
import inspect
import textwrap

import pytest

from gateway import run as gateway_run


@pytest.fixture(scope="module")
def start_gateway_fn() -> ast.AsyncFunctionDef:
    src = textwrap.dedent(inspect.getsource(gateway_run.start_gateway))
    fn = ast.parse(src).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    return fn


def _calls_in(nodes: list[ast.stmt]) -> set[str]:
    """Dotted call names inside ``nodes`` (``a.b.set()`` -> ``a.b.set``)."""
    out: set[str] = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                out.add(ast.unparse(sub.func))
    return out


def _outer_retiring_try(fn: ast.AsyncFunctionDef) -> ast.Try:
    """The outermost ``try`` of the function whose ``finally`` retires the
    planned-stop watcher. There must be exactly one such statement at the
    function's top level -- nested ones would cover only some returns."""
    candidates = [
        node for node in fn.body
        if isinstance(node, ast.Try) and "_planned_stop_watcher_stop.set" in _calls_in(node.finalbody)
    ]
    assert len(candidates) == 1, (
        "start_gateway() must retire the planned-stop watcher from ONE top-level "
        f"try/finally; found {len(candidates)}"
    )
    return candidates[0]


def _watcher_start_line(fn: ast.AsyncFunctionDef) -> int:
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and ast.unparse(sub.func) == "_planned_stop_watcher_thread.start":
            return sub.lineno
    raise AssertionError("start_gateway() never starts the planned-stop watcher")


def _exits_outside(fn: ast.AsyncFunctionDef, covered: ast.Try) -> list[str]:
    """Every return / raise-SystemExit of the function AFTER the watcher has
    started that is NOT inside the covered try's body (its finally runs for
    those; a return in the finally itself or after the try would not be
    retired). Exits before the thread exists cannot leak it."""
    started_at = _watcher_start_line(fn)
    inside: set[int] = set()
    for node in covered.body + covered.handlers + covered.orelse:
        for sub in ast.walk(node):
            inside.add(id(sub))
    leaks: list[str] = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef) and sub is not fn:
            continue
        is_exit = isinstance(sub, ast.Return) or (
            isinstance(sub, ast.Raise) and "SystemExit" in ast.unparse(sub)
        )
        if is_exit and sub.lineno > started_at and id(sub) not in inside:
            leaks.append(f"line {sub.lineno}: {ast.unparse(sub)}")
    return leaks


def test_every_exit_of_start_gateway_is_covered_by_the_retiring_finally(start_gateway_fn):
    """A return that skips the finally leaks the 0.5s marker-poll loop for the
    life of the process (and, past the cron start, the housekeeping thread
    whose hourly cleanup_image_cache() unlinks real ~/.hermes/image_cache
    entries once HERMES_HOME is restored)."""
    covered = _outer_retiring_try(start_gateway_fn)
    # Nested helper defs (``_recover_pending`` etc.) are skipped by _exits_outside;
    # their returns are not exits of start_gateway.
    leaks = _exits_outside(start_gateway_fn, covered)
    assert leaks == [], "start_gateway() exits that skip the retiring finally: " + "; ".join(leaks)


def test_the_retiring_finally_stops_the_watcher_and_drains_cron(start_gateway_fn):
    """The one finally must name BOTH stops: the watcher event and the cron
    drain that sets ``cron_stop`` (shared by the housekeeping loop)."""
    finalbody = _outer_retiring_try(start_gateway_fn).finalbody
    calls = _calls_in(finalbody)
    assert "_planned_stop_watcher_stop.set" in calls
    assert "_planned_stop_watcher_thread.join" in calls, "the watcher is set but never joined"
    assert "_stop_gateway_cron_resources" in calls, (
        "cron_stop is only set inside _stop_gateway_cron_resources(); the finally must call it"
    )


def test_stop_gateway_cron_resources_sets_cron_stop_first():
    """The drain helper is what the finally relies on for cron_stop."""
    src = textwrap.dedent(inspect.getsource(gateway_run._stop_gateway_cron_resources))
    fn = ast.parse(src).body[0]
    first_call = next(
        ast.unparse(node.func) for stmt in fn.body for node in ast.walk(stmt) if isinstance(node, ast.Call)
    )
    assert first_call == "cron_stop.set"


def test_the_watcher_is_started_before_the_retiring_try(start_gateway_fn):
    """If the watcher were started INSIDE the try, a failure before that line
    would be fine -- but the thread exists before the PID claim on purpose
    (the marker must be honoured during a slow start), so it must be created
    ahead of the try that retires it."""
    body = start_gateway_fn.body
    covered = _outer_retiring_try(start_gateway_fn)
    try_index = body.index(covered)
    started = any("_planned_stop_watcher_thread.start" in _calls_in([node]) for node in body[:try_index])
    assert started, "planned-stop watcher must start before the try whose finally retires it"


def test_the_ast_check_would_catch_a_return_outside_the_try(start_gateway_fn):
    """Self-check: the reachability walker is not vacuous."""
    mutant = ast.parse(textwrap.dedent(
        """
        async def start_gateway():
            if no_pid:
                return False          # before the thread exists: not a leak
            _planned_stop_watcher_stop = threading.Event()
            _planned_stop_watcher_thread.start()
            if early:
                return False          # after it: a leak
            try:
                return True
            finally:
                _planned_stop_watcher_stop.set()
                _planned_stop_watcher_thread.join(timeout=2)
        """
    )).body[0]
    leaks = _exits_outside(mutant, _outer_retiring_try(mutant))
    assert leaks == ["line 8: return False"]
