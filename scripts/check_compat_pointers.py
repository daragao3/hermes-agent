#!/usr/bin/env python3
"""Fail when in-tree code depends on a plugin-compat pointer.

``compat_manifest.json`` lists every name the Sep 2026 decomposition kept importable from its OLD
module purely for external plugins (the `PLUGIN-COMPAT` blocks). Those blocks are removed on a
schedule by reverting the commit that added them, so nothing inside this repository may depend on
them — otherwise the revert breaks the tree. This check walks every first-party Python file (source
AND tests) and flags:

  from <facade> import <compat_name>          # direct import through the old path
  import <facade>; <facade>.<compat_name>     # attribute access through the old path
  patch("<facade>.<compat_name>") / monkeypatch.setattr(<facade>, "<compat_name>")

Name resolution is SCOPE-AWARE (see ``_resolve``): a function-local alias binds only
inside that function, a parameter or assignment shadows an enclosing alias, and a class
body is not an enclosing scope for its methods. A module-level alias still reaches nested
functions -- that direction is the true positive, and losing it would make this gate
useless.

Exit 1 with a file:line list on any hit. Run: python scripts/check_compat_pointers.py
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "compat_manifest.json"
SKIP_DIRS = {".git", "node_modules", "website", "skills", "optional-skills", "apps", "evals", "build", "MagicMock", ".worktrees", "__pycache__",
             ".claude", ".venv", "venv"}
# ``.claude`` holds this repo's per-session git worktrees (".claude/worktrees/<name>"),
# each a full ~13k-file checkout. Without it this walk covers ~20 sibling trees, takes
# over ten minutes, and reports other sessions' files as if they were ours. ".worktrees"
# above never matched anything here -- it is not the path this repo actually uses.

# The compat layer's own tests use the pointers on purpose -- as fixtures and as the
# subject under test -- and they are deleted or rewritten along with the layer. Flagging
# them is noise that would keep this checker permanently red, so it could never be used
# as a gate. test_check_compat_pointers.py is THIS script's own regression test: its
# sample sources deliberately contain pointer-shaped strings.
#
# These are matched on BARE FILENAME, so a rename leaves a dead entry behind that will
# silently skip any future file that happens to take the name -- nothing about a stale
# entry makes this checker red. tests/scripts/test_check_compat_pointers.py pins each
# name to the one path it is allowed to match; keep the two in sync.
_COMPAT_OWN_TESTS = {
    "test_compat_manifest_targets.py": "tests/test_compat_manifest_targets.py",
    "test_plugin_compat_notice.py": "tests/test_plugin_compat_notice.py",
    "test_check_compat_pointers.py": "tests/scripts/test_check_compat_pointers.py",
}


def _py_files():
    for p in ROOT.rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        if parts[0] in SKIP_DIRS or p.name == "check_compat_pointers.py":
            continue
        if p.name in _COMPAT_OWN_TESTS:
            continue
        yield p


class _Scope:
    """One Python name-resolution scope.

    ``aliases`` are the facade imports bound HERE; ``shadowed`` is every other
    name bound here (parameter, assignment, loop target, ``def``/``class``,
    non-facade import, ``except ... as``). A name in ``shadowed`` is NOT the
    facade, whatever an enclosing scope bound it to.
    """

    __slots__ = ("kind", "parent", "aliases", "shadowed", "globals", "nonlocals")

    def __init__(self, kind: str, parent: "_Scope | None") -> None:
        self.kind = kind  # "module" | "function" | "class" | "comprehension"
        self.parent = parent
        self.aliases: dict[str, str] = {}
        self.shadowed: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()


def _target_names(node):
    """Every Name bound by an assignment target, through tuple/list/star nesting."""
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _target_names(elt)
    elif isinstance(node, ast.Starred):
        yield from _target_names(node.value)


def _arg_nodes(args: ast.arguments):
    yield from getattr(args, "posonlyargs", [])
    yield from args.args
    if args.vararg is not None:
        yield args.vararg
    yield from args.kwonlyargs
    if args.kwarg is not None:
        yield args.kwarg


def _resolve(scope: "_Scope", name: str) -> str | None:
    """The facade ``name`` refers to in ``scope``, or None.

    Models the two Python rules this checker kept getting wrong:

    * a binding ANYWHERE in a function makes the name local to that function
      for the whole body, so a parameter named ``kb`` shadows an enclosing
      ``import ... as kb`` even if the import is textually later; and
    * a class body is not an enclosing scope for functions nested in it, so a
      class-level alias does not reach its own methods.

    Names bound at module level DO reach nested functions -- that direction is
    the true positive this must not lose.
    """
    s: "_Scope | None" = scope
    first = True
    while s is not None:
        if not first and s.kind == "class":
            s = s.parent
            continue
        if name in s.globals:
            module = s
            while module.parent is not None:
                module = module.parent
            return module.aliases.get(name)
        if name in s.nonlocals:
            s = s.parent
            first = False
            continue
        # aliases before shadowed: when one scope both imports the facade and
        # rebinds the name, keep flagging. Without flow analysis that is the
        # choice that cannot drop a real dependency.
        if name in s.aliases:
            return s.aliases[name]
        if name in s.shadowed:
            return None
        s = s.parent
        first = False
    return None


def _scope_map(tree: ast.Module, facades: set[str]) -> dict[ast.AST, "_Scope"]:
    """Map every node to the scope it executes in, collecting that scope's bindings.

    Bindings for a scope are complete before anything is resolved, which is what
    makes "parameter shadows a textually later import" come out right.
    """
    module = _Scope("module", None)
    node_scope: dict[ast.AST, "_Scope"] = {}

    def bind(scope: "_Scope", name: str, facade: str | None = None) -> None:
        if facade is not None:
            scope.aliases[name] = facade
        else:
            scope.shadowed.add(name)

    def bind_import(node: ast.Import, scope: "_Scope") -> None:
        for a in node.names:
            if a.asname:
                # `import pkg.mod as m` -> "m" is the module itself
                bind(scope, a.asname, a.name if a.name in facades else None)
            else:
                # `import pkg.mod` binds only "pkg" -- but that package object
                # still reaches pkg.mod's attributes, so keep it if it is a facade
                top = a.name.split(".")[0]
                bind(scope, top, top if top in facades else None)

    def bind_import_from(node: ast.ImportFrom, scope: "_Scope") -> None:
        for a in node.names:
            full = f"{node.module}.{a.name}" if (node.level == 0 and node.module) else None
            bind(scope, a.asname or a.name, full if full in facades else None)

    def visit_args(args: ast.arguments, outer: "_Scope", inner: "_Scope") -> None:
        node_scope[args] = outer
        for d in list(args.defaults) + [k for k in args.kw_defaults if k is not None]:
            visit(d, outer)  # defaults evaluate in the ENCLOSING scope
        for arg in _arg_nodes(args):
            node_scope[arg] = inner
            bind(inner, arg.arg)
            if arg.annotation is not None:
                visit(arg.annotation, outer)

    def visit(node, scope: "_Scope") -> None:
        node_scope[node] = scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bind(scope, node.name)
            inner = _Scope("function", scope)
            for d in node.decorator_list:
                visit(d, scope)
            if node.returns is not None:
                visit(node.returns, scope)
            visit_args(node.args, scope, inner)
            for child in getattr(node, "type_params", []):
                visit(child, inner)
            for st in node.body:
                visit(st, inner)
            return
        if isinstance(node, ast.Lambda):
            inner = _Scope("function", scope)
            visit_args(node.args, scope, inner)
            visit(node.body, inner)
            return
        if isinstance(node, ast.ClassDef):
            bind(scope, node.name)
            for child in node.decorator_list + list(node.bases) + list(node.keywords):
                visit(child, scope)
            inner = _Scope("class", scope)
            for child in getattr(node, "type_params", []):
                visit(child, inner)
            for st in node.body:
                visit(st, inner)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            inner = _Scope("comprehension", scope)
            for gen in node.generators:
                for n in _target_names(gen.target):
                    bind(inner, n)
            for child in ast.iter_child_nodes(node):
                visit(child, inner)
            return

        if isinstance(node, ast.Import):
            bind_import(node, scope)
        elif isinstance(node, ast.ImportFrom):
            bind_import_from(node, scope)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in _target_names(t):
                    bind(scope, n)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            for n in _target_names(node.target):
                bind(scope, n)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for n in _target_names(node.target):
                bind(scope, n)
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                for n in _target_names(node.optional_vars):
                    bind(scope, n)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                bind(scope, node.name)
        elif isinstance(node, ast.Global):
            scope.globals.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            scope.nonlocals.update(node.names)

        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, module)
    return node_scope


def main() -> int:
    if not MANIFEST.exists():
        print("compat_manifest.json missing — nothing to check (compat layer already reverted?)")
        return 0
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
    compat: dict[str, set[str]] = {}
    for e in entries:
        compat.setdefault(e["facade"], set()).add(e["name"])
    facades = set(compat)
    hits: list[str] = []
    # NO QUOTE CHARACTERS HERE. This is fullmatch'ed against ``ast.Constant.value``,
    # which is the string's VALUE -- the quotes are syntax and are long gone by then.
    # The original pattern required them, so this branch could never match and the
    # ``patch("facade.name")`` shape -- the most common one in this test suite -- went
    # uncaught from the day it was written.
    str_pat = re.compile(r"(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*")
    for path in _py_files():
        rel = path.relative_to(ROOT)
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except SyntaxError:
            continue
        # ``from <facade> import <pointer>`` is a dependency wherever it appears --
        # module level, inside a function, inside a class body. No scope needed.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in facades and node.level == 0:
                for b in [a.name for a in node.names if a.name in compat[node.module]]:
                    hits.append(f"{rel}:{node.lineno}: from {node.module} import {b}")
        # Everything below resolves a bare Name, so it needs to know which binding
        # of that name is live where it is used. The alias map used to be built in
        # one flat ``ast.walk`` over the whole file, which made a FUNCTION-LOCAL
        # ``from hermes_cli import kanban_db as kb`` bind "kb" for every other
        # function too. Measured 2026-09-13: 31 false positives in
        # tests/stress/test_atypical_scenarios.py, whose scenario functions take an
        # unrelated ``kb`` parameter. The flat map is wrong in only that one
        # direction -- an OUTER import really does reach inner functions -- so
        # ``_resolve`` walks outward from the use site rather than dropping
        # function-local aliases.
        node_scope = _scope_map(tree, facades)
        for node in ast.walk(tree):
            scope = node_scope.get(node)
            if scope is None:
                # Belt and braces, not a known gap: measured 0 unscoped nodes over
                # 1,646 real files in this tree. A future grammar could add a node
                # kind ``_scope_map`` does not descend into; skipping is the
                # behaviour that cannot invent a hit out of the wrong scope.
                continue
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                fac = _resolve(scope, node.value.id)
                if fac and node.attr in compat[fac]:
                    hits.append(f"{rel}:{node.lineno}: {node.value.id}.{node.attr} (via {fac})")
            elif isinstance(node, ast.Call):
                # monkeypatch.setattr(<facade alias>, "<name>", ...) / patch.object(<facade alias>, "<name>")
                fn = node.func
                is_setattr = (isinstance(fn, ast.Attribute) and fn.attr in ("setattr", "delattr", "object")) or (
                    isinstance(fn, ast.Name) and fn.id in ("setattr", "delattr", "getattr", "hasattr"))
                if is_setattr and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    fac = _resolve(scope, node.args[0].id)
                    if fac and node.args[1].value in compat[fac]:
                        hits.append(f"{rel}:{node.lineno}: setattr/patch({node.args[0].id}, \"{node.args[1].value}\") (via {fac})")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                m = str_pat.fullmatch(node.value.strip())
                if m:
                    dotted = m.group(0); fac, _, name = dotted.rpartition(".")
                    if fac in facades and name in compat[fac]:
                        hits.append(f"{rel}:{node.lineno}: \"{dotted}\" (string patch target)")
    if hits:
        print("❌ in-tree code depends on plugin-compat pointers (scheduled for removal):")
        for h in sorted(set(hits)):
            print("  " + h)
        print(f"\n{len(set(hits))} site(s). Import from the defining module instead (see COMPAT_MANIFEST.md).")
        return 1
    print(f"✅ no in-tree dependency on the {len(entries)} plugin-compat pointers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
