"""Build the actual Desktop renderer into a fresh per-run output directory."""
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import run_text_capture
from tests.wave_runtime_support import wave_node

@pytest.mark.timeout(325)
def test_desktop_renderer_build(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = wave_node()
    output = tmp_path / "desktop-renderer-build"
    assert not output.exists()
    print("Renderer artifact:", output, flush=True)
    result = run_text_capture([str(node), str(root / "node_modules/vite/bin/vite.js"), "build", "--outDir", str(output)], cwd=root / "apps/desktop", timeout=300)
    print(result.stdout + result.stderr, flush=True)
    assert result.returncode == 0
    assert (output / "index.html").is_file()
    assert any((output / "assets").glob("*.js"))
