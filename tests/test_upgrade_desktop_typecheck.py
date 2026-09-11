"""Check the three existing configs used by Desktop's typecheck script."""
import subprocess
from pathlib import Path

import pytest

from hermes_cli._subprocess_compat import run_text_capture


@pytest.mark.parametrize("config,cache_name", [
    ("tsconfig.json", "desktop-renderer"),
    ("tsconfig.electron.json", "desktop-electron"),
    ("tsconfig.e2e.json", "desktop-e2e"),
])
@pytest.mark.timeout(325)
def test_desktop_typecheck(config, cache_name):
    root = Path(__file__).resolve().parents[1]
    node = root.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"
    cache = Path("C:/Users/diego/architecture-map/wave-execution/2026-09-08") / (cache_name + ".tsbuildinfo")
    try:
        result = run_text_capture([
            str(node), str(root / "node_modules/typescript/bin/tsc"),
            "--project", "apps/desktop/" + config, "--noEmit", "--pretty", "false",
            "--incremental", "--tsBuildInfoFile", str(cache),
        ], cwd=root, timeout=300)
    except subprocess.TimeoutExpired as exc:
        print(str(exc.output or "") + str(exc.stderr or ""), flush=True)
        pytest.fail("TypeScript exceeded the 300s capture budget", pytrace=False)
    if result.returncode:
        print(result.stdout + result.stderr, flush=True)
        pytest.fail("TypeScript diagnostics above", pytrace=False)
