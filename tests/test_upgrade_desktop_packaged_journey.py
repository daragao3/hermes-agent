"""Probe packaged startup only after debugger-gated host isolation is installed."""
import json
import uuid
import winreg
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import run_text_capture

def protocol_command():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\hermes\shell\open\command") as key:
        return winreg.QueryValueEx(key, '')[0]

@pytest.mark.timeout(175)
def test_packaged_failure_journey():
    root = Path(__file__).resolve().parents[1]
    app = root / 'apps/desktop'
    node = root.parent / 'runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe'
    output = Path('C:/Users/diego/architecture-map/wave-execution/2026-09-08') / ('desktop-packaged-guarded-' + uuid.uuid4().hex[:8])
    before = protocol_command()
    print('Guarded journey artifacts:', output, flush=True)
    try:
        result = run_text_capture([str(node), str(app / 'e2e/upgrade-packaged-debugger-probe.mjs'), str(output)], cwd=app, timeout=150)
        print(result.stdout + result.stderr, flush=True)
        assert result.returncode == 0
        assert json.loads((output / 'result.json').read_text())['passed'] is True
    finally:
        after = protocol_command()
        if output.exists():
            (output / 'protocol-state.json').write_text(json.dumps({'before':before,'after':after,'unchanged':before==after},indent=2))
        assert before == after, 'Protocol routing changed during guarded test'
