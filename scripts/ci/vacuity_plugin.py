"""pytest plugin: PROVE that a candidate presence assertion cannot fail.

Companion to ``scripts/check_testname_substring_assertions.py``.  That scanner
is static and reports CANDIDATES; this plugin supplies the one fact static
analysis cannot reach, and together they form a proof rather than a heuristic.

THE PROOF.  An ``assert LIT in HAYSTACK`` inside ``def test_*`` is
unfalsifiable-by-name when all three hold:

  (0) ``in`` means SUBSTRING -- i.e. HAYSTACK is a ``str`` at runtime
      -- decided here, by recovering the operand's real value.
  (1) ``LIT`` is a substring of the test's ``tmp_path`` basename
      -- decided statically by the scanner (it models pytest's own
      non-word-to-underscore sanitisation and 30-character cut).
  (2) the basename is a substring of that HAYSTACK VALUE at runtime
      -- decided here, against the operand alone, never the whole explanation.

Given (0), conditions (1) and (2) compose by transitivity of substring into
``LIT in HAYSTACK`` for every possible value of the production code under test.
The assertion is then green no matter what production does: it pins the PATH,
not the reason.

WHY ALL THREE, each measured rather than reasoned about.  Dropping (0) is what
this plugin shipped with, and the first full ``--all`` run then reported TWO
findings, BOTH false positives -- one a dict membership, one a path that lived
only in pytest's ``+ where`` provenance; see ``haystack_value``, which is what
rejects each.  Dropping (1) makes the check useless rather than merely wider:
measured on
``tests/hermes_cli/test_certifi_repair.py::test_broken_bundle_fails_without_fix``,
condition (2) alone flags ``any("doctor --fix" in i for i in issues)`` -- the
haystack does carry the path, but ``doctor --fix`` is nowhere in the test's
name, so the assertion is perfectly load-bearing.  Dropping (2) is the 85%
false-positive rate that makes a purely static gate unusable here: of the 99
sites at the strictest static width, only 15 were real.

WHAT THIS CANNOT SEE, stated so a green is not read as more than it is.  Only
assertions that actually EXECUTE can be proven either way.  A candidate whose
test is skipped, errors before reaching the line, or whose assertion sits on an
unexecuted branch is reported UNPROVEN, never silently clean --
``check_testname_assertion_vacuity.py`` prints those separately.  ``match=``
candidates (``pytest.raises``/``warns``) are out of scope here: they raise
rather than assert, so no ``pytest_assertion_pass`` fires for them.

The hook this relies on is off by default and costs nothing in a normal run;
the driver turns it on with ``-o enable_assertion_pass_hook=true``.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

#: Env var naming the scanner's ``--json`` candidate file (input).
CANDIDATES_ENV = "VACUITY_CANDIDATES"
#: Env var naming the file this plugin writes its verdicts to (output).
RESULTS_ENV = "VACUITY_RESULTS"

# Mirrors ``_pytest.tmpdir``: every non-word character becomes ``_`` and the
# result is cut to 30 characters before the numeric suffix is appended.  Kept
# here (rather than imported from the scanner) so the plugin stays a single
# file pytest can load with ``-p``; the scanner's own test pins the model and
# tests/scripts/test_check_testname_assertion_vacuity.py pins that the two
# agree.
_MAXVAL = 30


def tmp_path_basename(func_name: str) -> str:
    """Reproduce pytest's ``tmp_path`` directory name for a test function."""
    return re.sub(r"[\W]", "_", func_name)[:_MAXVAL]


def haystack_value(expl: str, literal: str) -> str | None:
    """The right operand of ``in``, as its actual runtime STRING, or None.

    Returns None when the operand is not a ``str`` -- and that distinction is
    load-bearing twice over, because BOTH of the first ``--all`` run's findings
    were false positives that this function is what rejects.

    1. THE OPERAND MUST BE A STRING.  The transitivity proof holds only for
       SUBSTRING containment; for a dict, list, set or tuple, ``in`` is ELEMENT
       membership, and a path sitting in some VALUE says nothing about whether
       the asserted KEY can be absent.  ``tests/gateway/test_weixin.py:897``
       asserts ``"event" in captured`` where ``captured = {}`` is a dict the
       test fills with ``captured["event"] = event``; the event's repr embeds a
       cached-audio path under ``tmp_path``, so the basename really is in the
       explanation -- but the assertion tests a KEY.  The 2026-09-14 audit
       rejected that exact site by hand for exactly this reason.

    2. ONLY THE OPERAND COUNTS -- NOT THE WHOLE EXPLANATION.  pytest appends
       ``+ where`` provenance lines that repr the intermediate objects, and
       those reprs routinely embed paths the haystack itself never contained.
       ``tests/hermes_cli/test_plugin_scanner_recursion.py:217`` asserts
       ``"exclusive" in (loaded.error or "")``; the haystack is the plain
       message ``'exclusive plugin -- activate via <category>.provider
       config'``, which carries NO path, while the ``+ where`` line reprs a
       LoadedPlugin whose ``path=`` field is under ``tmp_path``.  Searching the
       explanation wholesale calls that vacuous; searching the operand does
       not.  Same shape as the qualname false positive that motivated
       _preceded_by_separator -- provenance is not the haystack.

    Parsed with ``ast.literal_eval`` rather than by inspecting the first
    character, because pytest wraps a parenthesised source expression in its
    own parentheses: the site above renders as ``(('...'))``.  A quote test
    reads that as a non-string and silently loses a real finding, while naive
    paren-stripping turns the tuple ``('a', 'b')`` into something that starts
    with a quote.  literal_eval settles both exactly.

    None on anything unparseable.  A gate must never claim a proof it could not
    check.
    """
    first = expl.split("\n", 1)[0]
    marker = " in "
    lhs = repr(literal)
    idx = first.find(lhs + marker)
    if idx == -1:
        return None
    rhs = first[idx + len(lhs) + len(marker):].strip()
    try:
        value = ast.literal_eval(rhs)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, str) else None


def _preceded_by_separator(haystack: str, basename: str) -> bool:
    """Is ``basename`` present in ``haystack`` as a PATH COMPONENT?

    Requires the occurrence to be immediately preceded by ``/`` or ``\\``, so a
    directory segment counts and prose quoting the test's name does not.  Works
    on a recovered operand VALUE (single backslashes) and equally on a raw
    explanation (repr-escaped, doubled) -- the character immediately before the
    segment is a backslash either way, so no unescaping is needed.
    """
    if not basename:
        return False
    start = 0
    while True:
        i = haystack.find(basename, start)
        if i == -1:
            return False
        if i > 0 and haystack[i - 1] in "\\/":
            return True
        start = i + 1


class VacuityPlugin:
    def __init__(self, candidates: list[dict], results_path: Path | None) -> None:
        # Index by (absolute file, line) -- the scanner reports the line of the
        # comparison, which is the line pytest_assertion_pass reports too.
        self._by_site: dict[tuple[str, int], dict] = {}
        for c in candidates:
            if c.get("kind") != "assert-in":
                continue  # match= never reaches pytest_assertion_pass
            key = (self._norm(c["file"]), int(c["line"]))
            self._by_site[key] = c
        self._results_path = results_path
        #: sites proven unfalsifiable
        self.proven: list[dict] = []
        #: sites whose assertion executed and did NOT leak
        self.cleared: set[tuple[str, int]] = set()

    @staticmethod
    def _norm(path: str) -> str:
        return str(Path(path)).replace("\\", "/").lower()

    # -- the hook --------------------------------------------------------
    def pytest_assertion_pass(self, item, lineno: int, orig: str, expl: str) -> None:
        key = (self._norm(str(item.fspath)), int(lineno))
        candidate = self._by_site.get(key)
        if candidate is None:
            return

        # Derive the basename from ``item.name``, not from the scanner's
        # ``func``: a parametrised test's directory is named after the full
        # node name ("test_x[a-b]" -> "test_x_a_b_"), so the function name is
        # the wrong string to look for once parameters are involved.  The
        # scanner reasons about ``func`` for SELECTION, which is fine because
        # it only needs to be a superset.
        basename = tmp_path_basename(item.name)
        if not basename:
            return

        # CASE IS PART OF THE PROOF, and the scanner is deliberately looser
        # here than the assertion is.  Its ``literal_in_tmp_path_basename``
        # folds both sides, so it offers ``assert "DIRTY" in out`` as a
        # candidate -- but that assertion compares case-SENSITIVELY against an
        # all-lowercase path segment and is therefore load-bearing.  (The
        # parent audit rejected exactly that site by hand.)  Re-decide both
        # conditions under the assertion's own case semantics: fold only when
        # the source folds the haystack with ``.lower()``/``.casefold()``.
        folded = bool(candidate.get("case_folded"))
        literal = candidate["literal"]
        needle = literal.lower() if folded else literal
        hay_basename = basename.lower() if folded else basename

        # Condition (1), re-decided with case.  Selection was wide on purpose;
        # the proof is narrow.  A candidate rejected here is CLEARED, not
        # silent: the assertion demonstrably ran, so reporting it as "did not
        # execute" would understate what is known about it.
        if needle not in hay_basename:
            self.cleared.add(key)
            return

        # Condition (0), and it gates the other two: ``in`` must mean SUBSTRING,
        # so recover the operand's actual runtime STRING.  This also narrows the
        # search for condition (2) from the whole explanation down to the
        # haystack itself -- see haystack_value for the two real false
        # positives that each of those does on its own.
        haystack = haystack_value(expl, literal)
        if haystack is None:
            self.cleared.add(key)
            return
        hay = haystack.lower() if folded else haystack

        # Condition (2): does the haystack carry the test's tmp_path segment?
        #
        # THE BASENAME MUST BE PRECEDED BY A PATH SEPARATOR.  A bare substring
        # test is unsound even against the operand alone, because a message can
        # quote the test's name as prose.  A real leak always arrives as a path
        # component -- ``...\\pytest-13361\\test_broken_bundle_fails_witho0\\
        # missing.pem`` -- and the separator is what tells the two apart.
        if _preceded_by_separator(hay, hay_basename):
            self.proven.append(
                {
                    "file": candidate["file"],
                    "line": lineno,
                    "nodeid": item.nodeid,
                    "func": candidate["func"],
                    "literal": candidate["literal"],
                    "tmp_path_basename": basename,
                    "source": candidate.get("source", ""),
                }
            )
        else:
            self.cleared.add(key)

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        if self._results_path is None:
            return
        payload = {
            "proven": self.proven,
            "cleared": [{"file": f, "line": ln} for f, ln in sorted(self.cleared)],
        }
        self._results_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def pytest_configure(config) -> None:
    cand_file = os.environ.get(CANDIDATES_ENV)
    if not cand_file:
        return
    candidates = json.loads(Path(cand_file).read_text(encoding="utf-8"))
    results = os.environ.get(RESULTS_ENV)
    plugin = VacuityPlugin(candidates, Path(results) if results else None)
    config.pluginmanager.register(plugin, "vacuity-plugin-instance")
