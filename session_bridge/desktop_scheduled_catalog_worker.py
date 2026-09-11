"""Passive disabled-definition replication for Desktop scheduled catalogs."""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .desktop_scheduled_catalog import (
    CatalogConflict,
    CatalogMutationConflict,
    apply_catalog_mutation,
    build_replication_plan,
    scan_catalogs,
)

LANE = "scheduled_catalog"
GROUPING_VERSION = 1
SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY = (
    "session-bridge:desktop-scheduled-catalog:worker-heartbeat"
)


class DesktopScheduledCatalogSyncWorker:
    def __init__(
        self,
        store: Any,
        *,
        catalogs: Mapping[str, Path],
        source_root: Callable[[], str | None],
        active_root: Callable[[], str | None],
        prompt_root: Path,
        run_min_interval_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not catalogs:
            raise ValueError("scheduled catalogs must not be empty")
        interval = float(run_min_interval_seconds)
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("run_min_interval_seconds must be finite and non-negative")
        self._store = store
        self._catalogs = dict(catalogs)
        self._source_root = source_root
        self._active_root = active_root
        self._prompt_root = prompt_root
        self._interval = interval
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._last_run_at: float | None = None

    def _scan(self):
        return scan_catalogs(self._catalogs, prompt_root=self._prompt_root)

    def run_once(self) -> dict[str, int]:
        counters = {
            "examined": len(self._catalogs),
            "patched": 0,
            "raced": 0,
            "conflicts": 0,
            "pending_active": 0,
            "scan_failed": 0,
            "recovered_runs": 0,
            "throttled": 0,
        }
        now = self._monotonic()
        if self._last_run_at is not None and now - self._last_run_at < self._interval:
            counters["throttled"] = 1
            return counters
        self._last_run_at = now

        pending = self._store.pending_desktop_surface_run(LANE)
        if pending is not None:
            self._store.finish_desktop_surface_run(
                LANE, pending["id"], "abandoned", resolution="recovered_by_replan"
            )
            counters["recovered_runs"] = 1
        try:
            source = self._source_root()
            active = self._active_root()
            if source is None or source not in self._catalogs:
                raise CatalogConflict("source catalog is not enrolled")
            if active is not None and active not in self._catalogs:
                raise CatalogConflict("active catalog is not enrolled")
            scan = self._scan()
            plan = build_replication_plan(
                scan, source_root_id=source, active_root_id=active
            )
        except (CatalogConflict, OSError, ValueError):
            counters["scan_failed"] = 1
            return counters

        counters["conflicts"] = len(plan.conflicts)
        counters["pending_active"] = len(plan.pending_active_roots)
        self._store.replace_desktop_surface_conflicts(
            LANE,
            [
                {
                    "item_id": task_id,
                    "group_name": "definition",
                    "reason": reason,
                    "candidates_json": "{}",
                }
                for task_id, reason in plan.conflicts
            ],
        )
        run_id: str | None = None
        if plan.mutations:
            run_id = self._id_factory()
            self._store.stage_desktop_surface_run(
                LANE,
                run_id,
                GROUPING_VERSION,
                json.dumps(
                    {
                        "phase": plan.phase,
                        "mutations": [
                            {
                                "root_id": mutation.root_id,
                                "task_ids": mutation.task_ids,
                                "expected_before_hash": mutation.expected_before_hash,
                            }
                            for mutation in plan.mutations
                        ],
                    },
                    sort_keys=True,
                ),
            )
            for mutation in plan.mutations:
                try:
                    apply_catalog_mutation(scan, mutation)
                except CatalogMutationConflict:
                    counters["raced"] += 1
                else:
                    counters["patched"] += 1
            self._store.finish_desktop_surface_run(
                LANE,
                run_id,
                "committed",
                resolution=(
                    None
                    if not counters["raced"]
                    else f"partial: raced={counters['raced']}"
                ),
            )
        self._beat(counters)
        return counters

    def _beat(self, counters: Mapping[str, int]) -> None:
        try:
            self._store.set_state(
                SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY,
                {
                    "at": float(self._wall_clock()),
                    "patched": int(counters["patched"]),
                    "conflicts": int(counters["conflicts"]),
                    "pending_active": int(counters["pending_active"]),
                },
            )
        except Exception:
            pass
