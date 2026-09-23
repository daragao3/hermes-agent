"""A mistyped skill name gets did-you-mean suggestions from ALL skills, not the alphabetical first 20."""

from tools.skills_tool import _close_skill_names

NAMES = ["agent-browser", "arch-review", "jobflow-tailoring-quality-control",
         "jobflow-tailor-batch-generation", "tailor-batch-gate-processing", "tailor-cron-triage"]


def test_category_prefixed_near_miss_resolves():
    assert _close_skill_names("orchestrator:tailor-tailoring-quality-control", NAMES)[0] == \
        "jobflow-tailoring-quality-control"


def test_missing_platform_prefix_resolves():
    assert "jobflow-tailor-batch-generation" in _close_skill_names("orchestrator:tailor-batch-generation", NAMES)


def test_unrelated_name_gets_nothing():
    assert _close_skill_names("zzzz", NAMES) == []
    assert _close_skill_names("", NAMES) == []
