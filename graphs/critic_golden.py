"""Critic calibration against the labelled golden set (Langfuse ``hermes-jobs-v3``).

WHY THIS REPLACED THE SHADOW DIFF (2026-09-23, loops critic-golden-set-calibration-20260923).
Critic used to calibrate on ``bin/matcher_diff.py`` reports: production mailbox Matcher vs the
shadow LangGraph Matcher, paired per job. The Phase-B cutover (``infra/phase-b/shadow_is_live.json``,
2026-09-06) made the graph lane the ONLY Matcher and the mailbox Matcher was deleted, so both
diff inputs froze on 09-07 and every report since re-paired the same frozen files. matcher_diff is
now RETIRED (~/.hermes d82ef801f) and writes no reports, so from ~09-30 Critic had no input.

WHAT CRITIC MEASURES NOW. Prod-vs-shadow agreement is gone because there is no shadow. The
question becomes the one the release gate already asks: does the PRODUCTION Matcher get the
golden labels right? Each run:

1. loads ``hermes-jobs-v3`` from Langfuse (56 items; labels are human approvals and posting facts,
   never the scorer's own verdicts -- see ``jobflow_quality/golden_set.py``);
2. replays the production graph (``graphs.jobflow.invoke(..., persist=False)``) on every item's
   posting, so the measurement is of TODAY's Matcher, never of frozen verdicts;
3. maps decisions the way baselines #1-#3 did (``tailor``/``review`` = ADVANCE because only
   ``archive`` destroys the opportunity; ``archive`` = EXCLUDE);
4. scores with ``jobflow_quality.evaluation.evaluate`` -- accuracy per difficulty against the
   chance floor, and protected positives (a Diego-approved job excluded fails outright).

FAILURE IS LOUD, NEVER "NO DRIFT". An unreachable Langfuse, an empty or unlabelled dataset, or a
replay where too many items errored is a distinct status (``unavailable`` / ``degraded``) that the
Critic graph turns into an error, an AGENT_ERROR event and a non-zero runner exit. Scorer errors are
never reported as Matcher misses: they are counted separately and, past a small bound, void the run.

READ-ONLY. ``persist=False`` makes ``match_score_node`` skip its pipeline.json upsert (the golden
items are live pipeline jobs). Nothing else in the graph writes.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any, Callable, Optional

from jobflow_quality.evaluation import Prediction, as_dict, evaluate
from jobflow_quality.golden_set import Difficulty, GoldenItem, Label, LabelSource

GOLDEN_DATASET = "hermes-jobs-v3"
# hermes-jobs-v1 was imported 2026-04-24 and never labelled (every item carries the stub
# ``relevance_tier: unknown``). The daily runner passed it by default for months; it can
# measure nothing, so a request for it is served from the labelled set and says so.
UNLABELLED_LEGACY_DATASETS = frozenset({"hermes-jobs-v1"})

ADVANCE_DECISIONS = frozenset({"tailor", "review"})
EXCLUDE_DECISIONS = frozenset({"archive"})

# More scorer errors than this and the run measures the transport, not the Matcher.
MAX_ERROR_FRACTION = 0.1
DEFAULT_WORKERS = 4


class GoldenSetUnavailable(RuntimeError):
    """The labelled set could not be read. Never to be reported as 'no drift'."""


def resolve_dataset(name: Optional[str]) -> tuple[str, Optional[str]]:
    """(dataset actually used, note) -- an unlabelled legacy name maps to the golden set."""
    if not name or name in UNLABELLED_LEGACY_DATASETS:
        note = None if not name else f"{name} is unlabelled; measured {GOLDEN_DATASET} instead"
        return GOLDEN_DATASET, note
    return name, None


def _langfuse_client():
    from langfuse import Langfuse

    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"],
    )


def load_golden_items(name: str = GOLDEN_DATASET, *, client_factory: Callable[[], Any] = _langfuse_client) -> list[dict]:
    """Every labelled item of ``name`` as ``{job_id, job, golden}``; raises GoldenSetUnavailable."""
    try:
        dataset = client_factory().get_dataset(name)
        raw_items = list(dataset.items)
    except Exception as exc:  # network, auth, missing dataset: all the same to the caller
        raise GoldenSetUnavailable(
            f"Langfuse dataset {name!r} unreachable: {type(exc).__name__}: {exc}") from exc
    items: list[dict] = []
    for it in raw_items:
        expected = getattr(it, "expected_output", None) or {}
        meta = getattr(it, "metadata", None) or {}
        job_input = getattr(it, "input", None) or {}
        job_id = str(meta.get("job_id") or "")
        try:
            golden = GoldenItem(
                job_id=job_id,
                label=Label(expected["label"]),
                source=LabelSource(expected["source"]),
                difficulty=Difficulty(expected["difficulty"]),
                evidence=str(expected.get("evidence") or ""),
                description_sha256=str(meta.get("description_sha256") or ""),
                conflicted=bool(expected.get("conflicted", False)),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise GoldenSetUnavailable(
                f"Langfuse dataset {name!r} item {getattr(it, 'id', '?')} carries no usable label "
                f"({type(exc).__name__}: {exc}); an unlabelled set cannot calibrate anything") from exc
        if not job_id:
            raise GoldenSetUnavailable(f"Langfuse dataset {name!r} item {getattr(it, 'id', '?')} has no job_id")
        items.append({"job_id": job_id, "job": dict(job_input, id=job_id), "golden": golden})
    if not items:
        raise GoldenSetUnavailable(f"Langfuse dataset {name!r} is empty")
    return items


def decision_to_label(decision: Any) -> Optional[Label]:
    d = str(decision or "").strip().lower()
    if d in ADVANCE_DECISIONS:
        return Label.ADVANCE
    if d in EXCLUDE_DECISIONS:
        return Label.EXCLUDE
    return None


def _production_scorer(job: dict) -> dict:
    from .jobflow import invoke

    return invoke(job, job_id=job.get("id"), persist=False)


def replay_production(items: list[dict], *, scorer: Callable[[dict], dict] = _production_scorer,
                      workers: int = DEFAULT_WORKERS) -> list[dict]:
    """Run the production Matcher on every item; one row per item, errors recorded not raised."""
    def _one(item: dict) -> dict:
        try:
            state = scorer(item["job"]) or {}
        except Exception as exc:
            return {"job_id": item["job_id"], "decision": None, "score": None,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}
        err = state.get("error")
        return {"job_id": item["job_id"], "decision": state.get("decision"),
                "score": state.get("score"), "error": str(err)[:300] if err else None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(_one, items))


def evaluate_production(dataset_name: Optional[str] = None, *,
                        loader: Callable[[str], list[dict]] = load_golden_items,
                        scorer: Callable[[dict], dict] = _production_scorer,
                        workers: int = DEFAULT_WORKERS) -> dict:
    """Measure today's production Matcher against the golden labels.

    ``status``: ``ok`` (a trustworthy measurement), ``unavailable`` (the set could not be read) or
    ``degraded`` (too many scorer errors to call the result a measurement of the Matcher).
    Only ``ok`` may feed drift detection."""
    started = time.time()
    name, note = resolve_dataset(dataset_name)
    base = {"dataset": name, "requested_dataset": dataset_name, "note": note,
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))}
    try:
        items = loader(name)
    except GoldenSetUnavailable as exc:
        return {**base, "status": "unavailable", "error": str(exc)}

    rows = replay_production(items, scorer=scorer, workers=workers)
    by_id = {r["job_id"]: r for r in rows}
    errors = [r for r in rows if r["error"] or decision_to_label(r["decision"]) is None]
    predictions = [Prediction(r["job_id"], decision_to_label(r["decision"]))
                   for r in rows if not r["error"] and decision_to_label(r["decision"]) is not None]
    goldens = [it["golden"] for it in items]
    result = evaluate(goldens, predictions)

    def _row(job_id: str) -> dict:
        item = next(i for i in items if i["job_id"] == job_id)
        r = by_id.get(job_id) or {}
        return {"job_id": job_id, "title": (item["job"].get("title") or "")[:80],
                "company": (item["job"].get("company") or "")[:60],
                "expected": item["golden"].label.value, "difficulty": item["golden"].difficulty.value,
                "decision": r.get("decision"), "score": r.get("score"), "evidence": item["golden"].evidence[:160]}

    out = {
        **base,
        "status": "ok",
        "items": len(items),
        "answered": len(predictions),
        "scorer_errors": [{"job_id": r["job_id"], "error": r["error"] or f"unmappable decision {r['decision']!r}"}
                          for r in errors],
        "evaluation": as_dict(result),
        "false_exclude_rows": [_row(j) for j in result.false_excludes],
        "false_advance_rows": [_row(j) for j in result.false_advances],
        "wall_seconds": round(time.time() - started, 1),
    }
    if len(errors) > MAX_ERROR_FRACTION * len(items):
        out["status"] = "degraded"
        out["error"] = (f"{len(errors)} of {len(items)} replays errored (> {MAX_ERROR_FRACTION:.0%}); "
                        "this run measured the transport, not the Matcher")
    return out


__all__ = [
    "GOLDEN_DATASET", "GoldenSetUnavailable", "decision_to_label", "evaluate_production",
    "load_golden_items", "replay_production", "resolve_dataset",
]
