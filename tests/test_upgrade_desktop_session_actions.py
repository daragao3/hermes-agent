"""Run existing desktop session_actions contracts under the isolated canonical runner."""
import json
import subprocess
import pytest
from pathlib import Path
from hermes_cli._subprocess_compat import run_text_capture


@pytest.mark.parametrize("spec", [
    "src/app/session/hooks/use-session-list-actions.test.tsx",
    "src/app/cron/cron-actions.test.ts",
])
@pytest.mark.timeout(85)
def test_desktop_session_actions_contracts(tmp_path, spec):
    root = Path(__file__).resolve().parents[1]
    node = root.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"
    assert node.is_file(), "isolated Wave 1 Node runtime is required"
    report = tmp_path / "vitest.json"
    try:
        result = run_text_capture([
            str(node), str(root / "node_modules/vitest/vitest.mjs"), "run",
            spec,
            "--project=ui", "--maxWorkers=1", "--no-file-parallelism", "--retry=0",
            "--reporter=verbose", "--reporter=json", "--outputFile=" + str(report),
        ], cwd=root / "apps/desktop", timeout=75)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(str(exc.output or "") + str(exc.stderr or ""))
    report_text = report.read_text(encoding="utf-8") if report.exists() else "{}"
    data = json.loads(report_text)
    failures = [{"file": row.get("name"), "message": row.get("message"),
                 "failed": [case for case in row.get("assertionResults", []) if case.get("status") == "failed"]}
                for row in data.get("testResults", []) if row.get("status") != "passed"]
    assert result.returncode == 0, result.stdout + result.stderr + json.dumps(failures, ensure_ascii=False)
    assert data["numTotalTests"] > 0, data
    assert data["success"] and data["numFailedTests"] == 0, data
    print("Desktop session_actions cases passed:", data["numPassedTests"])
