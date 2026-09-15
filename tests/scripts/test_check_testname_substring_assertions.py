"""Control for the test-name substring-assertion scanner.

The scanner flags a presence assertion whose asserted literal is already
satisfied by the enclosing test function's own name, because pytest names
``tmp_path`` after the test and most refusal messages echo the path.

An audit matcher is green by default: it reports nothing when it is broken and
nothing when the tree is clean, and those two look identical.  So this file
pins BOTH halves — spellings the scanner MUST catch and spellings it MUST NOT —
including the real shapes from the 2026-09-14 audit and the near-misses that
decide the matcher's width.  Without the must-not half a matcher can be widened
until it flags everything; without the must-catch half it can be narrowed back
to one spelling.  Either way the suite stays green, which is how the original
blind spot survived.

The worked reference is
``tests/tools/test_skill_manager_tool.py::test_symlinked_skill_dir_refused``,
whose ``assert "symlink" in result["error"].lower()`` could not fail: the
refusal echoes a path under ``test_symlinked_skill_dir_refus0``.  Fixed in
``6753c9e127`` by pinning ``"is a symlink/junction"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_testname_substring_assertions import (
    squash,
    sweep_source,
    tmp_path_basename,
)


def _scan(body: str) -> list[dict]:
    return sweep_source(Path("test_probe.py"), body.lstrip("\n"))


def _literals(body: str) -> set[str]:
    return {h["literal"] for h in _scan(body)}


# ── MUST CATCH ─────────────────────────────────────────────────────────


MUST_CATCH = [
    pytest.param(
        '''
def test_symlinked_skill_dir_refused(tmp_path):
    assert "symlink" in result["error"].lower()
''',
        "symlink",
        id="the reference defect, case-folded haystack",
    ),
    pytest.param(
        '''
def test_missing_job_id_raises(tmp_path):
    with pytest.raises(IntentParseError, match="job_id"):
        parse_intent_file(path)
''',
        "job_id",
        id="pytest.raises match= with a plain literal",
    ),
    pytest.param(
        '''
def test_entry_not_a_mapping_fails(tmp_path):
    assert "mapping" in (result.stdout + result.stderr)
''',
        "mapping",
        id="haystack is an expression, not a bare name",
    ),
    pytest.param(
        '''
class TestDoctorCertificates:
    def test_broken_bundle_fails_without_fix(self, tmp_path):
        assert "broken" in out.lower()
''',
        "broken",
        id="method of a Test class",
    ),
    pytest.param(
        '''
def test_ahead_head_warns_unlanded(tmp_path):
    assert "AHEAD" in out and "unlanded" in out.lower()
''',
        "unlanded",
        id="second operand of a BoolOp and-chain",
    ),
    pytest.param(
        '''
async def test_long_output_truncated_for_non_chunking_adapter(tmp_path):
    assert "truncated" in delivered.lower()
''',
        "truncated",
        id="async test function",
    ),
    pytest.param(
        '''
def test_unencodable_surrogate_rejected_before_write(tmp_path):
    assert res.error and "surrogate" in res.error
''',
        "surrogate",
        id="no .lower(), literal already lowercase",
    ),
    pytest.param(
        '''
def test_removed_item_missing_name_fails(tmp_path):
    with pytest.warns(UserWarning, match="name"):
        run()
''',
        "name",
        id="pytest.warns is the same shape as raises",
    ),
]


@pytest.mark.parametrize("body,literal", MUST_CATCH)
def test_scanner_catches(body: str, literal: str) -> None:
    assert literal in _literals(body)


# ── MUST NOT CATCH ─────────────────────────────────────────────────────


MUST_NOT_CATCH = [
    pytest.param(
        '''
def test_delete_refuses_pinned(tmp_path):
    assert "is pinned and cannot be deleted" in result["error"].lower()
''',
        id="a pinned PHRASE -- the fix shape must not re-flag",
    ),
    pytest.param(
        '''
def test_symlinked_skill_dir_refused(tmp_path):
    assert "is a symlink/junction" in result["error"]
''',
        id="the actual 6753c9e127 fix",
    ),
    pytest.param(
        '''
def test_write_rejects_bad_input(tmp_path):
    assert "surrogate" in res.error
''',
        id="literal absent from the test name",
    ),
    pytest.param(
        '''
def helper_symlink_check(tmp_path):
    assert "symlink" in result["error"]
''',
        id="not a test function -- pytest gives it no tmp_path",
    ),
    pytest.param(
        '''
def test_symlinked_skill_dir_refused(tmp_path):
    """Docstring mentioning symlink in prose, and a comment below."""
    # the symlink case is the one that matters here
    assert result["error"]
''',
        id="prose only -- ast never sees comments or docstrings as Compares",
    ),
    pytest.param(
        '''
def test_symlink_is_refused(tmp_path):
    assert "symlink" not in result["error"]
''',
        id="ABSENCE assertion -- a different population, audited separately",
    ),
    pytest.param(
        '''
def test_symlink_is_refused(tmp_path):
    assert result["error"] in "symlink"
''',
        id="operands reversed -- the literal is the container",
    ),
    pytest.param(
        '''
def test_symlink_error_equals(tmp_path):
    assert result["error"] == "symlink"
''',
        id="equality, not membership -- a path cannot satisfy it",
    ),
    pytest.param(
        '''
def test_missing_job_id_raises(tmp_path):
    with pytest.raises(IntentParseError, match=EXPECTED_PATTERN):
        parse_intent_file(path)
''',
        id="match= is a name, not a literal -- nothing to compare",
    ),
]


@pytest.mark.parametrize("body", MUST_NOT_CATCH)
def test_scanner_ignores(body: str) -> None:
    assert _scan(body) == []


# ── the truncation model is load-bearing, not incidental ───────────────


def test_tmp_path_basename_truncates_at_thirty_characters() -> None:
    """pytest cuts the sanitised node name to 30 chars, and that decides cases.

    ``test_patch_replace_funnel_rejects_surrogate_new_string`` CONTAINS
    "surrogate", but the directory pytest creates is
    ``test_patch_replace_funnel_reje`` -- the token never reaches the path, so
    its ``assert "surrogate" in res.error`` is genuinely load-bearing.  A naive
    name-substring check would have false-flagged it.  Its sibling
    ``test_unencodable_surrogate_rejected_before_write`` truncates to
    ``test_unencodable_surrogate_rej``, which DOES carry the token -- that one
    was a real finding.
    """
    safe = "test_patch_replace_funnel_rejects_surrogate_new_string"
    unsafe = "test_unencodable_surrogate_rejected_before_write"

    assert tmp_path_basename(safe) == "test_patch_replace_funnel_reje"
    assert "surrogate" not in tmp_path_basename(safe)

    assert tmp_path_basename(unsafe) == "test_unencodable_surrogate_rej"
    assert "surrogate" in tmp_path_basename(unsafe)

    # Both names contain the token; only the truncation separates them, which
    # is why the scanner reports `literal_in_tmp_path_basename` separately from
    # the coarse name collision.
    assert "surrogate" in safe and "surrogate" in unsafe


def test_strict_flag_is_reported_separately_from_the_name_collision() -> None:
    """The coarse signal is a deliberate SUPERSET of the tmp_path signal.

    Squashing drops the ``_`` separators pytest actually keeps, so a literal
    can collide with the name while being unable to reach the directory.  That
    is on purpose: a haystack can carry the test name by other routes (a node
    id, ``request.node.name``), so the coarse signal stays the net and the
    strict field says whether a tmp_path leak specifically is possible.
    """
    hits = _scan(
        '''
def test_read_past_eof_note(tmp_path):
    assert "past eof" in result["hint"]
'''
    )
    assert len(hits) == 1
    assert hits[0]["literal"] == "past eof"
    # Collides once non-alphanumerics are dropped ...
    assert squash("past eof") in squash("test_read_past_eof_note")
    # ... but the space cannot survive into the directory name.
    assert not hits[0]["literal_in_tmp_path_basename"]


def test_case_folding_of_the_haystack_is_recorded() -> None:
    """``.lower()`` widens the collision, because the path segment is already
    lowercase -- an uppercase literal cannot be satisfied by the path without
    it.  ``test_dirty_tree_noted_but_not_counted``'s ``assert "DIRTY" in out``
    was rejected at confirmation on exactly this axis."""
    folded = _scan(
        '''
def test_dirty_tree_noted(tmp_path):
    assert "dirty" in out.lower()
'''
    )
    plain = _scan(
        '''
def test_dirty_tree_noted(tmp_path):
    assert "dirty" in out
'''
    )
    assert folded[0]["case_folded"] is True
    assert plain[0]["case_folded"] is False
