"""Spell Windows-drive test paths as absolute paths on the running host.

Session-bridge fixtures were written on Windows and use drive-rooted literals
(``"C:/work/active"``) wherever a provider hands back an absolute cwd or file
path. The product validates those with the host's own path rules
(``Path(value).is_absolute()``), so on POSIX a ``C:/...`` spelling is a
*relative* path and every fixture row is rejected as invalid before the
behaviour under test is reached.

``native_path`` keeps the literal byte-for-byte on Windows (so the Windows lane
still exercises exactly what it always did) and drops the drive on POSIX
(``"C:/work/active"`` -> ``"/work/active"``). Only a leading ``X:/`` is
rewritten; anything else -- relative paths, backslash spellings used by the
Windows-only equivalence tests -- is returned unchanged.
"""

from __future__ import annotations

import re
import sys
from typing import Any

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:(?=/)")


def native_path(value: str) -> str:
    if sys.platform == "win32":
        return value
    return _DRIVE_PREFIX.sub("", value, count=1)


def native_paths(value: Any) -> Any:
    """Apply ``native_path`` to every string inside a JSON-shaped value."""

    if isinstance(value, str):
        return native_path(value)
    if isinstance(value, list):
        return [native_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: native_paths(item) for key, item in value.items()}
    return value
