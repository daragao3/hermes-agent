"""Check the three existing configs used by Desktop's typecheck script."""
import subprocess
from pathlib import Path

import pytest

from hermes_cli._subprocess_compat import run_text_capture
from tests.wave_runtime_support import wave_node


@pytest.mark.parametrize("config,cache_name", [
    ("tsconfig.json", "desktop-renderer"),
    ("tsconfig.electron.json", "desktop-electron"),
    ("tsconfig.e2e.json", "desktop-e2e"),
])
@pytest.mark.timeout(325)
def test_desktop_typecheck(config, cache_name, tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = wave_node()
    # The incremental cache once persisted in the wave evidence tree; a suite
    # run has no business writing there, so it is per-run under tmp_path.
    cache = tmp_path / (cache_name + ".tsbuildinfo")
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
