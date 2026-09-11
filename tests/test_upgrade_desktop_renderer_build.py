"""Build the actual Desktop renderer into a fresh isolated evidence directory."""
from pathlib import Path
import uuid
import pytest
from hermes_cli._subprocess_compat import run_text_capture

@pytest.mark.timeout(325)
def test_desktop_renderer_build():
    root = Path(__file__).resolve().parents[1]
    node = root.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"
    output = Path("C:/Users/diego/architecture-map/wave-execution/2026-09-08") / ("desktop-renderer-build-" + uuid.uuid4().hex[:8])
    assert not output.exists()
    print("Renderer artifact:", output, flush=True)
    result = run_text_capture([str(node), str(root / "node_modules/vite/bin/vite.js"), "build", "--outDir", str(output)], cwd=root / "apps/desktop", timeout=300)
    print(result.stdout + result.stderr, flush=True)
    assert result.returncode == 0
    assert (output / "index.html").is_file()
    assert any((output / "assets").glob("*.js"))
