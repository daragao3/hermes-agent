#!/usr/bin/env python3
"""Guard: every module attribute a test patches is still bound by that module.

WHY THIS EXISTS
---------------
``mock.patch.object(module, "name")`` and ``monkeypatch.setattr(module,
"name", ...)`` raise ``AttributeError`` at RUN time when ``module`` no longer
binds ``name``; ``patch("pkg.mod.name")`` does the same through its importer.
Nothing before the test body runs can see it: the test module imports clean,
``pytest --collect-only`` and ``--setup-plan`` pass, and the red is
deterministic but head-only, so it surfaces during the next acceptance A/B
instead of at the landing that caused it.

On 2026-09-17 the platform.* sweep (cfd903802b, merge 0e6f27c5c3) replaced
``import platform`` in ``tools/voice_mode.py`` with ``from
hermes_cli._subprocess_compat import host_system``.  The sweep updated every
test it could find -- but it searched for DOTTED patch strings such as
``patch("tools.tirith_security.platform.system")``, and
``tests/tools/test_voice_mode_playback_env_scrub.py`` reached the same seam as
``patch.object(vm, "platform")`` through ``import tools.voice_mode as vm``.
That one stayed stale until agent-src-acceptance-ceremony-de1f83cddf-20260917
and was fixed test-only as 006faacb8b.  A first cut of this scan, run on the
tree at the time, found exactly that seam.  The same day 3a392cdb87 moved
``WMI_STRAY_THREAD_FIXED`` from module scope into a function in
hermes_cli/_subprocess_compat.py and tests/hermes_cli/test_host_platform_
helpers.py kept READING ``compat.WMI_STRAY_THREAD_FIXED`` -- no patch involved,
the same head-only red (fixed 5432bf59ce), which is why plain reads are
seams here too.  The first run of this file over the trunk (2026-09-18, 33.5k
patch seams) found six more of the same class that no run had reported: tests/integration/test_scout_firecrawl_credit_circuit.py still
patched five helpers that de60f789a7 moved out of tools/browser_tool.py (a red
at its first setattr), and tests/hermes_cli/test_doctor.py stubbed a Gemini
OAuth status function that 7130d60861 removed, inside a ``try/except
Exception: pass`` that had been swallowing the AttributeError.  Both fixed
test-only alongside this script.

WHAT IT CHECKS
--------------
For every tracked ``.py`` under ``tests/`` (or the files given), each seam of
these shapes:

* ``patch.object(<target>, "<name>", ...)`` / ``patch.multiple(<target>, name=...)``
  -- also ``mock.patch.object``, ``unittest.mock.patch.object``, ``mocker.patch.object``;
* ``<x>.setattr(<target>, "<name>", ...)`` / ``<x>.delattr(<target>, "<name>")``
  -- any receiver, so ``monkeypatch``, ``mp``, ``m`` all count;
* ``patch("<dotted.module>.<name>", ...)`` / ``patch.multiple("<dotted>", name=...)``
  / ``<x>.setattr("<dotted.module>.<name>", value)``;
* a plain READ ``<target>.<name>`` (``compat.WMI_STRAY_THREAD_FIXED``,
  ``vm.play_audio_file(...)``): the same AttributeError at the same moment.
  ``--no-reads`` limits the scan to the patch forms;

is resolved WITHOUT importing anything.  ``<target>`` is a ``Name`` or a dotted
``Attribute`` chain whose leading name is bound in the test file by an import
(``import x.y as alias``, ``from x import alias``, ``import x.y`` -> ``x``; at
module level or inside a function, absolute or relative).  The chain is walked
against the repository's SOURCE: each component is a submodule on disk, or a
name the module binds at top level (``import``, ``import ... as``, ``from ...
import``, ``def``, ``class``, ``x = ...``, ``for x``, ``with ... as x``,
``except ... as x``, walrus, ``type x = ...``, at module scope including inside
``if``/``try``/``with``/``for``/``while`` blocks).  The seam is reported when a
component is neither.

Deliberately NOT reported (each is counted under ``--verbose``):

* a leading name the file binds any other way -- a parameter or fixture,
  ``vm = importlib.reload(vm)``, ``x = _load()``, or two imports of different
  modules under one name -- is DYNAMIC and skipped, never guessed at;
* ``patch.object(type(x), ...)``, ``patch.object(sys.modules[...], ...)``,
  ``patch.object(self.obj, ...)``: not a module seam;
* a target module outside this repository (``sys``, ``os.path``, third-party):
  EXTERNAL, out of scope;
* an attribute the test tree CREATES: ``mod.x = v`` / ``setattr(mod, "x", v)``
  / ``monkeypatch.setattr(mod, "x", v, raising=False)`` / ``patch.object(mod,
  "x", create=True)`` in the same file, or in any ``conftest.py`` (the one
  place a creation reaches other files, through a fixture -- tests/tools/
  conftest.py's ``_find_cli_unpatched``).  The conftest set is computed once
  per scan, tree-wide, whatever files are in scope;
* a read the test GUARDS: ``hasattr(mod, "x")`` / ``getattr(mod, "x", default)``
  anywhere in the file, or inside a ``try`` whose ``except`` catches
  AttributeError (or wider), ``pytest.raises(AttributeError)`` or
  ``contextlib.suppress(AttributeError)``;
* a chain that reaches a bound object and keeps going (``vm.shutil.which``,
  ``mod.Class.method``): an object/class attribute, out of scope -- the module
  seam it crossed was verified;
* a module with a wildcard import, or one that hands its namespace to a call
  (``register(sys.modules[__name__])``, ``bind_module(globals(), ...)`` -- the
  tui_gateway.server split-module pattern -- or ``globals().update(computed)``):
  its attribute set is not static, so names it does not bind explicitly are
  skipped.  ``globals()["x"] = v`` binds ``x`` and ``globals()[f"check_{n}_
  requirements"] = v`` (tools/browser_tool.py) binds the pattern, so a module
  that only does that stays static;
* a PEP 562 ``__getattr__`` IS read: the names it compares ``name`` with and the
  keys of the module-level literal it looks ``name`` up in (``_PLUGIN_COMPAT_LAZY
  .get(name)``, ``name not in __all__``) count as bound -- tools/voice_mode.py,
  the incident module, has one.  A hook that inspects ``name`` some other way
  makes the module non-static like a wildcard import;
* ``create=True`` / ``raising=False``: the caller allows a missing attribute.

Findings the model is known to get wrong go in ``ALLOWLIST`` (``path::target``),
which is empty; a green here is meant to mean zero stale seams, not zero
un-allowlisted ones.  The pytest wrapper (tests/scripts/test_check_patch_seams.py)
runs this over the tracked tree and pins the model on demo repos in both
directions.

USAGE
-----
    python scripts/check_patch_seams.py            # tracked tests/**/*.py
    python scripts/check_patch_seams.py tests/tools/test_voice_mode_playback_env_scrub.py
    python scripts/check_patch_seams.py --repo /path/to/checkout --verbose --jobs 1

Exit 0 when clean, 1 with one ``path:line: ...`` line per stale seam, 2 on a
usage error.  Reads triple the seam count (~290k over ~4600 files vs ~34k) for
about half again the wall time.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import concurrent.futures
import os
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ``path::target`` of seams the model is known to misjudge.  Empty on purpose.
ALLOWLIST: frozenset[str] = frozenset()

_PATCH_CALLEES = ("object", "multiple")
_SETATTR_CALLEES = ("setattr", "delattr")

# Every module object carries these whether or not its source mentions them.
_MODULE_DUNDERS = frozenset({
    "__name__", "__doc__", "__package__", "__loader__", "__spec__", "__file__",
    "__cached__", "__builtins__", "__dict__", "__annotations__", "__path__",
})
# mock.patch / patch.object silently set create=True for a builtin name on a
# module (``patch("pkg.mod.input")`` works with no ``input`` bound); monkeypatch
# does not, so this leniency applies to the patch forms only.
_BUILTIN_NAMES = frozenset(name for name in dir(builtins) if not name.startswith("_"))


# ── Findings ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Seam:
    """One patch site in a test file, before resolution."""

    path: str            # repo-relative, forward slashes
    line: int
    form: str            # patch.object | patch.multiple | setattr | delattr | patch
    chain: tuple[str, ...]   # dotted target: leading name + attribute chain
    names: tuple[str, ...]   # attribute names patched on the resolved target
    lenient: bool        # create=True / raising=False present
    string: bool = False  # target came from a dotted string, not a Name/Attribute
    guarded: bool = False  # a read inside try/except AttributeError, pytest.raises, suppress

    @property
    def target(self) -> str:
        return ".".join(self.chain)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    form: str
    target: str
    reason: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.form}({self.target}) -- {self.reason}"

    @property
    def key(self) -> str:
        return f"{self.path}::{self.target}"


@dataclass
class Stats:
    files: int = 0
    seams: int = 0
    verified: int = 0
    dynamic: int = 0
    external: int = 0
    object_attr: int = 0
    not_static: int = 0
    lenient: int = 0
    created: int = 0     # the attribute is one the test tree itself creates (conftest / this file)
    guarded: int = 0     # a read the test guards (hasattr / try-except AttributeError / raises)
    unparseable: list[str] = field(default_factory=list)

    def merge(self, other: "Stats") -> None:
        self.files += other.files
        self.seams += other.seams
        self.verified += other.verified
        self.dynamic += other.dynamic
        self.external += other.external
        self.object_attr += other.object_attr
        self.not_static += other.not_static
        self.lenient += other.lenient
        self.created += other.created
        self.guarded += other.guarded
        self.unparseable.extend(other.unparseable)

    def render(self) -> str:
        return (
            f"files={self.files} seams={self.seams} verified={self.verified} "
            f"skipped: dynamic={self.dynamic} external={self.external} "
            f"object_attr={self.object_attr} not_static={self.not_static} "
            f"lenient={self.lenient} created={self.created} guarded={self.guarded} "
            f"unparseable={len(self.unparseable)}"
        )


# ── Module source model ─────────────────────────────────────────────────────

@dataclass
class ModuleFacts:
    """Top-level names a module binds, from its source alone."""

    bound: set[str]
    wildcard: bool = False       # ``from x import *`` at top level
    getattr_hook: bool = False   # module-level ``def __getattr__``
    lazy: set[str] | None = None  # names that ``__getattr__`` serves, when its body says so
    patterns: tuple[re.Pattern[str], ...] = ()  # ``globals()[f"check_{x}_requirements"] = ...``
    shared_namespace: bool = False  # hands ``globals()``/``sys.modules[__name__]`` to a call
    namespace_package: bool = False  # a directory without __init__.py: binds nothing itself

    @property
    def static(self) -> bool:
        """The attribute set is known from the source: no wildcard import, no
        namespace handed away, and any ``__getattr__`` names its keys."""
        if self.wildcard or self.shared_namespace:
            return False
        return not self.getattr_hook or self.lazy is not None

    def binds(self, name: str) -> bool:
        if name in self.bound or (self.lazy is not None and name in self.lazy):
            return True
        return any(pattern.fullmatch(name) for pattern in self.patterns)


def _target_names(node: ast.AST) -> set[str]:
    """Names bound by an assignment/for/with target expression."""
    out: set[str] = set()
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            out |= _target_names(elt)
    elif isinstance(node, ast.Starred):
        out |= _target_names(node.value)
    return out


def _walk_top_level(body: list[ast.stmt]):
    """Yield statements at module scope, descending into compound statements
    but never into ``def``/``class`` bodies (those bind names elsewhere)."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            yield from _walk_top_level(stmt.body)
            yield from _walk_top_level(stmt.orelse)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from _walk_top_level(stmt.body)
        elif isinstance(stmt, ast.Try) or (hasattr(ast, "TryStar") and isinstance(stmt, ast.TryStar)):
            yield from _walk_top_level(stmt.body)
            for handler in stmt.handlers:
                yield from _walk_top_level(handler.body)
            yield from _walk_top_level(stmt.orelse)
            yield from _walk_top_level(stmt.finalbody)
        elif isinstance(stmt, ast.Match):
            for case in stmt.cases:
                yield from _walk_top_level(case.body)


def _walk_expressions(stmt: ast.stmt):
    """Every node of ``stmt``'s own expressions -- not of the statements nested
    in its body/orelse/handlers (those are yielded by _walk_top_level in turn)."""
    for field_name, value in ast.iter_fields(stmt):
        if field_name in ("body", "orelse", "finalbody", "handlers", "cases"):
            continue
        if isinstance(value, ast.AST):
            yield from ast.walk(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ast.AST):
                    yield from ast.walk(item)


def _is_own_namespace(node: ast.expr) -> bool:
    """``globals()`` / ``vars()`` / ``locals()`` with no argument, or
    ``sys.modules[__name__]``: the module's own namespace as a value."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("globals", "vars", "locals"):
        return not node.args and not node.keywords
    return (isinstance(node, ast.Subscript) and _dotted_chain(node.value) == ("sys", "modules")
            and isinstance(node.slice, ast.Name) and node.slice.id == "__name__")


def _key_pattern(key: ast.expr) -> tuple[str | None, re.Pattern[str] | None, bool]:
    """A namespace key as (exact name, pattern, unknown): a string constant is
    a name; an f-string with constant parts (``f"check_{x}_requirements"``) is
    a pattern over its literal segments; anything else is unknown."""
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value, None, False
    if isinstance(key, ast.JoinedStr):
        parts = []
        for value in key.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(re.escape(value.value))
            else:
                parts.append(".*")
        return None, re.compile("".join(parts)), False
    return None, None, True


def _namespace_effects(stmt: ast.stmt) -> tuple[set[str], list[re.Pattern[str]], bool]:
    """What a module-scope statement does to the module's own namespace
    besides ordinary binding.  Returns (names bound by key, key patterns,
    unknown): ``globals()["x"] = v`` binds ``x``; ``globals()[f"check_{n}_
    requirements"] = v`` binds a pattern; ``globals().update({"x": v})`` binds
    its literal keys; ``register(sys.modules[__name__])`` / ``bind_module(
    globals(), ...)`` / ``globals().update(computed)`` hand the namespace to
    code this source does not show, so the attribute set is unknown."""
    names: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    unknown = False
    for sub in _walk_expressions(stmt):
        if isinstance(sub, ast.Subscript) and _is_own_namespace(sub.value):
            if isinstance(sub.ctx, ast.Store):
                name, pattern, bad = _key_pattern(sub.slice)
                if name is not None:
                    names.add(name)
                elif pattern is not None:
                    patterns.append(pattern)
                unknown |= bad
            # a read (``"x" in globals()``, ``globals()["x"]``) binds nothing
        elif isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute) and _is_own_namespace(func.value):
                # globals().update(...) / .setdefault(...) / .pop(...)
                if func.attr == "update" and len(sub.args) == 1 and not sub.keywords:
                    keys = _literal_strings(sub.args[0]) if isinstance(sub.args[0], ast.Dict) else None
                    if keys is None:
                        unknown = True
                    else:
                        names |= keys
                elif func.attr == "setdefault" and sub.args:
                    name, pattern, bad = _key_pattern(sub.args[0])
                    if name is not None:
                        names.add(name)
                    elif pattern is not None:
                        patterns.append(pattern)
                    unknown |= bad
                elif func.attr in ("get", "keys", "items", "values", "copy"):
                    pass  # a read
                else:
                    unknown = True
            elif isinstance(func, ast.Name) and func.id == "setattr" and len(sub.args) >= 2 and _is_own_namespace(sub.args[0]):
                name, pattern, bad = _key_pattern(sub.args[1])
                if name is not None:
                    names.add(name)
                elif pattern is not None:
                    patterns.append(pattern)
                unknown |= bad
            else:
                for arg in (*sub.args, *(kw.value for kw in sub.keywords)):
                    if _is_own_namespace(arg):
                        unknown = True  # the namespace handed to a callee
    return names, patterns, unknown


def _parse(source: bytes, filename: str) -> ast.Module | None:
    """``ast.parse`` without the SyntaxWarnings a docstring's stray backslash
    would print (they are the file's business, not this scan's)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.parse(source, filename=filename)
        except (SyntaxError, ValueError):
            return None


def _literal_strings(node: ast.expr) -> set[str] | None:
    """Keys of a dict display / elements of a list, tuple or set display when
    every one is a string constant; None otherwise."""
    if isinstance(node, ast.Dict):
        items = node.keys
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        items = node.elts
    else:
        return None
    out: set[str] = set()
    for item in items:
        if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
            return None  # ``**other`` / a computed key: not static
        out.add(item.value)
    return out


def _display_strings(node: ast.expr) -> set[str] | None:
    """Every string constant inside a literal display, however nested
    (``{"mod": ("a", "b")}`` -> {"mod", "a", "b"}); None when the display
    holds anything computed."""
    if not isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return None
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Dict, ast.List, ast.Tuple, ast.Set, ast.Load)):
            continue
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value)
        else:
            return None
    return out


def _comprehension_strings(node: ast.expr, deep: dict[str, set[str] | None]) -> set[str] | None:
    """A dict/set comprehension re-keyed from module-level literal displays
    (``{attr: mod for mod, attrs in SURFACE.items() for attr in attrs}``):
    every string in the displays it iterates, an over-approximation that only
    ever makes MORE names count as served.  None when a generator iterates
    anything else."""
    if not isinstance(node, (ast.DictComp, ast.SetComp)):
        return None
    out: set[str] = set()
    for gen in node.generators:
        source = gen.iter
        if (isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute)
                and source.func.attr in ("items", "keys", "values") and not source.args):
            source = source.func.value
        if isinstance(source, ast.Name) and deep.get(source.id) is not None:
            out |= deep[source.id]
        elif isinstance(source, ast.Name) and any(source.id == t.id for g in node.generators for t in ast.walk(g.target) if isinstance(t, ast.Name)):
            continue  # the inner loop over a value of the outer display
        else:
            return None
    return out


def _lazy_names(func: ast.FunctionDef, literals: dict[str, set[str] | None]) -> set[str] | None:
    """The names a PEP 562 ``__getattr__`` can serve, read from its body: every
    string ``name`` is compared with (``name == "x"``, ``name in ("x", "y")``)
    and every key of a module-level literal it looks ``name`` up in
    (``_LAZY.get(name)``, ``_LAZY[name]``, ``name not in __all__``).  None when
    the body looks ``name`` up in something the source does not spell out, or
    never inspects ``name`` at all (a proxy that serves anything)."""
    if not func.args.args:
        return None
    param = func.args.args[0].arg
    names: set[str] = set()
    seen_lookup = False

    def is_param(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == param

    def container(node: ast.expr) -> set[str] | None:
        lit = _literal_strings(node)
        if lit is not None:
            return lit
        if isinstance(node, ast.Name):
            return literals.get(node.id)
        return None

    for node in ast.walk(func):
        found: set[str] | None = None
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left, op, right = node.left, node.ops[0], node.comparators[0]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                other = right if is_param(left) else left if is_param(right) else None
                if other is None:
                    continue
                found = {other.value} if isinstance(other, ast.Constant) and isinstance(other.value, str) else None
            elif isinstance(op, (ast.In, ast.NotIn)) and is_param(left):
                found = container(right)
            else:
                continue
        elif isinstance(node, ast.Subscript) and is_param(node.slice) and isinstance(node.ctx, ast.Load):
            found = container(node.value)  # a store (``globals()[name] = v``) is the cache, not a lookup
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
              and node.args and is_param(node.args[0])):
            found = container(node.func.value)
        else:
            continue
        seen_lookup = True
        if found is None:
            return None
        names |= found
    return names if seen_lookup else None


def module_facts(tree: ast.Module) -> ModuleFacts:
    bound: set[str] = set()
    wildcard = False
    # Every top-level ``def __getattr__``: a later one chains onto the earlier
    # (``_prev = __getattr__`` ... ``return _prev(name)``), so the served names
    # are the union, and one unreadable hook makes the whole set unknown.
    getattr_hooks: list[ast.FunctionDef] = []
    shared = False
    patterns: list[re.Pattern[str]] = []
    # Module-level string-literal containers, for reading a __getattr__ body;
    # a name assigned twice, augmented, or mutated in place is not a literal.
    literals: dict[str, set[str] | None] = {}
    deep: dict[str, set[str] | None] = {}  # every string inside the display, for comprehensions
    for stmt in _walk_top_level(tree.body):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
            if stmt.name == "__getattr__" and isinstance(stmt, ast.FunctionDef):
                getattr_hooks.append(stmt)
            continue  # bodies bind elsewhere; never walked
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)) or (
                isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None):
            key = stmt.targets[0].id if isinstance(stmt, ast.Assign) else stmt.target.id
            if key in literals:
                literals[key] = deep[key] = None  # rebound: not a literal
            else:
                literals[key] = _literal_strings(stmt.value)
                if literals[key] is None:
                    literals[key] = _comprehension_strings(stmt.value, deep)
                deep[key] = _display_strings(stmt.value)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            literals[stmt.target.id] = deep[stmt.target.id] = None
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
            literals[stmt.target.id] = deep[stmt.target.id] = None
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    literals[target.value.id] = deep[target.value.id] = None  # X[k] = v
        elif (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
              and isinstance(stmt.value.func, ast.Attribute) and isinstance(stmt.value.func.value, ast.Name)):
            literals[stmt.value.func.value.id] = deep[stmt.value.func.value.id] = None  # X.update(...)
        names, stmt_patterns, unknown = _namespace_effects(stmt)
        bound |= names
        patterns.extend(stmt_patterns)
        shared |= unknown
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    wildcard = True
                else:
                    bound.add(alias.asname or alias.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                bound |= _target_names(target)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            bound |= _target_names(stmt.target)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            bound |= _target_names(stmt.target)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    bound |= _target_names(item.optional_vars)
        elif isinstance(stmt, ast.Try) or (hasattr(ast, "TryStar") and isinstance(stmt, ast.TryStar)):
            for handler in stmt.handlers:
                if handler.name:
                    bound.add(handler.name)
        elif hasattr(ast, "TypeAlias") and isinstance(stmt, ast.TypeAlias):
            bound |= _target_names(stmt.name)
        # Walrus anywhere in a module-scope expression binds at module scope too.
        for node in _walk_expressions(stmt):
            if isinstance(node, ast.NamedExpr):
                bound |= _target_names(node.target)
    lazy: set[str] | None = set()
    for hook in getattr_hooks:
        served = _lazy_names(hook, literals)
        if served is None:
            lazy = None
            break
        lazy |= served
    return ModuleFacts(
        bound=bound,
        wildcard=wildcard,
        getattr_hook=bool(getattr_hooks),
        lazy=lazy if getattr_hooks else None,
        patterns=tuple(patterns),
        shared_namespace=shared,
    )


class Repo:
    """Resolve dotted module paths against one checkout, caching parses."""

    def __init__(self, root: Path):
        self.root = root
        self._facts: dict[str, ModuleFacts | None] = {}
        self._files: dict[str, Path | None] = {}

    def module_file(self, dotted: str) -> Path | None:
        """``a.b.c`` -> ``a/b/c.py``, ``a/b/c/__init__.py``, or the directory
        ``a/b/c`` itself (a namespace package, which binds nothing of its own)
        under the root; None when the module is not in this repo."""
        if dotted in self._files:
            return self._files[dotted]
        rel = Path(*dotted.split("."))
        found = None
        for candidate in (self.root / rel.with_suffix(".py"), self.root / rel / "__init__.py"):
            if candidate.is_file():
                found = candidate
                break
        else:
            if (self.root / rel).is_dir():
                found = self.root / rel
        self._files[dotted] = found
        return found

    def is_module(self, dotted: str) -> bool:
        return self.module_file(dotted) is not None

    def facts(self, dotted: str) -> ModuleFacts | None:
        if dotted in self._facts:
            return self._facts[dotted]
        path = self.module_file(dotted)
        facts = None
        if path is not None and path.is_dir():
            facts = ModuleFacts(bound=set(), namespace_package=True)
        elif path is not None:
            tree = _parse(path.read_bytes(), str(path))
            if tree is not None:
                facts = module_facts(tree)
        self._facts[dotted] = facts
        return facts


# ── Test-file model ─────────────────────────────────────────────────────────

class _Bindings(ast.NodeVisitor):
    """Every way a test file binds each leading name: import targets (with
    their dotted module) and everything else (parameters, assignments, defs,
    fixtures via parameters, with/for/except targets, walrus)."""

    def __init__(self, package: str, path: str = "", reads: bool = True):
        self.package = package          # dotted package of the test file, for relative imports
        self.path = path
        self.reads = reads              # also collect plain ``alias.NAME`` reads as seams
        self.imports: dict[str, set[str]] = {}   # name -> {dotted module, ...}
        self.other: set[str] = set()             # names bound by anything but an import
        self.seams: list[Seam] = []              # collected in the same pass
        # Attributes this file CREATES on a chain: ``alias.NAME = v``,
        # ``setattr(alias, "NAME", v)``, a lenient patch/setattr.  (chain, NAME).
        self.created: set[tuple[tuple[str, ...], str]] = set()
        # Attributes this file checks before touching: ``hasattr(alias, "NAME")``,
        # ``getattr(alias, "NAME", default)``.  (chain, NAME).
        self.guards: set[tuple[tuple[str, ...], str]] = set()
        self._guard_depth = 0           # inside try/except AttributeError, raises(), suppress()
        self.created_resolved: Created = frozenset()  # set by check_file once chains resolve

    def visit_Call(self, node: ast.Call) -> None:
        seam = seam_of(self.path, node)
        if seam is not None:
            self.seams.append(seam)
            if seam.lenient and not seam.string:
                for name in seam.names:
                    self.created.add((seam.chain, name))
        elif isinstance(node.func, ast.Name) and len(node.args) >= 2:
            chain = _dotted_chain(node.args[0])
            key = node.args[1]
            if chain is not None and isinstance(key, ast.Constant) and isinstance(key.value, str):
                if node.func.id == "setattr":
                    self.created.add((chain, key.value))
                elif node.func.id == "hasattr" or (node.func.id == "getattr" and len(node.args) >= 3):
                    self.guards.add((chain, key.value))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = _dotted_chain(node)
        if chain is None:
            self.generic_visit(node)  # ``f().x`` / ``a[0].x``: the base may hold calls
            return
        # A pure Name chain: record it once, at its outermost node, and do not
        # descend -- every inner Attribute is a prefix of this one.
        if isinstance(node.ctx, ast.Store):
            self.created.add((chain[:-1], chain[-1]))
        elif isinstance(node.ctx, ast.Load) and self.reads and len(chain) >= 2:
            self.seams.append(Seam(self.path, node.lineno, "read", chain[:-1], (chain[-1],), False,
                                   guarded=self._guard_depth > 0))

    def visit_Try(self, node: ast.Try) -> None:
        """A body that catches AttributeError (or anything wider) is a guard
        for the reads inside it; the handlers, else and finally are not."""
        guarded = any(_catches_attribute_error(h.type) for h in node.handlers)
        self._guard_depth += guarded
        for stmt in node.body:
            self.visit(stmt)
        self._guard_depth -= guarded
        for part in (node.handlers, node.orelse, node.finalbody):
            for stmt in part:
                self.visit(stmt)

    visit_TryStar = visit_Try  # type: ignore[assignment]

    def _bind_import(self, name: str, dotted: str | None) -> None:
        if dotted is None:
            self.other.add(name)
        else:
            self.imports.setdefault(name, set()).add(dotted)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname:
                self._bind_import(alias.asname, alias.name)
            else:
                self._bind_import(alias.name.split(".", 1)[0], alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            parts = self.package.split(".") if self.package else []
            if node.level - 1 > len(parts):
                for alias in node.names:
                    self.other.add(alias.asname or alias.name)
                return
            parts = parts[: len(parts) - (node.level - 1)]
            base = ".".join(p for p in parts + ([base] if base else []) if p)
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            self._bind_import(name, f"{base}.{alias.name}" if base else alias.name)

    def _bind_other(self, node: ast.AST) -> None:
        self.other |= _target_names(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.other.add(node.name)
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.other.add(arg.arg)
        for arg in (args.vararg, args.kwarg):
            if arg is not None:
                self.other.add(arg.arg)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.other.add(arg.arg)
        for arg in (args.vararg, args.kwarg):
            if arg is not None:
                self.other.add(arg.arg)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.other.add(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind_other(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._bind_other(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._bind_other(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._bind_other(node.target)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._bind_other(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For  # type: ignore[assignment]

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._bind_other(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        guarded = False
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_other(item.optional_vars)
            self.visit(item.context_expr)
            guarded |= _is_attribute_error_context(item.context_expr)
        self._guard_depth += guarded
        for stmt in node.body:
            self.visit(stmt)
        self._guard_depth -= guarded

    visit_AsyncWith = visit_With  # type: ignore[assignment]

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.other.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.other.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.other.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.other.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.other.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.other.add(node.rest)
        self.generic_visit(node)

    def is_guarded(self, seam: Seam) -> bool:
        """``hasattr(a, "b")`` guards ``a.b``, ``a.b.c`` and a patch on ``a.b``:
        the name and every component of the chain after the first."""
        if any((seam.chain, name) in self.guards for name in seam.names):
            return True
        return any((seam.chain[:i], seam.chain[i]) in self.guards for i in range(1, len(seam.chain)))

    def resolve(self, name: str) -> str | None:
        """Dotted module for a leading name, or None when the name is bound
        dynamically, ambiguously, or not at all."""
        if name in self.other:
            return None
        modules = self.imports.get(name)
        if not modules or len(modules) != 1:
            return None
        return next(iter(modules))


def _catches_attribute_error(handler_type: ast.expr | None) -> bool:
    """``except:`` / ``except AttributeError`` / ``except (X, AttributeError)`` /
    ``except Exception`` / ``except BaseException``."""
    if handler_type is None:
        return True
    names = [handler_type] if not isinstance(handler_type, ast.Tuple) else list(handler_type.elts)
    for name in names:
        leaf = name.attr if isinstance(name, ast.Attribute) else name.id if isinstance(name, ast.Name) else None
        if leaf in ("AttributeError", "Exception", "BaseException"):
            return True
    return False


def _is_attribute_error_context(expr: ast.expr) -> bool:
    """``pytest.raises(AttributeError)`` / ``raises(AttributeError, ...)`` /
    ``contextlib.suppress(AttributeError)`` as a ``with`` item."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    leaf = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    if leaf not in ("raises", "suppress"):
        return False
    return any(_catches_attribute_error(arg) for arg in expr.args if not isinstance(arg, ast.Constant))


def _dotted_chain(node: ast.expr) -> tuple[str, ...] | None:
    """``a.b.c`` as ``("a", "b", "c")``; None for anything but a Name/Attribute chain."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return tuple(reversed(parts))


def _callee(node: ast.Call) -> tuple[str | None, str | None]:
    """(``patch``-style head, last attribute): ``patch.object`` -> ("patch", "object"),
    ``mock.patch`` -> ("patch", None), ``monkeypatch.setattr`` -> (None, "setattr")."""
    func = node.func
    if isinstance(func, ast.Name):
        return (func.id if func.id == "patch" else None), None
    if isinstance(func, ast.Attribute):
        last = func.attr
        if last in _PATCH_CALLEES and isinstance(func.value, (ast.Name, ast.Attribute)):
            head = func.value.id if isinstance(func.value, ast.Name) else func.value.attr
            if head == "patch":
                return "patch", last
            return None, None
        if last == "patch":
            return "patch", None
        if last in _SETATTR_CALLEES:
            return None, last
    return None, None


def _has_lenient_kw(node: ast.Call, *names: str) -> bool:
    for kw in node.keywords:
        if kw.arg in names and isinstance(kw.value, ast.Constant):
            want = kw.value.value
            if (kw.arg == "create" and want is True) or (kw.arg == "raising" and want is False):
                return True
    return False


def seam_of(path: str, node: ast.Call) -> Seam | None:
    """The seam a call expresses, or None when it is not a patch site or not
    one whose target is a Name/Attribute chain or a dotted string."""
    if not node.args:
        return None
    head, last = _callee(node)
    first = node.args[0]
    if head == "patch" and last in _PATCH_CALLEES:
        # patch.object(target, "name", ...) / patch.multiple(target, name=...)
        lenient = _has_lenient_kw(node, "create")
        if last == "object":
            if len(node.args) < 2 or not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
                return None
            names: tuple[str, ...] = (node.args[1].value,)
        else:
            names = tuple(kw.arg for kw in node.keywords if kw.arg and kw.arg != "create")
            if not names:
                return None
        form = f"patch.{last}"
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return Seam(path, node.lineno, form, tuple(first.value.split(".")), names, lenient, string=True)
    elif head == "patch" and last is None:
        # patch("dotted.module.name", ...)
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value):
            return None
        dotted, _, attr = first.value.rpartition(".")
        return Seam(path, node.lineno, "patch", tuple(dotted.split(".")), (attr,), _has_lenient_kw(node, "create"), string=True)
    elif last in _SETATTR_CALLEES:
        # monkeypatch.setattr(target, "name", value) / setattr("dotted.name", value)
        lenient = _has_lenient_kw(node, "raising")
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if "." not in first.value:
                return None
            dotted, _, attr = first.value.rpartition(".")
            return Seam(path, node.lineno, last, tuple(dotted.split(".")), (attr,), lenient, string=True)
        if len(node.args) < 2 or not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            return None
        names = (node.args[1].value,)
        form = last
    else:
        return None
    chain = _dotted_chain(first)
    if chain is None:
        return None  # type(x), sys.modules[...], a call: not a module seam
    return Seam(path, node.lineno, form, chain, names, lenient)


# ── Resolution ──────────────────────────────────────────────────────────────

Created = frozenset[tuple[str, str]]  # (dotted module, attribute) the test tree creates


def _walk_chain(repo: Repo, dotted: str, rest: tuple[str, ...], created: Created = frozenset()) -> tuple[str, str | None]:
    """Walk ``rest`` from module ``dotted``.  Returns (verdict, detail):
    ``module`` (the whole chain is a module; detail = its dotted path),
    ``object_attr`` (crossed into a bound object), ``not_static``,
    ``unbound`` (detail = the message), ``unparseable``, ``created`` (crossed
    an attribute the test tree itself creates)."""
    for i, name in enumerate(rest):
        sub = f"{dotted}.{name}"
        if repo.is_module(sub):
            dotted = sub
            continue
        facts = repo.facts(dotted)
        if facts is None:
            return "unparseable", dotted
        if facts.binds(name) or name in _MODULE_DUNDERS:
            return ("object_attr", None) if i + 1 < len(rest) else ("bound", dotted)
        if (dotted, name) in created:
            return "created", dotted
        if not facts.static:
            return "not_static", dotted
        return "unbound", f"{dotted} binds no `{name}` at top level ({repo.module_file(dotted).relative_to(repo.root).as_posix()})"
    return "module", dotted


_SEAM_BYTES = (b"patch", b"setattr", b"delattr")


def _model(repo: Repo, rel: str, source: bytes, reads: bool) -> _Bindings | None:
    tree = _parse(source, rel)
    if tree is None:
        return None
    package = ".".join(Path(rel).with_suffix("").parts[:-1])
    bindings = _Bindings(package, rel, reads=reads)
    bindings.visit(tree)
    return bindings


def _module_of_chain(repo: Repo, bindings: _Bindings, chain: tuple[str, ...], string: bool = False) -> tuple[str | None, str]:
    """Resolve a seam's target chain to a repo module: (dotted, "module"), or
    (None, reason) with reason in dynamic / external / object_attr /
    not_static / unparseable / created / unbound."""
    if string:
        top = chain[0]
        if not repo.is_module(top):
            return None, "external"
        dotted, rest = top, chain[1:]
    else:
        dotted = bindings.resolve(chain[0])
        if dotted is None:
            return None, "dynamic"
        if not repo.is_module(dotted):
            # ``from pkg import name`` where name is not a submodule: an object
            # (class/function) or an external module.  Either way not a module seam.
            parent, _, _leaf = dotted.rpartition(".")
            return None, "object_attr" if parent and repo.is_module(parent) else "external"
        rest = chain[1:]
    verdict, detail = _walk_chain(repo, dotted, rest, bindings.created_resolved)
    if verdict == "module":
        return detail or dotted, "module"
    if verdict == "bound":
        return None, "object_attr"
    return None, verdict if verdict != "unbound" else f"unbound:{detail}"


def created_by(repo: Repo, bindings: _Bindings) -> set[tuple[str, str]]:
    """The (module, attribute) pairs a file creates, its chains resolved."""
    out: set[tuple[str, str]] = set()
    bindings.created_resolved = frozenset()
    for chain, name in bindings.created:
        module, _ = _module_of_chain(repo, bindings, chain)
        if module is not None:
            out.add((module, name))
    return out


def check_file(repo: Repo, rel: str, source: bytes, stats: Stats, allow: frozenset[str] = ALLOWLIST,
               created: Created = frozenset(), reads: bool = True) -> list[Finding]:
    stats.files += 1
    if not reads and not any(token in source for token in _SEAM_BYTES):
        return []  # no patch seam can be spelled without one of these
    bindings = _model(repo, rel, source, reads)
    if bindings is None:
        stats.unparseable.append(rel)
        return []
    # What the tree creates (conftests, passed in) plus what this file creates.
    bindings.created_resolved = frozenset(created | created_by(repo, bindings))
    findings: list[Finding] = []
    for seam in bindings.seams:
        stats.seams += 1
        if seam.lenient:
            stats.lenient += 1
            continue
        if seam.guarded or bindings.is_guarded(seam):
            stats.guarded += 1
            continue
        dotted, reason = _module_of_chain(repo, bindings, seam.chain, seam.string)
        if dotted is None:
            if reason.startswith("unbound:"):
                # The chain itself does not resolve: report once, for the chain.
                finding = Finding(rel, seam.line, seam.form, seam.target, reason[len("unbound:"):])
                if finding.key not in allow:
                    findings.append(finding)
            elif reason == "unparseable":
                stats.unparseable.append(seam.target)
            else:
                setattr(stats, reason, getattr(stats, reason) + 1)
            continue
        module = dotted
        facts = repo.facts(module)
        if facts is None:
            stats.unparseable.append(module)
            continue
        for name in seam.names:
            target = f"{seam.target}.{name}"
            if facts.binds(name) or name in _MODULE_DUNDERS or repo.is_module(f"{module}.{name}"):
                stats.verified += 1
                continue
            if (module, name) in bindings.created_resolved:
                stats.created += 1
                continue
            if seam.form.startswith("patch") and name in _BUILTIN_NAMES:
                stats.lenient += 1
                continue
            if not facts.static:
                stats.not_static += 1
                continue
            finding = Finding(
                rel, seam.line, seam.form, target,
                f"{module} binds no `{name}` at top level ({repo.module_file(module).relative_to(repo.root).as_posix()})",
            )
            if finding.key not in allow:
                findings.append(finding)
    return findings


# ── Driver ──────────────────────────────────────────────────────────────────

def tracked_test_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--", "tests/*.py", "tests/**/*.py"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed in %s:\n%s" % (repo, proc.stderr.decode(errors="replace").strip()))
    return sorted({p for p in proc.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p.endswith(".py")})


def conftest_files(repo_root: Path) -> list[str]:
    """Every ``conftest.py`` under ``tests/`` (plus a root one): the only test
    files whose attribute creations reach OTHER files, through fixtures."""
    found = sorted(p.relative_to(repo_root).as_posix() for p in (repo_root / "tests").rglob("conftest.py"))
    if (repo_root / "conftest.py").is_file():
        found.insert(0, "conftest.py")
    return found


def conftest_created(repo_root: Path) -> Created:
    """(module, attribute) pairs any conftest creates -- ``monkeypatch.setattr(
    mod, "x", v, raising=False)`` in a fixture, ``mod.x = v``, ``setattr(mod,
    "x", v)`` -- so a test reading them is not judged against the module."""
    repo = Repo(repo_root)
    out: set[tuple[str, str]] = set()
    for rel in conftest_files(repo_root):
        try:
            bindings = _model(repo, rel, (repo_root / rel).read_bytes(), reads=False)
        except OSError:
            continue
        if bindings is not None:
            out |= created_by(repo, bindings)
    return frozenset(out)


def scan(repo_root: Path, files: list[str], allow: frozenset[str] = ALLOWLIST,
         created: Created | None = None, reads: bool = True) -> tuple[list[Finding], Stats]:
    """Scan ``files`` (repo-relative) in this process.  ``created`` is the
    tree-wide conftest creation set; computed here when not given."""
    repo = Repo(repo_root)
    if created is None:
        created = conftest_created(repo_root)
    stats = Stats()
    findings: list[Finding] = []
    for rel in files:
        path = repo_root / rel
        try:
            source = path.read_bytes()
        except OSError:
            stats.unparseable.append(rel)
            continue
        findings.extend(check_file(repo, Path(rel).as_posix(), source, stats, allow, created, reads))
    findings.sort(key=lambda f: (f.path, f.line, f.target))
    return findings, stats


def _scan_chunk(args: tuple[str, list[str], Created, bool]) -> tuple[list[Finding], Stats]:
    root, files, created, reads = args
    return scan(Path(root), files, created=created, reads=reads)


def default_jobs() -> int:
    return max(1, min(4, os.cpu_count() or 1))


def scan_parallel(repo_root: Path, files: list[str], jobs: int, reads: bool = True) -> tuple[list[Finding], Stats]:
    """``scan`` split over ``jobs`` worker processes (parsing ~4600 test files
    is the whole cost; each worker keeps its own module-facts cache).  Serial
    when ``jobs`` is 1 or the scope is small; the workers re-import this file
    by path, so this is only reachable from the CLI, never from ``scan()``."""
    created = conftest_created(repo_root)
    if jobs <= 1 or len(files) < 64:
        return scan(repo_root, files, created=created, reads=reads)
    chunks = [files[i::jobs] for i in range(jobs)]
    findings: list[Finding] = []
    stats = Stats()
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        for chunk_findings, chunk_stats in pool.map(_scan_chunk, [(str(repo_root), chunk, created, reads) for chunk in chunks]):
            findings.extend(chunk_findings)
            stats.merge(chunk_stats)
    findings.sort(key=lambda f: (f.path, f.line, f.target))
    return findings, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("files", nargs="*", help="test files to scan (default: every tracked .py under tests/)")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="repository root (default: this checkout)")
    parser.add_argument("--verbose", action="store_true", help="print scan statistics to stderr")
    parser.add_argument("--jobs", type=int, default=default_jobs(), help="worker processes for a full scan (default: min(4, cpus); 1 = in-process)")
    parser.add_argument("--no-reads", action="store_true", help="check patch/setattr seams only, not plain `alias.NAME` reads")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"error: --repo {args.repo!r} is not a directory", file=sys.stderr)
        return 2
    if args.files:
        files = []
        for raw in args.files:
            p = Path(raw)
            if p.is_absolute():
                try:
                    p = p.resolve().relative_to(repo_root)
                except ValueError:
                    print(f"error: {raw!r} is outside --repo {repo_root}", file=sys.stderr)
                    return 2
            files.append(p.as_posix())
    else:
        try:
            files = tracked_test_files(repo_root)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    findings, stats = scan_parallel(repo_root, files, args.jobs, reads=not args.no_reads)
    for finding in findings:
        print(finding.render())
    if args.verbose or stats.unparseable:
        print(stats.render(), file=sys.stderr)
        for rel in stats.unparseable:
            print(f"  unparseable: {rel}", file=sys.stderr)
    if findings:
        print(
            f"{len(findings)} stale seam(s): the patched or read name is not bound by the "
            "module's source, so the test raises AttributeError at run time.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
