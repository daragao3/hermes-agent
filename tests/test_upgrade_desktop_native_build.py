"""Assemble the actual Desktop bundle with already-installed native artifacts."""
from pathlib import Path
import shutil
import pytest
from hermes_cli._subprocess_compat import run_text_capture
from tests.wave_runtime_support import wave_node

# The renderer this assembles is the one the 2026-09-08 wave built and kept in
# its evidence tree (the output of test_upgrade_desktop_renderer_build at the
# time). It is a ceremony artifact, not a fixture this suite can produce.
_WAVE_RENDERER = Path("C:/Users/diego/architecture-map/wave-execution/2026-09-08/desktop-renderer-build-035aef08")

@pytest.mark.timeout(385)
def test_desktop_native_build():
    root = Path(__file__).resolve().parents[1]
    app = root / "apps/desktop"
    dist = app / "dist"
    node = wave_node()
    renderer = _WAVE_RENDERER
    if not (renderer / "index.html").is_file():
        pytest.skip(f"wave renderer build absent: {renderer}")
    assert not dist.exists(), "Preserve existing build before explicitly rebuilding"
    assert (root / "node_modules/node-pty/prebuilds/win32-x64/pty.node").is_file()
    assert (root / "node_modules/get-windows/lib/binding/napi-9-win32-unknown-x64/node-get-windows.node").is_file()
    shutil.copytree(renderer, dist)
    for script in ("assert-root-install.mjs", "write-build-stamp.mjs", "bundle-electron-main.mjs", "stage-native-deps.mjs", "assert-dist-built.mjs"):
        for name in ("node-pty", "get-windows"):
            target = (dist / "node_modules" / name).resolve()
            assert target.is_relative_to(root.resolve())
        result = run_text_capture([str(node), str(app / "scripts" / script)], cwd=app, timeout=60)
        print(script, result.stdout + result.stderr, flush=True)
        assert result.returncode == 0, script
    assert (dist / "electron-main.mjs").is_file()
    assert (dist / "electron-preload.js").is_file()
    assert (dist / "node_modules/node-pty/prebuilds/win32-x64/pty.node").is_file()
    assert (dist / "node_modules/get-windows/package.json").is_file()
