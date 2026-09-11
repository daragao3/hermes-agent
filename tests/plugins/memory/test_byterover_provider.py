"""Tests for the ByteRover memory provider config gates."""

from plugins.memory.byterover import ByteRoverMemoryProvider


def test_auto_extract_false_skips_sync_turn(monkeypatch):
    calls = []
    provider = ByteRoverMemoryProvider({"auto_extract": False})
    provider.initialize("session-1")

    monkeypatch.setattr("plugins.memory.byterover._run_brv", lambda *args, **kwargs: calls.append((args, kwargs)))

    provider.sync_turn("please remember this detail", "acknowledged")

    assert calls == []
    assert provider._sync_thread is None




def test_brv_capture_preserves_scope_and_timeout(monkeypatch, tmp_path):
    import os
    import subprocess
    from plugins.memory import byterover as brv
    from hermes_cli import _subprocess_compat

    binary = str(tmp_path / "bin" / "brv.cmd")
    cwd = tmp_path / "profile" / "byterover"
    monkeypatch.setattr(brv, "_resolve_brv_path", lambda: binary)
    calls = []

    def capture(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "  remembered ✓  ", "")

    monkeypatch.setattr(_subprocess_compat, "run_text_capture", capture)
    assert brv._run_brv(["query", "--", "detail"], timeout=3, cwd=str(cwd)) == {
        "success": True, "output": "remembered ✓"}
    argv, options = calls[0]
    assert argv == [binary, "query", "--", "detail"]
    assert options["cwd"] == str(cwd)
    assert options["timeout"] == 3
    assert options["env"]["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
    assert cwd.is_dir()


def test_brv_capture_timeout_returns_provider_error(monkeypatch, tmp_path):
    import subprocess
    from plugins.memory import byterover as brv
    from hermes_cli import _subprocess_compat

    monkeypatch.setattr(brv, "_resolve_brv_path", lambda: "brv.cmd")

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(_subprocess_compat, "run_text_capture", timeout)
    assert brv._run_brv(["query"], timeout=2, cwd=str(tmp_path)) == {
        "success": False, "error": "brv timed out after 2s"}
