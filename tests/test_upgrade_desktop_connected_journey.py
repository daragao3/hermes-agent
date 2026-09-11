"""Connect the real packaged renderer to an owned isolated candidate backend."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import winreg
from pathlib import Path
import pytest
from hermes_cli._subprocess_compat import kill_process_tree, run_text_capture

def protocol_command():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\hermes\shell\open\command') as key:
        return winreg.QueryValueEx(key, '')[0]

@pytest.mark.timeout(265)
def test_packaged_candidate_backend_connection():
    root = Path(__file__).resolve().parents[1]
    output = Path('C:/Users/diego/architecture-map/wave-execution/2026-09-08') / ('desktop-connected-' + uuid.uuid4().hex[:8])
    home = output / 'backend-home'
    home.mkdir(parents=True)
    (home / 'config.yaml').write_text('''model:
  default: mock-model
  provider: mock
providers:
  mock:
    api: http://127.0.0.1:1/v1
    name: Mock
    api_mode: chat_completions
    key_env: MOCK_API_KEY
    models:
      mock-model: {}
auxiliary:
  title_generation:
    enabled: false
''')
    (home / '.env').write_text('MOCK_API_KEY=fixture-only\n')
    secondary = home / 'profiles/wave1-secondary'
    secondary.mkdir(parents=True)
    (secondary / 'config.yaml').write_text((home / 'config.yaml').read_text())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    token = 'wave1-fixture-' + uuid.uuid4().hex
    env = {k:v for k,v in os.environ.items() if not re.search(r'(_API_KEY|_TOKEN|_SECRET|_PASSWORD|_CREDENTIALS|BASE_URL)$', k)}
    env.pop('HERMES_PROFILE', None)
    env.update(HERMES_HOME=str(home), HERMES_TEST_ISOLATION=str(home), HERMES_DASHBOARD_SESSION_TOKEN=token, NO_PROXY='127.0.0.1,localhost')
    before = protocol_command()
    print('Connected journey evidence:', output, flush=True)
    with (output / 'backend.log').open('w', encoding='utf-8') as log:
        boot_probe = "import faulthandler,runpy,sys;print('Owned backend interpreter:',sys.executable,flush=True);faulthandler.dump_traceback_later(20,repeat=True);runpy.run_module('hermes_cli.main',run_name='__main__',alter_sys=True)"
        proc = subprocess.Popen([sys.executable, '-u', '-c', boot_probe, 'serve', '--host', '127.0.0.1', '--port', str(port), '--skip-build'], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                assert proc.poll() is None, (output / 'backend.log').read_text(errors='replace')[-6000:]
                try:
                    req = urllib.request.Request(url + '/api/status', headers={'X-Hermes-Session-Token':token})
                    with urllib.request.urlopen(req, timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                pytest.fail('Owned backend readiness deadline: ' + (output / 'backend.log').read_text(errors='replace')[-6000:])
            node = root.parent / 'runtime-wave01-20260908/node/node-v24.20.0-win-x64/node.exe'
            env.update(HERMES_UPGRADE_REMOTE_URL=url,HERMES_UPGRADE_REMOTE_TOKEN=token,HERMES_UPGRADE_CONTRACTS='profile-cron')
            result = run_text_capture([str(node),str(root / 'apps/desktop/e2e/upgrade-packaged-debugger-probe.mjs'),str(output / 'desktop')],cwd=root,env=env,timeout=150)
            print(result.stdout + result.stderr,flush=True)
            assert result.returncode == 0
            assert json.loads((output / 'desktop/result.json').read_text())['scenario'] == 'connected'
        finally:
            if proc.poll() is None:
                kill_process_tree(proc)
            proc.wait(timeout=15)
            after = protocol_command()
            (output / 'cleanup.json').write_text(json.dumps({'backendPid':proc.pid,'exitCode':proc.returncode,'protocolUnchanged':before==after}))
            assert before == after
