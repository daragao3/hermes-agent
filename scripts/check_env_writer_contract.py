#!/usr/bin/env python3
"""Guard: every ``.env`` read-modify-write carries all THREE encoding properties.

WHY THIS EXISTS
---------------
A ".env writer" reads an existing ``.env``, updates some keys and writes the
file back.  Every untouched line in that file is round-tripped through the
writer, so the read and the write together form a byte-preservation contract
with three independent properties.  Each was added REACTIVELY, after its own
incident:

1. ``encoding="utf-8-sig"`` on the READ.  A Notepad BOM otherwise hides the
   first key behind U+FEFF, the key match misses, and the writer appends a
   DUPLICATE of the line it meant to update.
2. ``errors="surrogateescape"`` on BOTH the read and the write.  One
   undecodable byte anywhere in the file -- a Windows editor that saved
   cp1252 -- otherwise raises UnicodeDecodeError before ANY key is written,
   out of the middle of a setup wizard.  ``errors="replace"`` does not raise
   but is not the contract either: it turns that byte into U+FFFD and writes
   the replacement back, so updating one credential silently corrupts an
   UNRELATED value.  Only surrogateescape round-trips the byte.
3. ``newline="\\n"`` on the WRITE.  Text mode otherwise rewrites every LF as
   CRLF on Windows, touching every line the call never updated and leaving a
   ``\\r`` in every value for a POSIX shell or Docker bind-mount that sources
   the same file.

The three landed separately -- OpenViking carried surrogateescape from
upstream 38175b8c22, newline="\\n" reached all writers in 97a6161495 (merge
356ece8c45, 2026-09-18), and Hindsight/Mem0 only got surrogateescape in
dc0901a275 (merge 82ea8bfc33, 2026-09-19).  For one day the Hindsight and Mem0
writers carried TWO of the three.  Nothing detected that; a human reading the
diff did.  This script is that detector.

Its first run over the trunk (2026-09-20) found three writers no memory and no
review had ever named, each missing ALL THREE properties, two of them writing
the canonical ``~/.hermes/.env``: ``control_center/apply.py``
(``_apply_threshold_adjust``), ``optional-skills/productivity/telephony/
scripts/telephony.py`` (``_upsert_env_file``) and ``scripts/
hermes_telegram_setup.py`` (``main``) -- plus ``hermes_cli/config.py``'s split
writer reading with ``errors="replace"``.  That is the argument for
DISCOVERING writers instead of listing them: a hand-maintained list rots in
exactly the way the memory it replaces did, and this one would have been born
already missing four entries.

WHAT COUNTS AS A WRITER
-----------------------
Every tracked ``.py`` outside ``tests/`` is parsed, never imported.  A
candidate site is:

* a read -- ``<t>.read_text(...)`` or ``open(<t>, ...)`` in a read mode;
* a write -- ``<t>.write_text(...)``, ``open(<t>, "w"/"a"/...)`` or
  ``os.fdopen(<fd>, "w", ...)``.

A site is about ``.env`` when its TARGET is env-ish -- the spelling's
underscore-separated tokens contain ``env``/``dotenv`` (``env_path``,
``env_file``, ``HERMES_ENV``, ``self._env_path``) -- or when the target name
is bound, in the same function or at MODULE SCOPE, to an expression naming a
``.env`` FILE: a string literal containing ``.env`` (control_center's
``HERMES_ENV = HERMES / ".env"``) or a path-like env name
(telephony's ``path = env_path or _env_path()``).  "Path-like" is what keeps
an environment MAPPING from reading as an environment FILE: ``config =
Path(env["HERMES_HOME"]) / "config.yaml"`` binds through a dict named ``env``
and is not a ``.env`` writer.  Module bindings are module-SCOPE only, never a
full-tree walk -- ``destination = self.target_root / ".env"`` inside one
method of openclaw_to_hermes.py otherwise leaks onto the ``destination``
parameter of every other method in the file, which is exactly the false
positive that produced this rule.

The unit checked is the READ-MODIFY-WRITE, so a function qualifies when it
holds both an env read and an env write, or when the same target spelling
reaches both across a call boundary -- a SPLIT writer.  All three split shapes
occur in ``hermes_cli/config.py``: helper+helper (``save_env_value`` calls
``_read_env_lines(env_path)`` and ``_write_env_lines(env_path, ...)``), own
read + helper write (``sanitize_env_file`` opens ``env_path`` inline and writes
it back through ``_write_env_lines``), and the mirror image.  Requiring the
SAME spelling is what keeps the pairing honest: ``plugins/memory/mem0/
_setup.py`` calls both ``_prompt_api_key(label, env_var, hermes_home)`` and
``_write_env(env_path, ...)`` from one wizard, and those share no target, so
the prompt's read stays unpaired.

Then, in a writer:

* every env WRITE site must pass ``encoding="utf-8"``,
  ``errors="surrogateescape"`` and ``newline="\\n"``;
* every env READ site must pass ``encoding="utf-8-sig"`` and
  ``errors="surrogateescape"``.

Deliberately NOT reported (all counted under ``--verbose``, so each carve-out
stays visible rather than silent):

* an UNPAIRED READ -- a read-only pre-check that never writes the file back:
  ``hermes_cli/profile_cmd.py``'s ``_env_file_has_key``, mem0's
  ``_prompt_api_key``, telephony's ``_read_env_file``.  Those already swallow
  or tolerate a decode failure and are out of this contract's scope: nothing
  they read is written back, so nothing they read can be corrupted;
* an UNPAIRED WRITE -- a create or full overwrite with no read of the file,
  whose content the caller generated whole: ``hermes_cli/profiles.py``'s
  ``backfill_profile_envs`` seeding a placeholder into a profile that has
  none, ``plugins/memory/hindsight/embedded.py``'s
  ``_secure_write_profile_env`` writing an O_TRUNC'd file.  There are no
  pre-existing bytes to preserve, so the round-trip contract does not apply;
* a site carrying the inline ``noqa: env-writer-contract`` marker, on the call
  or in the four comment lines above it (same shape as
  ``scripts/check_subprocess_stdin.py``).  The marker travels with the line,
  so it survives edits that shift numbers.

DISCOVERY ROT IS ITSELF CHECKED
-------------------------------
Discovery is the load-bearing part, and a discovery rule that quietly stops
matching fails OPEN -- the scan goes green because it found nothing.  So
``KNOWN_WRITERS`` below pins the writers that must still be found.  It is not
the enforcement (the scan checks whatever it discovers, listed or not); it is
a tripwire ON the enforcement.  Rename ``env_path`` to ``target`` in one of
these and the scan fails naming the writer it lost, instead of passing.

COST
----
``git grep`` narrows the tree to the files that could hold a site, then each
is parsed once.  About 35 s over ~480 files on this host.  Reading all 6800
tracked files in Python first cost 68 s before the scan did any work, and a
first cut that also built a binding table for every function in the repo took
over five minutes -- which would have got it disabled rather than fixed the
first time it slowed a suite down.

Exit codes:
  0 -- every discovered .env writer carries all three properties
  1 -- violations found, or a pinned writer was no longer discovered
  2 -- script error

Usage:
  python scripts/check_env_writer_contract.py                 # all tracked .py
  python scripts/check_env_writer_contract.py path/to/x.py    # just these
  python scripts/check_env_writer_contract.py --verbose       # + what was skipped
  python scripts/check_env_writer_contract.py --list          # writers, no verdict
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The contract, as (keyword, required value) pairs.  Split by side because the
# read tolerates a BOM (``utf-8-sig``) and the write must not emit one.
READ_CONTRACT = (("encoding", "utf-8-sig"), ("errors", "surrogateescape"))
WRITE_CONTRACT = (("encoding", "utf-8"), ("errors", "surrogateescape"), ("newline", "\n"))

# Why each property is there -- printed with the violation, so the failure
# explains itself without a trip through this docstring.
REASONS = {
    ("read", "encoding"): "a Notepad BOM hides the first key and the writer duplicates that line",
    ("read", "errors"): ("a cp1252 byte must round-trip: bare utf-8 raises UnicodeDecodeError "
                        "before any key is written, and 'replace' writes U+FFFD over it"),
    ("write", "encoding"): "the write must not re-emit a BOM",
    ("write", "errors"): "an undecodable byte on an unrelated line must round-trip, not become U+FFFD",
    ("write", "newline"): "text mode rewrites every untouched LF as CRLF on Windows",
}

# Tripwire on discovery, NOT the enforcement -- see "DISCOVERY ROT" above.
# "<posix path>::<function>" for each writer the scan must still find.
KNOWN_WRITERS = {
    "plugins/memory/openviking/__init__.py::_write_env_vars",
    "plugins/memory/hindsight/setup.py::_write_env",
    "plugins/memory/mem0/_setup.py::_write_env",
    "hermes_cli/config.py::_write_env_lines",
    "control_center/apply.py::_apply_threshold_adjust",
    "optional-skills/productivity/telephony/scripts/telephony.py::_upsert_env_file",
    "scripts/hermes_telegram_setup.py::main",
}

EXEMPT_MARKER = "noqa: env-writer-contract"

_ENV_TOKENS = {"env", "dotenv"}
# An env-ish name is only evidence that a BINDING names a .env FILE when it
# also looks like a path.  Without this, the mapping in ``Path(env["HOME"]) /
# "config.yaml"`` makes every such target read as a .env writer.
_PATHY_TOKENS = {"path", "file", "dir", "root", "dotenv"}
_READ_METHODS = {"read_text"}
_WRITE_METHODS = {"write_text"}

# The test tree is out of scope: these are the writers that touch a REAL user
# .env.  Fixtures legitimately write throwaway .env files with whatever
# encoding the test is pinning -- including, deliberately, a wrong one.
SKIP_PREFIXES = ("tests/",)

# Cheap pre-filter, derived from what discovery actually REQUIRES: a site is
# only ever found through an env-ish identifier or a literal mentioning
# ``.env``.  A file with neither cannot produce one.  ``os.environ`` alone
# does not match (no ``_`` boundary, no ``.env``), which is what keeps this
# from degenerating into "parse the whole repo".
_CALL_NEEDLES = ("read_text", "write_text", "open(", "fdopen")
_ENV_NEEDLE = r"\.env|_env|env_|dotenv"
_ENV_NEEDLE_RE = re.compile(_ENV_NEEDLE, re.IGNORECASE)


def _tokens(spelling: str) -> set[str]:
    """Underscore-separated, lowercased tokens of the LAST component of a dotted
    spelling: ``self._env_path`` -> {'env', 'path'}."""
    return {t for t in spelling.rsplit(".", 1)[-1].lower().split("_") if t}


def _is_env_name(spelling: str) -> bool:
    return bool(_tokens(spelling) & _ENV_TOKENS)


def _is_env_file_name(spelling: str) -> bool:
    """env-ish AND path-like: ``env_path``, ``_env_path``, ``dotenv_file``."""
    tok = _tokens(spelling)
    return bool(tok & _ENV_TOKENS) and bool(tok & _PATHY_TOKENS)


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - total for parsed trees
        return ""


def _node_names_env_file(node: ast.AST) -> bool:
    """True when a bound expression names a ``.env`` FILE -- the literal
    ``".env"``, or a path-like env name/call."""
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and ".env" in n.value:
            return True
        if isinstance(n, ast.Name) and _is_env_file_name(n.id):
            return True
        if isinstance(n, ast.Attribute) and _is_env_file_name(n.attr):
            return True
    return False


class _Binding:
    """Names bound in a scope -> the AST nodes they were bound to.

    Nodes, not source text: unparsing every assignment in the repo and
    re-parsing it per lookup is what made the first cut too slow to finish.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, list[ast.AST]] = {}
        self._memo: dict[str, bool] = {}

    def add(self, name: str, node: ast.AST) -> None:
        self.nodes.setdefault(name, []).append(node)

    def names_env_file(self, name: str) -> bool:
        if name not in self._memo:
            self._memo[name] = any(_node_names_env_file(n) for n in self.nodes.get(name, ()))
        return self._memo[name]

    def has_env_name(self) -> bool:
        return any(_is_env_name(name) for name in self.nodes)


def _assignments(stmts: list[ast.stmt], binding: _Binding, *, descend_functions: bool) -> None:
    """Record ``x = <expr>`` bindings.  At module scope this walks ``if``/``try``/
    ``with``/``for`` bodies but NOT function or class bodies: a local binding in
    one method must not leak onto a same-named parameter of another."""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not descend_functions:
                continue
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    binding.add(t.id, stmt.value)
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list):
                _assignments(inner, binding, descend_functions=descend_functions)
        for handler in getattr(stmt, "handlers", []) or []:
            _assignments(handler.body, binding, descend_functions=descend_functions)


def module_bindings(tree: ast.Module) -> _Binding:
    binding = _Binding()
    _assignments(tree.body, binding, descend_functions=False)
    return binding


def function_bindings(fn: ast.AST) -> _Binding:
    binding = _Binding()
    a = fn.args
    for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
        binding.add(arg.arg, ast.Name(id=arg.arg))
    _assignments(fn.body, binding, descend_functions=True)
    return binding


def _string_kwarg(call: ast.Call, name: str) -> tuple[bool, str | None]:
    """(present, literal value) for keyword ``name``; value None when non-literal."""
    for kw in call.keywords:
        if kw.arg == name:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return True, kw.value.value
            return True, None
    return False, None


def _open_mode(call: ast.Call) -> str:
    """Mode string of an ``open``/``os.fdopen`` call; "r" when omitted."""
    present, value = _string_kwarg(call, "mode")
    if present:
        return value or ""
    if len(call.args) > 1:
        arg = call.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return ""
    return "r"


class Site:
    """One env read or write call site."""

    def __init__(self, *, kind: str, call: ast.Call, target: str, path: str, func: str) -> None:
        self.kind = kind  # "read" | "write"
        self.call = call
        self.target = target
        self.path = path
        self.func = func
        self.lineno = call.lineno
        self.skip_reason = ""

    def violations(self) -> list[tuple[str, str | None, str]]:
        """(keyword, actual, required) for each property this site fails."""
        contract = READ_CONTRACT if self.kind == "read" else WRITE_CONTRACT
        out = []
        for keyword, required in contract:
            present, value = _string_kwarg(self.call, keyword)
            if not present or value != required:
                out.append((keyword, value if present else None, required))
        return out


def _candidate_calls(tree: ast.Module) -> list[tuple[ast.AST | None, ast.Call]]:
    """(enclosing function or None, call) for every call that COULD be a site.

    One traversal, tracking the nearest enclosing function; nothing else in the
    module is touched until a candidate turns up.
    """
    found: list[tuple[ast.AST | None, ast.Call]] = []

    def walk(node: ast.AST, fn: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Attribute) and f.attr in _READ_METHODS | _WRITE_METHODS:
                    found.append((fn, child))
                elif isinstance(f, ast.Name) and f.id == "open":
                    found.append((fn, child))
                elif isinstance(f, ast.Attribute) and f.attr == "fdopen":
                    found.append((fn, child))
            walk(child, inner)

    walk(tree, None)
    return found


def _sites_for_function(
    fn: ast.AST | None, calls: list[ast.Call], module_binding: _Binding, path: str
) -> list[Site]:
    local = function_bindings(fn) if fn is not None else module_binding
    func_name = getattr(fn, "name", "<module>")
    # ``_write_env_lines`` writes through a mkstemp fd whose spelling says
    # nothing about .env; the FUNCTION is what identifies the target there.
    func_env = bool(fn is not None and _is_env_name(func_name) and local.has_env_name())

    def env_target(node: ast.AST) -> str | None:
        spelling = _unparse(node)
        if not spelling:
            return None
        if _is_env_name(spelling):
            return spelling
        base = spelling.split(".")[0].split("[")[0].split("(")[0]
        if local.names_env_file(base) or module_binding.names_env_file(base):
            return spelling
        return None

    sites: list[Site] = []
    for call in calls:
        f = call.func
        kind: str | None = None
        target: str | None = None

        if isinstance(f, ast.Attribute) and f.attr in _READ_METHODS | _WRITE_METHODS:
            target = env_target(f.value)
            if target is None:
                continue
            kind = "read" if f.attr in _READ_METHODS else "write"
        else:
            if not call.args:
                continue
            is_fdopen = isinstance(f, ast.Attribute)
            target = env_target(call.args[0])
            if target is None:
                if not (func_env and is_fdopen):
                    continue
                target = _unparse(call.args[0])
            kind = "write" if any(c in _open_mode(call) for c in "wax+") else "read"

        if kind is None or target is None:
            continue
        sites.append(Site(kind=kind, call=call, target=target, path=path, func=func_name))
    return sites


def _split_writer_halves(tree: ast.Module, per_func: dict[str, list[Site]]) -> set[str]:
    """Function names that take part in a SPLIT read-modify-write.

    A function composes one read-modify-write out of two when the same target
    spelling reaches both a read and a write across a call boundary.  Three
    shapes count, and all three occur in ``hermes_cli/config.py``:

    * helper + helper -- ``save_env_value`` calls ``_read_env_lines(env_path)``
      and ``_write_env_lines(env_path, ...)``; both halves are writers;
    * own read + helper write -- ``sanitize_env_file`` opens ``env_path``
      INLINE and writes it back through ``_write_env_lines(env_path, ...)``;
    * own write + helper read, the mirror image.

    Only the first shape was matched at first, so ``sanitize_env_file``'s read
    was classed an unpaired pre-check and its ``errors="replace"`` went
    unreported -- the scan going GREEN on a site it exists to catch.

    Requiring the SAME spelling is what keeps this honest: ``plugins/memory/
    mem0/_setup.py`` calls both ``_prompt_api_key(label, env_var,
    hermes_home)`` and ``_write_env(env_path, ...)`` from one wizard, and those
    share no target, so the prompt's read stays unpaired.
    """
    readers = {n for n, s in per_func.items() if any(x.kind == "read" for x in s)}
    writers = {n for n, s in per_func.items() if any(x.kind == "write" for x in s)}
    if not (readers or writers):
        return set()

    def own_targets(name: str, kind: str) -> set[str]:
        return {s.target for s in per_func.get(name, ()) if s.kind == kind}

    paired: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        read_args: dict[str, set[str]] = {}
        write_args: dict[str, set[str]] = {}
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args):
                continue
            name = node.func.id
            if name not in readers and name not in writers:
                continue
            first = _unparse(node.args[0])
            if name in readers:
                read_args.setdefault(first, set()).add(name)
            if name in writers:
                write_args.setdefault(first, set()).add(name)

        # The caller's own sites take part too, on the same target.
        mine_read = own_targets(fn.name, "read")
        mine_write = own_targets(fn.name, "write")

        for arg, names in read_args.items():
            if arg in write_args:
                paired |= names | write_args[arg]
            if arg in mine_write:
                paired |= names | {fn.name}
        for arg, names in write_args.items():
            if arg in mine_read:
                paired |= names | {fn.name}
    return paired


def _exempt(site: Site, lines: list[str]) -> bool:
    end = site.call.end_lineno or site.call.lineno
    call_text = "\n".join(lines[site.call.lineno - 1 : end])
    above = "\n".join(lines[max(0, site.call.lineno - 5) : site.call.lineno - 1])
    return EXEMPT_MARKER in call_text or EXEMPT_MARKER in above


def scan_source(source: str, path: str) -> tuple[list[Site], list[Site]]:
    """(checked sites, skipped sites) for one module's source."""
    if not any(needle in source for needle in _CALL_NEEDLES):
        return [], []
    if not _ENV_NEEDLE_RE.search(source):
        return [], []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []

    candidates = _candidate_calls(tree)
    if not candidates:
        return [], []

    by_func: dict[ast.AST | None, list[ast.Call]] = {}
    for fn, call in candidates:
        by_func.setdefault(fn, []).append(call)

    module_binding = module_bindings(tree)
    per_func: dict[str, list[Site]] = {}
    for fn, calls in by_func.items():
        found = _sites_for_function(fn, calls, module_binding, path)
        if found:
            per_func.setdefault(getattr(fn, "name", "<module>"), []).extend(found)
    if not per_func:
        return [], []

    paired = _split_writer_halves(tree, per_func)
    lines = source.split("\n")

    checked: list[Site] = []
    skipped: list[Site] = []
    for name, sites in per_func.items():
        reads_here = any(s.kind == "read" for s in sites)
        writes_here = any(s.kind == "write" for s in sites)
        # The unit is the read-modify-write: both halves here, or one half of
        # a split pair.  Anything else is a pre-check read or a whole-file
        # create, neither of which round-trips pre-existing bytes.
        is_rmw = (reads_here and writes_here) or name in paired
        for site in sites:
            if not is_rmw:
                site.skip_reason = (
                    "read-only pre-check" if site.kind == "read" else "create-only write"
                )
                skipped.append(site)
            elif _exempt(site, lines):
                site.skip_reason = "noqa marker"
                skipped.append(site)
            else:
                checked.append(site)
    return checked, skipped


def candidate_files() -> list[Path]:
    """Tracked ``.py`` that could hold a site, per ``_ENV_NEEDLE``.

    ``git grep`` does the narrowing because reading all 6800 tracked files in
    Python cost 68 s on this host before the scan did any work at all.  The
    grep is an optimisation, never a second opinion: it uses the same pattern
    ``scan_source`` short-circuits on.
    """
    out = subprocess.run(
        ["git", "grep", "-l", "-z", "-I", "-E", "-i", _ENV_NEEDLE, "--", "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    return [
        REPO_ROOT / rel
        for rel in out.split("\0")
        if rel and not rel.startswith(SKIP_PREFIXES)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the .env read-modify-write encoding contract.")
    parser.add_argument("paths", nargs="*", help="files to scan (default: all tracked .py)")
    parser.add_argument("--verbose", action="store_true",
                        help="also report sites skipped as out of scope")
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="list discovered writers, no verdict")
    args = parser.parse_args(argv)

    scoped = bool(args.paths)
    files = [Path(p).resolve() for p in args.paths] if scoped else candidate_files()

    violations: list[tuple[Site, list[tuple[str, str | None, str]]]] = []
    skipped_all: list[Site] = []
    discovered: set[str] = set()

    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)
        checked, skipped = scan_source(source, rel)
        skipped_all.extend(skipped)
        for site in checked:
            if site.kind == "write":
                discovered.add(f"{rel}::{site.func}")
            bad = site.violations()
            if bad:
                violations.append((site, bad))

    if args.list_only:
        for name in sorted(discovered):
            print(name)
        return 0

    exit_code = 0

    if violations:
        exit_code = 1
        print(f"FAIL: {len(violations)} .env read-modify-write site(s) break the encoding contract:\n")
        for site, bad in sorted(violations, key=lambda v: (v[0].path, v[0].lineno)):
            print(f"  {site.path}:{site.lineno}  {site.func}()  [{site.kind} of {site.target}]")
            for keyword, actual, required in bad:
                actual_text = "missing" if actual is None else repr(actual)
                print(f"      {keyword}={actual_text}, must be {required!r}"
                      f"  -- {REASONS[(site.kind, keyword)]}")
            print()

    # Discovery tripwire: only meaningful on a full scan.
    if not scoped:
        lost = KNOWN_WRITERS - discovered
        if lost:
            exit_code = 1
            print("FAIL: discovery rot -- pinned .env writer(s) are no longer being found:\n")
            for name in sorted(lost):
                print(f"  {name}")
            print("\n  Either the writer moved or was removed (update KNOWN_WRITERS), or the\n"
                  "  discovery rule stopped matching it and this scan is now failing OPEN.\n")

    if args.verbose:
        print(f"\n-- {len(skipped_all)} site(s) skipped as out of scope:")
        for site in sorted(skipped_all, key=lambda s: (s.path, s.lineno)):
            print(f"   {site.path}:{site.lineno}  {site.func}()  "
                  f"{site.kind} of {site.target}  [{site.skip_reason}]")

    if exit_code == 0:
        print(f"OK: {len(discovered)} .env writer(s) carry utf-8-sig + surrogateescape + newline=LF")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
