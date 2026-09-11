"""Guarded two-phase transfer of Desktop scheduled-task dispatch ownership."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .desktop_scheduled_catalog import (
    CatalogConflict,
    CatalogMutationConflict,
    apply_catalog_mutation,
    build_handoff_plan,
    scan_catalogs,
)

LANE = "scheduled_catalog"
GROUPING_VERSION = 1
OWNER_STATE_KEY = "session-bridge:desktop-scheduled-catalog:owner"
PENDING_HANDOFF_STATE_KEY = "session-bridge:desktop-scheduled-catalog:pending-handoff"
CONFIRMATION = "TRANSFER_DESKTOP_SCHEDULED_TASK_OWNER"


class DesktopScheduledHandoff:
    def __init__(
        self,
        store: Any,
        *,
        catalogs: Mapping[str, Path],
        prompt_root: Path,
        backup_root: Path,
        live_target: str | None,
        live_status: str = "one",
        clock: callable = time.time,
    ) -> None:
        self._store = store
        self._catalogs = dict(catalogs)
        self._prompt_root = prompt_root
        self._backup_root = backup_root
        self._live_target = live_target
        self._live_status = live_status
        self._clock = clock

    def plan(
        self, *, source_root_id: str, target_root_id: str, task_ids: Iterable[str]
    ) -> dict[str, object]:
        selected = tuple(dict.fromkeys(task_ids))
        scan = scan_catalogs(self._catalogs, prompt_root=self._prompt_root)
        source = scan.roots.get(source_root_id)
        if source is None:
            raise CatalogConflict("source catalog is not enrolled")
        pending = self._store.get_state(PENDING_HANDOFF_STATE_KEY)
        enabled_source = tuple(
            sorted(
                task_id
                for task_id, task in source.tasks.items()
                if task.get("enabled") is True
            )
        )
        if enabled_source and tuple(sorted(selected)) != enabled_source:
            raise CatalogConflict("handoff must include the complete enabled source set")
        plan = build_handoff_plan(
            scan,
            source_root_id=source_root_id,
            target_root_id=target_root_id,
            task_ids=selected,
        )
        if plan.phase == "disable_old_owners":
            if self._live_status != "one" or self._live_target != target_root_id:
                raise CatalogConflict("target is not the one live Desktop catalog")
        else:
            if self._live_status != "none":
                raise CatalogConflict("Desktop must be provably closed before target enable")
            expected = {
                "source_root_id": source_root_id,
                "target_root_id": target_root_id,
                "task_ids": list(selected),
            }
            if not isinstance(pending, Mapping) or any(
                pending.get(key) != value for key, value in expected.items()
            ):
                raise CatalogConflict("verified pending handoff is required")
        return {
            "phase": plan.phase,
            "source_root_id": source_root_id,
            "target_root_id": target_root_id,
            "task_ids": list(selected),
            "mutations": [
                {
                    "root_id": mutation.root_id,
                    "expected_before_hash": mutation.expected_before_hash,
                    "after_hash": hashlib.sha256(mutation.after_bytes).hexdigest(),
                    "task_ids": mutation.task_ids,
                }
                for mutation in plan.mutations
            ],
            "plan": plan,
        }

    def apply(
        self,
        *,
        source_root_id: str,
        target_root_id: str,
        task_ids: Iterable[str],
        confirmation: str,
    ) -> dict[str, object]:
        if confirmation != CONFIRMATION:
            raise CatalogConflict("scheduled handoff confirmation is required")
        selected = tuple(dict.fromkeys(task_ids))
        planned = self.plan(
            source_root_id=source_root_id,
            target_root_id=target_root_id,
            task_ids=selected,
        )
        plan = planned.pop("plan")
        pending = self._store.pending_desktop_surface_run(LANE)
        if pending is not None:
            self._store.finish_desktop_surface_run(
                LANE, pending["id"], "abandoned", resolution="recovered_by_replan"
            )
        run_id = str(uuid.uuid4())
        payload = json.dumps(
            {key: value for key, value in planned.items() if key != "mutations"}
            | {"mutations": planned["mutations"]},
            ensure_ascii=False,
            sort_keys=True,
            default=list,
        )
        self._store.stage_desktop_surface_run(
            LANE, run_id, GROUPING_VERSION, payload
        )
        if plan.phase == "disable_old_owners":
            self._store.set_state(
                PENDING_HANDOFF_STATE_KEY,
                {
                    "source_root_id": source_root_id,
                    "target_root_id": target_root_id,
                    "task_ids": list(selected),
                    "at": float(self._clock()),
                },
            )
        backup = self._backup(plan, run_id)
        applied = 0
        try:
            for mutation in plan.mutations:
                apply_catalog_mutation(plan.scan, mutation)
                applied += 1
            fresh = scan_catalogs(self._catalogs, prompt_root=self._prompt_root)
            self._verify_phase(plan.phase, fresh, target_root_id, selected)
        except (CatalogConflict, CatalogMutationConflict, OSError, ValueError) as exc:
            self._store.finish_desktop_surface_run(
                LANE, run_id, "abandoned", resolution=f"apply_failed:{type(exc).__name__}"
            )
            raise
        self._store.finish_desktop_surface_run(
            LANE, run_id, "committed", resolution=plan.phase
        )
        if plan.phase == "enable_target":
            self._store.set_state(
                OWNER_STATE_KEY,
                {
                    "root_id": target_root_id,
                    "source_root_id": source_root_id,
                    "at": float(self._clock()),
                },
            )
            self._store.set_state(PENDING_HANDOFF_STATE_KEY, {"completed": True, "at": float(self._clock())})
        return {
            **planned,
            "status": "applied",
            "run_id": run_id,
            "applied": applied,
            "backup": str(backup),
        }

    def _backup(self, plan: Any, run_id: str) -> Path:
        destination = self._backup_root / run_id
        destination.mkdir(parents=True, exist_ok=False)
        manifest: dict[str, object] = {"files": []}
        for mutation in plan.mutations:
            source = plan.scan.roots[mutation.root_id].path
            safe_root = hashlib.sha256(mutation.root_id.encode("utf-8")).hexdigest()[:16]
            target = destination / f"{safe_root}.scheduled-tasks.json"
            shutil.copyfile(source, target)
            manifest["files"].append(
                {
                    "root_id": mutation.root_id,
                    "source": str(source),
                    "backup": str(target),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination

    @staticmethod
    def _verify_phase(
        phase: str, scan: Any, target_root_id: str, task_ids: Iterable[str]
    ) -> None:
        selected = tuple(task_ids)
        for task_id in selected:
            owners = [
                root_id
                for root_id, root in scan.roots.items()
                if root.tasks.get(task_id, {}).get("enabled") is True
            ]
            if phase == "disable_old_owners" and any(
                owner != target_root_id for owner in owners
            ):
                raise CatalogConflict(f"old owner still enabled for task {task_id}")
            if phase == "enable_target" and owners != [target_root_id]:
                raise CatalogConflict(f"target is not sole owner for task {task_id}")
