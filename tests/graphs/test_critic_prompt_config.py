"""The Matcher-configuration block Critic reads before proposing changes.

That block is prose inside CRITIC_PROPOSAL_USER_TEMPLATE, so nothing but a
test notices when it drifts from graphs/jobflow.py. It did: until 2026-09-05
it told Critic the Matcher ran gpt-4o-mini at temperature 0.1, while
jobflow.DEFAULT_MODEL had been gpt-5.5 since 2026-04-24 and the Codex path
had never sent a temperature at all. Every proposal about model choice or
cost was reasoning from that false premise.

The model is now rendered into the prompt from the Matcher module at call
time. The rest of the block is pinned here against its source of truth.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from graphs import _critic_prompts, _prompts, critic, jobflow

TEMPLATE = _critic_prompts.CRITIC_PROPOSAL_USER_TEMPLATE


@pytest.fixture(autouse=True)
def _deployed_thresholds(monkeypatch):
    """Pin the deployed values so a host .env cannot move what gets rendered."""
    monkeypatch.delenv("HERMES_JOBFLOW_PROCEED_THRESHOLD", raising=False)
    monkeypatch.delenv("HERMES_JOBFLOW_REVIEW_THRESHOLD", raising=False)
    monkeypatch.delenv("HERMES_JOBFLOW_COMP_FLOOR", raising=False)


def _render_proposal_prompt(monkeypatch) -> str:
    """Run the real generate_proposals_node and capture the user prompt it sends."""
    captured = {}

    def fake_invoke(schema, *, instructions, user, model, max_retries):
        captured["user"] = user
        return critic.ProposalList(proposals=[])

    monkeypatch.setattr(critic, "codex_structured_invoke", fake_invoke)
    out = critic.generate_proposals_node({"clusters": [{"pattern_name": "probe"}]})
    assert out == {"proposals_raw": []}
    return captured["user"]


def test_prompt_names_the_matcher_models_live_value(monkeypatch):
    user = _render_proposal_prompt(monkeypatch)
    assert f"model: {jobflow.DEFAULT_MODEL} (env: HERMES_JOBFLOW_MODEL" in user


def test_prompt_follows_the_matcher_module_not_a_snapshot(monkeypatch):
    # The value must be read from jobflow at call time. A literal copied into
    # the prompt module, or a default restated in critic.py, would not move.
    monkeypatch.setattr(jobflow, "DEFAULT_MODEL", "probe-model-9f3a")
    user = _render_proposal_prompt(monkeypatch)
    assert "model: probe-model-9f3a (env: HERMES_JOBFLOW_MODEL" in user


def test_no_stale_model_literal_survives_in_the_prompt_module():
    src = Path(_critic_prompts.__file__).read_text(encoding="utf-8")
    assert "gpt-4o" not in src, "a hardcoded model literal is back in the Critic prompt"


def test_temperature_claim_matches_the_matcher_call():
    # The Matcher's LLM call goes through obs/oauth_llm.py, which sends no
    # temperature because the Codex Responses endpoint rejects it. The prompt
    # must not tell Critic there is a number to tune.
    assert "temperature" not in Path(jobflow.__file__).read_text(encoding="utf-8")
    assert re.search(r"temperature:\s*[0-9]", TEMPLATE) is None
    assert "temperature: none" in TEMPLATE


_WEIGHT_TOLD = re.compile(r"- (\w+) \((\d\.\d\d)\)")
_WEIGHT_REAL = re.compile(r"\d\. (\w+) \(weight (\d\.\d\d)\)")


def test_dimension_weights_match_the_matcher_system_prompt():
    told = dict(_WEIGHT_TOLD.findall(TEMPLATE))
    real = dict(_WEIGHT_REAL.findall(_prompts.MATCHER_SYSTEM_PROMPT))
    assert len(real) == 7, real
    assert told == real


def test_comp_floor_matches_the_route_decision_default(monkeypatch):
    user = _render_proposal_prompt(monkeypatch)
    assert f"comp_floor: {jobflow._DEFAULT_COMP_FLOOR} (env: HERMES_JOBFLOW_COMP_FLOOR)" in user


def test_prompt_names_the_deployed_routing_bands(monkeypatch):
    user = _render_proposal_prompt(monkeypatch)
    assert f"proceed_threshold: {jobflow._DEFAULT_PROCEED_THRESHOLD} (env: " in user
    assert f"review_threshold: {jobflow._DEFAULT_REVIEW_THRESHOLD} (env: " in user


def test_thresholds_are_resolved_at_call_time_not_at_import(monkeypatch):
    # route_decision_node reads the env inside the node, so an override moves
    # the live routing. The prompt must report what the router would do now,
    # not the value that was set when the Critic process started.
    monkeypatch.setenv("HERMES_JOBFLOW_PROCEED_THRESHOLD", "9.25")
    monkeypatch.setenv("HERMES_JOBFLOW_REVIEW_THRESHOLD", "4.5")
    monkeypatch.setenv("HERMES_JOBFLOW_COMP_FLOOR", "3.5")
    user = _render_proposal_prompt(monkeypatch)
    assert "proceed_threshold: 9.25 (env: " in user
    assert "review_threshold: 4.5 (env: " in user
    assert "comp_floor: 3.5 (env: " in user


def test_no_threshold_literal_survives_in_the_configuration_block():
    # The block is rendered, so a re-typed number here would be a claim no
    # override can move -- the defect this file exists to catch.
    block = TEMPLATE.split("## Current Matcher configuration", 1)[1]
    for literal in ("8.75", "5.0", "2.0"):
        assert literal not in block, f"a hardcoded {literal} is back in the config block"


def test_matcher_system_prompt_bands_match_the_routing_defaults():
    # The Matcher LLM is told the bands in prose too. Same drift class, and
    # this prompt is not rendered, so a test is the only thing watching it.
    proceed = jobflow._DEFAULT_PROCEED_THRESHOLD
    review = jobflow._DEFAULT_REVIEW_THRESHOLD
    system = _prompts.MATCHER_SYSTEM_PROMPT
    assert f"score >= {proceed} -> PROCEED" in system
    assert f"{review} <= score < {proceed} -> REVIEW" in system
    assert f"score < {review} -> ARCHIVE" in system


def test_route_decision_docstring_defaults_match_the_constants():
    doc = jobflow.route_decision_node.__doc__ or ""
    assert f"HERMES_JOBFLOW_PROCEED_THRESHOLD  (default {jobflow._DEFAULT_PROCEED_THRESHOLD})" in doc
    assert f"HERMES_JOBFLOW_REVIEW_THRESHOLD   (default {jobflow._DEFAULT_REVIEW_THRESHOLD})" in doc


def test_matcher_temperature_is_taxonomy_not_an_auto_apply_route():
    """Kept as a kind, but nothing may claim it can be applied.

    Diego's call, 2026-09-06: a future backend may accept a temperature and
    historical proposals must keep validating, so the kind stays -- but the
    module docstring claimed it was auto-applicable 'under the
    reasoning_effort umbrella' while KIND_TO_KNOB never held it and the
    constitution has no temperature knob.
    """
    kinds = get_args(critic.Proposal.model_fields["kind"].annotation)
    assert "matcher.temperature" in kinds
    assert "matcher.temperature" not in critic.KIND_TO_KNOB
    assert "under reasoning_effort umbrella" not in (critic.__doc__ or "")


def test_readme_routing_diagram_matches_the_constants():
    readme = (Path(jobflow.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert f"score >= {jobflow._DEFAULT_PROCEED_THRESHOLD}" in readme
    assert f"score >= {jobflow._DEFAULT_REVIEW_THRESHOLD}" in readme
