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

PROPOSAL JUDGING (2026-09-23, loops critic-threshold-replay-golden-20260923). Critic's own
threshold proposals used to be replayed against prod-vs-shadow pairs, which no longer exist, so
the check skipped. ``judge_threshold_proposal`` re-routes the SAME run's stored per-item scores
(total + comp_alignment) under the current and the proposed (proceed, review, comp_floor) triple
with ``graphs.jobflow.decide_route`` -- the production routing function itself, no Matcher re-run
-- and judges the pair with the release gate: a proposal is ACCEPTED only if it is no worse on
every difficulty's accuracy, adds no false exclude of a Diego-approved job, is not a
same-answer-for-everything router, and is strictly better on something. A positive control runs
first: re-routing under the CURRENT triple must reproduce every stored decision, or the verdict
is HELD (the stored scores do not explain the routing, so nothing computed from them can be
trusted). An unavailable golden replay HOLDS every proposal; weight/prompt proposals are held too,
because the total is the model's own weighted score after penalties and cannot be recomputed.
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
        breakdown = state.get("breakdown") if isinstance(state.get("breakdown"), dict) else {}
        return {"job_id": item["job_id"], "decision": state.get("decision"),
                "score": state.get("score"), "comp": breakdown.get("comp_alignment"),
                "error": str(err)[:300] if err else None}

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

    try:
        from .jobflow import routing_thresholds
        thresholds = list(routing_thresholds())
    except Exception:
        thresholds = None
    out = {
        **base,
        "status": "ok",
        # The routing triple live during this replay, and every item's stored inputs to routing,
        # so a proposal can be judged by re-routing THIS run's scores (judge_threshold_proposal).
        "thresholds_at_replay": thresholds,
        "rows": [{"job_id": it["job_id"], "label": it["golden"].label.value,
                  "difficulty": it["golden"].difficulty.value, "source": it["golden"].source.value,
                  "score": by_id[it["job_id"]].get("score"), "comp": by_id[it["job_id"]].get("comp"),
                  "decision": by_id[it["job_id"]].get("decision"), "error": by_id[it["job_id"]].get("error")}
                 for it in items],
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


# ---------------------------------------------------------------------------------------------
# Proposal judging on the stored replay
# ---------------------------------------------------------------------------------------------

_THRESHOLD_ENV = {"proceed": "HERMES_JOBFLOW_PROCEED_THRESHOLD",
                  "review": "HERMES_JOBFLOW_REVIEW_THRESHOLD",
                  "comp_floor": "HERMES_JOBFLOW_COMP_FLOOR"}


def parse_proposed_thresholds(specific_change: str, current: tuple[float, float, float]) -> Optional[tuple[float, float, float]]:
    """The proposed (proceed, review, comp_floor) from ``specific_change`` text such as
    ``set HERMES_JOBFLOW_PROCEED_THRESHOLD=8.50, was 8.75``; unmentioned values stay current.
    None when the text names none of the three."""
    import re

    values = dict(zip(("proceed", "review", "comp_floor"), current))
    found = False
    for key, env in _THRESHOLD_ENV.items():
        m = re.search(rf"{env}\s*=\s*(-?[0-9]+(?:\.[0-9]+)?)", specific_change or "")
        if m:
            values[key] = float(m.group(1))
            found = True
    return (values["proceed"], values["review"], values["comp_floor"]) if found else None


def _route_rows(rows: list[dict], triple: tuple[float, float, float]) -> dict[str, Optional[str]]:
    from .jobflow import decide_route

    proceed, review, comp_floor = triple
    out: dict[str, Optional[str]] = {}
    for r in rows:
        if r.get("error") or not isinstance(r.get("score"), (int, float)):
            out[r["job_id"]] = None  # unanswered stays unanswered under any triple
        else:
            out[r["job_id"]] = decide_route(float(r["score"]), r.get("comp"), proceed, review, comp_floor)
    return out


def _evaluate_routing(rows: list[dict], decisions: dict[str, Optional[str]]):
    items = [GoldenItem(job_id=r["job_id"], label=Label(r["label"]), source=LabelSource(r["source"]),
                        difficulty=Difficulty(r["difficulty"]), evidence="", description_sha256="")
             for r in rows]
    preds = [Prediction(j, decision_to_label(d)) for j, d in decisions.items()
             if d is not None and decision_to_label(d) is not None]
    return evaluate(items, preds)


def _summary(result) -> dict:
    return {"accuracy_by_difficulty": dict(result.accuracy_by_difficulty),
            "correct": result.correct, "total": result.total,
            "false_excludes": list(result.false_excludes), "false_advances": list(result.false_advances),
            "passed": result.passed, "reasons": list(result.reasons)}


def judge_threshold_proposal(golden: Optional[dict], proposed: tuple[float, float, float]) -> dict:
    """Judge one routing-triple proposal on the stored golden replay.

    Returns ``{"status": golden_accepted | golden_rejected | held_*, "notes": why, ...numbers}``.
    Accept iff: every difficulty's accuracy is >= current; no Diego-approved job becomes a false
    exclude that was not one already; the proposed routing is not degenerate (one label for every
    item); and at least one of (some difficulty's accuracy, false excludes, false advances) strictly
    improves."""
    if not golden or golden.get("status") != "ok":
        status = (golden or {}).get("status") or "missing"
        return {"status": "held_golden_unavailable",
                "notes": (f"HELD: the golden-set replay is {status} this run "
                          f"({(golden or {}).get('error') or 'no measurement'}), so this proposal was NOT "
                          "judged and must not be applied on today's evidence.")}
    rows = golden.get("rows") or []
    current = golden.get("thresholds_at_replay")
    if not rows or not current:
        return {"status": "held_no_stored_scores",
                "notes": "HELD: this golden replay carries no per-item scores or routing triple to re-route."}
    current = tuple(float(v) for v in current)

    # Positive control: the stored scores must reproduce the stored decisions under today's triple.
    replayed = _route_rows(rows, current)
    mismatched = [r["job_id"] for r in rows
                  if replayed[r["job_id"]] is not None and replayed[r["job_id"]] != r.get("decision")]
    if mismatched:
        return {"status": "held_recompute_mismatch",
                "notes": (f"HELD: re-routing the stored scores under the current thresholds disagrees with "
                          f"{len(mismatched)} recorded decision(s) ({', '.join(mismatched[:5])}); the stored "
                          "scores do not explain the routing, so no verdict computed from them is trustworthy.")}

    base = _evaluate_routing(rows, replayed)
    proposed_routing = _route_rows(rows, proposed)
    cand = _evaluate_routing(rows, proposed_routing)
    flips = [{"job_id": j, "old": replayed[j], "new": proposed_routing[j]}
             for j in replayed if replayed[j] != proposed_routing[j]]

    b_acc, c_acc = base.accuracy_by_difficulty, cand.accuracy_by_difficulty
    worse = [f"{d} accuracy {b_acc[d]:.1%} -> {c_acc.get(d, 0.0):.1%}"
             for d in sorted(b_acc) if c_acc.get(d, 0.0) < b_acc[d]]
    new_fe = sorted(set(cand.false_excludes) - set(base.false_excludes))
    degenerate = any("degenerate candidate" in r for r in cand.reasons)
    better = ([f"{d} accuracy {b_acc[d]:.1%} -> {c_acc[d]:.1%}" for d in sorted(b_acc) if c_acc.get(d, 0.0) > b_acc[d]]
              + ([f"false excludes {len(base.false_excludes)} -> {len(cand.false_excludes)}"]
                 if len(cand.false_excludes) < len(base.false_excludes) else [])
              + ([f"false advances {len(base.false_advances)} -> {len(cand.false_advances)}"]
                 if len(cand.false_advances) < len(base.false_advances) else []))

    rejections = ([f"worse: {w}" for w in worse]
                  + ([f"new false exclude(s) of Diego-approved job(s): {', '.join(new_fe)}"] if new_fe else [])
                  + (["degenerate: the proposed routing gives every item the same label"] if degenerate else []))
    if not rejections and not better:
        rejections.append("no improvement: identical on every floor, false excludes and false advances")
    accepted = not rejections
    numbers = (f"current {current} vs proposed {tuple(proposed)} on {golden.get('dataset')} "
               f"({len(rows)} items, {len(flips)} decision flip(s)): accuracy "
               + ", ".join(f"{d} {b_acc[d]:.1%}->{c_acc.get(d, 0.0):.1%}" for d in sorted(b_acc))
               + f"; false excludes {len(base.false_excludes)}->{len(cand.false_excludes)}"
               + f"; false advances {len(base.false_advances)}->{len(cand.false_advances)}")
    notes = (f"ACCEPTED ({'; '.join(better)}). {numbers}" if accepted
             else f"REJECTED ({'; '.join(rejections)}). {numbers}")
    return {"status": "golden_accepted" if accepted else "golden_rejected", "notes": notes,
            "current": list(current), "proposed": list(proposed),
            "baseline": _summary(base), "candidate": _summary(cand),
            "recommendation_flips": flips, "new_false_excludes": new_fe,
            "improvements": better, "rejections": rejections}


__all__ = [
    "GOLDEN_DATASET", "GoldenSetUnavailable", "decision_to_label", "evaluate_production",
    "judge_threshold_proposal", "parse_proposed_thresholds",
    "load_golden_items", "replay_production", "resolve_dataset",
]
