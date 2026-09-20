"""Completed work remains retrievable when its finite CLI owner exits."""

import http.server
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import textwrap
import threading

import pytest

from tests.timeout_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[2]

# Backstop only (tests/timeout_budget.py rule 2): every bound in this file is an
# incidental safety net around a spawn. Nothing here asserts a duration -- the
# contract is that completed work stays retrievable after its finite CLI owner
# exits -- so each gets a generous base scaled by HERMES_TEST_TIMEOUT_SCALE.
#
# The 30s per-test cap from pyproject addopts is what actually fired, and both
# in-test bounds below were INERT because they sat AT or ABOVE it: pytest-timeout
# killed the parent first and dumped the stack of whatever the main thread was
# blocked in, which was subprocess._communicate waiting on its reader threads.
# That reads exactly like a TimeoutExpired raised by the child, so the bound
# everyone reaches to raise (the 60s producer bound) is not the one that fired.
# Same inversion as the detached-child bounds in
# tests/session_bridge/test_claude_registrar.py: "a child bound sitting above the
# pytest-level cap is inert". Keep them ordered inner < outer < pytest-level.
#
# Measured 2026-09-20 on this box at -j 1 through the canonical runner, n=10
# spanning 32-72 concurrent python processes (CPU pinned at 100% throughout, so
# process count is a poor load proxy -- the lowest-process sample was among the
# SLOWEST). Whole test 46.9-76.3s (p50 57.3); producer spawn ALONE 41.6-65.9s
# (p50 54.0). So 10 of 10 samples blow the 30s cap and its FLOOR is ~47s: this
# test cannot meet that cap here at any load, which is why it reproduces at -j 1
# in isolation and is not sweep contention. The old 60s producer bound was also
# genuinely undersized, tripping in 2 of 10 samples independently of the cap.
# `import cli` is only ~3s of that; the rest is real agent work plus the profile's
# own terminal.oneshot_completion_wait_seconds. The bases below are ~2.7x and
# ~10x the measured worst case at scale 1, and stay inside the unscaled 1800s
# per-file budget at scale 4 (240 < 720 < 1200 < 1800).
pytestmark = pytest.mark.timeout(scaled(300))


def test_headless_terminal_result_survives_cli_exit(tmp_path):
    """Real CLI, tool dispatch, shell child and fresh reader; only the LLM is local."""
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  provider: custom\n  api_mode: chat_completions\n"
        "terminal:\n  env: local\n  oneshot_completion_wait_seconds: 10\n"
        "memory:\n  memory_enabled: false\n  user_profile_enabled: false\n",
        encoding="utf-8",
    )
    release = tmp_path / "release"
    child = tmp_path / "review.py"
    child.write_text(textwrap.dedent('''
        import pathlib, sys, time
        deadline = time.monotonic() + 15
        while not pathlib.Path(sys.argv[1]).exists():
            if time.monotonic() > deadline:
                sys.exit(91)
            time.sleep(0.02)
        print("SYNTHETIC_REVIEW_COMPLETE")
        print("review stderr", file=sys.stderr)
        sys.exit(7)
    '''), encoding="utf-8")
    # The local terminal backend uses bash, including Git Bash on Windows.
    command = shlex.join(path.as_posix() for path in (Path(sys.executable), child, release))
    observed = []

    class Provider(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_error(404)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "messages" not in request:
                self.send_error(404)
                return
            tool_results = [m for m in request["messages"] if m["role"] == "tool"]
            has_terminal = any(t.get("function", {}).get("name") == "terminal"
                               for t in request.get("tools", []))
            message = {"role": "assistant", "content": "Coordinator finished."}
            if has_terminal and not tool_results:
                message.update(content=None, tool_calls=[{
                    "id": "call_review", "type": "function", "function": {
                        "name": "terminal", "arguments": json.dumps({
                            "command": command, "background": True, "notify": True,
                        }),
                    },
                }])
            elif tool_results:
                observed.extend(json.loads(m["content"]) for m in tool_results)
                release.touch()
            response = {
                "id": "chatcmpl-local", "object": "chat.completion", "created": 1,
                "model": "test-model", "choices": [{
                    "index": 0, "message": message,
                    "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                }], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
            content_type = "application/json"
            if request.get("stream"):
                response["object"] = "chat.completion.chunk"
                response["choices"][0]["delta"] = response["choices"][0].pop("message")
                for index, tool in enumerate(message.get("tool_calls", [])):
                    tool["index"] = index
                raw = ("data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n").encode()
                content_type = "text/event-stream"
            else:
                raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1"
    env = {**os.environ, "HERMES_HOME": str(home), "HOME": str(tmp_path),
           "USERPROFILE": str(tmp_path), "TERMINAL_CWD": str(tmp_path),
           "OPENAI_BASE_URL": url, "OPENAI_API_KEY": "local-test-only",
           "PYTHONPATH": str(REPO_ROOT)}
    try:
        producer = subprocess.run([
            sys.executable, "-c",
            "import cli; cli.main(query='Run the background review', quiet=True, "
            "oneshot=True, provider='custom', model='test-model', api_key='local-test-only', "
            f"base_url={url!r}, toolsets='terminal', max_turns=3, ignore_rules=True)",
        ], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", timeout=scaled(180))
    finally:
        release.touch()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert producer.returncode == 0, producer.stdout + producer.stderr
    assert "Coordinator finished." in producer.stdout
    assert len(observed) == 1, (observed, producer.stdout, producer.stderr)
    process_id = observed[0]["session_id"]
    assert observed[0].get("notify_on_complete") is True, observed

    consumer = textwrap.dedent('''
        import json, sys
        import tools.process_registry as pr
        from tools.registry import registry
        result = registry.get_entry("process_manage").handler(
            {"action": "log", "session_id": sys.argv[1]})
        status = registry.get_entry("process_manage").handler(
            {"action": "poll", "session_id": sys.argv[1]})
        print(json.dumps({"result": json.loads(result), "status": json.loads(status),
                          "replayed": not pr.process_registry.completion_queue.empty()}))
    ''')
    def read_result(profile):
        result = subprocess.run([sys.executable, "-c", consumer, process_id],
                                cwd=tmp_path, env={**env, "HERMES_HOME": str(profile)},
                                check=True, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", timeout=scaled(60))
        return json.loads(result.stdout)

    receipt = json.loads((home / "logs" / "process-results" / f"{process_id}.json").read_text(encoding="utf-8"))
    assert receipt["parent_session_id"]  # CLI owner must be stamped before its reader starts.
    env["HERMES_SESSION_ID"] = receipt["parent_session_id"]
    recovered = read_result(home)
    assert recovered["result"]["status"] == "exited", recovered
    assert recovered["status"]["exit_code"] == 7, recovered
    assert "SYNTHETIC_REVIEW_COMPLETE" in recovered["result"]["output"]
    assert "review stderr" in recovered["result"]["output"]
    assert recovered["replayed"] is False
    assert read_result(tmp_path / "other-profile")["result"]["status"] == "not_found"


def test_receipts_are_bounded_redacted_and_session_scoped(tmp_path, monkeypatch):
    import time
    from tools import process_registry_results as receipts
    from tools.process_registry import MAX_OUTPUT_CHARS, ProcessRegistry, ProcessSession

    from agent import redact
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)
    monkeypatch.setattr(receipts, "MAX_RETAINED_RESULTS", 2)
    secret = "sk-" + "aB2cD3eF4gH5iJ6kL7mN8pQ9rS0tU1vW2xY3zA4bC5dE6fG7"
    from gateway.session_context import scoped_current_session_id
    from tools.process_registry_results import load_completed_results
    monkeypatch.setenv("HERMES_SESSION_ID", "owner-session")
    sessions = []
    registry = ProcessRegistry()
    for index in range(3):
        session = ProcessSession(
            id=f"proc_{index:012x}", command=f"echo {secret}", task_id=f"owner-{index}",
            owner_task_id=f"owner-{index}", session_key=f"chat-{index}",
            parent_session_id="owner-session",
            started_at=time.time() - receipts.RESULT_RETENTION_SECONDS * 2,
            output_buffer="x" * MAX_OUTPUT_CHARS + "\n" + secret,
            exited=True, exit_code=index,
        )
        registry._running[session.id] = session
        registry._move_to_finished(session)
        sessions.append(session)
    from hermes_constants import get_hermes_home
    paths = list((get_hermes_home() / "logs" / "process-results").glob("*.json"))
    assert len(paths) == 2
    assert all(secret not in path.read_text(encoding="utf-8") for path in paths)
    fresh = ProcessRegistry()
    assert fresh.get(sessions[0].id) is None
    recovered = fresh.get(sessions[-1].id)
    assert recovered.owner_task_id == sessions[-1].owner_task_id
    assert len(recovered.output_buffer) <= MAX_OUTPUT_CHARS
    assert fresh.list_sessions() == []  # Status/liveness scans stay in memory.
    assert [s["session_id"] for s in fresh.list_sessions(
        task_id="owner-2", include_retained=True)] == [recovered.id]
    assert fresh.list_sessions(task_id="unrelated", session_key="unrelated", include_retained=True) == []
    assert fresh.get("proc_0000") is None  # Ambiguous across durable results.
    with scoped_current_session_id("unrelated-session"):
        assert load_completed_results(recovered.id) == {}
        assert fresh.get(recovered.id) is None
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        db.create_session("owner-session", "cli")
        db.create_session("delegated-child", "subagent", parent_session_id="owner-session")
        with scoped_current_session_id("delegated-child"):
            assert fresh.get(recovered.id) is None
        db.end_session("owner-session", end_reason="compression")
        db.create_session("owner-tip", "cli", parent_session_id="owner-session")
        with scoped_current_session_id("owner-tip"):
            assert fresh.get(recovered.id).output_buffer == recovered.output_buffer
    finally:
        db.close()
    assert fresh.completion_queue.empty()
    for path in paths:
        expired = time.time() - receipts.RESULT_RETENTION_SECONDS - 1
        os.utime(path, (expired, expired))
    assert fresh.get(recovered.id) is None

    # Multiplex readers must keep the producer's profile on native threads.
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    profile = tmp_path / "thread-profile"
    token = set_hermes_home_override(profile)
    try:
        with scoped_current_session_id("thread-owner"):
            child = registry.spawn_local(
                shlex.join([Path(sys.executable).as_posix(), "-c", "print('SCOPED_RESULT')"]),
                cwd=str(tmp_path), task_id="thread-task")
            child._reader_thread.join(timeout=20)
            assert not child._reader_thread.is_alive()
            assert (profile / "logs" / "process-results" / f"{child.id}.json").exists()
            assert "SCOPED_RESULT" in ProcessRegistry().read_log(child.id)["output"]
    finally:
        reset_hermes_home_override(token)
    assert not (get_hermes_home() / "logs" / "process-results" / f"{child.id}.json").exists()
