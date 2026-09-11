"""Tests for the systemd ExecStopPost cgroup reaper (issue #37454)."""

from __future__ import annotations

import os as os
import signal
from pathlib import Path

import pytest

from gateway import cgroup_cleanup

# The cgroup reaper is a systemd ExecStopPost hook — Linux-only by design
# (gateway/cgroup_cleanup.py carries a `# windows-footgun: ok` marker). Tests
# that assert on signal.SIGKILL cannot even be evaluated on Windows, where the
# attribute is absent; skip them there rather than mask a real regression.
_requires_sigkill = pytest.mark.skipif(
    not hasattr(signal, "SIGKILL"),
    reason="cgroup reaper is Linux-only; signal.SIGKILL absent on Windows",
)


class TestOwnCgroupPath:
    def test_parses_v2_cgroup_path(self, tmp_path, monkeypatch):
        proc_self = tmp_path / "cgroup"
        proc_self.write_text("0::/user.slice/user-1000.slice/hermes-gateway.service\n")
        monkeypatch.setattr(
            cgroup_cleanup,
            "Path",
            lambda p: proc_self if p == "/proc/self/cgroup" else Path(p),
        )

        assert cgroup_cleanup._own_cgroup_path() == "/user.slice/user-1000.slice/hermes-gateway.service"


class TestReapCgroup:


    def test_noop_when_procs_file_missing(self, tmp_path, monkeypatch):
        cgroup_path = "/missing.slice/hermes-gateway.service"
        monkeypatch.setattr(
            cgroup_cleanup,
            "Path",
            lambda p: tmp_path / "does-not-exist" if "cgroup.procs" in p else Path(p),
        )

        def _explode(*_a, **_kw):
            pytest.fail("os.kill must not be called when cgroup.procs is unreadable")

        monkeypatch.setattr(cgroup_cleanup.os, "kill", _explode)
        assert cgroup_cleanup.reap_cgroup(cgroup_path) == 0
