"""Plugin-compat pointers must resolve to the SAME object the name moved to, never a same-named stranger.

Regression: ``hermes_cli.kanban_db.connect`` was pointed at ``hermes_cli.projects_db.connect`` (a different
database, no ``board=`` parameter) because the generator ranked candidate homes by path proximity. The
manifest codified the mistake, so the compat lint treated it as valid.

Invariant checked here: for every ``moved-lazy`` entry whose target module also exists in the manifest of
some other facade under the same name, or whose facade stem has a sibling ``<stem>_*`` module defining the
name, the facade attribute IS the sibling's object.
"""
import functools
import importlib
import importlib.util
import json
import pkgutil
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "compat_manifest.json"

# This file resolves every pointer on purpose; the once-per-name plugin warning is expected here.
pytestmark = [
    pytest.mark.skipif(not MANIFEST.exists(), reason="compat layer removed (scheduled revert)"),
    pytest.mark.filterwarnings("ignore::FutureWarning"),
    # Resolving every pointer imports 138 facades and the hundreds of modules they lazily pull in,
    # so this is an import-cost test and the 30 s default does not fit it. Cold, it ran 33-64 s and
    # died on the timeout *before reaching its own assertion* -- which read as an ordinary assertion
    # failure only when a sibling file happened to warm the imports first. Same budget the other
    # import-cost tests here use (tests/cron/test_home_target_import_cost.py).
    pytest.mark.timeout(300),
]


def _entries():
    return [e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"] if e["kind"] == "moved-lazy"]


# A pointer whose target module imports an OS-gated stdlib module cannot resolve on the other OS and
# never could. ``hermes_cli.pty_bridge`` (PtyBridge, PtyUnavailableError) is POSIX-only by design --
# its own docstring says so -- so on Windows those two entries made the whole assertion fail on a
# platform fact, hiding the same-named-stranger check for every pointer that CAN be resolved here.
# Skip only this cause, and only when the module is genuinely absent from this interpreter.
_PLATFORM_ONLY_STDLIB = frozenset({
    "fcntl", "termios", "tty", "pty", "pwd", "grp", "crypt", "posix", "resource", "syslog",
    "msvcrt", "winreg", "winsound", "_winapi",
})


def _unavailable_platform_module(exc: BaseException) -> str | None:
    """Name of the OS-gated stdlib module that made ``exc`` unresolvable, or None for any other cause."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ModuleNotFoundError) and cur.name in _PLATFORM_ONLY_STDLIB:
            try:
                absent = importlib.util.find_spec(cur.name) is None
            except Exception:
                absent = True
            if absent:
                return cur.name
        cur = cur.__cause__ or cur.__context__
    return None


# 1,147 moved-lazy entries share only 138 distinct facades, and each uncached call re-runs
# pkgutil.iter_modules (an os.listdir of the package directory). Uncached, the call phase runs past
# the 30 s pytest-timeout whenever this file is run on its own, so the test never reached its own
# assertion -- it only looked like an assertion failure when a sibling file had already warmed the
# imports. Memoised it finishes well inside the budget. Returns a tuple: the value is shared.
@functools.lru_cache(maxsize=None)
def _sibling_modules(facade: str) -> tuple[str, ...]:
    pkg, _, stem = facade.rpartition(".")
    try:
        parent = importlib.import_module(pkg) if pkg else None
    except Exception:
        return ()
    paths = getattr(parent, "__path__", None) if parent else [str(ROOT)]
    if not paths:
        return ()
    prefix = f"{pkg}." if pkg else ""
    return tuple(prefix + m.name for m in pkgutil.iter_modules(paths) if m.name.startswith(stem + "_"))


def test_moved_lazy_pointers_resolve_to_the_split_off_siblings_object():
    """When a facade's own ``<stem>_*`` sibling binds the name, the facade attribute must be THAT object.

    A sibling may legitimately re-import the value from elsewhere (then the pointer target is the origin and
    the objects are identical); what must never happen is the pointer resolving to a same-named stranger.
    """
    bad = []
    skipped = []
    compared = 0
    for e in _entries():
        facade, name = e["facade"], e["name"]
        sibs = _sibling_modules(facade)
        if not sibs:
            continue
        try:
            got = getattr(importlib.import_module(facade), name)
        except Exception as exc:  # unresolvable pointer is its own failure
            missing = _unavailable_platform_module(exc)
            if missing is not None:
                skipped.append((facade, name, f"needs {missing}, absent on this platform"))
                continue
            bad.append((facade, name, f"unresolvable: {exc!r}"))
            continue
        for s in sibs:
            try:
                mod = importlib.import_module(s)
            except Exception:
                continue
            if name in vars(mod):
                compared += 1
                sib_obj = vars(mod)[name]
                same = (sib_obj == got) if isinstance(got, (int, float, str, bytes, bool, type(None))) else (sib_obj is got)
                if not same:
                    bad.append((facade, name, e["target"], s))
    # Lower bound first: without it the platform skip above could grow until the stranger check runs
    # over nothing and this test passes vacuously. Measured 2026-09-13 on Windows: 610 compared,
    # 2 skipped (the pty_bridge pair), 0 bad. The floor is deliberately far below 610 so shrinking
    # the manifest is not a false red, but far above 0 so a swallow-everything regression is.
    assert compared > 100, (
        f"only {compared} pointer(s) were actually compared against a sibling binding "
        f"({len(skipped)} skipped as platform-gated: {skipped}) -- the stranger check is not running"
    )
    assert not bad, f"compat pointers resolve to a different object than the facade's own sibling binds: {bad}"


def test_kanban_db_connect_opens_a_kanban_board(tmp_path, monkeypatch):
    """The historical ``kanban_db.connect(board=...)`` opens a Kanban DB, not projects.db."""
    import hermes_cli.kanban_db as kanban_db
    import hermes_cli.kanban_db_connect as kanban_db_connect

    assert kanban_db.connect is kanban_db_connect.connect
    assert kanban_db.connect_closing is kanban_db_connect.connect_closing
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db = tmp_path / "board.db"
    conn = kanban_db.connect(db, board="qa")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "tasks" in tables, tables
    assert not (tmp_path / "projects.db").exists()
    assert isinstance(sqlite3.connect(db), sqlite3.Connection)
