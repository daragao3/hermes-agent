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

from graphs import _critic_prompts, _prompts, critic, jobflow

TEMPLATE = _critic_prompts.CRITIC_PROPOSAL_USER_TEMPLATE


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


def test_comp_floor_matches_the_route_decision_default():
    assert f"comp_floor: {jobflow._DEFAULT_COMP_FLOOR} (env: HERMES_JOBFLOW_COMP_FLOOR)" in TEMPLATE
