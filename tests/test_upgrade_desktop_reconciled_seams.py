"""Validate reconciled Desktop seams in one shared, serial Vitest run."""
import json
import subprocess
from pathlib import Path

import pytest
from hermes_cli._subprocess_compat import noninteractive_git_env, run_text_capture
from tests.wave_runtime_support import wave_node


@pytest.mark.timeout(205)
def test_desktop_reconciled_seams(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = wave_node()
    report = tmp_path / "desktop-reconciled-seams-vitest.json"
    print("Vitest report:", report, flush=True)
    specs = ["electron/git-review-ops.test.ts"]
    git_env = noninteractive_git_env()
    git_env["GIT_ALLOW_PROTOCOL"] = "none"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_TEMPLATE_DIR"):
        git_env.pop(key, None)
    try:
        result = run_text_capture([
            str(node), str(root / "node_modules/vitest/vitest.mjs"), "run", *specs,
            "--project=electron", "-t", "resolveRenamePath|gitFor|repoStatus|reviewList", "--maxWorkers=1", "--no-file-parallelism", "--retry=0",
            "--reporter=verbose", "--reporter=json", "--outputFile=" + str(report),
        ], cwd=root / "apps/desktop", timeout=180, env=git_env)
    except subprocess.TimeoutExpired as exc:
        print(str(exc.output or "") + str(exc.stderr or ""), flush=True)
        pytest.fail("Desktop seam run exceeded180s; use completed nodes in partial output", pytrace=False)
    print(result.stdout + result.stderr, flush=True)
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    assert data.get("numTotalTests", 0) > 0, data
    assert result.returncode == 0 and data.get("success") and data.get("numFailedTests") == 0, data
