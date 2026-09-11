import os
from types import SimpleNamespace
from unittest.mock import Mock

from gateway import status
from gateway.platforms.base import BasePlatformAdapter


def test_live_prior_pid_is_not_reported_as_dead_after_other_staleness(monkeypatch):
    monkeypatch.setattr(status, "_read_json_file", lambda path: {"pid": 987654})
    monkeypatch.setattr(status, "acquire_scoped_lock", lambda *args, **kwargs: (True, None))
    monkeypatch.setattr(status, "pid_exists", lambda pid: True)
    adapter = SimpleNamespace(platform=SimpleNamespace(value="telegram"),
        _synthesize_previous_gateway_stopped=Mock())
    assert BasePlatformAdapter._acquire_platform_lock(adapter, "test", "fake-token", "test identity")
    adapter._synthesize_previous_gateway_stopped.assert_not_called()


def test_media_nul_is_discarded_without_losing_other_attachments():
    media, _ = BasePlatformAdapter.extract_media("MEDIA:/tmp/bad\x00.png\nMEDIA:/tmp/good.png")
    assert media == [("/tmp/good.png", False)]


def test_windows_home_relative_bare_file_uses_actual_scratch_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"scratch attachment")
    if os.name != "nt":
        import pytest
        pytest.skip("Windows expanduser path semantics")
    paths, cleaned = BasePlatformAdapter.extract_local_files(r"Here is ~\report.pdf")
    assert paths == [str(artifact)]
    assert "report.pdf" not in cleaned


def test_public_lazy_adapter_aliases_point_at_current_owners():
    import gateway.platforms as platforms
    from gateway.platforms.qqbot.adapter import QQAdapter
    from gateway.platforms.yuanbao import YuanbaoAdapter
    assert platforms.QQAdapter is QQAdapter
    assert platforms.YuanbaoAdapter is YuanbaoAdapter


def test_docker_volume_with_windows_forward_slash_host_translates(tmp_path, monkeypatch):
    import json
    from gateway.platforms import base
    import pytest
    if os.name != "nt":
        pytest.skip("Windows drive-prefix parsing")
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"scratch")
    spec = json.dumps([f"{tmp_path.as_posix()}:/workspace:rw"])
    monkeypatch.setattr(base, "_tenv", lambda name, default="": spec if name == "TERMINAL_DOCKER_VOLUMES" else default)
    monkeypatch.setattr(base, "_media_delivery_allowed_roots", lambda: [tmp_path])
    assert BasePlatformAdapter.validate_media_delivery_path("/workspace/report.pdf") == str(artifact.resolve())


def test_unmapped_container_root_is_not_resolved_on_windows_current_drive(monkeypatch):
    from gateway.platforms import base
    import pytest
    if os.name != "nt":
        pytest.skip("Windows current-drive ambiguity")
    monkeypatch.setattr(base, "_translate_docker_container_media_path", lambda *args, **kwargs: None)
    resolver = Mock()
    monkeypatch.setattr(base, "_resolve_path", resolver)
    assert BasePlatformAdapter.validate_media_delivery_path("/unmapped/secret.txt") is None
    resolver.assert_not_called()
