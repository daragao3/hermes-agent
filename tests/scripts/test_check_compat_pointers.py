"""Regression tests for the plugin-compat pointer detector.

The string-target branch of this checker was DEAD CODE from the day it was
written, and nothing noticed because a checker that finds nothing and a checker
that cannot find anything print the same thing. ``str_pat`` required quote
characters but was ``fullmatch``ed against ``ast.Constant.value``, which is the
string's *value* -- the quotes are syntax and are gone by then. So
``patch("facade.name")``, the shape the script's own docstring advertises and the
most common one in this test suite, never matched.

The lesson these tests exist to lock: a detector needs a case that MUST fire, not
only cases that must not.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

import pytest

import scripts.check_compat_pointers as ccp

_MANIFEST = {
    "schema": 1,
    "note": "test fixture",
    "entries": [
        {"facade": "run_agent", "name": "OpenAI", "kind": "moved-lazy",
         "target": "agent.process_bootstrap"},
        {"facade": "hermes_cli.kanban_db", "name": "connect", "kind": "moved-lazy",
         "target": "hermes_cli.kanban_db_connect"},
    ],
}


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the checker at a throwaway tree with a two-entry manifest."""
    manifest = tmp_path / "compat_manifest.json"
    manifest.write_text(json.dumps(_MANIFEST), encoding="utf-8")
    monkeypatch.setattr(ccp, "ROOT", tmp_path)
    monkeypatch.setattr(ccp, "MANIFEST", manifest)
    return tmp_path


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.lstrip("\n"), encoding="utf-8")


def _run(capsys) -> tuple[int, str]:
    rc = ccp.main()
    return rc, capsys.readouterr().out


def test_string_patch_target_is_flagged(tree: Path, capsys) -> None:
    """THE REGRESSION. Before the fix this returned 0 and printed the all-clear."""
    _write(tree, "tests/test_thing.py", '''
from unittest.mock import patch

def test_x():
    with patch("run_agent.OpenAI"):
        pass
''')
    rc, out = _run(capsys)
    assert rc == 1, f"string patch target not detected:\n{out}"
    assert "run_agent.OpenAI" in out


def test_string_target_for_a_dotted_facade_is_flagged(tree: Path, capsys) -> None:
    """The facade itself may be dotted; rpartition must split on the LAST dot."""
    _write(tree, "tests/test_kanban.py", '''
from unittest.mock import patch
patch("hermes_cli.kanban_db.connect")
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert "hermes_cli.kanban_db.connect" in out


def test_unrelated_dotted_string_is_not_flagged(tree: Path, capsys) -> None:
    _write(tree, "tests/test_other.py", '''
x = "os.path.join"
y = "run_agent.something_that_never_moved"
''')
    rc, out = _run(capsys)
    assert rc == 0, out


def test_prose_mentioning_a_pointer_is_not_flagged(tree: Path, capsys) -> None:
    """``fullmatch`` is load-bearing: a docstring naming the path is not a use."""
    _write(tree, "tests/test_prose.py", '''
"""We used to patch run_agent.OpenAI here; see COMPAT_MANIFEST.md."""
z = "the old path was run_agent.OpenAI"
''')
    rc, out = _run(capsys)
    assert rc == 0, out


def test_worktrees_under_dot_claude_are_skipped(tree: Path, capsys) -> None:
    """This repo's per-session worktrees live at ``.claude/worktrees/<name>``.

    Without ``.claude`` in SKIP_DIRS the walk covers every sibling checkout --
    it never finished, and it would report other sessions' files as ours.
    """
    _write(tree, ".claude/worktrees/sibling/tests/test_thing.py", '''
from unittest.mock import patch
patch("run_agent.OpenAI")
''')
    rc, out = _run(capsys)
    assert rc == 0, f"scanned a sibling worktree:\n{out}"


# --------------------------------------------------------------------------
# Scope awareness.
#
# The alias map used to be built in ONE flat ``ast.walk`` over the whole file,
# so a function-local ``from hermes_cli import kanban_db as kb`` bound "kb" for
# every other function in the module. Measured 2026-09-13 against
# tests/stress/test_atypical_scenarios.py: 31 false positives, every scenario
# call site, because those functions take an unrelated ``kb`` parameter.
#
# The trap in fixing it is the OTHER direction. On the sweep before the
# namespace change those same sites were genuinely the facade, and the flat map
# happened to be right. So every must-not-fire case below is paired with a
# must-fire case that only differs in where the binding lives.
# --------------------------------------------------------------------------


def test_module_level_alias_reaches_a_nested_function(tree: Path, capsys) -> None:
    """THE TRUE POSITIVE A SCOPE FIX MUST NOT LOSE."""
    _write(tree, "tests/test_outer.py", '''
from hermes_cli import kanban_db as kb

def outer():
    def inner():
        return kb.connect()
    return inner
''')
    rc, out = _run(capsys)
    assert rc == 1, f"module-level alias stopped reaching a nested function:\n{out}"
    assert "kb.connect" in out


def test_module_level_alias_reaches_a_method(tree: Path, capsys) -> None:
    """A class body is skipped on the way OUT, not treated as a wall."""
    _write(tree, "tests/test_method.py", '''
import run_agent

class C:
    def m(self):
        return run_agent.OpenAI()
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert "run_agent.OpenAI" in out


def test_function_local_alias_fires_in_its_own_function(tree: Path, capsys) -> None:
    _write(tree, "tests/test_local.py", '''
def worker():
    from hermes_cli import kanban_db as kb
    return kb.connect()
''')
    rc, out = _run(capsys)
    assert rc == 1, out


def test_function_local_alias_does_not_leak_to_a_sibling_parameter(tree: Path, capsys) -> None:
    """THE REGRESSION: the exact shape of test_atypical_scenarios.py.

    One helper imports the facade locally; the scenarios take a same-named
    parameter that is a different object entirely. Only the helper is a hit.
    """
    _write(tree, "tests/test_scenarios.py", '''
def _race_worker():
    from hermes_cli import kanban_db as kb
    return kb.connect()

def scenario(home, kb):
    kb.connect()
    kb.connect()
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert out.count("kb.connect") == 1, f"parameter shadowing leaked:\n{out}"
    assert "test_scenarios.py:3" in out


def test_parameter_shadows_a_module_level_alias(tree: Path, capsys) -> None:
    """A binding anywhere in a function makes the name local for the whole body."""
    _write(tree, "tests/test_shadow_param.py", '''
from hermes_cli import kanban_db as kb

def f(kb):
    return kb.connect()
''')
    rc, out = _run(capsys)
    assert rc == 0, f"parameter did not shadow the module alias:\n{out}"


def test_assignment_and_loop_and_with_and_except_shadow(tree: Path, capsys) -> None:
    _write(tree, "tests/test_shadow_binds.py", '''
import run_agent

def a():
    run_agent = make_stub()
    return run_agent.OpenAI()

def b(items):
    for run_agent in items:
        run_agent.OpenAI()

def c(cm):
    with cm as run_agent:
        run_agent.OpenAI()

def d():
    try:
        pass
    except Exception as run_agent:
        run_agent.OpenAI()
''')
    rc, out = _run(capsys)
    assert rc == 0, f"a local rebinding was read as the facade:\n{out}"


def test_class_body_alias_does_not_reach_its_methods(tree: Path, capsys) -> None:
    """Class scopes are not enclosing scopes -- that ``kb`` is a NameError at runtime."""
    _write(tree, "tests/test_class_scope.py", '''
class C:
    from hermes_cli import kanban_db as kb

    def m(self):
        return kb.connect()
''')
    rc, out = _run(capsys)
    assert rc == 0, out


def test_global_declaration_resolves_at_module_scope(tree: Path, capsys) -> None:
    """``global kb`` re-points the lookup at the module binding, so it IS a hit."""
    _write(tree, "tests/test_global.py", '''
from hermes_cli import kanban_db as kb

def f(kb=None):
    return kb.connect()

def g():
    global kb
    return kb.connect()
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert out.count("kb.connect") == 1, f"the shadowed default-arg use also fired:\n{out}"
    assert "test_global.py:8" in out


def test_local_from_import_of_a_pointer_is_still_a_hit(tree: Path, capsys) -> None:
    """Scope does not excuse a direct import -- it is a dependency wherever it sits."""
    _write(tree, "tests/test_local_from.py", '''
def f():
    from run_agent import OpenAI
    return OpenAI
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert "from run_agent import OpenAI" in out


def test_setattr_target_is_resolved_in_scope(tree: Path, capsys) -> None:
    """The monkeypatch.setattr branch resolves a bare Name too, so it needs scope."""
    _write(tree, "tests/test_setattr_scope.py", '''
def worker(monkeypatch):
    from hermes_cli import kanban_db as kb
    monkeypatch.setattr(kb, "connect", None)

def scenario(monkeypatch, kb):
    monkeypatch.setattr(kb, "connect", None)
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert out.count("setattr/patch") == 1, f"parameter shadowing leaked:\n{out}"
    assert "test_setattr_scope.py:3" in out


# --------------------------------------------------------------------------
# The exclusion list vs. the real tree.
#
# ``_COMPAT_OWN_TESTS`` is matched on BARE FILENAME against every file in the
# walk. The loud direction is safe on its own: a NEW compat-layer test that
# nobody excludes turns the gate red, and somebody has to look. The silent
# direction is the one that needs a test -- rename or delete an excluded file
# and the dead entry just sits there, skipping any future file that takes the
# name, anywhere in the tree, with no signal of any kind.
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=1)
def _real_tree_index() -> dict[str, tuple[str, ...]]:
    """bare filename -> every path holding it, for the names we exclude.

    One os.walk, cached: rglob'ing this checkout per name costs ~13s each, and
    the parametrized cases below would otherwise walk it three times over.
    """
    wanted = set(ccp._COMPAT_OWN_TESTS)
    index: dict[str, list[str]] = {n: [] for n in wanted}
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        rel = Path(dirpath).relative_to(_REPO_ROOT).parts
        if rel and rel[0] in ccp.SKIP_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not (len(rel) == 0 and d in ccp.SKIP_DIRS)]
        for fn in filenames:
            if fn in wanted:
                index[fn].append("/".join(rel + (fn,)))
    return {k: tuple(sorted(v)) for k, v in index.items()}


def _real_tree_matches(name: str) -> list[str]:
    return list(_real_tree_index()[name])


@pytest.mark.parametrize("name", sorted(ccp._COMPAT_OWN_TESTS))
def test_each_excluded_filename_resolves_to_its_one_declared_path(name: str) -> None:
    expected = ccp._COMPAT_OWN_TESTS[name]
    found = _real_tree_matches(name)
    assert found == [expected], (
        f"_COMPAT_OWN_TESTS['{name}'] declares {expected!r} but the tree has {found!r}.\n"
        "An excluded name that no longer exists is a dead exclusion: it will silently "
        "skip whatever file next takes that name. A second match means the bare-name "
        "rule is skipping a file it was never meant to. Update _COMPAT_OWN_TESTS."
    )


def test_the_exclusion_constant_is_actually_wired_into_the_walk(tree: Path, capsys) -> None:
    """Guards the constant against drifting away from ``_py_files``.

    Without this, someone could keep ``_COMPAT_OWN_TESTS`` tidy and correct while
    the walk stopped consulting it, and every test above would still pass.
    """
    for name in ccp._COMPAT_OWN_TESTS:
        _write(tree, f"tests/{name}", '''
from unittest.mock import patch
patch("run_agent.OpenAI")
''')
    rc, out = _run(capsys)
    assert rc == 0, f"an excluded compat-layer test was scanned:\n{out}"


def test_every_node_in_a_dense_module_gets_a_scope() -> None:
    """``main`` skips nodes ``_scope_map`` did not reach, so nothing may be missed.

    Measured over 1,646 real files in this tree: zero unscoped nodes. This pins a
    dense sample so a future grammar addition that ``_scope_map`` does not descend
    into fails here instead of quietly shrinking the gate's coverage.
    """
    import ast

    dense = ast.parse('''
import os
from a import b as c

D: int = 1
E = F = [x for x in range(3)]
G = {k: v for k, v in ()}
H = lambda p, *args, q=1, **kw: p

@dec
class K(Base, metaclass=M):
    attr = 1

    @property
    def m(self, a, b=os.sep, *r, c: int = 2, **kw) -> "K":
        async def inner():
            async for i in aiter():
                pass
            async with ctx() as cm:
                yield cm
        global D
        nonlocal_free = (n := 5)
        for u, (v, *w) in pairs:
            try:
                del u
            except ValueError as err:
                raise err
            finally:
                with open("f") as fh, open("g") as gh:
                    fh.read()
        return {y for y in w}, (z for z in w)
''')
    import scripts.check_compat_pointers as _ccp
    scoped = _ccp._scope_map(dense, set())
    unscoped = [type(n).__name__ for n in ast.walk(dense) if n not in scoped]
    assert unscoped == [], f"_scope_map did not reach: {sorted(set(unscoped))}"
