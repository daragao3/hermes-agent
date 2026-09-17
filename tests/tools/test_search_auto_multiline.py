"""Tests for search_files auto-multiline routing on \\n patterns."""

import json

import pytest

from tools.file_operations_search import _crlf_tolerant_newlines
from tools.file_tools import search_tool

_SOURCE = (
    "def setup():\n    init_db()\n    return True\n\n"
    "def teardown():\n    close_db()\n"
)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    d = tmp_path / "proj"
    d.mkdir()
    # newline="\n": a text-mode write on Windows would turn this into CRLF and
    # the LF fixture the tests below assume would silently be a CRLF one.
    (d / "mod.py").write_text(_SOURCE, encoding="utf-8", newline="\n")
    return d


@pytest.fixture
def crlf_proj(tmp_path, monkeypatch):
    """The same module with CRLF line endings, the common case on a Windows checkout."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    d = tmp_path / "proj_crlf"
    d.mkdir()
    (d / "mod.py").write_bytes(_SOURCE.replace("\n", "\r\n").encode("utf-8"))
    return d


class TestAutoMultiline:
    def test_newline_regex_matches_across_lines(self, proj):
        r = json.loads(search_tool(r"def setup\(\):\n    init_db\(\)", path=str(proj), task_id="t-ml"))
        assert "error" not in r
        assert r["total_count"] >= 1
        assert "multiline mode (-U)" in r.get("warning", "")

    def test_literal_newline_in_pattern_matches(self, proj):
        # A raw newline in the pattern (not the \n escape) also routes to
        # multiline mode. Keep the pattern free of regex metachars.
        r = json.loads(search_tool("return True\n\ndef teardown", path=str(proj), task_id="t-ml"))
        assert "error" not in r
        assert r["total_count"] >= 1

    def test_plain_pattern_unaffected(self, proj):
        r = json.loads(search_tool("init_db", path=str(proj), task_id="t-ml"))
        assert r["total_count"] == 1
        assert "multiline mode (-U)" not in r.get("warning", "")

    def test_escaped_backslash_n_stays_literal(self, proj):
        # \\n = literal backslash+n search, not a newline: no multiline mode.
        (proj / "strings.py").write_text('SEP = "a\\\\nb"\n', encoding="utf-8")
        r = json.loads(search_tool(r"a\\nb", path=str(proj), task_id="t-ml"))
        assert "error" not in r
        # The mode note, not the bare word: the zero-match hint embeds the search
        # path, and the runner names temp dirs after this test FILE.
        assert "multiline mode (-U)" not in (r.get("warning") or "")

    def test_multiline_zero_match_is_clean(self, proj):
        r = json.loads(search_tool(r"def missing\(\):\n    nope\(\)", path=str(proj), task_id="t-ml"))
        assert "error" not in r
        assert r["total_count"] == 0

    def test_newline_regex_matches_across_crlf_lines(self, crlf_proj):
        """ripgrep's \\n never matches CRLF (not even under --crlf), so the
        auto-multiline promise silently returned 0 matches on CRLF files."""
        r = json.loads(search_tool(r"def setup\(\):\n    init_db\(\)", path=str(crlf_proj), task_id="t-ml"))
        assert "error" not in r
        assert r["total_count"] >= 1
        assert "multiline mode (-U)" in r.get("warning", "")

    def test_literal_newline_in_pattern_matches_crlf(self, crlf_proj):
        r = json.loads(search_tool("return True\n\ndef teardown", path=str(crlf_proj), task_id="t-ml"))
        assert "error" not in r
        assert r["total_count"] >= 1


class TestCrlfTolerantNewlines:
    """The rewrite applied to a multiline pattern before it reaches rg."""

    @pytest.mark.parametrize("pattern, expected", [
        (r"a\nb", r"a(?:\r?\n)b"),
        ("a\nb", r"a(?:\r?\n)b"),                      # raw newline character
        (r"x\n{2}", r"x(?:\r?\n){2}"),                 # quantifier stays on the whole break
        (r"a\\nb", r"a\\nb"),                         # literal backslash + n: untouched
        (r"tail\\\n", r"tail\\(?:\r?\n)"),           # escaped backslash, then a real \n
        (r"[\n]x", r"[\n]x"),                           # inside a class: untouched
        (r"[^\n]+\nend", r"[^\n]+(?:\r?\n)end"),      # class kept, break outside rewritten
        (r"[a\]]\n", r"[a\]](?:\r?\n)"),              # escaped ] does not close the class
        ("plain", "plain"),
    ])
    def test_rewrite(self, pattern, expected):
        assert _crlf_tolerant_newlines(pattern) == expected
