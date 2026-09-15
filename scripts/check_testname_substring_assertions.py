#!/usr/bin/env python3
"""Find PRESENCE substring assertions the test's own NAME already satisfies.

The defect, measured 2026-09-14 in
``tests/tools/test_skill_manager_tool.py::TestDeleteSkillRmtreeGuard``::

    def test_symlinked_skill_dir_refused(self, tmp_path):
        ...
        assert "symlink" in result["error"].lower()

``result["error"]`` is ``"Refusing to delete '<skill_dir>': ..."`` and
``<skill_dir>`` lives under pytest's ``tmp_path``.  pytest derives ``tmp_path``
from the test FUNCTION name, so the directory is
``...\\test_symlinked_skill_dir_refus0\\skills\\evil-skill``.  The token
"symlink" is in the haystack no matter what production code does.

Proof that this is not theoretical: mutating
``tools/skill_manager_guards.py::_is_path_redirect`` to drop its
``is_junction()`` clause changed WHICH guard refused — the message became
``"path does not resolve inside any known skills root."`` — and the test STILL
PASSED, because that message also embeds the path.  A correct mutation at the
correct site produced a green.  Fixed in ``6753c9e127`` by pinning the
distinctive phrase ``"is a symlink/junction"`` instead.

What this scanner reports is a CANDIDATE, never a finding.  The assertion is
only unfalsifiable if the haystack can actually carry the path, the node id or
the test name.  Confirm per site, then prove it by mutating the production
predicate the test claims to pin and showing the test still passes.

Two shapes are matched inside any ``def test_*``:

  * ``assert "<literal>" in <expr>`` and ``assert "<literal>" in <expr>.lower()``
  * ``pytest.raises(..., match="<literal>")`` where the pattern is a plain
    string literal

The ``.lower()`` matters rather than being incidental: pytest's ``tmp_path``
segment is already lowercase, so folding the haystack WIDENS the collision.

Exit codes:
  0 — no candidates
  1 — candidates found
  2 — script error

Usage:
  python scripts/check_testname_substring_assertions.py [ROOT ...]
  python scripts/check_testname_substring_assertions.py --json
  python scripts/check_testname_substring_assertions.py --only-tmp-path-shaped
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Methods of a Test* class are matched through the same ``test``-prefix rule
# pytest itself applies, so no separate class check is needed — but the class
# name is reported, because it is what a reader needs to locate the site.
_TEST_PREFIX = "test"

# Receivers whose ``.raises``/``.warns`` take a ``match=`` regex.
_RAISES_ATTRS = frozenset({"raises", "warns"})

# String methods that fold case on the haystack side of ``in``.
_CASE_FOLDERS = frozenset({"lower", "upper", "casefold"})


def tmp_path_basename(func_name: str) -> str:
    """Reproduce pytest's ``tmp_path`` directory name for a test function.

    ``_pytest.tmpdir.TempPathFactory.mktemp`` sanitises the node name by
    replacing every non-word character with ``_`` and truncating to 30
    characters, then appends a numeric suffix.  Only those first 30 characters
    can leak into a path, which is why the strict signal below is narrower than
    the name-collision signal.
    """
    return re.sub(r"[\W]", "_", func_name)[:30]


def squash(text: str) -> str:
    """Lowercase and drop every non-alphanumeric character."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _str_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover — defensive
        return "<unparseable>"


def _strip_case_fold(node: ast.AST) -> tuple[ast.AST, bool]:
    """Peel a trailing ``.lower()``/``.upper()``/``.casefold()`` off a haystack."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CASE_FOLDERS
        and not node.args
        and not node.keywords
    ):
        return node.func.value, True
    return node, False


class _Sweeper(ast.NodeVisitor):
    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.lines = source.splitlines()
        self.class_stack: list[str] = []
        self.func_stack: list[str] = []
        self.hits: list[dict] = []

    # -- scoping ---------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_func(self, node: ast.AST) -> None:
        self.func_stack.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self.func_stack.pop()

    visit_FunctionDef = _visit_func  # type: ignore[assignment]
    visit_AsyncFunctionDef = _visit_func  # type: ignore[assignment]

    def _test_func(self) -> str | None:
        """Innermost enclosing pytest test function, or None.

        Innermost rather than outermost: a helper nested inside a test does not
        get its own ``tmp_path``, but an assertion written inside a ``def
        test_*`` nested in another ``def test_*`` would collide against the
        inner name pytest never uses.  Walking from the inside out and taking
        the first ``test``-prefixed frame keeps the reported name the one whose
        body the assertion is in.
        """
        for name in reversed(self.func_stack):
            if name.startswith(_TEST_PREFIX):
                return name
        return None

    # -- the two shapes --------------------------------------------------
    def visit_Assert(self, node: ast.Assert) -> None:
        for cmp_node in self._compares(node.test):
            if len(cmp_node.ops) != 1 or not isinstance(cmp_node.ops[0], ast.In):
                continue
            literal = _str_literal(cmp_node.left)
            if literal is None:
                continue
            inner, folded = _strip_case_fold(cmp_node.comparators[0])
            self._record(
                kind="assert-in",
                literal=literal,
                haystack=inner,
                case_folded=folded,
                lineno=cmp_node.lineno,
            )
        self.generic_visit(node)

    @staticmethod
    def _compares(test: ast.AST):
        """Yield Compare nodes, descending through ``and``.

        ``assert "x" in a and "y" in b`` is one Assert with a BoolOp test; both
        halves are members of this population.
        """
        if isinstance(test, ast.Compare):
            yield test
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            for value in test.values:
                if isinstance(value, ast.Compare):
                    yield value

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_raises_like(node.func):
            for kw in node.keywords:
                if kw.arg != "match":
                    continue
                literal = _str_literal(kw.value)
                if literal is None:
                    continue
                self._record(
                    kind="raises-match",
                    literal=literal,
                    haystack=None,
                    case_folded=False,
                    lineno=node.lineno,
                )
        self.generic_visit(node)

    @staticmethod
    def _is_raises_like(func: ast.AST) -> bool:
        # Any receiver: pytest.raises, pt.raises, a bare imported raises.
        if isinstance(func, ast.Attribute):
            return func.attr in _RAISES_ATTRS
        if isinstance(func, ast.Name):
            return func.id in _RAISES_ATTRS
        return False

    # -- collision test --------------------------------------------------
    def _record(
        self,
        *,
        kind: str,
        literal: str,
        haystack: ast.AST | None,
        case_folded: bool,
        lineno: int,
    ) -> None:
        func = self._test_func()
        if func is None:
            return
        squashed_literal = squash(literal)
        if not squashed_literal:
            return
        if squashed_literal not in squash(func):
            return

        basename = tmp_path_basename(func)
        self.hits.append(
            {
                "file": str(self.path).replace("\\", "/"),
                "line": lineno,
                "kind": kind,
                "class": "::".join(self.class_stack) or None,
                "func": func,
                "literal": literal,
                "haystack": _unparse(haystack),
                "case_folded": case_folded,
                "tmp_path_basename": basename,
                # Strict signal: does the literal survive pytest's own
                # sanitisation into the real directory name?  The squashed
                # comparison above is deliberately a superset (it ignores the
                # ``_`` separators and the 30-char cut) so that a node-id or
                # ``request.node.name`` haystack is not missed; this field says
                # whether a tmp_path leak specifically is possible.
                "literal_in_tmp_path_basename": literal.lower() in basename.lower(),
                "source": (
                    self.lines[lineno - 1].strip()
                    if 0 < lineno <= len(self.lines)
                    else ""
                ),
            }
        )


def sweep_source(path: Path, source: str) -> list[dict]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    sweeper = _Sweeper(path, source)
    sweeper.visit(tree)
    return sweeper.hits


def sweep_file(path: Path) -> list[dict]:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return sweep_source(path, source)


def iter_targets(roots: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_file():
            out.append(root)
        elif root.is_dir():
            out.extend(sorted(root.rglob("*.py")))
    return out


def default_roots(repo: Path) -> list[Path]:
    return [repo / "tests", *sorted(repo.glob("profiles/*/workspace"))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag presence substring assertions satisfied by the test's own name."
    )
    ap.add_argument("roots", nargs="*", help="files or directories (default: tests/ + profiles/*/workspace)")
    ap.add_argument("--json", action="store_true", help="emit candidates as JSON")
    ap.add_argument(
        "--only-tmp-path-shaped",
        action="store_true",
        help="restrict to literals that survive pytest's tmp_path sanitisation",
    )
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    roots = [Path(r) for r in args.roots] if args.roots else default_roots(repo)

    hits: list[dict] = []
    for path in iter_targets(roots):
        hits.extend(sweep_file(path))

    if args.only_tmp_path_shaped:
        hits = [h for h in hits if h["literal_in_tmp_path_basename"]]

    if args.json:
        print(json.dumps(hits, indent=2))
        return 1 if hits else 0

    if not hits:
        print("✅ no presence assertion is satisfied by its own test's name")
        return 0

    for h in hits:
        flag = "TMP_PATH-SHAPED" if h["literal_in_tmp_path_basename"] else "name-only"
        fold = " +.lower()" if h["case_folded"] else ""
        print(f"{h['file']}:{h['line']}  [{h['kind']}{fold}]  {flag}")
        print(f"    func    : {h['func']}   (tmp_path -> {h['tmp_path_basename']})")
        print(f"    literal : {h['literal']!r}")
        print(f"    haystack: {h['haystack']}")
        print(f"    source  : {h['source']}")
    print(f"\n❌ {len(hits)} candidate(s) — each needs the haystack checked and a mutation run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
