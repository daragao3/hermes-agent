"""Run existing desktop highlight contracts under the isolated canonical runner."""
import json
import pytest
from pathlib import Path
from hermes_cli._subprocess_compat import run_text_capture


@pytest.mark.timeout(85)
def test_desktop_highlight_contracts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = root.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"
    assert node.is_file(), "isolated Wave 1 Node runtime is required"
    report = tmp_path / "vitest.json"
    result = run_text_capture([
        str(node), str(root / "node_modules/vitest/vitest.mjs"), "run",
        "src/components/chat/shiki-block.test.tsx",
        "src/components/chat/shiki-highlight-cache.test.ts",
        "src/components/chat/shiki-highlighter.test.ts",
        "--project=ui", "--maxWorkers=1", "--no-file-parallelism", "--retry=0",
        "--reporter=json", "--outputFile=" + str(report),
    ], cwd=root / "apps/desktop", timeout=75)
    report_text = report.read_text(encoding="utf-8") if report.exists() else "{}"
    data = json.loads(report_text)
    failures = [{"file": row.get("name"), "message": row.get("message"),
                 "failed": [case for case in row.get("assertionResults", []) if case.get("status") == "failed"]}
                for row in data.get("testResults", []) if row.get("status") != "passed"]
    assert result.returncode == 0, result.stdout + result.stderr + json.dumps(failures, ensure_ascii=False)
    assert data["numTotalTests"] > 0, data
    assert data["success"] and data["numFailedTests"] == 0, data
    print("Desktop highlight cases passed:", data["numPassedTests"])
