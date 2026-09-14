"""Tests for the symlink-capability probe itself.

These are deliberately platform-agnostic: each asserts a relationship that
holds whether or not this machine can create symlinks, so the probe is
verified on Windows (where it reports False without Developer Mode) and on
POSIX (where it reports True) by the same assertions.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.symlink_support import (
    dir_links_supported,
    make_dir_link,
    requires_dir_links,
    requires_symlinks,
    symlinks_supported,
)


def test_probe_returns_a_bool() -> None:
    assert isinstance(symlinks_supported(), bool)


def test_probe_agrees_with_a_real_symlink_attempt() -> None:
    """The probe must match what actually happens, not guess from the platform."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        target = d / "t"
        target.write_text("x", encoding="utf-8")
        try:
            (d / "l").symlink_to(target)
            actually_worked = (d / "l").is_symlink()
        except (OSError, NotImplementedError, AttributeError):
            actually_worked = False

    assert symlinks_supported() is actually_worked


@requires_symlinks
def test_guarded_test_can_build_a_directory_symlink_fixture(tmp_path: Path) -> None:
    """Several guarded tests link directories, so the mark must cover that too.

    Windows treats file and directory symlinks as distinct reparse types; a
    probe that only proved file symlinks would let these fail at fixture time.
    """
    target_dir = tmp_path / "real_dir"
    target_dir.mkdir()
    (target_dir / "inside.txt").write_text("data", encoding="utf-8")

    link = tmp_path / "dir_link"
    link.symlink_to(target_dir, target_is_directory=True)

    assert link.is_symlink()
    assert link.is_dir()
    assert (link / "inside.txt").read_text(encoding="utf-8") == "data"


def test_probe_is_cached() -> None:
    """Collection-time marks call this; it must not re-probe the filesystem."""
    symlinks_supported()
    hits_before = symlinks_supported.cache_info().hits
    symlinks_supported()
    assert symlinks_supported.cache_info().hits == hits_before + 1


def test_requires_symlinks_is_a_skipif_mark_tracking_the_probe() -> None:
    assert requires_symlinks.name == "skipif"
    # skipif skips when the condition is truthy, so it must be the negation.
    assert requires_symlinks.args == (not symlinks_supported(),)
    assert "SeCreateSymbolicLinkPrivilege" in requires_symlinks.kwargs["reason"]


@requires_symlinks
def test_guarded_test_can_build_a_symlink_fixture(tmp_path: Path) -> None:
    """A test wearing the mark must never hit WinError 1314 in its fixture."""
    target = tmp_path / "real"
    target.write_text("data", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)

    assert link.is_symlink()
    assert link.read_text(encoding="utf-8") == "data"


# ---------------------------------------------------------------------------
# make_dir_link / requires_dir_links
# ---------------------------------------------------------------------------


@requires_dir_links
def test_make_dir_link_produces_a_traversable_directory_link(tmp_path: Path) -> None:
    target = tmp_path / "real_dir"
    target.mkdir()
    (target / "inside.txt").write_text("data", encoding="utf-8")

    kind = make_dir_link(tmp_path / "link", target)

    assert kind in {"symlink", "junction"}
    assert (tmp_path / "link").is_dir()
    assert (tmp_path / "link" / "inside.txt").read_text(encoding="utf-8") == "data"


@requires_dir_links
def test_make_dir_link_reaches_further_than_requires_symlinks(tmp_path: Path) -> None:
    """The whole point: a directory link is available where a symlink is not.

    On a Windows host without SeCreateSymbolicLinkPrivilege this asserts the
    junction fallback actually engaged; where symlinks work it asserts the
    preferred mechanism was used instead of needlessly shelling out.
    """
    target = tmp_path / "d"
    target.mkdir()

    kind = make_dir_link(tmp_path / "l", target)

    assert kind == ("symlink" if symlinks_supported() else "junction")
    assert dir_links_supported() is True


@requires_dir_links
def test_junction_is_a_link_to_the_shell_but_not_to_pathlib(tmp_path: Path) -> None:
    """Pin the asymmetry the helper exists for, so a future change cannot quietly
    invalidate every consumer.

    A junction satisfies ``[ -L ]`` but NOT ``Path.is_symlink()``. Consumers
    assert through the shell precisely because of this; if a Python release ever
    starts reporting junctions as symlinks, that is a behaviour change worth
    seeing here rather than as a puzzling failure in a stage2-hook test.
    """
    target = tmp_path / "d"
    target.mkdir()
    link = tmp_path / "l"
    kind = make_dir_link(link, target)

    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("sh not available")
    proc = subprocess.run(
        [shell, "-c", f'if [ -L "{link}" ]; then echo yes; else echo no; fi'],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.stdout.strip() == "yes", f"sh must see a {kind} as -L"

    if kind == "junction":
        assert link.is_symlink() is False
        assert os.path.islink(link) is False


@requires_dir_links
def test_rmtree_does_not_delete_through_a_dir_link(tmp_path: Path) -> None:
    """Safety property that makes this usable inside tmp_path at all.

    Python reports a junction as NOT a symlink, so "rmtree will step over it"
    is not obvious -- rmtree keys off the reparse-point attribute via scandir.
    If that ever changed, every consumer would start deleting its own fixture
    target, so pin it.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    make_dir_link(sandbox / "link", outside)

    shutil.rmtree(sandbox)

    assert not sandbox.exists()
    assert (outside / "precious.txt").read_text(encoding="utf-8") == "keep"
