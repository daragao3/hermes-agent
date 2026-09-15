#!/usr/bin/env python3
"""PROVE, by running them, which presence assertions their own test name satisfies.

``scripts/check_testname_substring_assertions.py`` is the STATIC half: it finds
``assert "<lit>" in <expr>`` inside ``def test_*`` where ``<lit>`` is also in the
test's own name, and therefore in its ``tmp_path``.  It reports candidates, and
it is deliberately loose -- measured 2026-09-14 on this tree, 1,595 raw / 592
tmp-path-shaped / 84 at its strictest width, of which the parent audit confirmed
15 real.  **That is an 85% false-positive rate, which is why the scanner is not
itself a gate**: every gating form of it (fail-on-count, or a frozen baseline
allowlist) makes waiving the normal response, and this repo has already measured
the harm that does -- see ``scripts/check-windows-footguns.py``, where
unnecessary ``# windows-footgun ok`` suppressions blind the scanner to real
footguns on that line forever.

This script is the RUNTIME half, and it is a proof rather than a heuristic.  An
assertion is unfalsifiable-by-name exactly when

    (1) the asserted literal is inside the test's ``tmp_path`` basename, and
    (2) that basename is inside the haystack at runtime,

because (1) and (2) give ``literal in haystack`` by transitivity, for every
possible value production code can produce.  (1) is static; (2) is what running
the assertion tells you, via ``pytest_assertion_pass`` (see
``scripts/ci/vacuity_plugin.py``).  Each condition alone is useless: (2) alone
flags ``any("doctor --fix" in i for i in issues)``, whose haystack does carry the
path but whose literal is nowhere in the test's name; (1) alone is the 85%.

So the output is three-valued, and the middle value is the point:

  PROVEN    -- both conditions hold.  The assertion cannot fail.  Exit 1.
  CLEARED   -- the assertion ran and its haystack does not carry the path.
  UNPROVEN  -- the assertion never executed (skipped test, earlier failure, an
               unexecuted branch, or a ``match=`` candidate, which raises rather
               than asserts and so fires no hook).  Reported, never counted as
               clean: a check that is green because it did not run is the exact
               defect this whole family exists to catch.

Usage:
  python scripts/check_testname_assertion_vacuity.py --diff main   # gate shape
  python scripts/check_testname_assertion_vacuity.py tests/foo/test_bar.py
  python scripts/check_testname_assertion_vacuity.py --all         # slow audit

Exit codes:
  0 -- no assertion proven unfalsifiable
  1 -- at least one proven
  2 -- script error
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "scripts" / "check_testname_substring_assertions.py"
PLUGIN = REPO / "scripts" / "ci" / "vacuity_plugin.py"

#: Fixtures whose directory pytest names after the requesting TEST function.
TMP_FIXTURES = frozenset({"tmp_path", "tmpdir", "tmp_path_factory", "tmpdir_factory"})


def _load_scanner():
    spec = importlib.util.spec_from_file_location("_testname_scanner", SCANNER)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load scanner at {SCANNER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _requests_tmp_fixture(path: Path, func: str) -> bool:
    """Does ``func`` in ``path`` take a tmp fixture as a parameter?

    This is a RUN-SELECTION optimisation, not part of the proof: it decides
    which test files are worth paying to execute.  It has one known hole --
    a test can request a project fixture that itself requests ``tmp_path``,
    which still yields a directory named after the test while the test's own
    signature shows nothing.  ``--no-fixture-filter`` turns it off.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return True  # cannot tell -- keep the file rather than skip it silently
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            a = node.args
            names = {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs}
            if names & TMP_FIXTURES:
                return True
    return False


def _changed_test_files(ref: str) -> list[Path]:
    """Test files changed vs ``ref`` (mirrors check-windows-footguns.py --diff)."""
    out = subprocess.run(
        ["git", "diff", f"{ref}...HEAD", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git diff vs {ref!r} failed: {out.stderr.strip()}")
    files = []
    for line in out.stdout.splitlines():
        p = REPO / line.strip()
        if p.suffix == ".py" and p.name.startswith("test_") and p.is_file():
            files.append(p)
    return files


def collect_candidates(scanner, roots: list[Path], fixture_filter: bool) -> list[dict]:
    """Static candidates at the tmp-path-shaped width, optionally fixture-filtered.

    Roots are RESOLVED first.  The plugin matches a candidate to a firing
    assertion by (file, line) against pytest's ``item.fspath``, which is always
    absolute; a relative candidate path silently matches nothing, so every site
    lands in "did not execute" and the driver exits 0 -- a false green of
    exactly the shape this tool exists to detect.  (Measured while building it:
    ``check_testname_assertion_vacuity.py tests/hermes_cli/test_certifi_repair.py``
    reported 2 candidates, 0 cleared, 0 proven, "not executed 2", while the hook
    had in fact fired on both lines.)
    """
    hits: list[dict] = []
    for path in scanner.iter_targets([Path(r).resolve() for r in roots]):
        hits.extend(scanner.sweep_file(path))
    hits = [h for h in hits if h["literal_in_tmp_path_basename"]]
    if fixture_filter:
        hits = [h for h in hits if _requests_tmp_fixture(Path(h["file"]), h["func"])]
    return hits


def _display(path: str) -> str:
    """Repo-relative form of an absolute candidate path, for printing."""
    try:
        return Path(path).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path


def run_prover(candidates: list[dict], extra_args: list[str]) -> dict:
    """Run the candidate files under the plugin and return its verdicts.

    Targets must live inside the repo.  The child runs with ``cwd=REPO`` so the
    repo's own pytest configuration and conftest chain apply -- which is the
    point, since that is how the assertion behaves in a real run -- but that
    combination HANGS when the target path is outside the tree (measured
    2026-09-14: >120s with no output, against 1.6s for the same file when
    pytest is invoked from its own directory).  Refuse instead of hanging.
    """
    files = sorted({str(Path(h["file"])) for h in candidates})
    outside = [f for f in files if REPO not in Path(f).resolve().parents]
    if outside:
        raise RuntimeError(
            "targets must be inside the repo; pytest hangs when run with "
            f"cwd={REPO} against an out-of-tree path. Offending: {outside[0]}"
        )

    # RUN THE CANDIDATE TESTS, NOT THEIR WHOLE FILES.  Passing the files alone
    # makes ``--all`` execute every test they contain: measured 2026-09-15,
    # 3,597 tests to decide 81 candidate functions, a 44x overshoot that put the
    # full audit past ten minutes and made it impractical on a loaded box.
    #
    # ``-k`` rather than constructed ``file::Class::func`` node ids, deliberately.
    # Node ids have to be rebuilt from the scanner's view of the class stack, and
    # that view can disagree with pytest's -- one did, on a nested class, and an
    # unresolvable node id is a pytest USAGE error that aborts the entire run
    # rather than skipping one target.  ``-k`` matches pytest's own collected
    # names, so parametrised cases (``test_x[a-b]``) and nested classes need no
    # special handling, and a name that matches nothing simply selects nothing.
    #
    # Over-selection is harmless and deliberate: ``-k`` is a substring match, so
    # ``test_foo`` also selects ``test_foo_bar``.  Extra tests only cost time --
    # the plugin still reports on candidate SITES only.  Under-selection is the
    # direction that could lie, and it cannot hide: a candidate whose test is
    # deselected never fires the hook, so it lands in UNPROVEN, and a filter that
    # selected nothing at all trips the "observed nothing" guard.
    selector = " or ".join(sorted({h["func"] for h in candidates}))
    # Windows caps a command line near 32k; keep well clear and fall back to
    # whole files rather than truncating the filter, which would silently
    # deselect real candidates.
    k_args = ["-k", selector] if selector and len(selector) < 16000 else []
    with tempfile.TemporaryDirectory() as td:
        cand_path = Path(td) / "candidates.json"
        res_path = Path(td) / "results.json"
        cand_path.write_text(json.dumps(candidates), encoding="utf-8")

        env = dict(os.environ)
        env["VACUITY_CANDIDATES"] = str(cand_path)
        env["VACUITY_RESULTS"] = str(res_path)
        # The plugin lives in scripts/ci/; make it importable.
        env["PYTHONPATH"] = os.pathsep.join(
            [str(PLUGIN.parent), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        # LOAD VIA ENV, NEVER VIA ``-p``.  This repo's conftest pre-parses
        # ``-p``/``--profile`` out of sys.argv as its own PROFILE flag before
        # imports, so ``-p vacuity_plugin`` is read as a request for a profile
        # named "vacuity_plugin" and every test in the file ERRORS at setup
        # inside _apply_profile_override.  Measured 2026-09-14: 8 errors, and
        # the driver reported them as "did not execute" and exited 0.
        env["PYTEST_PLUGINS"] = "vacuity_plugin"
        # ISOLATE THE BYTECODE CACHE.  pytest does NOT invalidate its rewritten
        # .pyc when ``enable_assertion_pass_hook`` changes -- the cache key is
        # the source's mtime and size, and the flag is not part of it.  So a
        # .pyc left by an ORDINARY pytest run is reused here, the rewritten
        # module contains no pass-hook calls, and the prover observes nothing
        # while every test passes.  Measured 2026-09-14: with a plain run of the
        # same file immediately before, the child finished in 0.75s with
        # "3 passed" and zero verdicts; alone it took ~9s and proved the defect.
        # Redirecting the cache to a fresh directory forces a real rewrite every
        # time and leaves no .pyc behind to poison the next ordinary run.
        env["PYTHONPYCACHEPREFIX"] = str(Path(td) / "pycache")

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *files,
            # Off by default and free when off; the driver is the only caller
            # that pays for it.  Toggling it does NOT invalidate pytest's
            # rewritten bytecode -- see PYTHONPYCACHEPREFIX above, which is what
            # makes this flag actually take effect.
            "-o",
            "enable_assertion_pass_hook=true",
            # ``-vv`` IS LOAD-BEARING, not noise.  pytest renders assertion
            # operands through ``saferepr``, which at default verbosity elides
            # the middle of anything long; a refusal message that embeds a path
            # is routinely over that limit, so the leaked directory segment is
            # exactly what gets cut and the prover reports a clean run.
            # Measured 2026-09-14 on the real historical defect
            # ``test_certifi_repair.py:139``: the leak is INVISIBLE at default
            # verbosity and VISIBLE under ``-vv``.  Dropping this flag turns the
            # gate green by truncation.
            "-vv",
            *k_args,
            *extra_args,
        ]
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if not res_path.exists():
            raise RuntimeError(
                "prover produced no results file; pytest said:\n"
                f"{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
            )
        data = json.loads(res_path.read_text(encoding="utf-8"))
        data["pytest_returncode"] = proc.returncode
        data["pytest_tail"] = proc.stdout[-2000:]
        return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Prove which presence assertions their own test name satisfies."
    )
    ap.add_argument("roots", nargs="*", help="test files or directories")
    ap.add_argument("--diff", metavar="REF", help="only test files changed vs REF")
    ap.add_argument("--all", action="store_true", help="scan the default roots (slow)")
    ap.add_argument(
        "--no-fixture-filter",
        action="store_true",
        help="do not require the test to take a tmp fixture (wider, slower)",
    )
    ap.add_argument("--json", action="store_true", help="emit verdicts as JSON")
    args = ap.parse_args(argv)

    try:
        scanner = _load_scanner()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.diff:
            roots = _changed_test_files(args.diff)
            if not roots:
                print("✅ no test files changed vs "
                      f"{args.diff} — nothing to prove")
                return 0
        elif args.roots:
            roots = [Path(r) for r in args.roots]
        elif args.all:
            roots = scanner.default_roots(REPO)
        else:
            ap.error("give paths, or --diff REF, or --all")
            return 2  # pragma: no cover - argparse exits
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        candidates = collect_candidates(scanner, roots, not args.no_fixture_filter)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not candidates:
        print("✅ no tmp-path-shaped candidate assertions in scope")
        return 0

    try:
        verdicts = run_prover(candidates, [])
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # A child run that did not really run is not a clean result.  pytest exits
    # 0 ok / 1 tests failed / 2 interrupted / 3 internal / 4 usage / 5 nothing
    # collected.  Only 0 and 1 mean the prover got to observe assertions; a
    # failed TEST is fine (its candidates land in UNPROVEN), but a usage or
    # collection failure must not read as "no leaks found".
    rc = verdicts.get("pytest_returncode")
    if rc not in (0, 1):
        print(
            f"error: the prover's pytest run exited {rc}, so nothing was "
            f"observed. Tail:\n{verdicts.get('pytest_tail', '')}",
            file=sys.stderr,
        )
        return 2

    proven = verdicts["proven"]
    cleared = {(c["file"], c["line"]) for c in verdicts["cleared"]}

    # OBSERVING NOTHING IS NOT A CLEAN RESULT.  If not one candidate produced a
    # verdict, the hook did not reach any of them -- a path-normalisation slip,
    # assertion rewriting disabled, the plugin not loaded -- and every site
    # lands in "did not execute" while the run exits 0.  That is this tool's own
    # version of the defect it hunts, and it has already happened twice during
    # development (relative candidate paths; a fixture file pytest declined to
    # rewrite).  Fail loudly and hand over the child's output.
    if candidates and not proven and not cleared:
        print(
            f"error: {len(candidates)} candidate(s) in scope but the prover "
            "observed NONE of them, so nothing was checked. The hook did not "
            "reach these assertions.\nChild pytest tail:\n"
            f"{verdicts.get('pytest_tail', '')}",
            file=sys.stderr,
        )
        return 2

    # A candidate the plugin never saw did not execute.  Name them: this is the
    # difference between "checked and clean" and "did not run".
    unproven = [
        h
        for h in candidates
        if h["kind"] == "assert-in"
        and (str(Path(h["file"])).replace("\\", "/").lower(), h["line"]) not in cleared
        and not any(p["file"] == h["file"] and p["line"] == h["line"] for p in proven)
    ]
    match_candidates = [h for h in candidates if h["kind"] == "raises-match"]

    if args.json:
        print(json.dumps(
            {"proven": proven, "unproven": unproven, "match": match_candidates}, indent=2
        ))
        return 1 if proven else 0

    # ``cleared`` is keyed by SITE (file, line) while ``candidates`` counts
    # COMPARISONS -- ``assert "a" in x and "b" in y`` is one line and two
    # candidates -- so the two numbers are not expected to reconcile. Say so
    # rather than printing a tally that looks like it is missing an entry.
    print(f"candidates in scope: {len(candidates)} comparison(s) over "
          f"{len({(h['file'], h['line']) for h in candidates})} site(s)  "
          f"(proven {len(proven)}, cleared {len(cleared)} site(s), "
          f"not executed {len(unproven)}, match= {len(match_candidates)})")

    for h in unproven:
        print(f"  UNPROVEN (did not execute): {_display(h['file'])}:{h['line']}  {h['literal']!r}")
    for h in match_candidates:
        print(f"  UNPROVEN (match= raises, no assert hook): "
              f"{_display(h['file'])}:{h['line']}  {h['literal']!r}")

    if not proven:
        print("\n✅ no assertion in scope was proven satisfiable by its own test name")
        return 0

    for p in proven:
        print(f"\n❌ {_display(p['file'])}:{p['line']}  PROVEN UNFALSIFIABLE")
        print(f"    test    : {p['nodeid']}")
        print(f"    literal : {p['literal']!r} is inside tmp_path "
              f"{p['tmp_path_basename']!r}, which the haystack contains")
        print(f"    source  : {p['source']}")
    print(
        f"\n❌ {len(proven)} assertion(s) cannot fail. Pin a distinctive PHRASE "
        "instead: a sanitised tmp_path cannot contain a space, so any multi-word "
        "production phrase is structurally immune."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
