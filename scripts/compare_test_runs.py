#!/usr/bin/env python3
"""Compare two run_tests_parallel logs and say which failures are REGRESSIONS.

Written 2026-09-14 after a deployment-validation pass on the 0.21.1 upstream merge,
where three separate measurement traps each produced a confidently wrong answer.
Every rule below exists because it already cost real time.

WHY NOT JUST DIFF THE FAILED SETS
---------------------------------
Because "did not appear in the baseline's FAILED list" is not the same as "passed on
the baseline", and the difference is where the wrong answers come from:

TRAP 1 - A FILE THAT DID NOT COLLECT EMITS ZERO ``FAILED`` LINES.
    A baseline file that dies at import/collection reports no failing nodes at all, so
    every node the candidate reports in that file looks brand new. Measured on this
    repo: 8 such files turned 13 real regressions into 47 apparent ones. Those files
    are UNCOMPARABLE, not green, and this tool refuses to classify them either way --
    it lists them separately and tells you to re-run that file on the baseline alone.

TRAP 2 - TWO RUNS CAN LAND IN ONE LOG FILE, AND THE RESULT LOOKS LIKE ONE RUN.
    Stopping a background shell does NOT stop the test subprocesses it spawned; the
    orphan keeps writing. Point a second run at the same log path and the file ends up
    holding two interleaved reports. Measured: one such file carried a live run (206
    files, 2468 passed, 17 failed) and an orphan's dying report (681 passed, 148 files
    under "no tests ran") -- and 140 of those 148 also had a passing progress line from
    the live run. Read naively that is a catastrophic-looking collapse; it is two runs
    in one file. So this tool REFUSES a log that does not contain exactly one discovery
    header and exactly one summary line, rather than analysing it.

TRAP 3 - PARALLELISM FABRICATES FAILURES.
    Under -j 8 on a loaded box, 10 of 28 apparent candidate-only failures passed when
    re-run serially. This tool never calls anything a regression on log evidence alone:
    candidate-only failures come out as SUSPECTED, with the exact serial command to
    confirm them. Confirmation is a separate, deliberate step.

Usage:
    python scripts/compare_test_runs.py BASELINE.log CANDIDATE.log
    python scripts/compare_test_runs.py BASELINE.log CANDIDATE.log --json out.json

Exit status: 0 when nothing is suspected and nothing is uncomparable, else 1. The
non-zero is a prompt to go look, not a verdict -- a SUSPECTED entry is a question.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ``FAILED <nodeid>`` inside the runner's boxed per-file output. The trailing
# " - <message>" is stripped: the same node can carry a different message between
# runs (an assertion repr with a tmp_path in it, say), and set-diffing the raw lines
# then reports every such node as both fixed AND new.
_FAILED = re.compile(r"^[^\w]*FAILED\s+(?P<node>\S+)")
_DISCOVERY = re.compile(r"^Discovered\s+\d+\s+test files")
_SUMMARY = re.compile(r"^=== Summary:")
_NO_TESTS_HDR = re.compile(r"^=== \d+ files? where no tests ran")
_TEST_FAIL_HDR = re.compile(r"^=== \d+ files? with test failures")
_PASSED_NONZERO_HDR = re.compile(r"^=== \d+ files? where all tests passed but")
_FLAKY_HDR = re.compile(r"^=== ⚠? ?\d+ FLAKY file")
_SECTION = re.compile(r"^=== ")
_LISTED_FILE = re.compile(r"^\s{2}(?P<file>\S+\.py)")


class LogIntegrityError(RuntimeError):
    """The log does not describe exactly one run (see TRAP 2)."""


@dataclass
class RunLog:
    path: Path
    failed_nodes: set = field(default_factory=set)
    no_tests_ran: set = field(default_factory=set)
    flaky_files: set = field(default_factory=set)
    summary: str = ""

    @property
    def failed_files(self) -> set:
        return {n.split("::", 1)[0] for n in self.failed_nodes}


def _norm(p: str) -> str:
    """Windows runners print ``tests\\cron\\x.py``; node ids use forward slashes."""
    return p.replace("\\", "/").strip()


def parse_log(path: Path) -> RunLog:
    """Parse one runner log, refusing anything that is not exactly one run."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    discoveries = sum(1 for ln in lines if _DISCOVERY.match(ln))
    summaries = [ln for ln in lines if _SUMMARY.match(ln)]
    if discoveries != 1 or len(summaries) != 1:
        raise LogIntegrityError(
            f"{path}: found {discoveries} discovery header(s) and {len(summaries)} summary "
            f"line(s); exactly 1 of each is required.\n"
            f"  More than one almost always means two runs wrote to this path -- stopping a "
            f"background shell does not stop the test subprocesses it spawned, and the orphan "
            f"keeps appending. Give every run its own log file and re-run.\n"
            f"  Zero means the run died before reporting (or was itself killed); there is "
            f"nothing here to compare."
        )

    run = RunLog(path=path, summary=summaries[0])
    section = None
    for ln in lines:
        m = _FAILED.match(ln.strip())
        if m:
            run.failed_nodes.add(_norm(m.group("node")))
            continue
        if _SECTION.match(ln):
            if _NO_TESTS_HDR.match(ln):
                section = "no_tests"
            elif _FLAKY_HDR.match(ln):
                section = "flaky"
            elif _TEST_FAIL_HDR.match(ln) or _PASSED_NONZERO_HDR.match(ln):
                section = "other_list"
            else:
                section = None
            continue
        if section in {"no_tests", "flaky"}:
            lm = _LISTED_FILE.match(ln)
            if lm:
                target = run.no_tests_ran if section == "no_tests" else run.flaky_files
                target.add(_norm(lm.group("file")))
    return run


@dataclass
class Comparison:
    suspected_regressions: list
    fixed: list
    failing_both: list
    uncomparable_files: list
    uncomparable_nodes: list
    flaky_either_side: list


def compare(base: RunLog, cand: RunLog) -> Comparison:
    """Classify candidate failures against the baseline, refusing to guess."""
    # TRAP 1: a file that did not collect on EITHER side carries no usable verdict for
    # any node in it. Quarantine those nodes instead of scoring them.
    blind = base.no_tests_ran | cand.no_tests_ran
    uncomparable_nodes = sorted(n for n in cand.failed_nodes if n.split("::", 1)[0] in blind)
    blind_nodes = set(uncomparable_nodes)

    suspected = sorted((cand.failed_nodes - base.failed_nodes) - blind_nodes)
    fixed = sorted((base.failed_nodes - cand.failed_nodes)
                   - {n for n in base.failed_nodes if n.split("::", 1)[0] in blind})
    both = sorted(cand.failed_nodes & base.failed_nodes)
    return Comparison(
        suspected_regressions=suspected,
        fixed=fixed,
        failing_both=both,
        uncomparable_files=sorted(blind),
        uncomparable_nodes=uncomparable_nodes,
        flaky_either_side=sorted(base.flaky_files | cand.flaky_files),
    )


def _serial_cmd(nodes: list) -> str:
    files = sorted({n.split("::", 1)[0] for n in nodes})
    return "python -m pytest " + " ".join(files) + " -p no:cacheprovider --timeout=300"


def render(base: RunLog, cand: RunLog, cmp_: Comparison) -> str:
    out = []
    out.append(f"baseline : {base.path}")
    out.append(f"           {base.summary}")
    out.append(f"candidate: {cand.path}")
    out.append(f"           {cand.summary}")
    out.append("")

    if cmp_.suspected_regressions:
        out.append(f"SUSPECTED REGRESSIONS ({len(cmp_.suspected_regressions)}) "
                   "-- failing on the candidate, passing on the baseline.")
        out.append("  NOT confirmed. Parallel contention fabricates failures (measured: 10 of 28).")
        out.append("  Re-run these SERIALLY on both revisions before calling any of them real:")
        out.append(f"    {_serial_cmd(cmp_.suspected_regressions)}")
        for n in cmp_.suspected_regressions:
            out.append(f"    {n}")
    else:
        out.append("SUSPECTED REGRESSIONS (0) -- no candidate-only failures.")
    out.append("")

    if cmp_.uncomparable_nodes:
        out.append(f"UNCOMPARABLE ({len(cmp_.uncomparable_nodes)} nodes in "
                   f"{len(cmp_.uncomparable_files)} files) -- a side did not collect these files,")
        out.append("  so it reported no failing nodes for them. That is NOT a pass. Re-run each")
        out.append("  file on the baseline alone to get a verdict:")
        for f in cmp_.uncomparable_files:
            out.append(f"    {f}")
        out.append("")

    out.append(f"FAILING ON BOTH ({len(cmp_.failing_both)}) -- pre-existing, not this change.")
    out.append(f"FIXED BY THE CANDIDATE ({len(cmp_.fixed)}).")
    for n in cmp_.fixed:
        out.append(f"    {n}")
    if cmp_.flaky_either_side:
        out.append("")
        out.append(f"FLAKY (passed on retry, either side) ({len(cmp_.flaky_either_side)}):")
        for f in cmp_.flaky_either_side:
            out.append(f"    {f}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline_log", type=Path)
    ap.add_argument("candidate_log", type=Path)
    ap.add_argument("--json", type=Path, default=None, help="also write the classification as JSON")
    args = ap.parse_args(argv)

    try:
        base = parse_log(args.baseline_log)
        cand = parse_log(args.candidate_log)
    except LogIntegrityError as exc:
        print(f"REFUSING TO COMPARE\n{exc}", file=sys.stderr)
        return 2

    cmp_ = compare(base, cand)
    print(render(base, cand, cmp_))
    if args.json:
        args.json.write_text(json.dumps({
            "baseline_summary": base.summary,
            "candidate_summary": cand.summary,
            "suspected_regressions": cmp_.suspected_regressions,
            "uncomparable_files": cmp_.uncomparable_files,
            "uncomparable_nodes": cmp_.uncomparable_nodes,
            "failing_both": cmp_.failing_both,
            "fixed": cmp_.fixed,
            "flaky_either_side": cmp_.flaky_either_side,
        }, indent=2), encoding="utf-8")
    return 1 if (cmp_.suspected_regressions or cmp_.uncomparable_nodes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
