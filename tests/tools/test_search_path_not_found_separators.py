"""Path-not-found suggestions keep the caller's separator (2026-09-23: "mailbox/researcher\\processed")."""

from types import SimpleNamespace

from tools.file_operations_search import SearchMixin


class _Ops(SearchMixin):
    def __init__(self, listing):
        self._listing = listing

    def _escape_shell_arg(self, s):
        return s

    def _exec(self, cmd):
        if cmd.startswith("test -d"):
            return SimpleNamespace(stdout="yes", exit_code=0)
        return SimpleNamespace(stdout=self._listing, exit_code=0)


def test_forward_slash_parent_gets_forward_slash_suggestions():
    res = _Ops("inbox\nprocessed\r\noutbox\n")._path_not_found_result(
        "C:/Users/diego/.hermes/mailbox/researcher/processing")
    assert "C:/Users/diego/.hermes/mailbox/researcher/processed" in res.error
    assert "\\" not in res.error


def test_backslash_parent_keeps_backslashes():
    res = _Ops("processed\n")._path_not_found_result(r"C:\Users\diego\mailbox\researcher\processing")
    assert r"C:\Users\diego\mailbox\researcher\processed" in res.error
