"""Pure planning for cross-account Claude Desktop scheduled-task catalogs.

Catalog definitions may be pre-positioned in dormant Desktop roots, but dispatch
ownership is never replicated.  A handoff is two-phase: disable every old owner,
then enable the target only after a fresh scan proves no other enabled owner.
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


PORTABLE_FIELDS = (
    "id",
    "displayName",
    "cronExpression",
    "fireAt",
    "cwd",
    "model",
    "permissionMode",
    "approvedPermissions",
    "useWorktree",
    "filePath",
)
EXECUTION_FIELDS = (
    "enabled",
    "lastRunAt",
    "lastScheduledFor",
    "missedRunScanFloor",
    "notifySessionId",
)


class CatalogConflict(ValueError):
    """Catalog evidence is incomplete, malformed, or ambiguous."""


class CatalogMutationConflict(RuntimeError):
    """A planned catalog mutation no longer matches filesystem evidence."""


@dataclass(frozen=True)
class CatalogObservation:
    root_id: str
    path: Path
    byte_hash: str
    raw_bytes: bytes
    document: Mapping[str, object]
    tasks: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class CatalogScan:
    roots: Mapping[str, CatalogObservation]
    prompt_root: Path


@dataclass(frozen=True)
class CatalogMutation:
    root_id: str
    expected_before_hash: str
    after_bytes: bytes
    task_ids: tuple[str, ...]


@dataclass(frozen=True)
class CatalogMutationResult:
    applied: bool
    byte_hash: str


@dataclass(frozen=True)
class CatalogPlan:
    scan: CatalogScan
    phase: str
    mutations: tuple[CatalogMutation, ...]
    pending_active_roots: tuple[str, ...]
    conflicts: tuple[tuple[str, str], ...]


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogConflict(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_document(raw: bytes, path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    try:
        document = json.loads(
            raw.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CatalogConflict(f"invalid JSON constant: {value}")
            ),
        )
    except CatalogConflict:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogConflict(f"invalid scheduled-task catalog: {path}") from exc
    if not isinstance(document, dict):
        raise CatalogConflict(f"scheduled-task catalog is not an object: {path}")
    rows = document.get("scheduledTasks")
    if not isinstance(rows, list):
        raise CatalogConflict(f"scheduledTasks is not a list: {path}")
    tasks: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise CatalogConflict(f"scheduled task has invalid id: {path}")
        task_id = row["id"]
        if task_id in tasks:
            raise CatalogConflict(f"duplicate scheduled task id {task_id}: {path}")
        tasks[task_id] = row
    return document, tasks


def scan_catalogs(
    roots: Mapping[str, Path] | Iterable[tuple[str, Path]], *, prompt_root: Path
) -> CatalogScan:
    observations: dict[str, CatalogObservation] = {}
    pairs = roots.items() if isinstance(roots, Mapping) else roots
    for root_id, path in pairs:
        if not root_id or root_id in observations:
            raise CatalogConflict(f"invalid or duplicate root id: {root_id!r}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CatalogConflict(f"scheduled-task catalog unavailable: {path}") from exc
        document, tasks = _parse_document(raw, path)
        observations[root_id] = CatalogObservation(
            root_id=root_id,
            path=path,
            byte_hash=hashlib.sha256(raw).hexdigest(),
            raw_bytes=raw,
            document=MappingProxyType(document),
            tasks=MappingProxyType(
                {task_id: MappingProxyType(task) for task_id, task in tasks.items()}
            ),
        )
    if not observations:
        raise CatalogConflict("no scheduled-task catalogs enrolled")
    return CatalogScan(MappingProxyType(observations), prompt_root)


def _portable(task: Mapping[str, object]) -> dict[str, object]:
    return {field: task.get(field) for field in PORTABLE_FIELDS}


def _portable_canonical(task: Mapping[str, object]) -> str:
    return json.dumps(_portable(task), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prompt_exists(scan: CatalogScan, task_id: str) -> bool:
    return (scan.prompt_root / task_id / "SKILL.md").is_file()


def _render_document(
    observation: CatalogObservation, tasks: Mapping[str, Mapping[str, object]]
) -> bytes:
    document = json.loads(json.dumps(dict(observation.document), ensure_ascii=False))
    original = observation.document["scheduledTasks"]
    original_order = [row["id"] for row in original if isinstance(row, dict)]  # type: ignore[union-attr]
    ordered = [tasks[task_id] for task_id in original_order if task_id in tasks]
    ordered.extend(tasks[task_id] for task_id in sorted(set(tasks) - set(original_order)))
    document["scheduledTasks"] = [dict(task) for task in ordered]
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _mutation(
    observation: CatalogObservation,
    tasks: Mapping[str, Mapping[str, object]],
    changed: Iterable[str],
) -> CatalogMutation | None:
    changed_ids = tuple(sorted(changed))
    if not changed_ids:
        return None
    after = _render_document(observation, tasks)
    if after == observation.raw_bytes:
        return None
    return CatalogMutation(
        root_id=observation.root_id,
        expected_before_hash=observation.byte_hash,
        after_bytes=after,
        task_ids=changed_ids,
    )


def build_replication_plan(
    scan: CatalogScan, *, source_root_id: str, active_root_id: str | None
) -> CatalogPlan:
    source = scan.roots.get(source_root_id)
    if source is None:
        raise CatalogConflict("source catalog is not enrolled")
    if active_root_id is not None and active_root_id not in scan.roots:
        raise CatalogConflict("active catalog is not enrolled")

    conflicts: list[tuple[str, str]] = []
    mutations: list[CatalogMutation] = []
    pending: list[str] = []
    portable = {
        task_id: task
        for task_id, task in source.tasks.items()
        if _prompt_exists(scan, task_id)
    }
    conflicts.extend(
        (task_id, "prompt_missing")
        for task_id in source.tasks
        if task_id not in portable
    )

    for root_id, observation in scan.roots.items():
        if root_id == source_root_id:
            continue
        target_tasks = {task_id: dict(task) for task_id, task in observation.tasks.items()}
        changed: list[str] = []
        for task_id, source_task in portable.items():
            current = target_tasks.get(task_id)
            if current is None:
                replacement = _portable(source_task)
                replacement.update({field: None for field in EXECUTION_FIELDS})
                replacement["enabled"] = False
                target_tasks[task_id] = replacement
                changed.append(task_id)
                continue
            replacement = dict(current)
            for field in PORTABLE_FIELDS:
                replacement[field] = source_task.get(field)
            if replacement != current:
                target_tasks[task_id] = replacement
                changed.append(task_id)
        mutation = _mutation(observation, target_tasks, changed)
        if mutation is None:
            continue
        if root_id == active_root_id:
            pending.append(root_id)
        else:
            mutations.append(mutation)
    return CatalogPlan(
        scan=scan,
        phase="replicate_disabled",
        mutations=tuple(mutations),
        pending_active_roots=tuple(sorted(pending)),
        conflicts=tuple(sorted(conflicts)),
    )


def _source_tasks_for_handoff(
    scan: CatalogScan, source_root_id: str, task_ids: tuple[str, ...]
) -> dict[str, Mapping[str, object]]:
    source = scan.roots.get(source_root_id)
    if source is None:
        raise CatalogConflict("source catalog is not enrolled")
    result: dict[str, Mapping[str, object]] = {}
    for task_id in task_ids:
        task = source.tasks.get(task_id)
        if task is None:
            raise CatalogConflict(f"source task is absent: {task_id}")
        if not _prompt_exists(scan, task_id):
            raise CatalogConflict(f"source task prompt is missing: {task_id}")
        result[task_id] = task
    return result


def build_handoff_plan(
    scan: CatalogScan,
    *,
    source_root_id: str,
    target_root_id: str,
    task_ids: Iterable[str],
) -> CatalogPlan:
    if source_root_id == target_root_id:
        raise CatalogConflict("source and target catalogs must differ")
    target = scan.roots.get(target_root_id)
    if target is None:
        raise CatalogConflict("target catalog is not enrolled")
    selected = tuple(dict.fromkeys(task_ids))
    if not selected:
        raise CatalogConflict("handoff requires at least one task id")
    source_tasks = _source_tasks_for_handoff(scan, source_root_id, selected)

    enabled_old = {
        root_id
        for root_id, observation in scan.roots.items()
        if root_id != target_root_id
        and any(task.get("enabled") is True for task in observation.tasks.values())
    }
    if enabled_old:
        mutations: list[CatalogMutation] = []
        for root_id in sorted(enabled_old):
            observation = scan.roots[root_id]
            tasks = {task_id: dict(task) for task_id, task in observation.tasks.items()}
            changed: list[str] = []
            for task_id, task in tasks.items():
                if task.get("enabled") is True:
                    task["enabled"] = False
                    changed.append(task_id)
            mutation = _mutation(observation, tasks, changed)
            if mutation is not None:
                mutations.append(mutation)
        return CatalogPlan(scan, "disable_old_owners", tuple(mutations), (), ())

    target_tasks = {task_id: dict(task) for task_id, task in target.tasks.items()}
    for task_id, source_task in source_tasks.items():
        replacement = _portable(source_task)
        for field in EXECUTION_FIELDS:
            replacement[field] = source_task.get(field)
        replacement["enabled"] = True
        replacement["notifySessionId"] = None
        target_tasks[task_id] = replacement
    mutation = _mutation(target, target_tasks, selected)
    return CatalogPlan(
        scan=scan,
        phase="enable_target",
        mutations=() if mutation is None else (mutation,),
        pending_active_roots=(),
        conflicts=(),
    )


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")


def apply_catalog_mutation(
    scan: CatalogScan, mutation: CatalogMutation
) -> CatalogMutationResult:
    observation = scan.roots.get(mutation.root_id)
    if observation is None:
        raise CatalogMutationConflict("mutation root is not enrolled")
    path = observation.path
    try:
        current = path.read_bytes()
    except OSError as exc:
        raise CatalogMutationConflict(f"catalog unavailable: {path}") from exc
    if hashlib.sha256(current).hexdigest() != mutation.expected_before_hash:
        raise CatalogMutationConflict(f"catalog does not match expected hash: {path}")
    temporary = _temporary_path(path)
    try:
        with temporary.open("xb") as handle:
            handle.write(mutation.after_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != current:
            raise CatalogMutationConflict(f"catalog changed before replace: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != mutation.after_bytes:
        raise CatalogMutationConflict("patched catalog failed immediate verification")
    return CatalogMutationResult(True, hashlib.sha256(mutation.after_bytes).hexdigest())
