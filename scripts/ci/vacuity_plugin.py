"""pytest plugin: PROVE that a candidate presence assertion cannot fail.

Companion to ``scripts/check_testname_substring_assertions.py``.  That scanner
is static and reports CANDIDATES; this plugin supplies the one fact static
analysis cannot reach, and together they form a proof rather than a heuristic.

THE PROOF.  An ``assert LIT in HAYSTACK`` inside ``def test_*`` is
unfalsifiable-by-name when both hold:

  (1) ``LIT`` is a substring of the test's ``tmp_path`` basename
      -- decided statically by the scanner (it models pytest's own
      non-word-to-underscore sanitisation and 30-character cut).
  (2) the basename is a substring of the HAYSTACK at runtime
      -- decided here, from the assertion's own explanation.

(1) and (2) together give ``LIT in HAYSTACK`` by transitivity of substring,
for every possible value of the production code under test.  The assertion is
then green no matter what production does: it pins the PATH, not the reason.

WHY BOTH CONDITIONS.  Dropping (1) makes the check useless rather than merely
wider: measured on
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


def _preceded_by_separator(haystack: str, basename: str) -> bool:
    """Is ``basename`` present in ``haystack`` as a PATH COMPONENT?

    Requires the occurrence to be immediately preceded by ``/`` or ``\\``, so
    a directory segment counts and a dotted qualname (``Cls.test_foo.<locals>``)
    does not.  ``haystack`` here is an assertion explanation, in which a Windows
    path's backslashes are repr-escaped -- the character before the segment is
    still a backslash either way, so no unescaping is needed.
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
        hay_basename, hay_expl, needle = (
            (basename.lower(), expl.lower(), literal.lower())
            if folded
            else (basename, expl, literal)
        )

        # Condition (1), re-decided with case.  Selection was wide on purpose;
        # the proof is narrow.  A candidate rejected here is CLEARED, not
        # silent: the assertion demonstrably ran, so reporting it as "did not
        # execute" would understate what is known about it.
        if needle not in hay_basename:
            self.cleared.add(key)
            return

        # Condition (2): ``expl`` is pytest's explanation with the operand
        # VALUES substituted, so the haystack's runtime content is in it.
        #
        # THE BASENAME MUST BE PRECEDED BY A PATH SEPARATOR.  A bare substring
        # test is unsound: ``expl`` also carries pytest's own ``+ where``
        # provenance, and Python object reprs embed the test's QUALNAME.
        # Measured on ``test_broken_bundle_fails_without_fix``, the assertion
        # ``any("doctor --fix" in i for i in issues)`` explains as
        # ``<generator object TestDoctorCertificates.test_broken_bundle_fails_
        # without_fix.<locals>.<genexpr> at 0x...>`` -- the test's own name, in
        # a perfectly load-bearing assertion, with no path anywhere.  A real
        # leak always arrives as a path component: ``...\\pytest-13361\\
        # test_broken_bundle_fails_witho0\\missing.pem``.  The separator is
        # what tells the two apart -- a qualname is preceded by ``.``.
        if _preceded_by_separator(hay_expl, hay_basename):
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
