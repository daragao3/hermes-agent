"""Tests for scripts/compare_test_runs.py.

Each test reproduces one of the three traps the tool exists to prevent, in the shape
that actually occurred on 2026-09-14, and asserts the tool does NOT give the wrong
answer that was given by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "compare_test_runs",
    Path(__file__).resolve().parents[2] / "scripts" / "compare_test_runs.py",
)
ctr = importlib.util.module_from_spec(_SPEC)
# Register BEFORE exec: @dataclass resolves annotations via sys.modules[cls.__module__],
# which is None for a spec-loaded module that was never registered, and the decorator
# dies at import with a bare AttributeError.
sys.modules[_SPEC.name] = ctr
_SPEC.loader.exec_module(ctr)


def _log(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


HEADER = "Discovered 3 test files (~30 tests) under ['tests']\n"
SUMMARY = "=== Summary: 3 files, 28 tests passed, 2 failed, 0 skipped (100% complete) in 10.0s ===\n"


def _one_run(failed=(), no_tests=(), flaky=()) -> str:
    out = [HEADER]
    for node in failed:
        out.append(f"  ║ FAILED {node} - AssertionError: whatever\n")
    out.append(SUMMARY)
    if no_tests:
        out.append(f"=== {len(no_tests)} files where no tests ran (collection/import error) ===\n")
        for f in no_tests:
            out.append(f"  {f}\n")
    if flaky:
        out.append(f"=== ⚠ {len(flaky)} FLAKY file (failed once, passed on retry — fix these) ===\n")
        for f in flaky:
            out.append(f"  {f}\n")
    return "".join(out)


class TestLogIntegrity:
    """TRAP 2: two runs in one file must be refused, not analysed."""

    def test_two_summaries_is_refused(self, tmp_path):
        merged = _one_run(failed=["tests/a.py::test_x"]) + _one_run(no_tests=["tests/b.py"])
        p = _log(tmp_path, "merged.log", merged)
        with pytest.raises(ctr.LogIntegrityError) as exc:
            ctr.parse_log(p)
        # The message must name the cause, not just complain -- the whole point is that
        # the reader does not know orphaned subprocesses keep writing.
        assert "two runs wrote to this path" in str(exc.value)

    def test_truncated_run_is_refused(self, tmp_path):
        p = _log(tmp_path, "died.log", HEADER + "  ║ FAILED tests/a.py::test_x\n")
        with pytest.raises(ctr.LogIntegrityError):
            ctr.parse_log(p)

    def test_single_clean_run_parses(self, tmp_path):
        p = _log(tmp_path, "ok.log", _one_run(failed=["tests/a.py::test_x"]))
        run = ctr.parse_log(p)
        assert run.failed_nodes == {"tests/a.py::test_x"}


class TestUncomparable:
    """TRAP 1: a baseline collection error is not a pass."""

    def test_baseline_collection_error_is_not_a_regression(self, tmp_path):
        # The real shape: baseline could not collect tests/a.py, so it reported no
        # FAILED lines for it. Diffing the sets by hand calls test_x a regression.
        base = _log(tmp_path, "base.log", _one_run(no_tests=["tests/a.py"]))
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        cmp_ = ctr.compare(ctr.parse_log(base), ctr.parse_log(cand))
        assert cmp_.suspected_regressions == []
        assert cmp_.uncomparable_nodes == ["tests/a.py::test_x"]
        assert cmp_.uncomparable_files == ["tests/a.py"]

    def test_windows_separators_match_node_ids(self, tmp_path):
        # The runner lists files as tests\a.py while node ids use tests/a.py; without
        # normalisation the quarantine silently misses.
        base = _log(tmp_path, "base.log",
                    _one_run(no_tests=[r"tests\a.py"]))
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        cmp_ = ctr.compare(ctr.parse_log(base), ctr.parse_log(cand))
        assert cmp_.uncomparable_nodes == ["tests/a.py::test_x"]
        assert cmp_.suspected_regressions == []


class TestClassification:
    def test_candidate_only_failure_is_suspected_not_confirmed(self, tmp_path):
        base = _log(tmp_path, "base.log", _one_run())
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        b, c = ctr.parse_log(base), ctr.parse_log(cand)
        cmp_ = ctr.compare(b, c)
        assert cmp_.suspected_regressions == ["tests/a.py::test_x"]
        text = ctr.render(b, c, cmp_)
        # TRAP 3: the wording must not let a reader treat this as confirmed.
        assert "SUSPECTED" in text and "NOT confirmed" in text
        assert "SERIALLY" in text

    def test_shared_failure_is_preexisting(self, tmp_path):
        base = _log(tmp_path, "base.log", _one_run(failed=["tests/a.py::test_x"]))
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        cmp_ = ctr.compare(ctr.parse_log(base), ctr.parse_log(cand))
        assert cmp_.failing_both == ["tests/a.py::test_x"]
        assert cmp_.suspected_regressions == []

    def test_fixed_node_is_reported(self, tmp_path):
        base = _log(tmp_path, "base.log", _one_run(failed=["tests/a.py::test_x"]))
        cand = _log(tmp_path, "cand.log", _one_run())
        cmp_ = ctr.compare(ctr.parse_log(base), ctr.parse_log(cand))
        assert cmp_.fixed == ["tests/a.py::test_x"]

    def test_differing_assertion_messages_do_not_double_count(self, tmp_path):
        # Same node, different message (a tmp_path in the repr). Without stripping the
        # " - msg" tail this node appears as BOTH fixed and newly failing.
        base = _log(tmp_path, "base.log",
                    HEADER + "  ║ FAILED tests/a.py::test_x - assert '/tmp/pytest-1' == 'x'\n" + SUMMARY)
        cand = _log(tmp_path, "cand.log",
                    HEADER + "  ║ FAILED tests/a.py::test_x - assert '/tmp/pytest-2' == 'x'\n" + SUMMARY)
        cmp_ = ctr.compare(ctr.parse_log(base), ctr.parse_log(cand))
        assert cmp_.failing_both == ["tests/a.py::test_x"]
        assert cmp_.suspected_regressions == []
        assert cmp_.fixed == []


class TestExitStatus:
    def test_clean_comparison_exits_zero(self, tmp_path, capsys):
        base = _log(tmp_path, "base.log", _one_run(failed=["tests/a.py::test_x"]))
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        assert ctr.main([str(base), str(cand)]) == 0

    def test_suspected_exits_one(self, tmp_path, capsys):
        base = _log(tmp_path, "base.log", _one_run())
        cand = _log(tmp_path, "cand.log", _one_run(failed=["tests/a.py::test_x"]))
        assert ctr.main([str(base), str(cand)]) == 1

    def test_refused_log_exits_two(self, tmp_path, capsys):
        merged = _one_run() + _one_run()
        p = _log(tmp_path, "merged.log", merged)
        good = _log(tmp_path, "good.log", _one_run())
        assert ctr.main([str(p), str(good)]) == 2
