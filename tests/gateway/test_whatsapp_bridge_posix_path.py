"""A bridge-reported media path is absolute under EITHER convention.

``_collect_bridge_media`` routes an ABSOLUTE ``mediaUrl`` through
``_is_allowed_bridge_path`` (must resolve inside a Hermes cache dir) and lets
everything else through unchecked. The WhatsApp bridge is a SEPARATE process
whose paths need not follow this host's convention -- it may run under WSL or a
container, and "a rogue bridge could hand back /etc/passwd" is the threat model
the containment check exists for -- so a POSIX-rooted path is a legitimate
spelling to see here.

CPython 3.13 made ``ntpath.isabs("/etc/passwd")`` False on Windows. With the
host-only predicate, such a path therefore stopped looking absolute, fell into
the accept-anything branch, and was handed to ``_inject_document_text``, which
reads up to 100 KB of the file straight into the agent prompt -- the exfiltration
the cache-dir check was written to stop.

The mechanism test holds on every host: the ``os`` binding of BOTH modules that
could serve the predicate is swapped for a proxy whose ``path.isabs`` is
3.13-ntpath-shaped, while each module's real ``posixpath`` stays intact. The
``windows_only`` test pins the real host predicate (venv 3.13.15).
"""

import os
import sys

import pytest

from gateway.platforms.event import MessageType
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from plugins.platforms.whatsapp import adapter as whatsapp_adapter
from tools import file_tools_paths


class _PathProxy:
    def __init__(self, isabs):
        self.isabs = isabs

    def __getattr__(self, name):
        return getattr(os.path, name)


class _OsProxy:
    """``os`` with only ``path.isabs`` replaced; everything else forwards."""

    def __init__(self, isabs):
        self.path = _PathProxy(isabs)

    def __getattr__(self, name):
        return getattr(os, name)


def _host_isabs_313_ntpath(path):
    """ntpath.isabs on CPython 3.13: only drive- or UNC-rooted paths are absolute."""
    text = os.fspath(path).replace("\\", "/")
    return (len(text) >= 3 and text[1] == ":" and text[2] == "/") or text.startswith("//")


def _pin_313_ntpath_host(monkeypatch):
    """Make every module that could serve the predicate see a 3.13 ntpath host."""
    for module in (whatsapp_adapter, file_tools_paths):
        monkeypatch.setattr(module, "os", _OsProxy(_host_isabs_313_ntpath))


class _FakeAdapter:
    """``_collect_bridge_media`` touches only ``self.name`` on this path."""

    name = "whatsapp"


async def _collect(urls, msg_type=MessageType.DOCUMENT):
    return await whatsapp_adapter.WhatsAppAdapter._collect_bridge_media(
        _FakeAdapter(), {"mediaUrls": list(urls)}, msg_type
    )


def _make_profile_document(root, name="doc_deadbeef_report.txt", body=b"cache contents"):
    documents = root / "cache" / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    target = documents / name
    target.write_bytes(body)
    return target


class TestBridgePathPredicate:
    def test_posix_rooted_is_absolute_under_either_convention(self, monkeypatch):
        _pin_313_ntpath_host(monkeypatch)
        assert whatsapp_adapter._is_rooted("/etc/passwd") is True
        assert whatsapp_adapter._is_rooted("/root/.ssh/id_rsa") is True
        assert whatsapp_adapter._is_rooted("C:/Users/me/img.jpg") is True
        assert whatsapp_adapter._is_rooted("relative/img.jpg") is False

    @pytest.mark.windows_only
    def test_windows_host_treats_posix_root_as_absolute(self):
        assert whatsapp_adapter._is_rooted("/etc/passwd") is True
        # The 3.13 ntpath delta itself. Before 3.13 (CI's 3.11 lane) ntpath still
        # called a root-only path absolute; the predicate above must hold either way.
        assert os.path.isabs("/etc/passwd") is (sys.version_info < (3, 13))


class TestBridgeMediaContainment:
    @pytest.mark.asyncio
    async def test_posix_rooted_bridge_path_is_containment_checked(self, monkeypatch):
        """The regression: it must NOT reach the accept-anything branch."""
        _pin_313_ntpath_host(monkeypatch)
        for url in ("/etc/passwd", "/root/.ssh/id_rsa", "/proc/self/environ"):
            urls, mimes = await _collect([url])
            assert urls == [], url
            assert mimes == [], url

    @pytest.mark.asyncio
    async def test_cache_dir_path_still_accepted(self, monkeypatch, tmp_path):
        """Positive control: containment must still ADMIT a real cache-dir path."""
        _pin_313_ntpath_host(monkeypatch)
        target = _make_profile_document(tmp_path)
        token = set_hermes_home_override(str(tmp_path))
        try:
            urls, mimes = await _collect([str(target)])
        finally:
            reset_hermes_home_override(token)
        assert urls == [str(target)]
        assert mimes == ["text/plain"]

    @pytest.mark.asyncio
    async def test_relative_bridge_path_keeps_its_unchecked_path(self, monkeypatch):
        """Only ABSOLUTE paths are containment-checked; relative ones are unchanged."""
        _pin_313_ntpath_host(monkeypatch)
        urls, mimes = await _collect(["media/img.jpg"], MessageType.PHOTO)
        assert urls == ["media/img.jpg"]
        assert mimes == ["unknown"]

    @pytest.mark.windows_only
    @pytest.mark.asyncio
    async def test_windows_host_rejects_posix_rooted_bridge_path(self):
        urls, mimes = await _collect(["/etc/passwd"])
        assert urls == []
        assert mimes == []
