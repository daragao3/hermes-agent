"""Tests: bot_relay.* JSON-RPC handlers (tui_gateway/methods_bot_relay.py).

The Desktop's relay door on each connected gateway. Contracts:
- roster.sync persists validated rows and reports the accepted count;
- outbox.drain returns queued envelopes exactly once;
- deliver validates the target profile against THIS install and runs the
  one-turn Bot Chat transport (subprocess is faked here — the argv contract
  is what's pinned);
- reply writes the waiter's file and rejects malformed envelope ids.
"""

from __future__ import annotations

import json

import pytest

import tui_gateway.server as srv
from tools import bot_relay


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    (h / "profiles" / "ops").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def _result(envelope):
    assert "error" not in envelope, envelope
    return envelope["result"]


def test_roster_sync_persists_and_counts(home):
    out = _result(
        srv._methods["bot_relay.roster.sync"](
            1,
            {
                "agents": [
                    {"profile": "scout", "handle": "scout", "connection_id": "cloud-1"},
                    {"profile": "", "connection_id": "cloud-1"},  # dropped
                ]
            },
        )
    )
    assert out["count"] == 1
    assert [r["profile"] for r in bot_relay.read_remote_roster(home)] == ["scout"]


def test_outbox_drain_returns_each_envelope_once(home):
    target = {"profile": "scout", "handle": "scout", "connection_id": "cloud-1",
              "connection_label": "", "title": "", "description": ""}
    env = bot_relay.enqueue_envelope(
        home, target=target, message="m", sender_profile="default", sender_handle="hermes"
    )
    first = _result(srv._methods["bot_relay.outbox.drain"](1, {}))
    assert [e["id"] for e in first["envelopes"]] == [env["id"]]
    second = _result(srv._methods["bot_relay.outbox.drain"](2, {}))
    assert second["envelopes"] == []


def test_deliver_validates_profile_and_runs_transport(home, monkeypatch):
    calls = {}

    class _Proc:
        returncode = 0
        stdout = "pong from ops"
        stderr = ""

    def _fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr("subprocess.run", _fake_run)
    out = _result(
        srv._methods["bot_relay.deliver"](1, {"profile": "ops", "message": "ping"})
    )
    assert out["reply"] == "pong from ops"
    # Decoding is pinned (#93590 sibling defect): without encoding= the
    # child's UTF-8 output is decoded with the locale codec — cp1252/GBK on
    # Windows — mangling non-ASCII replies; errors="replace" keeps a bad
    # byte from raising instead of delivering.
    assert calls["kwargs"]["encoding"] == "utf-8"
    assert calls["kwargs"]["errors"] == "replace"
    argv = calls["argv"]
    # argv[0] may be a resolved venv path (#93590) — match by basename.
    assert argv[1:3] == ["-p", "ops"]
    assert argv[0].rsplit("\\", 1)[-1].rsplit("/", 1)[-1] in ("hermes", "hermes.exe")
    assert "Bot Chat" in argv and "--query-file" in argv

    # 'hermes' alias resolves to default
    _result(srv._methods["bot_relay.deliver"](2, {"profile": "hermes", "message": "x"}))
    assert calls["argv"][1:3] == ["-p", "default"]

    # unknown profile refuses without spawning
    calls.clear()
    err = srv._methods["bot_relay.deliver"](3, {"profile": "ghost", "message": "x"})
    assert "error" in err and "ghost" in err["error"]["message"]
    assert not calls


def test_deliver_requires_params(home):
    err = srv._methods["bot_relay.deliver"](1, {"profile": "", "message": ""})
    assert "error" in err


def test_deliver_lands_in_live_bot_chat_instead_of_subprocess(home, monkeypatch):
    """#100523: a Desktop-owned Bot Chat receives the DM as a normal user turn.

    With the target's Bot Chat live in this gateway, the subprocess transport
    would be fenced out by the single-owner lease and drop the payload. The
    handler must route through prompt.submit (the composer's choke point) and
    never spawn the CLI.
    """
    import threading

    spawned = []
    submitted = []
    main_thread = threading.main_thread()

    class _Proc:
        returncode, stdout, stderr = 0, "pong", ""

    def _fake_run(argv, *a, **k):
        # Capture only what the handler itself spawns. ``bot_relay.deliver`` runs
        # synchronously on the calling thread, so anything arriving here from
        # another thread is background noise, not the transport under test.
        #
        # The noise is the server module's import-time ``prefetch_update_check()``
        # daemon thread: ``check_for_updates`` -> ``_check_via_local_git`` ->
        # ``_fetch`` -> ``hermes_cli.gitlock.clear_stale_{git_locks,tmp_packs}`` ->
        # ``_git_proc_running()``, which is a bare ``git fetch`` on POSIX and a
        # ``tasklist /FI "IMAGENAME eq git.exe"`` probe on Windows. Whether it lands
        # inside the monkeypatch window is a race, and it only runs at all when the
        # 6h ``.update_check`` cache is cold AND ``.git`` is a real directory (in a
        # git worktree it is a file, so the sweep returns before the probe) -- which
        # is why this reproduced on the main checkout and never under a worktree.
        #
        # Filtering on the THREAD excludes that whole class at source. Matching on
        # argv instead only ever excluded ``git`` and so missed the ``tasklist``
        # form; naming each background command in turn is whack-a-mole, and every
        # spawn the deliver path itself makes -- ``git`` included -- is still caught.
        if argv and threading.current_thread() is main_thread:
            spawned.append(argv)
        return _Proc()

    # Warm platform.uname()'s one-shot stdlib cache BEFORE the fake is installed.
    # (hermes_state_dbfile.quarantine_cross_process_lock used to call platform.system()
    # on this path; it now tests sys.platform, but the server's own platform touches
    # remain.) On Windows the first uname() in a process shells out to `ver`
    # (platform._syscmd_ver).
    # That probe is a subprocess.run the handler never asked for: it lands in _fake_run and
    # reads as a CLI spawn. It is a RACE, not a fixed order -- the server module's import-time
    # update prefetch also touches platform on its daemon thread, so whether the cache is
    # already warm when this test runs decides pass/fail (measured 2/4 either way).
    import platform
    platform.uname()  # windows-footgun: ok — deliberate cache warm; conftest keeps it off WMI

    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setitem(
        srv._methods, "prompt.submit", lambda rid, p: submitted.append(p) or srv._ok(rid, {"status": "streaming"})
    )
    monkeypatch.setattr(srv, "_profile_home", lambda name: home / "profiles" / name)
    monkeypatch.setitem(
        srv._sessions,
        "live-ops",
        {"profile_home": str(home / "profiles" / "ops"), "pending_title": "Bot Chat", "history": []},
    )
    out = _result(srv._methods["bot_relay.deliver"](1, {"profile": "ops", "message": "ping"}))
    # queued=True is the invariant: a DM never interrupts a turn in flight.
    assert submitted == [{"session_id": "live-ops", "text": "ping", "queued": True}]
    assert not spawned
    assert "reply" in out

    # A live session titled anything else for the same profile does not qualify:
    # the subprocess path runs exactly as before.
    srv._sessions["live-ops"]["pending_title"] = "Scratch"
    submitted.clear()

    out = _result(srv._methods["bot_relay.deliver"](2, {"profile": "ops", "message": "ping"}))
    assert out["reply"] == "pong" and spawned and not submitted


def test_reply_roundtrip_and_id_validation(home):
    envelope_id = "c" * 32
    _result(srv._methods["bot_relay.reply"](1, {"id": envelope_id, "reply": "hi"}))
    path = bot_relay.relay_root(home) / bot_relay.REPLIES_DIR / f"{envelope_id}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["reply"] == "hi"

    err = srv._methods["bot_relay.reply"](2, {"id": "../evil"})
    assert "error" in err


def test_deliver_write_failure_still_removes_tempfile(home, monkeypatch, tmp_path):
    """A failed payload write must not leak the relay DM tempfile."""
    import glob
    import os
    import tempfile as _tempfile

    made = []
    real_mkstemp = _tempfile.mkstemp

    def _tracking_mkstemp(*args, **kwargs):
        kwargs["dir"] = str(tmp_path)
        fd, path = real_mkstemp(*args, **kwargs)
        made.append(path)
        return fd, path

    class _BrokenWriter:
        """Stands in for the real file object os.fdopen returns -- including fd ownership.

        The real object closes the descriptor on ``__exit__`` even when ``write``
        raises, and on Windows that close is load-bearing: ``os.unlink`` on a file
        whose handle is still open fails with PermissionError (WinError 32), which
        the handler's ``contextlib.suppress(OSError)`` swallows. A mock that keeps
        the fd open therefore manufactures the very leak this test asserts against
        -- on Windows only; on POSIX the unlink succeeds regardless.
        """

        def __init__(self, fd):
            self._fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            os.close(self._fd)
            return False

        def write(self, content):
            raise OSError("disk full")

    monkeypatch.setattr("tempfile.mkstemp", _tracking_mkstemp)
    monkeypatch.setattr("os.fdopen", lambda fd, *a, **k: _BrokenWriter(fd))
    err = srv._methods["bot_relay.deliver"](1, {"profile": "ops", "message": "x"})
    assert "error" in err
    assert made, "mkstemp was never reached"
    assert not glob.glob(str(tmp_path / "hermes-relay-dm-*")), "tempfile leaked"
