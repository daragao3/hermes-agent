"""Package the accepted candidate build locally with publication disabled."""
import os
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import run_text_capture

@pytest.mark.timeout(325)
def test_desktop_windows_directory_package():
    root = Path(__file__).resolve().parents[1]
    app = root / "apps/desktop"
    release = (app / "release").resolve()
    assert release.is_relative_to(root.resolve())
    assert not release.exists(), "Preserve existing packaged output before a justified rebuild"
    for target in (app / "dist/node_modules/node-pty", app / "dist/node_modules/get-windows"):
        assert target.resolve().is_relative_to(root.resolve())
    node = root.parent / "runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe"
    env = dict(os.environ)
    env['CSC_IDENTITY_AUTO_DISCOVERY'] = 'false'
    env['PATH'] = str(node.parent) + os.pathsep + env.get('PATH', '')
    result = run_text_capture([str(node), str(app / 'scripts/run-electron-builder.mjs'), '--dir', '--win', '--x64', '--publish', 'never'], cwd=app, env=env, timeout=300)
    print(result.stdout + result.stderr, flush=True)
    assert result.returncode == 0
    assert (release / 'win-unpacked/Hermes.exe').is_file()
    assert (release / 'win-unpacked/resources/app.asar').is_file()
