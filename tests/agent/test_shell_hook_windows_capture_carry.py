import json
import sys
import pytest
from agent.shell_hooks import ShellHookSpec, _spawn


@pytest.mark.skipif(sys.platform != "win32", reason="Windows inherited capture handles")
def test_successful_hook_does_not_wait_for_inherited_writer(tmp_path):
    script = tmp_path / "hook.py"
    script.write_text("import subprocess, sys\n" +
                      "payload = sys.stdin.read()\n" +
                      "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'], creationflags=0x08000000)\n" +
                      "print(payload, flush=True)\n", encoding="utf-8")
    spec = ShellHookSpec(event="post_tool_call", command=f'"{sys.executable}" "{script}"', timeout=2)
    result = _spawn(spec, '{"fixture": "ok"}')
    assert result["timed_out"] is False, result
    assert result["returncode"] == 0, result
    assert json.loads(result["stdout"]) == {"fixture": "ok"}
