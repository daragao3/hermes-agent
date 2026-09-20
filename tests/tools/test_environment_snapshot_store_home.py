"""The modal/singularity snapshot stores must resolve under the ACTIVE profile's home.

Why this exists
---------------
Both modules bound ``_SNAPSHOT_STORE = get_hermes_home() / "<name>_snapshots.json"`` at module
scope. ``get_hermes_home()`` resolves a context-local ContextVar override first, and
``gateway/run.py::_profile_runtime_scope`` sets that override around a WHOLE TURN of a
multiplexed profile ("Scope config/skills/memory AND credentials to a profile for one turn").
Environment tools run inside a turn, so a snapshot taken at import means one profile's turn
READS and WRITES the launch profile's snapshot store.

Same bug class and same fix as skills_tool (f8723c478), skill_manager_tool (c6a3d412d) and
skills_sync (issue #65828), and as agent/auxiliary_client (loops
auxiliary-client-auth-json-module-scope-snapshot-20260920). These two need no import-time
sentinel because nothing monkeypatches ``_SNAPSHOT_STORE``.

The store functions are stubbed rather than allowed to run: this asserts the path the code
WOULD use, so a red run cannot write ``*_snapshots.json`` into the developer's real
``$HERMES_HOME``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override

MODULES = [
    ("tools.environments.modal", "modal_snapshots.json"),
    ("tools.environments.singularity", "singularity_snapshots.json"),
]


@pytest.mark.parametrize("module_name,filename", MODULES)
def test_saving_a_snapshot_targets_the_overridden_home(module_name, filename, tmp_path,
                                                       monkeypatch):
    mod = importlib.import_module(module_name)
    recorded: list[Path] = []
    monkeypatch.setattr(mod, "_save_json_store",
                        lambda path, data: recorded.append(Path(path)))

    token = set_hermes_home_override(tmp_path)
    try:
        mod._save_snapshots({"task": "snap"})
    finally:
        reset_hermes_home_override(token)

    assert recorded == [tmp_path / filename], (
        f"{module_name} wrote its snapshot store to {recorded} instead of the overridden "
        f"home -- a multiplexed profile turn persists into the launch profile's store")


@pytest.mark.parametrize("module_name,filename", MODULES)
def test_loading_a_snapshot_reads_the_overridden_home(module_name, filename, tmp_path,
                                                      monkeypatch):
    mod = importlib.import_module(module_name)
    recorded: list[Path] = []

    def _fake_load(path):
        recorded.append(Path(path))
        return {}

    monkeypatch.setattr(mod, "_load_json_store", _fake_load)

    token = set_hermes_home_override(tmp_path)
    try:
        mod._load_snapshots()
    finally:
        reset_hermes_home_override(token)

    assert recorded == [tmp_path / filename], (
        f"{module_name} read its snapshot store from {recorded} instead of the overridden "
        "home -- a profile turn sees another profile's snapshots")
