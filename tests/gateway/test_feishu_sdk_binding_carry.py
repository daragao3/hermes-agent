import importlib
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

from plugins.platforms.feishu import adapter


def _fake_sdk(monkeypatch):
    modules = {"lark_oapi": SimpleNamespace(), "lark_oapi.ws": SimpleNamespace(Client=object())}
    expected = {}
    for module, names in adapter._LARK_SDK_IMPORTS:
        values = {name: object() for name in names}
        modules[module] = SimpleNamespace(**values)
        expected.update(values)
    expected.update(lark=modules["lark_oapi"], FeishuWSClient=modules["lark_oapi.ws"].Client)
    for name in expected:
        monkeypatch.setattr(adapter, name, None)
    monkeypatch.setattr(adapter, "FEISHU_AVAILABLE", False)
    return modules, expected


def test_sdk_binding_is_atomic_and_serialized_on_concurrent_first_use(monkeypatch):
    modules, expected = _fake_sdk(monkeypatch)
    calls = []
    def load(name):
        calls.append(name)
        time.sleep(0.002)
        return modules[name]
    monkeypatch.setattr(importlib, "import_module", load)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: adapter._load_lark_oapi(), range(8)))
    assert all(results)
    assert len(calls) == len(modules)
    assert set(calls) == set(modules)
    assert adapter.FEISHU_AVAILABLE is True
    assert all(getattr(adapter, name) is value for name, value in expected.items())


def test_failed_binding_does_not_publish_partial_sdk_globals(monkeypatch):
    modules, expected = _fake_sdk(monkeypatch)
    def load(name):
        if name == "lark_oapi.core":
            raise ImportError("missing SDK component")
        return modules[name]
    monkeypatch.setattr(importlib, "import_module", load)
    assert adapter._load_lark_oapi() is False
    assert adapter.FEISHU_AVAILABLE is False
    assert all(getattr(adapter, name) is None for name in expected)


def test_explicit_use_does_not_reinstall_an_already_usable_sdk(monkeypatch):
    from tools import lazy_deps
    monkeypatch.setattr(adapter, "FEISHU_AVAILABLE", False)
    monkeypatch.setattr(adapter, "_load_lark_oapi", lambda: True)
    install = Mock(side_effect=AssertionError("must not reinstall a usable SDK"))
    monkeypatch.setattr(lazy_deps, "ensure", install)
    assert adapter.check_feishu_requirements() is True
    install.assert_not_called()
