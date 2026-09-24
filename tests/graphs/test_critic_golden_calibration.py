"""Critic calibrates on the labelled golden set, never on frozen prod-vs-shadow pairs.

2026-09-23 (loops critic-golden-set-calibration-20260923): the Phase-B cutover made the graph lane
the only Matcher; bin/matcher_diff.py is retired and writes no reports, so Critic's diff input
would be empty from ~09-30 -- and until then it re-read pairs frozen since 09-07. Critic now
replays the PRODUCTION Matcher against Langfuse hermes-jobs-v3 and reports the release gate's own
measures. Pinned here:

* the measurement (accuracy by difficulty, protected positives, scorer errors kept apart);
* an unreachable/unlabelled set is LOUD (status, error, AGENT_ERROR event), never "no drift";
* the replay is read-only (persist=False skips the pipeline.json upsert);
* the old diff path is used only while fresh and never after the Phase-B marker;
* finalize writes golden results to the changelog, and an unavailable run writes none.
"""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import pytest

# graphs needs langgraph, which is only in requirements-local-graph.txt, not
# the CI extras; skip rather than error at collection (same as test_critic_paths).
pytest.importorskip("langgraph.graph")

from graphs import critic, critic_golden, jobflow
from jobflow_quality.golden_set import Difficulty, GoldenItem, Label, LabelSource


def _item(job_id, label, difficulty, title="Role", company="Co"):
    return {
        "job_id": job_id,
        "job": {"id": job_id, "title": title, "company": company, "description": "posting"},
        "golden": GoldenItem(
            job_id=job_id, label=label,
            source=LabelSource.HUMAN_APPROVAL if label is Label.ADVANCE else LabelSource.DETERMINISTIC_EXCLUSION,
            difficulty=difficulty, evidence="ev", description_sha256="ab" * 32),
    }


# 3 nuanced (human-approved = advance) + 3 obvious (below the bail line = exclude): balanced.
ITEMS = [
    _item("n1", Label.ADVANCE, Difficulty.NUANCED, "Head of Deposits", "Goldman"),
    _item("n2", Label.ADVANCE, Difficulty.NUANCED),
    _item("n3", Label.ADVANCE, Difficulty.NUANCED),
    _item("o1", Label.EXCLUDE, Difficulty.OBVIOUS),
    _item("o2", Label.EXCLUDE, Difficulty.OBVIOUS),
    _item("o3", Label.EXCLUDE, Difficulty.OBVIOUS),
]


def _scorer(decisions):
    def score(job):
        d = decisions[job["id"]]
        if isinstance(d, Exception):
            raise d
        return {"decision": d, "score": 7.5 if d != "archive" else 3.0}
    return score


# ---- the measurement ------------------------------------------------------------------------

def test_perfect_production_matcher_passes_with_per_difficulty_accuracy():
    out = critic_golden.evaluate_production(
        "hermes-jobs-v3", loader=lambda name: ITEMS, workers=2,
        scorer=_scorer({"n1": "tailor", "n2": "review", "n3": "review",
                        "o1": "archive", "o2": "archive", "o3": "archive"}))
    assert out["status"] == "ok"
    ev = out["evaluation"]
    assert ev["passed"] is True
    assert ev["accuracy_by_difficulty"] == {"nuanced": 1.0, "obvious": 1.0}
    assert out["false_exclude_rows"] == [] and out["false_advance_rows"] == []


def test_an_archived_human_approval_is_a_protected_positive_loss():
    out = critic_golden.evaluate_production(
        "hermes-jobs-v3", loader=lambda name: ITEMS, workers=2,
        scorer=_scorer({"n1": "archive", "n2": "review", "n3": "review",
                        "o1": "archive", "o2": "review", "o3": "archive"}))
    assert out["status"] == "ok"
    assert out["evaluation"]["passed"] is False
    assert [r["job_id"] for r in out["false_exclude_rows"]] == ["n1"]
    assert out["false_exclude_rows"][0]["company"] == "Goldman"
    assert [r["job_id"] for r in out["false_advance_rows"]] == ["o2"]


def test_scorer_errors_are_counted_apart_and_past_the_bound_void_the_run():
    out = critic_golden.evaluate_production(
        "hermes-jobs-v3", loader=lambda name: ITEMS, workers=2,
        scorer=_scorer({"n1": RuntimeError("socket"), "n2": "review", "n3": "review",
                        "o1": "archive", "o2": "archive", "o3": "archive"}))
    assert [e["job_id"] for e in out["scorer_errors"]] == ["n1"]
    assert out["false_exclude_rows"] == [], "a transport error must never read as a Matcher false exclude"
    assert out["status"] == "degraded", "1 of 6 errored is past the 10% bound"
    assert "transport" in out["error"]


def test_unavailable_set_is_a_status_not_an_empty_measurement():
    def boom(name):
        raise critic_golden.GoldenSetUnavailable("Langfuse dataset 'hermes-jobs-v3' unreachable: ConnectError")
    out = critic_golden.evaluate_production("hermes-jobs-v3", loader=boom)
    assert out["status"] == "unavailable" and "unreachable" in out["error"]
    assert "evaluation" not in out


def test_unlabelled_v1_request_is_served_from_the_golden_set():
    seen = []
    critic_golden.evaluate_production("hermes-jobs-v1", loader=lambda n: seen.append(n) or ITEMS,
                                      scorer=_scorer({i["job_id"]: "review" for i in ITEMS}))
    assert seen == ["hermes-jobs-v3"]
    assert critic_golden.resolve_dataset(None)[0] == "hermes-jobs-v3"
    assert critic_golden.resolve_dataset("hermes-jobs-v4") == ("hermes-jobs-v4", None)


def test_decision_mapping_matches_the_baselines():
    assert critic_golden.decision_to_label("tailor") is Label.ADVANCE
    assert critic_golden.decision_to_label("review") is Label.ADVANCE
    assert critic_golden.decision_to_label("archive") is Label.EXCLUDE
    assert critic_golden.decision_to_label(None) is None


# ---- loading from Langfuse --------------------------------------------------------------------

def _lf_item(job_id, label="advance", difficulty="nuanced", source="human_approval"):
    return SimpleNamespace(
        id=f"hermes-jobs-v3-{job_id}", input={"title": "T", "company": "C", "description": "d"},
        expected_output={"label": label, "source": source, "difficulty": difficulty, "evidence": "e"},
        metadata={"job_id": job_id, "description_sha256": "cd" * 32})


def test_load_golden_items_parses_labels_and_keeps_the_job_id():
    client = SimpleNamespace(get_dataset=lambda name: SimpleNamespace(items=[_lf_item("a"), _lf_item("b", "exclude", "obvious", "deterministic_exclusion")]))
    items = critic_golden.load_golden_items(client_factory=lambda: client)
    assert [i["job_id"] for i in items] == ["a", "b"]
    assert items[1]["golden"].label is Label.EXCLUDE and items[0]["job"]["id"] == "a"


def test_unreachable_langfuse_raises_unavailable():
    def factory():
        raise ConnectionError("localhost:3050 refused")
    with pytest.raises(critic_golden.GoldenSetUnavailable, match="unreachable"):
        critic_golden.load_golden_items(client_factory=factory)


def test_unlabelled_item_raises_unavailable():
    stub = SimpleNamespace(id="x", input={}, expected_output={"notes": "Fill via Langfuse UI", "relevance_tier": "unknown"},
                           metadata={"job_id": "x"})
    client = SimpleNamespace(get_dataset=lambda name: SimpleNamespace(items=[stub]))
    with pytest.raises(critic_golden.GoldenSetUnavailable, match="no usable label"):
        critic_golden.load_golden_items(client_factory=lambda: client)


# ---- read-only replay ---------------------------------------------------------------------------

def _matcher_score():
    return jobflow.MatcherScore(
        score=7.0, recommendation="REVIEW",
        breakdown=jobflow.ScoreBreakdown(**{n: 7.0 for n in jobflow.ScoreBreakdown.model_fields}))


@pytest.mark.parametrize("persist,expected_upserts", [(True, 1), (False, 0)])
def test_evaluation_replay_never_upserts_pipeline_json(monkeypatch, persist, expected_upserts):
    import pipeline_state
    upserts = []
    monkeypatch.setattr(jobflow, "codex_structured_invoke", lambda *a, **k: _matcher_score())
    monkeypatch.setattr(pipeline_state.PipelineManager, "upsert_metadata",
                        lambda self, **kw: upserts.append(kw), raising=True)
    state = {"job": {"id": "j", "title": "T", "company": "C"}, "job_id": "j", "profile_summary": "p"}
    if not persist:
        state["persist_pipeline"] = False
    out = jobflow.match_score_node(state)
    assert out["score"] == 7.0
    assert len(upserts) == expected_upserts


# ---- Critic graph wiring ------------------------------------------------------------------------

def _write_report(age_s=0.0):
    d = critic.diff_reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"r{time.time_ns()}.json"
    p.write_text(json.dumps({"pairs": [{"job_id": "p1"}, {"job_id": "p2"}], "summary": {"paired_count": 2}}), encoding="utf-8")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(critic, "_emit_event", lambda et, src, payload, priority=None: seen.append((et, payload, priority)))
    return seen


def _golden_ok(**extra):
    return {"status": "ok", "dataset": "hermes-jobs-v3", "items": 56, "scorer_errors": [],
            "evaluation": {"passed": True, "total": 56, "correct": 56, "accuracy_by_difficulty": {"nuanced": 1.0, "obvious": 1.0},
                           "false_excludes": [], "false_advances": [], "reasons": []},
            "false_exclude_rows": [], "false_advance_rows": [], "wall_seconds": 1.0, **extra}


def test_unavailable_golden_set_is_loud(monkeypatch, events):
    monkeypatch.setattr(critic_golden, "evaluate_production",
                        lambda name: {"status": "unavailable", "dataset": "hermes-jobs-v3", "error": "ConnectError"})
    out = critic.load_calibration_node({"dataset_name": "hermes-jobs-v3"})
    assert out["calibration_status"] == "unavailable"
    assert "golden-set calibration unavailable" in out["error"]
    assert events and events[0][0] == "agent_error" and events[0][2] == "high"


def test_phase_b_marker_retires_even_fresh_diff_reports(monkeypatch, events):
    monkeypatch.setattr(critic_golden, "evaluate_production", lambda name: _golden_ok())
    _write_report()
    marker = critic.phase_b_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    out = critic.load_calibration_node({})
    assert out["paired_jobs"] == [] and out["diff_reports_used"] == []
    assert out["prior_path_note"].startswith("retired")
    assert out["calibration_status"] == "ok" and "error" not in out


def test_fallback_is_used_only_while_fresh(monkeypatch, events):
    monkeypatch.setattr(critic_golden, "evaluate_production", lambda name: _golden_ok())
    stale = _write_report(age_s=48 * 3600)
    out = critic.load_calibration_node({})
    assert out["paired_jobs"] == [] and out["prior_path_note"].startswith("stale")
    _write_report(age_s=60)
    out = critic.load_calibration_node({})
    assert len(out["paired_jobs"]) == 2 and out["prior_path_note"] == "fresh"
    stale.unlink()


def test_golden_misses_become_clusters_without_an_llm(monkeypatch):
    monkeypatch.setattr(critic, "codex_structured_invoke",
                        lambda *a, **k: pytest.fail("no LLM call without paired jobs"))
    golden = _golden_ok(
        false_exclude_rows=[{"job_id": "n1", "company": "Goldman", "title": "Head", "score": 4.1, "difficulty": "nuanced"}],
        false_advance_rows=[{"job_id": f"o{i}", "company": "X", "title": "Y", "score": 6.0, "difficulty": "obvious"} for i in range(3)],
        evaluation={"passed": False, "total": 56, "correct": 40,
                    "accuracy_by_difficulty": {"nuanced": 0.96, "obvious": 0.4},
                    "false_excludes": ["n1"], "false_advances": ["o0", "o1", "o2"], "reasons": []})
    out = critic.detect_drift_node({"golden": golden, "paired_jobs": []})
    names = {c["pattern_name"]: c for c in out["clusters"]}
    assert names["golden_protected_positive_excluded"]["severity"] == "high"
    assert names["golden_protected_positive_excluded"]["evidence_job_ids"] == ["n1"]
    assert "golden_accuracy_floor_obvious" in names and "golden_accuracy_floor_nuanced" not in names
    assert names["golden_false_advances"]["severity"] == "medium"


def test_finalize_records_golden_results_and_never_says_no_drift_when_unavailable(monkeypatch):
    out = critic.finalize_node({"golden": _golden_ok(), "run_id": "gold1"})
    assert out["changelog_appended"] is True
    entry = json.loads(critic.changelog_path().read_text(encoding="utf-8").splitlines()[-1])
    assert entry["calibration_source"] == "golden_set" and entry["golden_passed"] is True
    assert entry["golden_accuracy_by_difficulty"] == {"nuanced": 1.0, "obvious": 1.0}

    before = critic.changelog_path().read_text(encoding="utf-8")
    out = critic.finalize_node({"golden": {"status": "unavailable", "error": "ConnectError"}, "run_id": "gold2"})
    assert out["changelog_appended"] is False
    assert critic.changelog_path().read_text(encoding="utf-8") == before
    retro = open(out["retro_path"], encoding="utf-8").read()
    assert "CALIBRATION UNAVAILABLE" in retro
    assert "No systematic drift" not in retro and "No drift:" not in retro


def test_invoke_critic_defaults_to_the_labelled_set():
    import inspect
    assert inspect.signature(critic.invoke_critic).parameters["dataset_name"].default == "hermes-jobs-v3"
