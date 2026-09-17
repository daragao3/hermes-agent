"""Probe packaged startup only after debugger-gated host isolation is installed."""
import json
import winreg
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import run_text_capture
from tests.wave_runtime_support import wave_node

def protocol_command():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\hermes\shell\open\command") as key:
        return winreg.QueryValueEx(key, '')[0]

@pytest.mark.timeout(175)
def test_packaged_failure_journey(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app = root / 'apps/desktop'
    node = wave_node()
    output = tmp_path / 'desktop-packaged-guarded'
    before = protocol_command()
    print('Guarded journey artifacts:', output, flush=True)
    try:
        result = run_text_capture([str(node), str(app / 'e2e/upgrade-packaged-debugger-probe.mjs'), str(output)], cwd=app, timeout=150)
        print(result.stdout + result.stderr, flush=True)
        assert result.returncode == 0
        assert json.loads((output / 'result.json').read_text(encoding="utf-8"))['passed'] is True
    finally:
        after = protocol_command()
        if output.exists():
            (output / 'protocol-state.json').write_text(json.dumps({'before':before,'after':after,'unchanged':before==after},indent=2), encoding="utf-8")
        assert before == after, 'Protocol routing changed during guarded test'
