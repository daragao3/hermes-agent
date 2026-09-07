"""Guards for the ``_ClaudeSortMemo`` reuse added on 2026-09-06.

The memo exists to stop ``_sort_claude_paths`` redoing per-path work on every
scan. The load-bearing property is therefore NOT "it is faster" but "it returns
exactly what the un-memoised function would have returned", including after the
corpus changes underneath it. Most of this file is that equivalence.

The performance guard uses an ABSOLUTE ceiling rather than a scaling ratio.
That is deliberate: the 2026-09-03 seen-set guard asserted a ratio on the
stated rationale that it cancels machine speed, and it flaked on a correctly
fixed tree because at small n the dominant noise is timing variance, not
machine speed -- the ratio cancelled the wrong variable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from session_bridge.coordinator import (
    _ClaudeSortMemo,
    _ClaudeStatCache,
    _sort_claude_paths,
)


def _write(root: Path, name: str, *, body: str = "x", mtime: float | None = None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def corpus(tmp_path: Path) -> list[Path]:
    base = 1_700_000_000.0
    return [
        _write(
            tmp_path, f"proj{i % 3}/sess{i}.jsonl", body="x" * (i + 1), mtime=base + i
        )
        for i in range(12)
    ]


def test_memo_matches_unmemoised_result(corpus: list[Path]) -> None:
    """The whole point: same paths, same stats, same answer."""
    plain = _sort_claude_paths(corpus)
    memoised = _sort_claude_paths(corpus, None, _ClaudeSortMemo())
    assert memoised == plain


def test_memo_hit_returns_the_same_answer(corpus: list[Path]) -> None:
    """A second call with nothing changed takes the memo path, not a rebuild."""
    memo = _ClaudeSortMemo()
    first = _sort_claude_paths(corpus, None, memo)
    assert memo.reusable(*_stats_and_unavailable(corpus))
    second = _sort_claude_paths(corpus, None, memo)
    assert second == first == _sort_claude_paths(corpus)


def _stats_and_unavailable(paths: list[Path]):
    stats: dict[str, tuple[int, int]] = {}
    unavailable: list[Path] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            unavailable.append(path)
            continue
        stats[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
    return stats, unavailable


def test_memo_does_not_go_stale_when_a_file_is_rewritten(
    corpus: list[Path],
) -> None:
    """A changed mtime must reorder AND refingerprint -- no stale hit."""
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    target = corpus[0]  # oldest, so a new mtime must move it to the front
    os.utime(target, (1_800_000_000.0, 1_800_000_000.0))

    ordered, _unavailable, fingerprints = _sort_claude_paths(corpus, None, memo)
    assert ordered == _sort_claude_paths(corpus)[0]
    assert ordered[0] == target
    assert fingerprints[target.stem]["mtime_ns"] == target.stat().st_mtime_ns


def test_memo_picks_up_a_size_only_change(corpus: list[Path]) -> None:
    """Same mtime, different size still invalidates the fingerprint."""
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    target = corpus[3]
    stat_before = target.stat()
    target.write_text("y" * 999, encoding="utf-8")
    os.utime(target, (stat_before.st_atime, stat_before.st_mtime))

    _ordered, _unavailable, fingerprints = _sort_claude_paths(corpus, None, memo)
    assert fingerprints[target.stem]["size"] == 999


def test_memo_picks_up_a_new_transcript(corpus: list[Path], tmp_path: Path) -> None:
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    fresh = _write(tmp_path, "proj9/brand-new.jsonl", mtime=1_900_000_000.0)
    grown = [*corpus, fresh]

    ordered, _unavailable, fingerprints = _sort_claude_paths(grown, None, memo)
    assert ordered == _sort_claude_paths(grown)[0]
    assert ordered[0] == fresh
    assert "brand-new" in fingerprints


def test_memo_drops_a_removed_transcript(corpus: list[Path]) -> None:
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    gone = corpus[-1]
    remaining = corpus[:-1]
    gone.unlink()

    ordered, _unavailable, fingerprints = _sort_claude_paths(remaining, None, memo)
    assert ordered == _sort_claude_paths(remaining)[0]
    assert gone not in ordered
    assert gone.stem not in fingerprints


def test_memo_reports_unavailable_paths_and_invalidates_on_them(
    corpus: list[Path],
) -> None:
    """An unstattable path is not in the ordering, and flipping it invalidates."""
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    missing = corpus[2]
    missing.unlink()

    ordered, unavailable, _fingerprints = _sort_claude_paths(corpus, None, memo)
    assert missing in unavailable
    assert missing not in ordered
    assert (ordered, unavailable) == _sort_claude_paths(corpus)[:2]


def test_memo_survives_a_long_sequence_of_mutations(
    corpus: list[Path], tmp_path: Path
) -> None:
    """The property that matters in production: never diverge, ever.

    A single hit/miss proves little -- the risk is drift accumulating across
    many cycles, which is exactly the shape of a live scan loop.
    """
    memo = _ClaudeSortMemo()
    paths = list(corpus)
    clock = 1_750_000_000.0

    for step in range(25):
        kind = step % 5
        if kind == 0:
            clock += 10
            os.utime(paths[step % len(paths)], (clock, clock))
        elif kind == 1:
            paths[step % len(paths)].write_text("z" * (step + 2), encoding="utf-8")
        elif kind == 2:
            clock += 10
            paths.append(_write(tmp_path, f"proj-new/added{step}.jsonl", mtime=clock))
        elif kind == 3 and len(paths) > 4:
            doomed = paths.pop(1)
            doomed.unlink()
        # kind == 4: no change at all, so the memo must HIT and still be right

        assert _sort_claude_paths(paths, None, memo) == _sort_claude_paths(paths), (
            f"memo diverged from the un-memoised result at step {step}"
        )


def test_memo_result_is_copied_so_callers_cannot_corrupt_it(
    corpus: list[Path],
) -> None:
    memo = _ClaudeSortMemo()
    ordered, unavailable, fingerprints = _sort_claude_paths(corpus, None, memo)
    ordered.clear()
    unavailable.append(Path("bogus"))
    fingerprints.clear()

    again = _sort_claude_paths(corpus, None, memo)
    assert again == _sort_claude_paths(corpus)


def test_stem_table_does_not_grow_without_bound(
    corpus: list[Path], tmp_path: Path
) -> None:
    """Sessions churn; the cached stems must not accumulate forever."""
    memo = _ClaudeSortMemo()
    _sort_claude_paths(corpus, None, memo)

    churned = list(corpus)
    for step in range(15):
        doomed = churned.pop(0)
        doomed.unlink()
        churned.append(_write(tmp_path, f"churn/c{step}.jsonl", mtime=1.8e9 + step))
        _sort_claude_paths(churned, None, memo)

    assert len(memo._stems) <= len(churned) + 1


def test_paths_are_not_rewrapped(corpus: list[Path]) -> None:
    """Reusing the caller's Path objects is what keeps pathlib's parse warm.

    ``ClaudeSourceAdapter.discover`` hands back the SAME objects from its TTL
    cache, so re-wrapping them threw away work already done. Identity here is
    the guard against that regression returning.
    """
    ordered, _unavailable, _fingerprints = _sort_claude_paths(corpus)
    by_id = {id(path) for path in corpus}
    assert all(id(path) in by_id for path in ordered)


def test_string_inputs_are_still_accepted(corpus: list[Path]) -> None:
    """The isinstance shortcut must not break the str path."""
    as_strings = [str(path) for path in corpus]
    assert _sort_claude_paths(as_strings) == _sort_claude_paths(corpus)


def test_non_path_list_still_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="no path list"):
        _sort_claude_paths(None)


def test_memo_composes_with_the_stat_cache(corpus: list[Path]) -> None:
    """Both caches on at once, as production runs them."""
    cache = _ClaudeStatCache()
    memo = _ClaudeSortMemo()
    first = _sort_claude_paths(corpus, cache, memo)
    second = _sort_claude_paths(corpus, cache, memo)
    assert first == second
    assert [p.name for p in first[0]] == [p.name for p in _sort_claude_paths(corpus)[0]]


@pytest.mark.parametrize("n", [4000])
def test_repeated_scans_stay_under_an_absolute_ceiling(tmp_path: Path, n: int) -> None:
    """A steady-state scan loop must not cost what a cold rebuild costs.

    Absolute bound, not a ratio -- see the module docstring. The measured
    production figure this replaces is 195 ms per scan at n=5,421 with the
    memo absent; twenty memo-assisted scans at n=4,000 finishing inside 2.0 s
    leaves well over an order of magnitude of headroom on CI hardware while
    still failing loudly if the per-path work comes back.
    """
    paths = [
        _write(tmp_path, f"p{i % 40}/s{i}.jsonl", mtime=1.7e9 + i) for i in range(n)
    ]
    cache = _ClaudeStatCache()
    memo = _ClaudeSortMemo()
    _sort_claude_paths(paths, cache, memo)  # warm

    started = time.perf_counter()
    for step in range(20):
        # Touch one file per cycle, which is the production shape: a median of
        # 2 changed files out of 5,424 measured on the live corpus.
        os.utime(paths[step], (1.8e9 + step, 1.8e9 + step))
        _sort_claude_paths(paths, cache, memo)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"20 memo-assisted scans at n={n} took {elapsed:.2f}s"
