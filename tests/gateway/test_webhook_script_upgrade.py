"""Real bounded route-script execution in an isolated profile."""
import os
import subprocess as subprocess
from unittest.mock import patch

from gateway.platforms.webhook_filters import WebhookRouteProcessor


def test_script_capture_uses_scoped_environment_and_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "transform.py"
    script.write_text('import json,os,sys; p=json.load(sys.stdin); p["scope"]=os.environ["WAVE_TEST_SCOPE"]; print(json.dumps(p))')
    scoped_env = dict(os.environ, WAVE_TEST_SCOPE="isolated")
    with patch("tools.environments.local.build_subprocess_env", return_value=scoped_env) as build:
        accepted, result = WebhookRouteProcessor().run_route_script(str(script), {"event": "test"})
    build.assert_called_once_with()
    assert accepted and result == {"event": "test", "scope": "isolated"}


def test_script_timeout_drops_event_with_bounded_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "slow.py"
    script.write_text('import time; time.sleep(30)')
    with patch("tools.environments.local.build_subprocess_env", return_value=dict(os.environ)):
        assert WebhookRouteProcessor(script_timeout_seconds=1).run_route_script(str(script), {}) == (False, None)
