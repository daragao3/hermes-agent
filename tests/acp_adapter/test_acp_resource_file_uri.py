"""``_path_from_file_uri``: where an ACP client's file URI lands on THIS host.

The ``/mnt/<drive>/...`` rewrite exists so Hermes running inside WSL can read
a Windows path that Zed hands it through ``wsl.exe``. It used to fire on every
host, so a Windows-hosted Hermes turned ``file:///C:/Users/me/notes.md`` into
``/mnt/c/Users/me/notes.md`` -- a path that does not exist there -- and every
attachment came back as ``[Could not read attached file: ...]``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from acp_adapter.content import _path_from_file_uri


@pytest.mark.parametrize("uri", ["file:///C:/Users/me/notes.md", "file:///c:/Users/me/notes.md"])
def test_windows_drive_uri_is_mounted_only_inside_wsl(uri):
    """The rewrite is a WSL fact (``in_wsl`` taken as data), not a Windows-path fact."""
    assert _path_from_file_uri(uri, in_wsl=True) == Path("/mnt/c/Users/me/notes.md")
    native = _path_from_file_uri(uri, in_wsl=False)
    assert native is not None
    assert native.drive.upper() == "C:", native
    assert native.parts[-3:] == ("Users", "me", "notes.md"), native


def test_this_hosts_own_file_uri_resolves_to_the_file(tmp_path):
    """A URI minted by this host's ``Path.as_uri()`` must read back on this host."""
    attached = tmp_path / "notes.md"
    attached.write_text("body", encoding="utf-8")
    resolved = _path_from_file_uri(attached.as_uri())
    assert resolved is not None
    assert resolved.is_file(), resolved
    assert resolved.read_text(encoding="utf-8") == "body"
