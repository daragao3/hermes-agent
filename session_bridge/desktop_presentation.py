"""Pure reconciliation planning for Claude Desktop pinned presentation state.

Session records carry ``isStarred``, but the Epitaxy sidebar renders its Pinned
section from two root-level preference lists in ``claude_desktop_config.json``.
This module reconciles those lists without touching session records and never
writes a config owned by the currently running Desktop root.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping


class PresentationConflict(ValueError):
    """Presentation state could not be read or safely interpreted."""


class PresentationMutationConflict(RuntimeError):
    """A planned config mutation no longer matches filesystem evidence."""


@dataclass(frozen=True)
class PresentationState:
    starred: tuple[str, ...]
    pinned_order: tuple[str, ...]

    @property
    def canonical(self) -> str:
        return json.dumps(
            {"starred": self.starred, "pinned_order": self.pinned_order},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @property
    def empty(self) -> bool:
        return not self.starred and not self.pinned_order


@dataclass(frozen=True)
class PresentationRootObservation:
    root_id: str
    config_path: Path
    sessions_path: Path
    byte_hash: str
    raw_bytes: bytes
    config: Mapping[str, object]
    state: PresentationState


@dataclass(frozen=True)
class PresentationScan:
    roots: Mapping[str, PresentationRootObservation]


@dataclass(frozen=True)
class PresentationMutation:
    root_id: str
    expected_before_hash: str
    after_bytes: bytes


@dataclass(frozen=True)
class PresentationMutationResult:
    applied: bool
    byte_hash: str


@dataclass(frozen=True)
class PresentationPlan:
    scan: PresentationScan
    desired: PresentationState | None
    mutations: tuple[PresentationMutation, ...]
    pending_active_roots: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class PresentationVerification:
    ok: bool
    failures: tuple[str, ...]


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PresentationConflict(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_config(raw: bytes, path: Path) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PresentationConflict(f"invalid JSON constant: {value}")
            ),
        )
    except PresentationConflict:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PresentationConflict(f"invalid Desktop config: {path}") from exc
    if not isinstance(value, dict):
        raise PresentationConflict(f"Desktop config is not an object: {path}")
    return value


def _list_of_unique_strings(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PresentationConflict(f"{field} must be a list of non-empty strings")
    items = tuple(value)
    if len(set(items)) != len(items):
        raise PresentationConflict(f"{field} contains duplicate entries")
    return items


def _extract_state(config: Mapping[str, object], sessions_path: Path) -> PresentationState:
    try:
        preferences = config["preferences"]
        epitaxy = preferences["epitaxyPrefs"]  # type: ignore[index]
        starred_raw = epitaxy["starred-local-code-sessions"]  # type: ignore[index]
        local_slice = epitaxy["dframe-local-slice"]  # type: ignore[index]
        order_raw = local_slice["pinnedOrder"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise PresentationConflict("Desktop config lacks Epitaxy pin state") from exc

    starred = _list_of_unique_strings(starred_raw, field="starred-local-code-sessions")
    order = _list_of_unique_strings(order_raw, field="pinnedOrder")
    if any(not item.startswith("code:local_") for item in order):
        raise PresentationConflict("pinnedOrder contains a non-Code session entry")
    ordered_ids = tuple(item.removeprefix("code:") for item in order)
    if set(starred) != set(ordered_ids):
        raise PresentationConflict("Pinned presentation lists have different membership")

    def _known(session_id: str) -> bool:
        direct = sessions_path / f"{session_id}.json"
        if direct.is_file():
            return True
        try:
            candidates = sessions_path.glob(f"*/*/{session_id}.json")
            return any(
                candidate.is_file()
                and not any(
                    marker in part.casefold()
                    for part in candidate.parts
                    for marker in ("junction-backup", "recovery-backup", ".real-")
                )
                for candidate in candidates
            )
        except OSError:
            return False

    unknown = sorted(session_id for session_id in starred if not _known(session_id))
    if unknown:
        raise PresentationConflict(f"Pinned presentation references unknown session: {unknown[0]}")
    return PresentationState(starred=starred, pinned_order=order)


def scan_presentation_roots(
    roots: Iterable[tuple[str, Path, Path]],
) -> PresentationScan:
    observations: dict[str, PresentationRootObservation] = {}
    for root_id, config_path, sessions_path in roots:
        if not root_id or root_id in observations:
            raise PresentationConflict(f"invalid or duplicate root id: {root_id!r}")
        try:
            raw = config_path.read_bytes()
        except OSError as exc:
            raise PresentationConflict(f"Desktop config unavailable: {config_path}") from exc
        config = _parse_config(raw, config_path)
        state = _extract_state(config, sessions_path)
        observations[root_id] = PresentationRootObservation(
            root_id=root_id,
            config_path=config_path,
            sessions_path=sessions_path,
            byte_hash=hashlib.sha256(raw).hexdigest(),
            raw_bytes=raw,
            config=MappingProxyType(config),
            state=state,
        )
    if not observations:
        raise PresentationConflict("no Desktop presentation roots enrolled")
    return PresentationScan(roots=MappingProxyType(observations))


def _replace_state(config: Mapping[str, object], state: PresentationState) -> bytes:
    cloned = json.loads(json.dumps(dict(config), ensure_ascii=False))
    epitaxy = cloned["preferences"]["epitaxyPrefs"]
    epitaxy["starred-local-code-sessions"] = list(state.starred)
    epitaxy["dframe-local-slice"]["pinnedOrder"] = list(state.pinned_order)
    return (json.dumps(cloned, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _bootstrap_desired(scan: PresentationScan) -> tuple[PresentationState | None, tuple[str, ...]]:
    nonempty = {root.state.canonical: root.state for root in scan.roots.values() if not root.state.empty}
    if len(nonempty) == 1:
        return next(iter(nonempty.values())), ()
    if len(nonempty) > 1:
        return None, ("bootstrap_divergence",)
    states = {root.state.canonical: root.state for root in scan.roots.values()}
    if len(states) == 1:
        return next(iter(states.values())), ()
    return None, ("bootstrap_divergence",)


def build_presentation_plan(
    scan: PresentationScan,
    *,
    baselines: Mapping[str, str],
    active_root_id: str | None,
) -> PresentationPlan:
    if active_root_id is not None and active_root_id not in scan.roots:
        raise PresentationConflict("active Desktop root is not enrolled")

    if not baselines:
        desired, conflicts = _bootstrap_desired(scan)
    else:
        missing_roots = set(baselines) - set(scan.roots)
        if missing_roots:
            raise PresentationConflict("a baselined presentation root disappeared")
        accepted_values = set(baselines.values())
        new_roots = set(scan.roots) - set(baselines)
        if new_roots:
            if len(accepted_values) != 1:
                raise PresentationConflict("presentation baselines diverge before root adoption")
            desired = next(
                root.state
                for root_id, root in scan.roots.items()
                if root_id in baselines
                and root.state.canonical == next(iter(accepted_values))
            )
            conflicts = ()
            changed = {}
        else:
            changed = {
                root_id: root.state
                for root_id, root in scan.roots.items()
                if root.state.canonical != baselines[root_id]
            }
        if new_roots:
            pass
        elif not changed:
            accepted = {value for value in baselines.values()}
            if len(accepted) != 1:
                desired, conflicts = None, ("baseline_divergence",)
            else:
                canonical = next(iter(accepted))
                desired = next(root.state for root in scan.roots.values() if root.state.canonical == canonical)
                conflicts = ()
        elif len({state.canonical for state in changed.values()}) == 1:
            desired, conflicts = next(iter(changed.values())), ()
        else:
            desired, conflicts = None, ("concurrent_divergence",)

    if desired is None:
        return PresentationPlan(scan, None, (), (), conflicts)

    mutations: list[PresentationMutation] = []
    pending: list[str] = []
    for root_id, root in scan.roots.items():
        if root.state.canonical == desired.canonical:
            continue
        if root_id == active_root_id:
            pending.append(root_id)
            continue
        mutations.append(
            PresentationMutation(
                root_id=root_id,
                expected_before_hash=root.byte_hash,
                after_bytes=_replace_state(root.config, desired),
            )
        )
    return PresentationPlan(
        scan=scan,
        desired=desired,
        mutations=tuple(mutations),
        pending_active_roots=tuple(sorted(pending)),
        conflicts=conflicts,
    )


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")


def apply_presentation_mutation(
    scan: PresentationScan, mutation: PresentationMutation
) -> PresentationMutationResult:
    root = scan.roots.get(mutation.root_id)
    if root is None:
        raise PresentationMutationConflict("mutation root is not enrolled")
    path = root.config_path
    try:
        current = path.read_bytes()
    except OSError as exc:
        raise PresentationMutationConflict(f"config unavailable: {path}") from exc
    if hashlib.sha256(current).hexdigest() != mutation.expected_before_hash:
        raise PresentationMutationConflict(f"config does not match expected hash: {path}")

    temporary = _temporary_path(path)
    try:
        with temporary.open("xb") as handle:
            handle.write(mutation.after_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != current:
            raise PresentationMutationConflict(f"config changed before replace: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != mutation.after_bytes:
        raise PresentationMutationConflict("patched config failed immediate verification")
    return PresentationMutationResult(
        applied=True,
        byte_hash=hashlib.sha256(mutation.after_bytes).hexdigest(),
    )


def verify_presentation_plan(
    plan: PresentationPlan, observed: PresentationScan
) -> PresentationVerification:
    if set(observed.roots) != set(plan.scan.roots):
        return PresentationVerification(False, ("root_set_changed",))
    if plan.desired is None:
        return PresentationVerification(False, plan.conflicts or ("no_desired_state",))
    failures = tuple(
        root_id
        for root_id, root in observed.roots.items()
        if root.state.canonical != plan.desired.canonical
        and root_id not in plan.pending_active_roots
    )
    return PresentationVerification(not failures, failures)
