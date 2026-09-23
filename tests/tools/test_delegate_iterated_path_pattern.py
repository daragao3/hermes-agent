"""A `{name}` path segment inside an explicit for-each fan-out is a per-item pattern, not a leftover template.

2026-09-22: the tailor sent "Jobs: 4459647437, 4469212967, ... For each, read the matching request,
applications/{job_id}/research-summary.md and stakeholders.json ..." -- valid, the job ids are listed
and the subagent substitutes each -- and the placeholder guard refused it. A lone unexpanded marker
must still be refused.
"""

from tools.delegate_tool_tasks import _validate_batch_tasks

ITERATED = ("Analyze four Tailor requests. Jobs: 4459647437, 4469212967, 4470408454, 4470482891. "
            "For each, read applications/{job_id}/research-summary.md and stakeholders.json, then "
            "return a tailoring config.")


def test_for_each_path_pattern_is_accepted():
    assert _validate_batch_tasks([{"goal": ITERATED}, {"goal": ITERATED.replace("four", "five")}]) is None


def test_windows_separator_and_extension_forms_are_accepted():
    for goal in (ITERATED.replace("/{job_id}/", "\\{job_id}\\"),
                 "For every run listed (a1, b2), open logs/{run_id}.json and summarise it."):
        assert _validate_batch_tasks([{"goal": goal}]) is None, goal


def test_lone_unexpanded_marker_is_still_refused():
    err = _validate_batch_tasks([{"goal": "Read applications/{job_id}/resume.md and fix the summary."}])
    assert err and "template marker" in err


def test_marker_outside_a_path_is_refused_even_when_iterating():
    err = _validate_batch_tasks([{"goal": "For each job, write a note about {company name} to the tracker."}])
    assert err and "{company name}" in err


def test_second_unexpanded_marker_is_found_past_an_allowed_one():
    goal = ITERATED + " Then email <recipient_name> the result."
    err = _validate_batch_tasks([{"goal": goal}])
    assert err and "<recipient_name>" in err
