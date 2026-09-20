"""Stable opaque identity shared by every profile in one Hermes install."""

from __future__ import annotations

import contextlib
import enum
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Optional
import uuid

from hermes_constants import get_default_hermes_root

_INSTALL_ID_FILENAME = "install_id"
_INSTALL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_INSTALL_ID_CACHE: dict[str, Optional[str]] = {"root": None, "value": None}
_INSTALL_ID_LOCK, _INSTALL_ID_PUBLICATION_LOCK = threading.Lock(), threading.Lock()
# A publication's rename and a lockless fast-path read of the same file exclude each other on
# Windows; either side can lose the instant, so the loser waits the other out rather than failing.
_PUBLISH_CONTENTION_TIMEOUT, _PUBLISH_CONTENTION_POLL = 1.0, 0.005


class _Read(enum.Enum):
    """What a read of the id file licenses the caller to do next."""

    USE = "use"                # a valid id is present
    MINT = "mint"              # missing or malformed: publishing over it is correct
    UNREADABLE = "unreadable"  # the read itself failed: nothing is known about the file yet


@contextlib.contextmanager
def _install_id_file_lock(root: Path):
    """Serialize identity publication across processes on POSIX and Windows."""
    fd = os.open(root / ".install_id.lock", os.O_RDWR | os.O_CREAT, 0o600)
    windows = os.name == "nt"
    try:
        if windows:
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if windows:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _fsync_directory(path: Path) -> None:
    """Best-effort durability for the directory entry after replace."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _read_existing(path: Path) -> tuple[Optional[str], _Read]:
    """``(valid id or None, verdict)`` — mint on a missing or malformed file, never on a read failure."""
    try:
        existing = path.read_text(encoding="utf-8").strip().lower()
    except FileNotFoundError:
        return None, _Read.MINT
    except (OSError, UnicodeDecodeError):
        return None, _Read.UNREADABLE
    return (existing, _Read.USE) if _INSTALL_ID_RE.fullmatch(existing) else (None, _Read.MINT)


def _publish(tmp_name: str, path: Path) -> None:
    """Swap the written id into place, waiting out a fast-path reader that holds the destination.

    Windows refuses the rename while any handle on the destination is open, and a fast-path read
    takes one without the publication locks, so this contention is transient by construction.
    """
    deadline = time.monotonic() + _PUBLISH_CONTENTION_TIMEOUT
    while True:
        try:
            os.replace(tmp_name, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_PUBLISH_CONTENTION_POLL)


def read_or_create_install_id(root: Path | None = None) -> Optional[str]:
    """Read or atomically mint the opaque id for the physical install.

    ``None`` = neither readable nor persistable; an ephemeral id would violate the authority/registry contract.
    """
    root = get_default_hermes_root() if root is None else root
    path = root / _INSTALL_ID_FILENAME
    existing, verdict = _read_existing(path)
    if verdict is _Read.USE:
        return existing
    try:
        root.mkdir(parents=True, exist_ok=True)
        # Windows byte-range locks can report a same-process conflict instead of waiting for another
        # thread: serialize threads here, then keep the file lock as the cross-process publication fence.
        with _INSTALL_ID_PUBLICATION_LOCK, _install_id_file_lock(root):
            # An UNREADABLE fast-path read decides nothing: both locks exclude every publisher, so
            # a read that merely collided with one succeeds here and only a lasting failure is fatal.
            existing, verdict = _read_existing(path)
            if verdict is _Read.USE:
                return existing
            if verdict is _Read.UNREADABLE:
                return None
            fd, tmp_name = tempfile.mkstemp(dir=str(root), prefix=".install_id-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(uuid.uuid4().hex + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                _publish(tmp_name, path)
                _fsync_directory(root)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                raise
            committed = path.read_text(encoding="utf-8").strip().lower()
            return committed if _INSTALL_ID_RE.fullmatch(committed) else None
    except OSError:
        return None


def get_install_id(*, cache: dict[str, Optional[str]] | None = None) -> Optional[str]:
    """Return the process-cached stable id for the active Hermes root."""
    root = get_default_hermes_root()
    root_key = str(root)
    target_cache = _INSTALL_ID_CACHE if cache is None else cache

    def _cached() -> Optional[str]:
        cached = target_cache.get("value")
        return cached if cached and target_cache.get("root") in (None, root_key) else None

    if value := _cached():
        return value
    with _INSTALL_ID_LOCK:
        if value := _cached():
            return value
        value = read_or_create_install_id(root)
        if value:
            target_cache["root"] = root_key
            target_cache["value"] = value
        return value


__all__ = ["get_install_id", "read_or_create_install_id"]
