"""Load staged native modules with the exact candidate Electron ABI, without opening windows."""
import json
import os
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import run_text_capture

@pytest.mark.timeout(55)
def test_staged_native_modules_load_in_electron():
    root = Path(__file__).resolve().parents[1]
    app = root / "apps/desktop"
    electron = app / "node_modules/electron/dist/electron.exe"
    pty = app / "dist/node_modules/node-pty"
    bindings = list((app / "dist/node_modules/get-windows/lib/binding").glob("*win32*x64/node-get-windows.node"))
    assert len(bindings) == 1
    code = "const assert=require('node:assert/strict');const pty=require(" + json.dumps(str(pty)) + ");const win=require(" + json.dumps(str(bindings[0])) + ");assert.equal(typeof pty.spawn,'function');assert.equal(typeof win.getActiveWindow,'function');assert.equal(typeof win.getOpenWindows,'function');console.log(JSON.stringify({electron:process.versions.electron,modules:process.versions.modules,pty:true,getWindows:true}));"
    env = dict(os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    result = run_text_capture([str(electron), "-e", code], cwd=app, env=env, timeout=30)
    print(result.stdout + result.stderr, flush=True)
    assert result.returncode == 0
    data = json.loads(result.stdout.strip())
    assert data['electron'] == '40.10.2'
    assert data['pty'] and data['getWindows']
