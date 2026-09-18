"""Full-repo self-scan wrapper for scripts/check-windows-footguns.py.

scripts/check_subprocess_stdin.py has had a pytest wrapper (see
tests/tools/test_subprocess_stdin_guard.py's test_all_tui_subprocess_calls_
have_stdin) that runs the checker with its default full-scan behavior and
asserts a clean exit — so a normal pytest run of that file catches
regressions even when no one remembers to run the standalone script by hand.
check-windows-footguns.py had no equivalent: only a narrow rule-level test
(tests/scripts/test_footgun_subprocess_encoding.py, scoped to the
text=True/encoding= rule) existed, so a bare ``os.killpg``/``signal.SIGKILL``
regression (caught by CI running the real script with --all, not by any
local pytest run) shipped in the T1-T3 npx-agent-browser hardening commit
before anyone ran the script directly. This closes that gap the same way
the stdin guard already closes its equivalent one.
"""

from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-windows-footguns.py"


# TIMEOUT BUDGET, re-set 2026-09-15 when tests/ and evals/ joined `--all`;
# made load-calibrated 2026-09-18.
#
# The scan went from 1932 files to 6651, i.e. ~7.9s to ~17.5s of per-line work
# on an idle box -- already past the old `timeout=20`, and this box measured
# 44.7s for the same scan while loaded, so a bound near the true cost is a
# flake generator, not a hang detector.
#
# The ORDER of the two bounds is the part that matters. pyproject sets
# `--timeout=30 --timeout-method=thread`; a thread watchdog cannot interrupt a
# blocked `subprocess.run`, so when it wins the race it dumps a stack ending in
# `threading._wait_for_tstate_lock` and, observed on this box, can take the
# whole session down with an INTERNALERROR instead of failing one test. So the
# per-test mark must sit ABOVE the subprocess bound, and the subprocess bound
# must be what actually fires: `subprocess.TimeoutExpired` names the scan.
#
# WHY THE SUBPROCESS BOUND IS CALIBRATED, NOT A CONSTANT (2026-09-18).
#
# A fixed 150s held while the box was merely busy, and broke the day the
# acceptance ceremonies became routine: with a ceremony validating (~6800
# tests, 12 workers, 100% CPU, ~900 processes) the same scan measured 584,
# 612, 658, 686, 966 and 1239s in six runs on 2026-09-17 -- 35x-70x idle, and
# ~6x-12x the ~104s it costs under the ceremony's lighter phases. Under
# scripts/run_tests.sh that is a TimeoutExpired on attempt 1 and a pass on the
# runner's one-shot retry, so every ceremony run reported this file FLAKY.
#
# A constant cannot be both a hang detector and load-proof here, because
# "load" on this box spans two orders of magnitude and changes by the minute.
# So the bound is derived from the box RIGHT NOW: scan a fixed 1-in-20 stride
# of the same file list in-process, scale by bytes to the whole tree (a
# 1-in-25 sample predicted 46.8s against a measured 44.4s in-process scan
# on 2026-09-18), and allow the subprocess _SCAN_TIMEOUT_FACTOR times that
# prediction. The factor is what keeps it a hang detector: a hang is a scan
# that runs past several times what the box was just measured to need,
# whatever the load. Two consecutive samples under a live ceremony differed
# by ~3x, so the factor must cover at least that on its own.
#
# Clamped both ways. The floor is the old constant (idle predicts ~17s, and
# the subprocess also pays interpreter start, imports and `git ls-files`).
# The cap keeps the file inside the runner's per-file kill (1800s,
# _DEFAULT_FILE_TIMEOUT_SECONDS in scripts/run_tests_parallel.py) with room
# for the calibration sample and the rest of this file; past the cap a
# genuine run is the runner's problem, not a flake to widen for. The pytest
# mark sits above the cap so the order property above holds for every value
# the calibration can produce.
#
# Rejected: skipping or widening only while a ~/.hermes loops record says a
# ceremony is active. The ceremony is a proxy -- a sibling's whole-suite
# sweep loads the box identically with no record -- and the ceremony's
# validation is exactly the run this test must not skip.
_SCAN_TIMEOUT_FLOOR_S = 150
_SCAN_TIMEOUT_CAP_S = 1500
_SCAN_TIMEOUT_FACTOR = 8
_SCAN_TIMEOUT_S = _SCAN_TIMEOUT_FLOOR_S  # the bound when nothing could be sampled
_TEST_TIMEOUT_S = 1650
_CALIBRATION_STRIDE = 20
assert _SCAN_TIMEOUT_FLOOR_S <= _SCAN_TIMEOUT_CAP_S < _TEST_TIMEOUT_S, (
    "the subprocess bound must fire first, for every calibrated value"
)


def _scan_timeout_from_prediction(predicted_s: float) -> int:
    """The subprocess bound for a scan predicted to take ``predicted_s``.

    Pure, so the clamp is testable without a scan: FACTOR times the
    prediction, never below the floor, never above the cap, always an int
    strictly under the pytest mark."""
    if not (predicted_s > 0) or math.isinf(predicted_s):
        return _SCAN_TIMEOUT_FLOOR_S
    bound = math.ceil(predicted_s * _SCAN_TIMEOUT_FACTOR)
    return max(_SCAN_TIMEOUT_FLOOR_S, min(_SCAN_TIMEOUT_CAP_S, bound))


def _calibrate_scan_timeout(linter) -> tuple[int, dict]:
    """(bound, receipt) from a stride sample of the real `--all` file set.

    Same file set `--all` walks (get_all_scan_files -> iter_files), sorted so
    the sample is the same files every run; every ``_CALIBRATION_STRIDE``-th
    file is scanned in-process with the real rules and the elapsed time is
    scaled by bytes to the whole set. The receipt is printed with the result
    and quoted in the failure, so a TimeoutExpired says what the box looked
    like when the bound was chosen rather than leaving a bare number."""
    files = sorted(linter.iter_files(linter.get_all_scan_files()))
    sizes = {}
    for path in files:
        try:
            sizes[path] = os.stat(path).st_size
        except OSError:
            sizes[path] = 0
    sample = files[::_CALIBRATION_STRIDE]
    sample_bytes = sum(sizes[p] for p in sample)
    total_bytes = sum(sizes.values())
    started = time.perf_counter()
    for path in sample:
        linter.scan_file(path, linter.FOOTGUNS)
    sample_s = time.perf_counter() - started
    predicted_s = sample_s * total_bytes / sample_bytes if sample_bytes else 0.0
    bound = _scan_timeout_from_prediction(predicted_s)
    receipt = {
        "files": len(files),
        "total_bytes": total_bytes,
        "sample_files": len(sample),
        "sample_bytes": sample_bytes,
        "sample_s": round(sample_s, 3),
        "predicted_s": round(predicted_s, 1),
        "factor": _SCAN_TIMEOUT_FACTOR,
        "floor_s": _SCAN_TIMEOUT_FLOOR_S,
        "cap_s": _SCAN_TIMEOUT_CAP_S,
        "bound_s": bound,
    }
    return bound, receipt


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_full_repo_scan_has_no_unsuppressed_windows_footguns():
    """Mirrors check_subprocess_stdin.py's wrapper: run the real checker
    against the whole repo (--all) and require a clean exit, so this test
    file — not just institutional memory — is what catches the next
    bare os.killpg/signal.SIGKILL-style regression."""
    scan_timeout_s, receipt = _calibrate_scan_timeout(_load_linter_module())
    print(f"footgun scan bound calibrated: {receipt}")
    started = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--all"],
            capture_output=True,
            text=True,
            # See the budget above: a hang detector, not a performance
            # budget. Scan cost is pinned in test_footgun_prefilter.py; what
            # this test asserts is the exit status.
            timeout=scan_timeout_s,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"the --all scan did not finish within {scan_timeout_s}s "
            f"({_SCAN_TIMEOUT_FACTOR}x what a sample of the same tree "
            f"predicted moments earlier, clamped to "
            f"[{_SCAN_TIMEOUT_FLOOR_S}, {_SCAN_TIMEOUT_CAP_S}]s): {receipt}"
        ) from exc
    print(f"footgun scan took {time.perf_counter() - started:.1f}s "
          f"(bound {scan_timeout_s}s)")
    assert result.returncode == 0, (
        f"Windows footgun check failed:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize(
    "predicted_s,expected",
    [
        (0.0, _SCAN_TIMEOUT_FLOOR_S),            # nothing sampled -> the old constant
        (-1.0, _SCAN_TIMEOUT_FLOOR_S),
        (float("nan"), _SCAN_TIMEOUT_FLOOR_S),
        (float("inf"), _SCAN_TIMEOUT_FLOOR_S),
        (17.5, _SCAN_TIMEOUT_FLOOR_S),           # idle: 8 x 17.5 = 140 < floor
        (100.0, 800),                            # ceremony, lighter phase
        (1239.0, _SCAN_TIMEOUT_CAP_S),           # worst measured 2026-09-17
        (1e9, _SCAN_TIMEOUT_CAP_S),
    ],
)
def test_scan_timeout_is_factor_times_prediction_clamped(predicted_s, expected):
    """The bound is FACTOR x prediction inside [floor, cap]; the hang-detector
    margin is the factor, and the clamp is what keeps the pytest mark (and
    the runner's 1800s per-file kill) above every value it can take."""
    bound = _scan_timeout_from_prediction(predicted_s)
    assert bound == expected
    assert isinstance(bound, int)
    assert _SCAN_TIMEOUT_FLOOR_S <= bound <= _SCAN_TIMEOUT_CAP_S < _TEST_TIMEOUT_S


def test_scan_timeout_never_shrinks_as_load_grows():
    """Monotone: a slower box never gets a tighter bound than a faster one."""
    points = [_scan_timeout_from_prediction(p) for p in (1, 10, 18, 19, 50, 187, 188, 400, 2000)]
    assert points == sorted(points)
    assert points[0] == _SCAN_TIMEOUT_FLOOR_S and points[-1] == _SCAN_TIMEOUT_CAP_S


def test_calibration_samples_the_real_all_file_set(monkeypatch):
    """The sample must be a stride over the file set `--all` itself walks
    (sorted, so it is the same files every run), scanned with the real rules,
    and scaled by bytes -- not a hand-picked directory that can drift from
    what `--all` covers. Timing is stubbed so this is a shape test."""
    linter = _load_linter_module()
    scanned: list[Path] = []
    monkeypatch.setattr(linter, "scan_file",
                        lambda path, footguns: (scanned.append(path), [])[1])
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(time, "perf_counter", lambda: next(ticks))

    bound, receipt = _calibrate_scan_timeout(linter)

    expected_files = sorted(linter.iter_files(linter.get_all_scan_files()))
    assert scanned == expected_files[::_CALIBRATION_STRIDE]
    assert receipt["files"] == len(expected_files)
    assert receipt["sample_files"] == len(scanned)
    assert receipt["sample_s"] == 2.0
    assert receipt["predicted_s"] == pytest.approx(
        2.0 * receipt["total_bytes"] / receipt["sample_bytes"], rel=0.01
    )
    assert bound == _scan_timeout_from_prediction(receipt["predicted_s"])
    assert receipt["bound_s"] == bound


def test_calibration_with_nothing_to_sample_falls_back_to_the_floor(monkeypatch):
    linter = _load_linter_module()
    monkeypatch.setattr(linter, "get_all_scan_files", lambda include_tests=False: [])
    bound, receipt = _calibrate_scan_timeout(linter)
    assert bound == _SCAN_TIMEOUT_FLOOR_S
    assert receipt["files"] == 0 and receipt["predicted_s"] == 0.0


def _load_linter_module():
    # Same shape as tests/scripts/test_footgun_prefilter.py: register in
    # sys.modules BEFORE exec_module so @dataclass can resolve __module__.
    spec = importlib.util.spec_from_file_location("check_windows_footguns", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_windows_footguns"] = mod
    spec.loader.exec_module(mod)
    return mod


def _tracked_python_files() -> set[str]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.py", "*.pyw", "*.pyi"],
        cwd=REPO_ROOT,
        text=True, encoding="utf-8", errors="replace",
    )
    return {rel for rel in (p.strip() for p in out.split("\0")) if rel}


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_all_covers_every_tracked_first_party_python_file():
    """`--all` must not silently stop covering a package.

    The list this replaced was eight hardcoded package names that never grew a
    `tui_gateway/` entry, so `tui_gateway/host_supervisor.py` carried a bare
    `os.kill(pid, 0)` indefinitely while CONTRIBUTING.md banned the pattern and
    lint.yml ran this script as a blocking gate. `--all` reported
    "No Windows footguns found" the entire time; the same checkout, pointed at
    that one file, exited 1. Nothing in the suite could tell the difference,
    because every test asserted the EXIT STATUS of a scan whose FILE SET was
    the broken part. This asserts the file set, as `--all` itself computes it.
    """
    linter = _load_linter_module()

    # Drive the REAL `--all` code path, not get_all_scan_files() directly.
    # Asserting against the helper is vacuous: it passes with `--all` still
    # wired to the old hardcoded root list, which is the one regression this
    # test exists to catch (confirmed by mutating main() and watching an
    # earlier version of this test stay green).
    #
    # The recorder does NOT call the real scan_file: this test asserts the
    # file set, and a second full scan of the tree in-process cost as much
    # as the subprocess one above (600-1200s under a live ceremony,
    # 2026-09-17) against the runner's 1800s per-file kill.
    seen: list[Path] = []
    real_scan_file = linter.scan_file
    linter.scan_file = lambda path, footguns: (seen.append(path), [])[1]
    try:
        linter.main(["--all"])
    finally:
        linter.scan_file = real_scan_file
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in seen}
    expected = {
        rel for rel in _tracked_python_files()
        if rel.split("/", 1)[0] not in linter.ALL_SCAN_SKIP_TOP_LEVEL
        and linter.should_scan_file(REPO_ROOT / rel)
    }
    missing = expected - scanned
    assert not missing, (
        "--all no longer covers tracked first-party Python files: "
        f"{sorted(missing)[:20]}"
    )


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_all_never_descends_into_agent_worktrees_or_stale_venvs():
    """The named-root list excluded `.claude/worktrees/` (one checkout per
    agent session on this box) and the stale venvs by accident of never naming
    them. The git-derived list must keep that property on purpose -- a scan
    that walked the worktrees would multiply its own cost by the fleet size and
    report other sessions' in-flight edits as findings in this tree."""
    files = _load_linter_module().get_all_scan_files()
    assert files, "--all resolved to an empty file set"

    # RELATIVE to REPO_ROOT, deliberately. This checkout is itself inside
    # `.claude/worktrees/`, so an absolute-substring test flags every file in
    # the tree and is not a test of anything (it failed that way when written).
    strays = []
    for path in files:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()  # raises if outside
        if rel.startswith((".claude/", ".venv/", "venv/")) or "/site-packages/" in rel:
            strays.append(rel)
    assert not strays, f"--all reached into a nested checkout or venv: {strays[:10]}"


def test_all_scan_skip_list_is_pinned():
    """test_all_covers_every_tracked_first_party_python_file derives what it
    expects FROM ALL_SCAN_SKIP_TOP_LEVEL, so adding a package to that set would
    silence it rather than fail it -- the same shape as the drift that started
    this. Pin the set here so growing it costs a deliberate edit to a test whose
    name says what it is guarding.

    It held {"tests", "evals"} while a measured 2996-finding backlog was worked
    down. That reached zero on 2026-09-15, so the set is now pinned EMPTY: any
    entry at all re-opens the hole the git-derived file list closed.
    """
    linter = _load_linter_module()
    assert linter.ALL_SCAN_SKIP_TOP_LEVEL == set(), (
        "--all stopped scanning a top-level tree. The skip list is empty by "
        "design -- the tests/evals backlog that justified it is gone. "
        "Excluding anything here hides first-party code from a blocking gate."
    )


# ---------------------------------------------------------------------------
# MULTI-LINE ENCODING CALLS
#
# `open()` and `subprocess text=True` are `multiline_encoding_aware`: a call
# that does not close on the flagged line is re-checked against its full paren
# span and dropped only if `encoding=` is genuinely in there.
#
# The cheap alternative -- skip every multi-line call, the way the read_text
# rule does -- was measured over the pre-sweep tree (9c5250323c) and lost six
# findings: two false positives and FOUR REAL FOOTGUNS. So the property under
# test is not "multi-line calls are exempt", it is "multi-line calls are exempt
# ONLY when the kwarg is actually present". Both directions are asserted
# together, from one source, so a filter that exempts too much cannot pass by
# also making the positive case disappear.
# ---------------------------------------------------------------------------

_MULTILINE_FIXTURES = (
    # (label, source, should_report)
    (
        "subprocess encoding on continuation line",
        'subprocess.run(cmd, capture_output=True, text=True,\n'
        '               encoding="utf-8")\n',
        False,
    ),
    (
        "subprocess with NO encoding anywhere",
        'subprocess.run(cmd, capture_output=True, text=True,\n'
        '               timeout=30)\n',
        True,
    ),
    (
        "open() encoding on continuation line",
        'fh = open(path, "r",\n'
        '          encoding="utf-8")\n',
        False,
    ),
    (
        "open() with NO encoding anywhere",
        'fh = open(path, "r",\n'  # windows-footgun: ok -- fixture source text, not a live call site
        '          newline="")\n',
        True,
    ),
    (
        "encoding= only AFTER the call closes is not in the span",
        'subprocess.run(cmd, text=True,\n'
        '               timeout=30)\n'
        'other(encoding="utf-8")\n',
        True,
    ),
    (
        "a comment mentioning encoding= does not count as the kwarg",
        'subprocess.run(cmd, text=True,\n'
        '               timeout=30)  # encoding= is deliberately omitted\n',
        True,
    ),
    # read_text/write_text joined the span-aware filter on 2026-09-15; until
    # then the rule exempted every wrapped call on shape alone.
    (
        "write_text encoding on continuation line",
        'path.write_text(\n'
        '    "gateway:\\n"\n'
        '    "  strict: true\\n",\n'
        '    encoding="utf-8",\n'
        ')\n',
        False,
    ),
    (
        "read_text encoding on continuation line",
        'data = path.read_text(\n'
        '    encoding="utf-8"\n'
        ').splitlines()\n',
        False,
    ),
    (
        "write_text with NO encoding anywhere",
        'path.write_text(\n'
        '    "gateway:\\n"\n'
        '    "  strict: true\\n"\n'
        ')\n',
        True,
    ),
    (
        "read_text with NO encoding anywhere",
        'data = path.read_text(\n'
        ').splitlines()\n',
        True,
    ),
    # The span walk tracks string state across lines: a ``)`` inside a string
    # argument must not close the span early (three correctly written
    # write_text(<shell script>, encoding=...) calls were reported before
    # this), and encoding= INSIDE a string argument is not the kwarg (a
    # child-script fixture whose TEXT said encoding= slipped through).
    (
        "close paren inside a string argument does not end the span",
        'script.write_text(\n'
        '    "case $1 in\\n"\n'
        '    "  bootout) exit 3 ;;\\n"\n'
        '    "esac\\n",\n'
        '    encoding="utf-8",\n'
        ')\n',
        False,
    ),
    (
        "encoding= inside a string argument is not the kwarg",
        'script.write_text(\n'
        '    """import json\n'
        'with open(p, encoding="utf-8") as fh:\n'
        '    pass\n'
        '"""\n'
        ')\n',
        True,
    ),
    (
        "open paren inside a one-line string argument still reports",
        'f.write_text("def broken(\\n")\n',
        True,
    ),
)


@pytest.mark.parametrize(
    "label,source,should_report",
    _MULTILINE_FIXTURES,
    ids=[f[0] for f in _MULTILINE_FIXTURES],
)
def test_multiline_call_is_exempt_only_when_encoding_is_really_in_the_span(
    tmp_path, label, source, should_report
):
    linter = _load_linter_module()
    target = tmp_path / "probe.py"
    target.write_text(source, encoding="utf-8", newline="")

    found = linter.scan_file(target, linter.FOOTGUNS)
    encoding_hits = [
        m for m in found if "encoding=" in m[2].name
    ]

    if should_report:
        assert encoding_hits, (
            f"{label}: a multi-line call with no encoding= in its span was "
            "NOT reported. The multi-line filter is exempting calls on shape "
            "alone -- that is the change measured to hide four real footguns."
        )
    else:
        assert not encoding_hits, (
            f"{label}: a correctly-written multi-line call was reported. "
            f"Findings: {[(m[0], m[2].name) for m in encoding_hits]}"
        )


def test_multiline_span_walk_is_bounded():
    """An unbalanced paren must not send the span walk to end of file, and an
    unterminated walk must report NO encoding -- i.e. keep the finding rather
    than silently drop it."""
    linter = _load_linter_module()
    lines = ['subprocess.run(cmd, text=True,'] + ["    # filler"] * 500
    lines.append('    encoding="utf-8")')
    assert linter._encoding_in_call_span(lines, 0, len("subprocess.run(")) is False, (
        "the walk ran past _MAX_CALL_SPAN_LINES and found a kwarg it should "
        "not have reached"
    )
