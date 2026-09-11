import json
import os
import queue
import subprocess
import threading
from pathlib import Path

from hermes_constants import real_executable


def _stdout_queue(proc: subprocess.Popen) -> queue.Queue[dict]:
    out: queue.Queue[dict] = queue.Queue()
    assert proc.stdout is not None

    def drain() -> None:
        for line in proc.stdout or []:
            out.put(json.loads(line))

    threading.Thread(target=drain, daemon=True).start()
    return out


def _read_json_line(out: queue.Queue[dict], timeout: float = 2.0) -> dict:
    try:
        return out.get(timeout=timeout)
    except queue.Empty as exc:
        raise AssertionError("timed out waiting for compute host JSON") from exc


def test_compute_host_line_json_hello_and_shutdown():
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [real_executable(), "-m", "tui_gateway.compute_host"],
        cwd=str(repo),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    out = _stdout_queue(proc)
    try:
        # Cold interpreter startup uses the supervisor's ten-second hello budget.
        # Subsequent protocol replies retain the two-second responsiveness check.
        hello = _read_json_line(out, timeout=10.0)
        assert hello["type"] == "hello"
        if os.name == "nt" and hello["host_pid"] != proc.pid:
            # Windows venv redirectors can own a separate interpreter process.
            # Require the announced host to be our actual child, not an arbitrary PID.
            import psutil
            assert psutil.Process(hello["host_pid"]).ppid() == proc.pid
        else:
            assert hello["host_pid"] == proc.pid

        proc.stdin.write(json.dumps({"type": "bogus", "request_id": "b"}) + "\n")
        proc.stdin.flush()
        error = _read_json_line(out)
        assert error["type"] == "error"
        assert error["message"] == "unknown frame type: bogus"

        proc.stdin.write(json.dumps({"type": "shutdown", "request_id": "stop"}) + "\n")
        proc.stdin.flush()
        assert _read_json_line(out)["type"] == "shutdown.ack"
        proc.wait(timeout=2)
    except AssertionError as exc:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr else ""
        raise AssertionError(f"{exc}; child exit={proc.returncode}; stderr={stderr[-4000:]}") from exc
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
