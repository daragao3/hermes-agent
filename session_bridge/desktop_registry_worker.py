"""Continuous single-writer reconciliation of the Desktop session registries.

``DesktopRegistrySyncWorker`` is the durable driver around the pure planning
core in :mod:`session_bridge.desktop_registry`.  One cycle is::

    recover -> scan -> plan -> stage run -> apply -> rescan -> verify
            -> advance baselines -> record conflicts -> commit run

Baselines advance only for records whose intended group values verified on
every enrolled root, and only after the run's mutations were staged durably.
Because every individual file write is atomic (same-directory temporary plus
``os.replace``) and baselines advance last, an interrupted cycle needs no byte
replay: the stale run is abandoned with an audit trail and the next cycle
re-derives the remaining deltas from the standing baselines.  A scan that
cannot produce complete, stable evidence writes nothing.
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from .desktop_registry import (
    DESKTOP_REGISTRY_GROUPING_VERSION,
    RegistryBaseline,
    RegistryMutationConflict,
    RegistryScanCache,
    RegistryBaselineError,
    RegistryScanError,
    apply_registry_mutation,
    build_registry_sync_plan,
    scan_desktop_registry_roots,
    verify_registry_sync_plan,
)

#: Written at the end of every cycle that completes reconciliation, whether or
#: not that cycle had anything to change.  This is the leg's only unambiguous
#: liveness signal: ``desktop_registry_runs`` rows are staged ONLY ``if
#: mutations``, and ``desktop_registry_conflicts.last_seen_at`` only moves while
#: conflicts stand, so BOTH go stale on a healthy, fully converged worker.
#: Measured 2026-09-07 over a week of healthy operation: the newest-run age
#: exceeded an hour 18 times and reached 26.1h overnight.  A monitor that gates
#: on either of those cannot tell "converged" from "stopped"; it can tell that
#: from this.
WORKER_HEARTBEAT_STATE_KEY = "session-bridge:desktop-registry:worker-heartbeat"
WORKER_LAST_ERROR_STATE_KEY = (
    "session-bridge:desktop-registry:worker-last-error"
)

_LOG = logging.getLogger(__name__)


class DesktopRegistrySyncWorker:
    """Reconcile enrolled Desktop registry roots against durable baselines."""

    def __init__(
        self,
        store: Any,
        *,
        registry_roots: Iterable[Path],
        run_min_interval_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        roots = tuple(registry_roots)
        if not roots:
            raise ValueError("registry_roots must not be empty")
        for root in roots:
            if not isinstance(root, Path):
                raise TypeError("registry_roots must contain Path entries")
        interval = float(run_min_interval_seconds)
        if not math.isfinite(interval) or interval < 0:
            raise ValueError(
                "run_min_interval_seconds must be finite and non-negative"
            )
        self._store = store
        self._registry_roots = roots
        self._run_min_interval_seconds = interval
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._last_run_at: float | None = None
        # Persistent across cycles and shared by both scans of one cycle:
        # unchanged files (same dev/ino/size/mtime_ns) are not re-read or
        # re-canonicalized, which keeps the CPU cost of a steady-state cycle
        # proportional to recent activity. Without it, every ~5-minute cycle
        # spent 60-90s of GIL-bound work over ~11,800 files, degrading the
        # async server enough that a concurrent launcher health smoke could
        # time out and falsely retire the healthy service tree (observed
        # 2026-08-31 10:18).
        self._scan_cache = RegistryScanCache()

    def run_once(self) -> dict[str, int]:
        counters = {
            "examined": 0,
            "patched": 0,
            "created": 0,
            "raced": 0,
            "conflicts": 0,
            "verify_failures": 0,
            "baseline_rows_advanced": 0,
            "stale_baseline_rows_pruned": 0,
            "recovered_runs": 0,
            "scan_failed": 0,
            "baseline_invalid": 0,
            "throttled": 0,
        }
        now = self._monotonic()
        if (
            self._last_run_at is not None
            and now - self._last_run_at < self._run_min_interval_seconds
        ):
            counters["throttled"] = 1
            return counters
        self._last_run_at = now

        pending = self._store.pending_desktop_registry_run()
        if pending is not None:
            # File writes are individually atomic and baselines advance last,
            # so a run that never committed left disk in a mixture of old and
            # accepted values -- exactly what a fresh plan against the standing
            # baselines converges. Abandon with audit and replan.
            self._store.finish_desktop_registry_run(
                pending["id"], "abandoned", resolution="recovered_by_replan"
            )
            counters["recovered_runs"] = 1

        try:
            scan = scan_desktop_registry_roots(
                self._registry_roots, cache=self._scan_cache
            )
        except RegistryScanError as exc:
            # Fail closed AND say why.  This bail used to persist nothing:
            # on 2026-09-16 22:01 an enrolled root became a junction,
            # _root_identity raised here on every 300s cycle for 11h17m, and
            # the only instrument that moved was the heartbeat age -- no log
            # line, no row, and no post_scan_worker_diagnostic either, since
            # nothing escaped run_once.  Naming it took py-spy plus an offline
            # replay; with the reason persisted it is one state.db read.
            counters["scan_failed"] = 1
            self._record_last_error(exc, stage="scan")
            return counters

        stored_rows = self._store.load_desktop_registry_baselines()
        baselines = [RegistryBaseline(**row) for row in stored_rows]
        try:
            plan = build_registry_sync_plan(scan, baselines=baselines)
        except RegistryBaselineError as exc:
            # Fail CLOSED, the same way an unreadable scan does.  Before this
            # guard the raise escaped run_once entirely -- run_once wraps only
            # the scan calls -- and _run_post_scan_worker swallowed it, so a
            # root-set change re-raised every cycle while converging nothing.
            #
            # Deliberately does NOT beat: a leg that reconciled nothing must
            # go stale so the mismatch stays visible.  _beat's own contract.
            # The reason is persisted because swallowing the raise also
            # removes the coordinator's post_scan_worker_diagnostic line,
            # which on 2026-09-12 was the ONLY artifact that named the fault.
            counters["baseline_invalid"] = 1
            self._record_last_error(exc, stage="plan")
            return counters
        counters["examined"] = len(plan.records)
        counters["conflicts"] = len(plan.conflicts)

        mutations = [
            mutation
            for record in plan.records.values()
            for mutation in record.mutations
        ]
        run_id: str | None = None
        if mutations:
            run_id = self._id_factory()
            payload = {
                "grouping_version": DESKTOP_REGISTRY_GROUPING_VERSION,
                "roots": {
                    root_id: observation.canonical_path
                    for root_id, observation in scan.roots.items()
                },
                "mutations": [
                    {
                        "root_id": mutation.root_id,
                        "filename": mutation.filename,
                        "operation": mutation.operation,
                        "expected_before_hash": mutation.expected_before_hash,
                        "changed_groups": sorted(mutation.changed_fields),
                    }
                    for mutation in mutations
                ],
            }
            self._store.stage_desktop_registry_run(
                run_id,
                DESKTOP_REGISTRY_GROUPING_VERSION,
                json.dumps(payload, ensure_ascii=False),
            )
            for mutation in mutations:
                try:
                    apply_registry_mutation(scan, mutation)
                except RegistryMutationConflict:
                    counters["raced"] += 1
                else:
                    key = "created" if mutation.operation == "create" else "patched"
                    counters[key] += 1

        try:
            fresh = scan_desktop_registry_roots(
                self._registry_roots, cache=self._scan_cache
            )
            verification = verify_registry_sync_plan(plan, fresh)
        except (RegistryScanError, ValueError) as exc:
            if run_id is not None:
                self._store.finish_desktop_registry_run(
                    run_id, "abandoned", resolution="verify_scan_failed"
                )
            counters["scan_failed"] = 1
            self._record_last_error(exc, stage="verify_scan")
            return counters

        failed_files = {failure.filename for failure in verification.failures}
        counters["verify_failures"] = len(verification.failures)

        stored_index = {
            (row["filename"], row["root_id"], row["group_name"]): row["value_json"]
            for row in stored_rows
        }
        advance = [
            {
                "filename": baseline.filename,
                "root_id": baseline.root_id,
                "group_name": baseline.group_name,
                "value_json": baseline.value_json,
                "revision": baseline.revision,
            }
            for baseline in plan.proposed_baselines
            if baseline.filename not in failed_files
            and stored_index.get(
                (baseline.filename, baseline.root_id, baseline.group_name)
            )
            != baseline.value_json
        ]
        if advance:
            counters["baseline_rows_advanced"] = (
                self._store.upsert_desktop_registry_baselines(advance)
            )
        if plan.stale_baselines:
            # Rows for roots this worker does not enrol (the topology shrank
            # between processes).  The plan above was built without them;
            # delete them so the next cycle -- and the next reader of the
            # table -- sees only the enrolled roots.  Named in the log because
            # it is durable state changing on its own, once per topology
            # change, and the only trace otherwise is a row count.
            pruned = self._store.delete_desktop_registry_baselines(
                [
                    {
                        "filename": baseline.filename,
                        "root_id": baseline.root_id,
                        "group_name": baseline.group_name,
                    }
                    for baseline in plan.stale_baselines
                ]
            )
            counters["stale_baseline_rows_pruned"] = int(pruned)
            _LOG.warning(
                "desktop_registry_stale_root_baselines_pruned roots=%s rows=%d "
                "enrolled=%s",
                ",".join(plan.stale_root_ids),
                int(pruned),
                ",".join(sorted(scan.roots)),
            )
        self._store.replace_desktop_registry_conflicts(
            [
                {
                    "filename": conflict.filename,
                    "group_name": conflict.group_name,
                    "reason": conflict.reason,
                    "candidates_json": json.dumps(
                        dict(conflict.candidates), ensure_ascii=False, sort_keys=True
                    ),
                }
                for conflict in plan.conflicts
            ]
        )
        if run_id is not None:
            resolution = None
            if failed_files or counters["raced"]:
                resolution = (
                    f"partial: raced={counters['raced']} "
                    f"verify_failed_files={len(failed_files)}"
                )
            self._store.finish_desktop_registry_run(
                run_id, "committed", resolution=resolution
            )
        self._beat(counters)
        return counters

    def _record_last_error(self, exc: Exception, *, stage: str) -> None:
        """Persist why a cycle converged nothing, for a stale-beat triage.

        ``stage`` names which bail wrote it -- ``scan`` (the pre-plan scan),
        ``plan`` (the planner rejected a baseline) or ``verify_scan`` (the
        post-mutation re-scan) -- because the three raise the same exception
        classes and a triage reads this row instead of a traceback.

        Telemetry must never cost a reconciliation, so a failed write is
        swallowed exactly as in :meth:`_beat`.  The cost of swallowing is an
        unexplained stale beat, which is still an alert.
        """
        try:
            self._store.set_state(
                WORKER_LAST_ERROR_STATE_KEY,
                {
                    "at": float(self._wall_clock()),
                    "stage": stage,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            pass

    def _beat(self, counters: dict[str, int]) -> None:
        """Record that a cycle reached the end of reconciliation.

        Deliberately NOT written for a throttled call (it did no work) nor for
        a cycle that bailed on ``scan_failed`` (it converged nothing).  A scan
        that keeps failing is a leg that is alive but not doing its job, and
        letting the beat go stale is how that becomes visible instead of
        sitting silent -- which is exactly how the 2026-09-06 ``scan_failed``
        class stranded records for days.  The stale beat says THAT it
        stopped; :meth:`_record_last_error` says WHY.

        Telemetry must never cost a reconciliation, so a failed write is
        swallowed: the cycle's real work is already committed by this point.
        The cost of swallowing is a stale beat, i.e. an alert, which is the
        safe direction to fail in.
        """
        try:
            self._store.set_state(
                WORKER_HEARTBEAT_STATE_KEY,
                {
                    "at": float(self._wall_clock()),
                    "examined": int(counters.get("examined", 0)),
                    "patched": int(counters.get("patched", 0)),
                    "created": int(counters.get("created", 0)),
                    "conflicts": int(counters.get("conflicts", 0)),
                    "verify_failures": int(counters.get("verify_failures", 0)),
                },
            )
        except Exception:
            pass
