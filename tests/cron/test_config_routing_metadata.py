"""Saved home routing must not activate adapter plugins."""
import json
from types import SimpleNamespace

import pytest

from gateway import config, config_env, config_loader
from cron import scheduler_delivery


@pytest.mark.parametrize('layout', ['platforms', 'gateway_platforms', 'legacy'])
def test_saved_home_metadata_skips_plugin_hooks(tmp_path, monkeypatch, layout, caplog):
    caplog.set_level('DEBUG', logger=scheduler_delivery.logger.name)
    platforms = {'telegram': {'home_channel': {'platform': 'telegram', 'chat_id': '-123', 'thread_id': '9'}}}
    if layout == 'legacy':
        (tmp_path / 'gateway.json').write_text(json.dumps({'platforms': platforms}), encoding='utf-8')
    else:
        payload = {'platforms': platforms} if layout == 'platforms' else {'gateway': {'platforms': platforms}}
        (tmp_path / 'config.yaml').write_text(json.dumps(payload), encoding='utf-8')
    monkeypatch.setattr(config, 'get_hermes_home', lambda: tmp_path)
    calls = []
    def activation(*args, **kwargs):
        calls.append('activation')
        raise AssertionError('routing metadata activated a plugin')
    monkeypatch.setattr(config_loader, 'apply_plugin_yaml_hooks', activation)
    monkeypatch.setattr(config_env, '_enable_plugin_platforms_from_env', activation)
    monkeypatch.setattr(config_env, '_ENV_STEPS', (activation,))
    home = scheduler_delivery._get_config_home_channel('telegram')
    assert home is not None, caplog.text
    assert (home.chat_id, home.thread_id) == ('-123', '9')
    assert calls == []


def test_normal_gateway_load_still_runs_plugin_enable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'get_hermes_home', lambda: tmp_path)
    calls = []
    def activation(value):
        calls.append(value)
    monkeypatch.setattr(config_env, '_enable_plugin_platforms_from_env', activation)
    monkeypatch.setattr(config_env, '_ENV_STEPS', (activation,))
    loaded = config.load_gateway_config()
    assert calls == [loaded]


def test_environment_home_override_still_precedes_saved_metadata(monkeypatch):
    monkeypatch.setattr(scheduler_delivery, '_env_home_target_chat_id', lambda name: '-override')
    def unexpected(name):
        raise AssertionError('configured env home should not need config')
    monkeypatch.setattr(scheduler_delivery, '_get_config_home_channel', unexpected)
    assert scheduler_delivery._get_home_target_chat_id('telegram') == '-override'


@pytest.mark.parametrize('saved_home', [None, '#saved'])
def test_plugin_seed_keeps_precedence_and_only_resolves_target(tmp_path, monkeypatch, saved_home, caplog):
    caplog.set_level('DEBUG', logger=scheduler_delivery.logger.name)
    monkeypatch.setattr(config, 'get_hermes_home', lambda: tmp_path)
    if saved_home:
        (tmp_path / 'gateway.json').write_text(json.dumps({'platforms': {
            'irc': {'home_channel': {'platform': 'irc', 'chat_id': saved_home}}
        }}), encoding='utf-8')
    calls = []
    def activation(value, *, platform_names=None):
        calls.append(platform_names)
        platform = config.Platform('irc')
        value.platforms[platform] = config.PlatformConfig(
            home_channel=config.HomeChannel(platform=platform, chat_id='#jobs', name='Home'))
    monkeypatch.setattr(config_env, '_enable_plugin_platforms_from_env', activation)
    monkeypatch.setattr(config_env, '_ENV_STEPS', (activation,))
    home = scheduler_delivery._get_config_home_channel('irc')
    assert home is not None, caplog.text
    assert home.chat_id == '#jobs'
    assert calls == [{'irc'}]


def test_unknown_platform_is_discovered_before_config_lookup(monkeypatch):
    from hermes_cli import plugins
    calls = []
    discovered = False
    def platform(name):
        if not discovered:
            raise ValueError(name)
        return name
    def discover():
        nonlocal discovered
        discovered = True
        calls.append('discover')
    def load(*, platform_plugin_names=None):
        calls.append(platform_plugin_names)
        return SimpleNamespace(get_home_channel=lambda value: SimpleNamespace(chat_id='external-home'))
    monkeypatch.setattr(config, 'Platform', platform)
    monkeypatch.setattr(config, 'load_gateway_config', load)
    monkeypatch.setattr(plugins, 'discover_plugins', discover)
    assert scheduler_delivery._get_config_home_channel('external-home-plugin').chat_id == 'external-home'
    assert calls == ['discover', {'external-home-plugin'}]


def test_candidate_filter_does_not_resolve_unrelated_adapters(monkeypatch):
    entries = {}
    calls = []
    def resolve(name):
        calls.append(name)
        entries[name] = SimpleNamespace(name=name, source='plugin')
    registry = SimpleNamespace(deferred_names=lambda: ['telegram', 'irc'],
                               loaded_entries=lambda: list(entries.values()), get=resolve)
    monkeypatch.setattr(config, '_deferred_platform_may_be_configured', lambda *args: True)
    monkeypatch.setattr(config, '_visible_env_keys', lambda: set())
    result = config._candidate_plugin_entries(registry, config.GatewayConfig(), platform_names={'irc'})
    assert calls == ['irc']
    assert [entry.name for entry in result] == ['irc']


def test_yaml_hook_filter_does_not_resolve_unrelated_adapters(monkeypatch):
    calls = []
    def resolve(name):
        calls.append(name)
        return SimpleNamespace(name=name, apply_yaml_config_fn=lambda *args: {})
    registry = SimpleNamespace(get=resolve)
    monkeypatch.setattr(config, '_platform_registry_names', lambda *args, **kwargs: ['telegram', 'irc'])
    config_loader.apply_plugin_yaml_hooks({'telegram': {}, 'irc': {}}, {}, {}, registry,
                                         platform_names={'irc'})
    assert calls == ['irc']
