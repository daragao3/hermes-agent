"""Symlink-capability probe for tests that must *create* a symlink.

Creating a symlink on Windows requires ``SeCreateSymbolicLinkPrivilege``,
which an ordinary process only holds when it is elevated or when Developer
Mode is enabled.  Without it ``Path.symlink_to()`` raises
``OSError: [WinError 1314] A required privilege is not held by the client``
while the test is still building its fixture — the code under test is never
reached.

Guard those tests with :data:`requires_symlinks` rather than a blanket
``os.name == "nt"`` skip.  Following and resolving symlinks works fine on
Windows (``os.path.islink`` / ``os.path.realpath`` are fully functional), so
invariants like "an atomic write must not detach a symlink" are just as real
there.  A platform skip would disable that coverage permanently, including on
Windows machines that *do* hold the privilege; a capability probe re-enables
it automatically the moment the privilege is present.

Usage::

    from tests.symlink_support import requires_symlinks

    @requires_symlinks
    def test_something_with_a_symlink(tmp_path):
        ...
"""
from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@functools.lru_cache(maxsize=1)
def symlinks_supported() -> bool:
    """Return True if this process can actually create a symlink.

    Probes by creating real symlinks in a temporary directory, because the
    answer depends on runtime privilege rather than on anything statically
    knowable — the same Windows build and Python answer differently depending
    on elevation and Developer Mode.

    Probes a *directory* symlink as well as a file one: Windows makes them
    distinct reparse types (hence ``target_is_directory``), and guarded tests
    here create both kinds.  A probe that only covered files would under-
    approximate what its consumers need.

    Fails closed: any error, or a link that does not report itself as one, is
    reported as "unsupported".  A false negative only skips a test; a false
    positive would surface as a confusing fixture-time crash.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="hermes-symlink-probe-") as td:
            probe_dir = Path(td)

            target_file = probe_dir / "target"
            target_file.write_text("probe", encoding="utf-8")
            file_link = probe_dir / "file-link"
            file_link.symlink_to(target_file)

            target_dir = probe_dir / "target-dir"
            target_dir.mkdir()
            dir_link = probe_dir / "dir-link"
            dir_link.symlink_to(target_dir, target_is_directory=True)

            return file_link.is_symlink() and dir_link.is_symlink()
    except (OSError, NotImplementedError, AttributeError):
        return False


requires_symlinks = pytest.mark.skipif(
    not symlinks_supported(),
    reason=(
        "cannot create symlinks in this process — on Windows this needs "
        "SeCreateSymbolicLinkPrivilege (enable Developer Mode or run elevated)"
    ),
)


# ---------------------------------------------------------------------------
# Directory links: reachable on Windows WITHOUT the privilege above
# ---------------------------------------------------------------------------
#
# A Windows directory JUNCTION needs no privilege at all, so a test that only
# needs "a directory that another path reaches through a link" does NOT have to
# skip here the way `requires_symlinks` does.
#
# READ THIS BEFORE REACHING FOR IT -- a junction is not a symlink to every
# observer, and the split is what makes it useful AND what makes it wrong in
# the other half of cases:
#
#   * `sh` says a junction IS a link          -- `[ -L "$p" ]` is TRUE
#   * Python says it is NOT                   -- os.path.islink() /
#                                                Path.is_symlink() are False
#
# So use this ONLY when the code under test decides "is this a link?" through
# the SHELL (or another API that honours reparse points). If the assertion is
# Path.is_symlink(), a junction fails it and you want `requires_symlinks`.
#
# Measured 2026-09-14: shutil.rmtree does NOT delete through a junction, so a
# link built inside tmp_path is safe for pytest's own cleanup. That is not
# obvious given islink() is False -- rmtree keys off the reparse-point
# attribute (FILE_ATTRIBUTE_REPARSE_POINT) via scandir, not off islink().


def make_dir_link(link: Path, target: Path) -> str:
    """Point ``link`` at directory ``target`` without elevation.

    Returns ``"symlink"`` or ``"junction"`` so a caller can assert on which
    mechanism it got. Raises ``OSError`` if neither is available; pair it with
    :data:`requires_dir_links` to skip at collection time instead.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 or not link.is_dir():
        raise OSError(
            f"neither a directory symlink nor a junction could be created at {link}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return "junction"


@functools.lru_cache(maxsize=1)
def dir_links_supported() -> bool:
    """True if :func:`make_dir_link` can build a directory link here.

    Practically always True (junctions need no privilege), but probed rather
    than assumed -- the same fail-closed reasoning as :func:`symlinks_supported`.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="hermes-dirlink-probe-") as td:
            probe = Path(td)
            target = probe / "target-dir"
            target.mkdir()
            make_dir_link(probe / "dir-link", target)
            return (probe / "dir-link").is_dir()
    except (OSError, NotImplementedError, AttributeError, subprocess.SubprocessError):
        return False


requires_dir_links = pytest.mark.skipif(
    not dir_links_supported(),
    reason="cannot create a directory symlink or junction in this process",
)
