"""OS-family detection must not query WMI during configuration import."""
import importlib
import os
import platform


def test_config_platform_identity_does_not_probe_machine(monkeypatch):
    import hermes_cli.config as config

    def unavailable():
        raise RuntimeError('WMI machine discovery must not run for an OS-family check')

    monkeypatch.setattr(platform, 'system', unavailable)
    importlib.reload(config)
    assert config._IS_WINDOWS == (os.name == 'nt')
