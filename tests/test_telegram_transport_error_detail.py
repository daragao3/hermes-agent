"""Telegram transport errors must name WHY a connect failed, not only THAT it failed.

BACKGROUND, measured.

`profiles/main/logs/errors-gateway.log` carried an escalating ramp of Telegram
reconnects: 21 on 2026-09-17, 66 on 09-18, 115 on 09-19 (peaking at 18/hour).
Every single line read:

    [Telegram] Telegram network error (attempt 1/10), reconnecting in 5s.
    Error: httpx.ConnectError:

A class name and nothing else. httpx raises ConnectError with an empty str()
after a failed connect, and PTB then formats the wrapped error as
f"{type(exc).__name__}: {exc}", which collapses to exactly that string.

The consequence is not cosmetic. A DNS failure, a routing/VPN drop and a
blocked socket are three unrelated root causes with three different fixes, and
all three log identically. The 2026-09-19 triage could not attribute the ramp
from logs at all: two candidate root causes (the NordVPN fallback-IP transport,
and ephemeral-port exhaustion) were checked and BOTH falsified, leaving no
third hypothesis the logs could even distinguish.

a04fcbf779 already fixed half of this -- it added the class name, because
before that the line read "Telegram network _redact_telegram_error_text(error)".
The detail was never actually lost, only unreachable: ConnectError still
carries the underlying OSError on its __cause__/__context__ chain, and
_iter_exception_graph already walks that graph for the error CLASSIFIERS. These
tests pin walking it for the error DESCRIPTION too.

What is pinned:
  - an OS error number is preferred over any other detail, because it is the
    part that discriminates between the three causes above;
  - a top-level error that already carries real text is left alone;
  - the walk never raises, never returns a secret, and never blocks the error
    path it describes.
"""
from __future__ import annotations

import pytest

from plugins.platforms.telegram.adapter import (
    _describe_transport_error,
    _redact_telegram_error_text,
    _transport_error_root,
)


class _FakeConnectError(Exception):
    """httpx.ConnectError's shape: raised with no args, so str() is empty."""


class _FakeNetworkError(Exception):
    """PTB's NetworkError wrap: f'{type(inner).__name__}: {inner}'."""


def _ptb_wrapped(inner: BaseException, label: str = "httpx.ConnectError") -> Exception:
    """Rebuild the real production shape: PTB NetworkError whose message is a
    bare 'ClassName: ' because the inner str() was empty, with the inner error
    still reachable on __cause__."""
    err = _FakeNetworkError(f"{label}: {inner}")
    err.__cause__ = inner
    return err


# --------------------------------------------------------------------------
# the production shape
# --------------------------------------------------------------------------

def test_the_2026_09_19_line_now_names_its_root_cause():
    """REGRESSION: the exact log line that appeared 115 times on 2026-09-19.

    Before: "httpx.ConnectError: ". After: the same, plus the WinError that
    says which of the three causes it was.
    """
    oserr = OSError(10060, "A connection attempt failed because the connected "
                           "party did not properly respond after a period of time")
    oserr.winerror = 10060
    connect = _FakeConnectError()
    connect.__cause__ = oserr
    wrapped = _ptb_wrapped(connect)

    # Precondition: this really is the undiagnosable shape.
    assert _redact_telegram_error_text(wrapped).rstrip().endswith(":"), (
        "test fixture no longer reproduces the empty-wrap shape")

    described = _describe_transport_error(wrapped)
    assert "10060" in described, (
        f"the discriminating WinError must reach the log line; got {described!r}")
    # Python maps OSError(10060) to the TimeoutError subclass via errno, so assert
    # the family rather than the literal name -- pinning "OSError" would fail on a
    # correct implementation.
    assert isinstance(oserr, OSError)
    assert type(oserr).__name__ in described


@pytest.mark.parametrize("winerror,fragment,meaning", [
    (11001, "getaddrinfo failed", "DNS"),
    (10060, "connection attempt failed", "routing/VPN"),
    (10013, "access a socket in a way forbidden", "blocked"),
])
def test_the_three_causes_are_now_distinguishable(winerror, fragment, meaning):
    """The whole point: three causes that logged identically must not any more."""
    oserr = OSError(winerror, fragment)
    oserr.winerror = winerror
    connect = _FakeConnectError()
    connect.__cause__ = oserr

    described = _describe_transport_error(_ptb_wrapped(connect))
    assert str(winerror) in described, f"{meaning} cause lost its errno"


def test_distinct_causes_produce_distinct_lines():
    """Stated as an inequality, so a regression that hardcodes one errno fails."""
    def line(winerror):
        oserr = OSError(winerror, "boom")
        oserr.winerror = winerror
        connect = _FakeConnectError()
        connect.__cause__ = oserr
        return _describe_transport_error(_ptb_wrapped(connect))

    assert line(11001) != line(10060) != line(10013)


# --------------------------------------------------------------------------
# root extraction
# --------------------------------------------------------------------------

def test_errno_is_preferred_over_a_chattier_ancestor():
    """An ancestor with prose must not win over one with an error number.

    The number is what discriminates; the prose is localised and varies by
    Windows build.
    """
    oserr = OSError(11001, "getaddrinfo failed")
    oserr.winerror = 11001
    chatty = RuntimeError("something went wrong while connecting")
    chatty.__cause__ = oserr
    connect = _FakeConnectError()
    connect.__cause__ = chatty

    root = _transport_error_root(_ptb_wrapped(connect))
    assert "11001" in root


def test_posix_errno_is_also_picked_up():
    """Not Windows-only: a bare errno (no winerror) must work too."""
    oserr = OSError(111, "Connection refused")  # ECONNREFUSED
    connect = _FakeConnectError()
    connect.__cause__ = oserr

    assert "111" in _transport_error_root(_ptb_wrapped(connect))


def test_context_chain_is_walked_not_just_cause():
    """`raise X` inside an `except Y` sets __context__, not __cause__."""
    oserr = OSError(10060, "timed out")
    oserr.winerror = 10060
    connect = _FakeConnectError()
    connect.__context__ = oserr

    assert "10060" in _transport_error_root(connect)


def test_text_only_ancestor_is_used_when_no_errno_exists():
    inner = RuntimeError("All connection attempts failed")
    connect = _FakeConnectError()
    connect.__cause__ = inner

    root = _transport_error_root(_ptb_wrapped(connect))
    assert "All connection attempts failed" in root


def test_bare_classname_tail_is_not_mistaken_for_detail():
    """PTB's empty wrap ends in 'ClassName:' -- that is not detail, and using it
    would reintroduce exactly the uninformative line."""
    empty_wrap = _FakeNetworkError("httpx.ConnectError: ")
    connect = _FakeConnectError()
    connect.__cause__ = empty_wrap
    outer = _ptb_wrapped(connect)

    assert _transport_error_root(outer) == "", (
        "a bare 'ClassName:' tail must not be reported as a root cause")


def test_silent_graph_returns_empty_not_a_dangling_arrow():
    """With nothing to add, the description must be unchanged -- no '<- ' tail."""
    connect = _FakeConnectError()
    described = _describe_transport_error(connect)

    assert described == "_FakeConnectError"
    assert "<-" not in described


# --------------------------------------------------------------------------
# the existing contract must not regress
# --------------------------------------------------------------------------

def test_error_with_real_text_is_left_alone():
    """When the top level already says something, the graph must not be appended.

    Otherwise every ordinary error grows a noisy duplicate tail.
    """
    described = _describe_transport_error(RuntimeError("Conflict: terminated by other getUpdates"))

    assert described == "RuntimeError: Conflict: terminated by other getUpdates"
    assert "<-" not in described


def test_none_still_describes_as_none():
    assert _describe_transport_error(None) == "None"


def test_non_exception_input_is_tolerated():
    """_describe_transport_error takes `object`; a non-exception must not explode."""
    assert _transport_error_root("just a string") == ""
    assert _describe_transport_error("just a string") == "str: just a string"


# --------------------------------------------------------------------------
# safety: diagnostics must never break the path they describe
# --------------------------------------------------------------------------

def test_cycle_in_the_cause_graph_terminates():
    """_iter_exception_graph is cycle-safe; pin that this helper inherits it."""
    a = _FakeConnectError()
    b = _FakeConnectError()
    a.__cause__ = b
    b.__cause__ = a

    assert _transport_error_root(a) == ""  # completes, does not hang


def test_an_exploding_ancestor_does_not_propagate():
    """A __str__ that raises must not turn a network blip into a crash on the
    error path."""
    class _Hostile(Exception):
        def __str__(self):
            raise ValueError("hostile __str__")

    connect = _FakeConnectError()
    connect.__cause__ = _Hostile()

    # Must not raise.
    assert isinstance(_transport_error_root(connect), str)
    assert isinstance(_describe_transport_error(connect), str)


def test_root_detail_is_redacted():
    """The recovered detail goes through the same redactor as everything else.

    This matters specifically because the change WIDENS what reaches the log:
    cause-chain text that was previously unreachable now gets printed, and httpx
    connect errors routinely carry the request URL -- which for Telegram embeds
    the bot token. Uses a realistically-shaped token (10-digit id, 35-char
    secret); a synthetic short one does not match the redactor's pattern and
    would make this test pass for the wrong reason.
    """
    token = "8154321098:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    secret = token.split(":", 1)[1]
    inner = RuntimeError(
        f"connect to https://api.telegram.org/bot{token}/getUpdates failed")
    connect = _FakeConnectError()
    connect.__cause__ = inner

    root = _transport_error_root(_ptb_wrapped(connect))
    assert secret not in root, "bot token leaked into the diagnostic tail"
    assert "api.telegram.org" in root, "redaction must not destroy the diagnostic"
