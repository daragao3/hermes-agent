import subprocess
from agent.secret_sources import base


def test_cli_allowlist_reads_active_profile_view(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "sibling-token")
    monkeypatch.setenv("SYSTEMDRIVE", "Z:")
    calls = []
    def run(argv, **kwargs):
        calls.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    monkeypatch.setattr(base, "run_cli", run)
    token = base.set_source_environment({"AUTH_TOKEN": "profile-token", "SYSTEMDRIVE": "C:", "UNREQUESTED_SECRET": "private"})
    try:
        base.run_secret_cli(["fixture-cli"], allow_env=["AUTH_TOKEN"])
    finally:
        base.reset_source_environment(token)
    assert calls == [{"AUTH_TOKEN": "profile-token", "SYSTEMDRIVE": "C:", "NO_COLOR": "1"}]
