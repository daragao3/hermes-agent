"""Local-CDP battery orchestrator: tasks x arms x models x reps.

Resume-safe: completed cells in results.jsonl are skipped, so a killed
battery continues where it left off (same pattern as scripts/toolperf_abeval).

Usage:
    # start a headless Chrome first:
    #   google-chrome --headless=new --remote-debugging-port=9333 \
    #     --user-data-dir=/tmp/bubench-chrome --no-first-run --disable-gpu about:blank
    BUBENCH_BASE_TREE=... BUBENCH_PR_TREE=... BENCH_CDP_URL=http://127.0.0.1:9333 \
        python3 orchestrate.py [--tasks tasks/hard.json] [--models m1,m2] \
                               [--arms base,pr,prns] [--reps 3]
"""

import argparse
import itertools
import json
import os
import signal
import subprocess
import sys
import time

# Repo root, for the shared Windows process-tree primitives (never taskkill).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from hermes_cli._subprocess_compat import (  # noqa: E402
    windows_job_close, windows_kill_popen_tree, windows_suspended_spawn_flag, windows_tree_capture)

ROOT = os.environ.get("BUBENCH_ROOT", os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
ENV = {**os.environ}
ENV["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + ENV.get("PATH", "")

parser = argparse.ArgumentParser()
parser.add_argument("--tasks", default=os.path.join(ROOT, "tasks", "hard.json"))
parser.add_argument("--models", default="anthropic/claude-opus-4.8,moonshotai/kimi-k3")
parser.add_argument("--arms", default="base,pr,prns")
parser.add_argument("--reps", type=int, default=3)
parser.add_argument("--results", default=os.path.join(ROOT, "results", "results.jsonl"))
parser.add_argument("--run-timeout", type=int, default=1200)
args = parser.parse_args()

os.makedirs(os.path.dirname(args.results), exist_ok=True)
ARMS = args.arms.split(",")
MODELS = args.models.split(",")
TASKS = list(json.load(open(args.tasks, encoding="utf-8")).keys())
REPS = list(range(1, args.reps + 1))

done = set()
if os.path.exists(args.results):
    for line in open(args.results, encoding="utf-8"):
        try:
            r = json.loads(line)
            done.add((r["arm"], r["task"], r["model"], r["rep"]))
        except Exception:
            pass


_last_cell = None  # (Popen, WindowsProcessTree | None) of the previous cell, reaped at the next reset


def _spawn_cell(argv, env):
    """Spawn one cell so its WHOLE tree stays reachable after it exits: a job object on
    Windows (captured before the child's first instruction), its own session on POSIX. A
    driver daemon the cell leaves behind is still a member of either."""
    kwargs = {}
    suspended = 0
    if sys.platform == "win32":
        suspended = windows_suspended_spawn_flag()
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | suspended
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", env=env, **kwargs)
    tree = windows_tree_capture(proc, suspended=bool(suspended)) if sys.platform == "win32" else None
    return proc, tree


def _kill_cell(proc, tree):
    """Kill the cell's tree by membership (job / session), never by image name.

    The old ``taskkill /F /IM agent-browser.exe /T`` killed every agent-browser on the box --
    other sessions' daemons included -- and ``/T`` adopted the orphans of recycled pids
    (2026-09-17); the POSIX command-line sweep was the same cross-session reach. Only what
    THIS battery spawned is touched.
    """
    try:
        if sys.platform == "win32":
            windows_kill_popen_tree(proc, tree)
        else:
            # start_new_session made the cell its own group leader (pgid == pid); the group
            # outlives the leader while any member (a lingering driver) is still in it.
            os.killpg(proc.pid, signal.SIGKILL)  # windows-footgun: ok -- POSIX branch of the platform split above
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def reset_browser_state():
    """Kill drivers the PREVIOUS cell left behind and clear cookies between cells."""
    global _last_cell
    if _last_cell is not None:
        proc, tree = _last_cell
        _last_cell = None
        _kill_cell(proc, tree)
        if tree is not None:
            windows_job_close(tree.job)
    code = "cdp('Network.clearBrowserCookies')\nprint('cleared')\n"
    try:
        subprocess.run(
            ["browser-use"],
            input=code,
            text=True,
            capture_output=True,
            timeout=120,
            env=ENV,
        )
    except Exception:
        pass


cells = [
    (arm, task, model, rep)
    for model, task, rep, arm in itertools.product(MODELS, TASKS, REPS, ARMS)
]
total = len(cells)
n = 0
for arm, task, model, rep in cells:
    n += 1
    if (arm, task, model, rep) in done:
        continue
    print(f"[{n}/{total}] {arm} {task} {model} rep{rep}", flush=True)
    reset_browser_state()
    t0 = time.time()
    proc, tree = _spawn_cell(
        [PY, os.path.join(ROOT, "single_run.py"), arm, task, model, str(rep)],
        env={**ENV, "BUBENCH_TASKS": args.tasks},
    )
    _last_cell = (proc, tree)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=args.run_timeout)
        except subprocess.TimeoutExpired:
            _kill_cell(proc, tree)
            try:
                proc.communicate(timeout=10)
            except Exception:
                pass
            raise
        rec = None
        for line in (stdout or "").splitlines():
            if line.startswith("RESULT_JSON:"):
                rec = json.loads(line[len("RESULT_JSON:") :])
        if rec is None:
            rec = {
                "arm": arm,
                "task": task,
                "model": model,
                "rep": rep,
                "ok": False,
                "error": "no-result",
                "stderr_tail": (stderr or "")[-800:],
                "stdout_tail": (stdout or "")[-400:],
            }
    except subprocess.TimeoutExpired:
        rec = {
            "arm": arm,
            "task": task,
            "model": model,
            "rep": rep,
            "ok": False,
            "error": f"orchestrator-timeout-{args.run_timeout}s",
        }
    rec["cell_wall_s"] = round(time.time() - t0, 1)
    with open(args.results, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(
        f"  -> ok={rec.get('ok')} err={rec.get('error')} wall={rec.get('cell_wall_s')}s",
        flush=True,
    )

print("BATTERY COMPLETE", flush=True)
