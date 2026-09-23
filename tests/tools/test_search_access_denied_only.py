"""ripgrep exits 2 on any unreadable entry; "no matches + only access-denied complaints" is an empty
result with a warning, not a failed search (2026-09-22: a cron search over %TEMP% died on a live
pytest dir)."""

from types import SimpleNamespace

from tools import file_operations_search as fos


def test_access_denied_only_detection():
    d = r"rg: C:/Users/diego/AppData/Local/Temp\pytest-of-diego\pytest-2931: Access is denied. (os error 5)"
    msg = fos._access_denied_only(d)
    assert msg and msg.startswith("Skipped 1 unreadable path(s)") and "pytest-2931" in msg
    assert fos._access_denied_only("rg: /x: Permission denied (os error 13)\nrg: /y: Permission denied (os error 13)")
    assert fos._access_denied_only("rg: regex parse error:\n    (\n    ^") is None
    assert fos._access_denied_only(d + "\nrg: some other failure") is None
    assert fos._access_denied_only("") is None


def test_content_search_returns_empty_with_warning():
    result = SimpleNamespace(
        exit_code=2, stdout="rg: C:/tmp/locked: Access is denied. (os error 5)\n")
    out = fos._parse_search_output(result, "content", limit=50, offset=0, context=0)
    assert out.error is None and out.total_count == 0 and "unreadable" in out.warning


def test_real_errors_still_fail():
    result = SimpleNamespace(exit_code=2, stdout="rg: regex parse error: unclosed group\n")
    out = fos._parse_search_output(result, "content", limit=50, offset=0, context=0)
    assert out.error and out.error.startswith("Search failed")
