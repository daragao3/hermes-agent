"""Discovery of real Claude Desktop roots and the one process-owned root."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .mirror_float import discover_ccd_convergence_roots

_BACKUP_MARKERS = ("junction-backup", "recovery-backup", ".real-")


def default_user_data_dirs() -> tuple[Path, ...]:
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        roots.append(Path(appdata) / "Claude")
    if local_appdata:
        roots.append(Path(local_appdata) / "Claude-3p")
    return tuple(roots)


def _root_id(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def discover_presentation_roots(
    user_data_dirs: Iterable[Path] | None = None,
) -> dict[str, tuple[Path, Path]]:
    roots: dict[str, tuple[Path, Path]] = {}
    for user_data in tuple(user_data_dirs or default_user_data_dirs()):
        config = user_data / "claude_desktop_config.json"
        sessions = user_data / "claude-code-sessions"
        if config.is_file() and sessions.is_dir():
            roots[_root_id(user_data)] = (config, sessions)
    return roots


def discover_scheduled_catalogs(
    user_data_dirs: Iterable[Path] | None = None,
) -> dict[str, Path]:
    catalogs: dict[str, Path] = {}
    for leaf in discover_ccd_convergence_roots(user_data_dirs):
        path = leaf / "scheduled-tasks.json"
        if path.is_file():
            catalogs[_root_id(leaf)] = path
    return catalogs


@dataclass(frozen=True)
class LiveRootResult:
    status: str
    root_id: str | None


def detect_live_user_data_root(
    user_data_dirs: Iterable[Path] | None = None,
) -> LiveRootResult:
    """Classify process ownership as one, none, ambiguous, or unavailable."""
    candidates = tuple(user_data_dirs or default_user_data_dirs())
    canonical = {_root_id(root): root for root in candidates}
    try:
        import psutil
    except ImportError:
        return LiveRootResult("unavailable", None)
    seen: set[str] = set()
    claude_seen = False
    unreadable_claude = False
    try:
        processes = psutil.process_iter(["name", "cmdline"])
        for process in processes:
            try:
                if str(process.info.get("name") or "").casefold() != "claude.exe":
                    continue
                claude_seen = True
                raw_command = process.info.get("cmdline")
                if not raw_command:
                    unreadable_claude = True
                    continue
                command = [str(part) for part in raw_command]
            except (psutil.Error, OSError):
                unreadable_claude = True
                continue
            for index, argument in enumerate(command):
                value: str | None = None
                if argument.casefold().startswith("--user-data-dir="):
                    value = argument.split("=", 1)[1]
                elif argument.casefold() == "--user-data-dir" and index + 1 < len(command):
                    value = command[index + 1]
                if value:
                    key = _root_id(Path(value.strip('"')))
                    if key in canonical:
                        seen.add(key)
    except (psutil.Error, OSError):
        return LiveRootResult("unavailable", None)
    if len(seen) == 1 and not unreadable_claude:
        return LiveRootResult("one", next(iter(seen)))
    if len(seen) > 1:
        return LiveRootResult("ambiguous", None)
    if claude_seen or unreadable_claude:
        return LiveRootResult("unavailable", None)
    return LiveRootResult("none", None)


def live_user_data_root(
    user_data_dirs: Iterable[Path] | None = None,
) -> str | None:
    return detect_live_user_data_root(user_data_dirs).root_id


def active_user_data_root_for_writes(
    user_data_dirs: Iterable[Path] | None = None,
) -> str | None:
    """Return the live root, None only for proven absence, else fail closed."""
    result = detect_live_user_data_root(user_data_dirs)
    if result.status == "one":
        return result.root_id
    if result.status == "none":
        return None
    raise RuntimeError(f"Desktop process ownership is {result.status}")


def user_data_root_for_catalog(catalog: Path) -> Path | None:
    for parent in catalog.parents:
        if parent.name.casefold() in {"claude", "claude-3p"}:
            return parent
    return None


def catalog_root_for_user_data(
    catalogs: dict[str, Path], user_data_root_id: str | None
) -> str | None:
    if user_data_root_id is None:
        return None
    candidates = [
        (root_id, catalog, user_data)
        for root_id, catalog in catalogs.items()
        if (user_data := user_data_root_for_catalog(catalog)) is not None
        and _root_id(user_data) == user_data_root_id
    ]
    if len(candidates) == 1:
        return candidates[0][0]
    if not candidates:
        return None
    user_data = candidates[0][2]
    try:
        document = json.loads((user_data / "config.json").read_text(encoding="utf-8-sig"))
        account = document.get("lastKnownAccountUuid")
    except (OSError, ValueError, AttributeError):
        return None
    matches = [
        root_id
        for root_id, catalog, _ in candidates
        if len(catalog.parents) >= 2 and catalog.parents[1].name == account
    ]
    return matches[0] if len(matches) == 1 else None
