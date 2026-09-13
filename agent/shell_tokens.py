"""Tokenising a command line without destroying Windows path separators.

``shlex.split`` defaults to POSIX mode, where a backslash escapes the next character and is
then discarded — so on Windows every native path in a command becomes an unusable token, with
no exception raised. Upstream reached the same fix independently, as
``hermes_cli._subprocess_compat.split_command_line``, and wired it through the shell-hook
runner. This module keeps its own name for its remaining callers, but DELEGATES rather than
carrying a second implementation of the same tokeniser.

The two implementations differ in method — this one cleared ``shlex``'s escape character,
upstream's uses ``posix=False`` plus a quote strip — but agree on every case
``tests/agent/test_shell_tokens.py`` pins, including POSIX escape semantics (upstream's POSIX
branch is literally ``shlex.split``) and the ValueError on an unbalanced quote.
"""
from __future__ import annotations

from typing import List

from hermes_cli._subprocess_compat import split_command_line


def split_command(cmd: str) -> List[str]:
    """Split ``cmd`` into tokens, keeping Windows path separators intact.

    Raises :class:`ValueError` on unbalanced quotes, exactly as ``shlex.split`` does, so
    existing callers can keep their fallbacks."""
    return split_command_line(cmd)
