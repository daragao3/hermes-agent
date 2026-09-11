"""Durable driver for cross-root Claude Desktop Pinned presentation state."""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .desktop_presentation import (
    PresentationConflict,
    PresentationMutationConflict,
    apply_presentation_mutation,
    build_presentation_plan,
    scan_presentation_roots,
    verify_presentation_plan,
)

LANE = "presentation"
GROUP = "pins"
GROUPING_VERSION = 1
PRESENTATION_HEARTBEAT_STATE_KEY = "session-bridge:desktop-presentation:worker-heartbeat"


class DesktopPresentationSyncWorker:
    def __init__(
        self,
        store: Any,
        *,
        roots: Mapping[str, tuple[Path, Path]],
        active_root: Callable[[], str | None],
        run_min_interval_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not roots:
            raise ValueError("presentation roots must not be empty")
        interval = float(run_min_interval_seconds)
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("run_min_interval_seconds must be finite and non-negative")
        self._store = store
        self._roots = dict(roots)
        self._active_root = active_root
        self._interval = interval
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._last_run_at: float | None = None

    def _scan(self):
        return scan_presentation_roots(
            (root_id, config, sessions)
            for root_id, (config, sessions) in self._roots.items()
        )

    def run_once(self) -> dict[str, int]:
        counters = {
            "examined": len(self._roots),
            "patched": 0,
            "raced": 0,
            "conflicts": 0,
            "pending_active": 0,
            "verify_failures": 0,
            "baseline_rows_advanced": 0,
            "recovered_runs": 0,
            "scan_failed": 0,
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
            active = self._active_root()
            if active is not None and active not in self._roots:
                raise PresentationConflict("active Desktop root is not enrolled")
            scan = self._scan()
            stored = self._store.load_desktop_surface_baselines(LANE)
            baselines = {row["root_id"]: row["value_json"] for row in stored}
            plan = build_presentation_plan(
                scan, baselines=baselines, active_root_id=active
            )
        except (PresentationConflict, OSError, ValueError):
            counters["scan_failed"] = 1
            return counters

        counters["conflicts"] = len(plan.conflicts)
        counters["pending_active"] = len(plan.pending_active_roots)
        self._store.replace_desktop_surface_conflicts(
            LANE,
            [
                {
                    "item_id": "claude_desktop_config.json",
                    "group_name": GROUP,
                    "reason": reason,
                    "candidates_json": json.dumps(
                        {
                            root_id: root.state.canonical
                            for root_id, root in scan.roots.items()
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
                for reason in plan.conflicts
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
                        "mutations": [
                            {
                                "root_id": mutation.root_id,
                                "expected_before_hash": mutation.expected_before_hash,
                            }
                            for mutation in plan.mutations
                        ]
                    },
                    sort_keys=True,
                ),
            )
            for mutation in plan.mutations:
                try:
                    apply_presentation_mutation(scan, mutation)
                except PresentationMutationConflict:
                    counters["raced"] += 1
                else:
                    counters["patched"] += 1

        try:
            fresh = self._scan()
            verification = verify_presentation_plan(plan, fresh)
        except PresentationConflict:
            verification = None
        if verification is None:
            counters["scan_failed"] = 1
        elif not verification.ok:
            counters["verify_failures"] = len(verification.failures)

        can_advance = (
            plan.desired is not None
            and not plan.pending_active_roots
            and verification is not None
            and verification.ok
            and not counters["raced"]
        )
        if can_advance:
            current = {
                row["root_id"]: (row["value_json"], row["revision"])
                for row in stored
            }
            rows = []
            for root_id in self._roots:
                previous = current.get(root_id)
                if previous is not None and previous[0] == plan.desired.canonical:
                    continue
                rows.append(
                    {
                        "root_id": root_id,
                        "group_name": GROUP,
                        "value_json": plan.desired.canonical,
                        "revision": 1 if previous is None else previous[1] + 1,
                    }
                )
            if rows:
                counters["baseline_rows_advanced"] = (
                    self._store.upsert_desktop_surface_baselines(LANE, rows)
                )
        if run_id is not None:
            resolution = None
            if counters["raced"] or counters["verify_failures"] or counters["scan_failed"]:
                resolution = (
                    f"partial: raced={counters['raced']} "
                    f"verify_failures={counters['verify_failures']}"
                )
            self._store.finish_desktop_surface_run(
                LANE, run_id, "committed", resolution=resolution
            )
        if not counters["scan_failed"]:
            self._beat(counters)
        return counters

    def _beat(self, counters: Mapping[str, int]) -> None:
        try:
            self._store.set_state(
                PRESENTATION_HEARTBEAT_STATE_KEY,
                {
                    "at": float(self._wall_clock()),
                    "patched": int(counters["patched"]),
                    "conflicts": int(counters["conflicts"]),
                    "pending_active": int(counters["pending_active"]),
                    "verify_failures": int(counters["verify_failures"]),
                },
            )
        except Exception:
            pass
