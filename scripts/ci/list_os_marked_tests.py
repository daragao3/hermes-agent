#!/usr/bin/env python3
"""List the test files that carry a given OS marker.

Used by ``.github/workflows/tests-os.yml`` to scope what the macOS and
Windows lanes import.

Why scope at all, when ``pytest -m macos_only`` already selects correctly?
Because ``-m`` filters AFTER collection, and collection IMPORTS every test
module under ``tests/``. On the Linux lane that is fine (it runs them all
anyway), but on the macOS/Windows lanes it would drag ~900 unrelated modules
through import on a host they were never expected to import on — one
unrelated ImportError would fail a job whose actual subject passed. Narrowing
the paths keeps each lane's failure signal about its own tests.

``-m`` is still passed by the workflow and remains the authoritative
selector: this script only decides which files get imported, never which
tests run. Over-selecting here is harmless (``-m`` drops the extras); the
failure mode to care about is UNDER-selecting, which is why the workflow
fails the job when zero tests end up selected.

Usage:
    python scripts/ci/list_os_marked_tests.py macos_only [tests_root]

Prints one path per line (POSIX separators, repo-relative), sorted.
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_VALID_MARKERS = ("linux_only", "macos_only", "windows_only")

#: Threads used for the content scan.
#:
#: The scan is ~4,400 file opens over ~49 MB and its cost is per-open latency,
#: not CPU and not disk bandwidth -- on Windows the antivirus filter driver
#: runs on every open. Measured on this tree: ``rglob`` takes 0.2-0.6 s while
#: the serial read loop takes 30-37 s in a warm checkout and over 120 s in a
#: freshly created worktree, whose files no process has opened yet. Python
#: releases the GIL for the duration of a read, so a small pool overlaps those
#: waits and recovers almost all of it: 31.6 s -> 2-4 s here.
#:
#: Deliberately a small constant rather than scaled to the CPU count, and 8 is
#: measured rather than picked. Sweeping cold subtrees of this repo -- content
#: never read, which is the freshly-created-worktree case that actually hurts --
#: the scan rate peaks at 8 and falls off after it: 1 worker 48 files/s, 8
#: workers 928, 16 workers 516, 32 workers 576. What is overlapped is
#: *waiting*, not computing, so once the device's queue is saturated more
#: threads only add contention. On a warm tree every count from 4 to 32 lands
#: inside run-to-run noise, so it is the cold numbers that chose this value.
_SCAN_THREADS = 8


def find_marked_files(marker: str, root: Path) -> list[Path]:
    """Return every ``test_*.py`` under *root* that references *marker*.

    Matches the marker as a whole word so ``macos_only`` doesn't pick up a
    hypothetical ``macos_only_extra``. Catches both the decorator form
    (``@pytest.mark.macos_only``, on a function or a class) and the
    module-level ``pytestmark`` form.
    """
    pattern = re.compile(rf"\b{re.escape(marker)}\b")
    paths = sorted(root.rglob("test_*.py"))

    def matches(path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return pattern.search(text) is not None

    # ``Executor.map`` yields results in SUBMISSION order, not completion order,
    # so pairing it back against ``paths`` preserves the sort without a second
    # sort, and the output stays byte-identical to the old serial loop. Do not
    # swap this for ``as_completed``, which would silently scramble the order
    # this module's docstring promises; ``test_output_is_sorted`` pins it.
    with ThreadPoolExecutor(max_workers=_SCAN_THREADS) as pool:
        return [path for path, hit in zip(paths, pool.map(matches, paths)) if hit]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    marker = argv[1]
    if marker not in _VALID_MARKERS:
        print(
            f"error: unknown marker {marker!r} (expected one of "
            f"{', '.join(_VALID_MARKERS)})",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(__file__).resolve().parents[2]
    root = Path(argv[2]) if len(argv) > 2 else repo_root / "tests"
    if not root.exists():
        print(f"error: no such directory: {root}", file=sys.stderr)
        return 2

    files = find_marked_files(marker, root)
    if not files:
        print(
            f"error: no test file references @pytest.mark.{marker} — the marker "
            "was probably renamed or dropped. Refusing to emit an empty list, "
            "which would let the OS lane pass without running anything.",
            file=sys.stderr,
        )
        return 1

    lines: list[str] = []
    for path in files:
        # POSIX separators so the output is safe to paste into a bash
        # command line on the Windows runner (Git Bash accepts them).
        #
        # Relative to the repo root when the path is inside it (the CI case —
        # pytest is invoked from the repo root). A root outside the repo is a
        # test/manual invocation; emit it as-is rather than raising, since
        # ``relative_to`` refuses non-descendant paths.
        try:
            rel = path.resolve().relative_to(repo_root)
        except ValueError:
            lines.append(path.as_posix())
        else:
            lines.append(rel.as_posix())

    # Write bytes with explicit LF rather than print(), which on Windows
    # translates "\n" to "\r\n" in text mode. The consumer reads this list with
    # ``$(cat ...)`` in bash, and word splitting uses IFS (space/tab/newline) —
    # a CR is NOT a separator, so it stays glued to each path and pytest then
    # fails with "file or directory not found: tests/...py" for a path that
    # looks correct in the log because the CR is invisible. Emitting bytes makes
    # the output identical on every host instead of depending on the platform's
    # newline translation.
    sys.stdout.buffer.write(b"".join(line.encode("utf-8") + b"\n" for line in lines))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
