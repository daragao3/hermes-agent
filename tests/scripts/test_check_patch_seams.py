"""Wrappers for scripts/check_patch_seams.py.

Same shape as tests/scripts/test_windows_footguns_full_repo_scan.py and
test_check_orphaned_fixtures.py: run the REAL script over the tracked tree
and require a clean exit, and pin the model on throwaway repos in both
directions -- a stale seam must be reported, and every shape the model
deliberately declines to judge must come back clean -- so a green here cannot
be a checker that refuses everything or one that sees nothing.

The defect this guards against is the 2026-09-17 ``tools.voice_mode.platform``
seam: the platform.* sweep (cfd903802b) replaced ``import platform`` with
``from hermes_cli._subprocess_compat import host_system``, its test update
searched for dotted patch strings only, and ``patch.object(vm, "platform")``
in tests/tools/test_voice_mode_playback_env_scrub.py stayed stale -- a
deterministic head-only red that no import-time or setup-time gate could see,
fixed test-only as 006faacb8b during the de1f83cddf acceptance ceremony.  The
historical positive control below replays exactly that pair: the pre-fix test
file against the current ``tools/voice_mode.py``.

The second class is a plain READ of a dropped name: 3a392cdb87 moved
``WMI_STRAY_THREAD_FIXED`` into function scope in hermes_cli/_subprocess_compat.py
and tests/hermes_cli/test_host_platform_helpers.py kept reading
``compat.WMI_STRAY_THREAD_FIXED`` (head-only red in ceremony 973255d3f5, fixed
5432bf59ce).  Reads are seams since 2026-09-18; the exclusion model that keeps
them at zero false positives (attributes the test tree creates, guarded
reads) is pinned below, each rule against a demo that would otherwise report.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.timeout_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_patch_seams.py"

# Same ordering rule as the footgun wrapper: the subprocess bound must fire
# before pyproject's thread watchdog, so a slow scan names itself.
# ~55 s with reads on this box under load (37 s patch-only); 190 s was seen
# once at 100% host CPU, so the net sits well above that.
_SCAN_TIMEOUT_S = scaled(420)
_TEST_TIMEOUT_S = scaled(480)


def _load():
    spec = importlib.util.spec_from_file_location("check_patch_seams", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass under `from __future__ import annotations`
    spec.loader.exec_module(module)
    return module


cps = _load()


# ── Full-repo scan ──────────────────────────────────────────────────────────


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_tracked_tests_patch_no_stale_module_seams():
    """Run the real checker over every tracked tests/**/*.py and require a
    clean exit, so THIS file -- not the next acceptance A/B -- is what
    catches a test still patching a name its target module stopped binding."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(REPO_ROOT), "--verbose"],
        capture_output=True,
        text=True,
        timeout=_SCAN_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"stale patch seams (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    # A scan that saw nothing is not a clean scan.
    assert "files=" in result.stderr and "seams=0 " not in result.stderr, result.stderr


# ── Demo repo ───────────────────────────────────────────────────────────────


def _write(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8", newline="\n")


def _demo_repo(tmp_path: Path) -> Path:
    """A miniature of the incident: ``pkg/vm.py`` used to ``import platform``
    and now binds ``host_system`` instead; ``pkg/star.py`` re-exports through
    a wildcard; ``pkg/hooked.py`` has a PEP 562 ``__getattr__``;
    ``pkg/shared.py`` hands its namespace to a registrar; ``ns/`` is a
    namespace package."""
    repo = tmp_path / "repo"
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/compat.py", "def host_system():\n    return 'Linux'\n")
    _write(repo, "pkg/vm.py", """
        import shutil
        import subprocess
        from pkg.compat import host_system

        try:
            import optional_dep
        except ImportError:  # pragma: no cover
            optional_dep = None

        if True:
            CONFIG = {}

        with open(__file__) as _fh:
            pass


        class Player:
            def play(self):
                return host_system()


        def play_audio_file(path):
            return shutil.which("ffplay") is not None
        """)
    _write(repo, "pkg/star.py", "from pkg.vm import *\n")
    _write(repo, "pkg/hooked.py", "def __getattr__(name):\n    return name\n")  # serves anything
    _write(repo, "pkg/lazy.py", """
        import sys
        __all__ = ["tick", "tock"]
        _PLUGIN_COMPAT_LAZY = {
            "platform": ("pkg.compat", "host_system"),
            "legacy_helper": ("pkg.vm", "play_audio_file"),
        }


        def __getattr__(name):  # PEP 562 -- lazy so no import cycles
            target = _PLUGIN_COMPAT_LAZY.get(name)
            if target is None:
                raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
            import importlib
            return getattr(importlib.import_module(target[0]), target[1])


        _prev_getattr = __getattr__


        def __getattr__(name):  # chained onto the module's own hook
            if name == "requests":
                import requests
                globals()[name] = requests
                return requests
            if name not in __all__:
                return _prev_getattr(name)
            return getattr(sys.modules["pkg.compat"], name)
        """)
    _write(repo, "pkg/lazy_opaque.py", """
        import os
        _RESOLVERS = {"HERMES_HOME": str, **{k: str for k in os.environ}}


        def __getattr__(name):
            resolver = _RESOLVERS.get(name)
            if resolver is not None:
                return resolver()
            raise AttributeError(name)
        """)
    # tools/skills_hub.py + tools/mcp_tool.py: the hook's container is built,
    # not spelled -- a dict display unpacking a comprehension re-keyed from a
    # tuple of module-level names, and a frozenset() of a union with a
    # comprehension over a module-level display; ``globals()[name]`` in the
    # hook serves nothing new.
    _write(repo, "pkg/lazy_built.py", """
        _FAMILIES = (
            ("mcp.types", ("CreateMessageResult", "ErrorData"), "sampling types not available"),
            ("mcp.types", ("ElicitResult",), "elicitation types not available"),
        )
        _SDK = frozenset({"stdio_client", "StdioServerParameters"} | {n for _mod, names, _msg in _FAMILIES for n in names})
        _ALSO = _SDK | {"extra"}


        def _path_resolver(name, parent, leaf):
            def resolve():
                return name
            resolve.__name__ = f"_{name.lower()}"
            return resolve


        _skills_dir = _path_resolver("SKILLS_DIR", "HERMES_HOME", "skills")
        _hub_dir = _path_resolver("HUB_DIR", "SKILLS_DIR", ".hub")
        _RESOLVERS = {"HERMES_HOME": str, **{
            r.__name__[1:].upper(): r for r in (_skills_dir, _hub_dir)
        }, **{k: str for k in ("INLINE_A",)}}


        def __getattr__(name):
            if name in _ALSO:
                try:
                    return globals()[name]
                except KeyError:
                    pass
            resolver = _RESOLVERS.get(name)
            if resolver is not None:
                return resolver()
            raise AttributeError(name)
        """)
    # agent/*_registry.py: an instance of a repo class is handed the namespace
    # dict; its method writes through the dict protocol.
    _write(repo, "pkg/provider_registry.py", """
        class ProviderRegistry:
            def __init__(self, label):
                self._providers = {}
                self._lock = None

            def register(self, name, provider):
                self._providers[name] = provider

            def export(self, namespace):
                namespace.update(
                    _providers=self._providers, _lock=self._lock,
                    register_provider=self.register, _reset_for_tests=self.reset,
                )
                namespace.update({"registry_generation": 0})
                namespace["snapshot_registration"] = self.snapshot
                namespace.setdefault("restore_registration", self.restore)
                namespace.get("nothing")

            def reset(self):
                self._providers.clear()

            def snapshot(self):
                return dict(self._providers)

            def restore(self, snap):
                self._providers = snap

        class StaticReg:
            @staticmethod
            def export(namespace):
                namespace.update(STATIC_NAME=1)


        class Opaque:
            def export(self, namespace):
                namespace.update(**self.__dict__)

            def export_computed(self, namespace):
                namespace.update(self._computed())

            def export_pop(self, namespace):
                namespace.pop("register_provider", None)
        """)
    _write(repo, "pkg/image_registry.py", """
        import logging
        from pkg.provider_registry import ProviderRegistry

        logger = logging.getLogger(__name__)
        _registry: ProviderRegistry = ProviderRegistry(label="Image gen")
        _registry.export(globals())


        def get_active_provider():
            return _registry


        _PLUGIN_COMPAT_LAZY = {"hermes_home_key": ("pkg.compat", "host_system")}


        def __getattr__(name):
            target = _PLUGIN_COMPAT_LAZY.get(name)
            if target is None:
                raise AttributeError(name)
            import importlib
            return getattr(importlib.import_module(target[0]), target[1])
        """)
    _write(repo, "pkg/attr_registry.py", """
        from pkg import provider_registry
        _registry = provider_registry.ProviderRegistry(label="x")
        _registry.export(globals())
        """)
    _write(repo, "pkg/static_registry.py", """
        from pkg.provider_registry import StaticReg
        _registry = StaticReg()
        _registry.export(globals())
        """)
    _write(repo, "pkg/shared.py", """
        import sys
        from pkg import registrar
        registrar.register(sys.modules[__name__])
        """)
    _write(repo, "pkg/table.py", """
        _TABLE = (("browser_snapshot", None), ("browser_click", None))
        _SURFACE: dict[str, tuple[str, ...]] = {
            "pkg.updater": ("_stash_changes", "_run_backup"),
            "pkg.procs": ("_kill_stale",),
        }
        _SOURCES: dict[str, str] = {attr: mod for mod, attrs in _SURFACE.items() for attr in attrs}
        globals()["ALIAS"] = 1
        globals().update({"FROM_UPDATE": 2})
        for _name, _fn in _TABLE:
            globals()[f"check_{_name}_requirements"] = _fn


        def __getattr__(name):
            module = _SOURCES.get(name)
            if module is None:
                raise AttributeError(name)
            return module
        """)
    _write(repo, "pkg/table_opaque.py", """
        import os
        globals().update(dict(os.environ))
        """)
    # A registrar whose body the scan cannot read: the namespace goes through
    # ``vars(mod).update(...)``, so pkg.shared stays non-static (a readable
    # registrar is the split-module demo, _split_repo).
    _write(repo, "pkg/registrar.py", "def register(mod):\n    vars(mod).update(_computed())\n\n\ndef _computed():\n    return {'published': 1}\n")
    _write(repo, "ns/sub/adapter.py", "def send():\n    pass\n")
    return repo


def _split_repo(tmp_path: Path) -> Path:
    """A miniature of tui_gateway/server.py's split-module pattern: ``server``
    imports its handler modules last and hands itself to each ``register`` in
    a loop; ``methods_a.register`` publishes the module through a
    ``bind_module(globals(), server, skip=...)`` with method_ctx's skip rules;
    ``methods_b`` installs handlers through a HandlerRegistry (no names), then
    publishes a literal setattr loop, an attribute assignment, and hands the
    server on to ``methods_c.bind_server`` / ``methods_c.register``."""
    repo = tmp_path / "split"
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/compat.py", "def host_system():\n    return 'Linux'\n")
    _write(repo, "pkg/consts.py", "LIMIT = 3\n")
    _write(repo, "pkg/gw/__init__.py", "")
    _write(repo, "pkg/gw/method_ctx.py", """
        import types

        class HandlerRegistry:
            def __init__(self):
                self._pending = []

            def method(self, name):
                def dec(fn):
                    self._pending.append((name, fn))
                    return fn
                return dec

            def install(self, server):
                for name, fn in self._pending:
                    server._methods[name] = fn


        _PLUMBING = {"HandlerRegistry", "method", "_profile_scoped", "register", "rebind", "logger"}


        def bind_module(module_globals, server, *, skip=()):
            for name, obj in list(module_globals.items()):
                if name.startswith("__") or name in _PLUMBING or name in skip or isinstance(obj, (types.ModuleType, HandlerRegistry)):
                    continue
                setattr(server, name, obj)
        """)
    _write(repo, "pkg/gw/methods_a.py", """
        import os
        from typing import TYPE_CHECKING
        from .method_ctx import HandlerRegistry, bind_module
        from pkg.compat import host_system      # a plain import of a def: server has its own
        from pkg.consts import LIMIT            # a constant: published as-is
        from . import methods_b                 # a module: skipped

        if TYPE_CHECKING:
            from .server import _sessions       # declared for the type checker, never bound

        _registry = HandlerRegistry()
        _ = None
        DISPATCH = {"prompt.submit": None}


        @_registry.method("prompt.submit")
        def _run_prompt_submit(params):
            return _sessions, LIMIT


        class Turn:
            pass


        def register(server):
            bind_module(globals(), server, skip=("_",))
        """)
    _write(repo, "pkg/gw/methods_b.py", """
        from .method_ctx import HandlerRegistry

        _registry = HandlerRegistry()


        @_registry.method("session.start")
        def _only_a_handler(params):
            return None


        def register(server):
            _registry.install(server)
            from . import methods_c
            server._LONG_HANDLERS = server._LONG_HANDLERS | methods_c.LONG_HANDLERS
            for name in ("_WORKER_UNAVAILABLE", "_profile_name"):
                setattr(server, name, getattr(methods_c, name))
            methods_c.bind_server(server)
            methods_c.register(server)
        """)
    _write(repo, "pkg/gw/methods_c.py", """
        LONG_HANDLERS = frozenset()
        _WORKER_UNAVAILABLE = "unavailable"
        _profile_name = "main"
        _profile_execution_policy = "strict"
        _bound_server = None


        def bind_server(server):
            global _bound_server
            _bound_server = server
            server._profile_execution_policy = _profile_execution_policy


        def register(server):
            pass
        """)
    _write(repo, "pkg/gw/server.py", """
        import sys

        # Static declarations for globals supplied by method_ctx.bind_module.
        if __import__("typing").TYPE_CHECKING:
            from .methods_a import _run_prompt_submit, _renamed_away

        _sessions = {}
        _methods = {}
        _LONG_HANDLERS = frozenset()


        def _emit(event):
            return event


        from . import methods_a as _methods_a, methods_b as _methods_b  # noqa: E402

        for _m in (_methods_a, _methods_b):
            _m.register(sys.modules[__name__])
        del _m
        """)
    return repo


def _scan(repo: Path, *files: str, reads: bool = False):
    """Patch seams only by default: the stats the older tests pin count those;
    the read tests pass ``reads=True`` explicitly."""
    findings, stats = cps.scan(repo, list(files), reads=reads)
    return [(f.path, f.line, f.form, f.target) for f in findings], stats


def test_stale_seam_reported_in_every_form(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_stale.py", """
        from unittest import mock
        from unittest.mock import patch
        import pkg.vm as vm
        from pkg import vm as vm2
        import pkg.vm


        def test_object(monkeypatch, mocker):
            with patch.object(vm, "platform"):
                pass
            with mock.patch.object(vm2, "platform"):
                pass
            monkeypatch.setattr(vm, "platform", None)
            monkeypatch.delattr(pkg.vm, "platform")
            mocker.patch.object(vm, "platform")


        @patch("pkg.vm.platform")
        def test_string(_):
            pass


        def test_string_setattr(monkeypatch):
            monkeypatch.setattr("pkg.vm.platform", None)


        def test_multiple():
            with patch.multiple(vm, platform=None, host_system=None):
                pass
            with patch.multiple("pkg.vm", platform=None):
                pass


        def test_missing_submodule():
            with patch("pkg.gone.thing"):
                pass
            with patch.object(vm.gone, "thing"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_stale.py")
    assert findings == [
        ("tests/test_stale.py", 9, "patch.object", "vm.platform"),
        ("tests/test_stale.py", 11, "patch.object", "vm2.platform"),
        ("tests/test_stale.py", 13, "setattr", "vm.platform"),
        ("tests/test_stale.py", 14, "delattr", "pkg.vm.platform"),
        ("tests/test_stale.py", 15, "patch.object", "vm.platform"),
        ("tests/test_stale.py", 18, "patch", "pkg.vm.platform"),
        ("tests/test_stale.py", 24, "setattr", "pkg.vm.platform"),
        ("tests/test_stale.py", 28, "patch.multiple", "vm.platform"),
        ("tests/test_stale.py", 30, "patch.multiple", "pkg.vm.platform"),
        ("tests/test_stale.py", 35, "patch", "pkg.gone"),
        ("tests/test_stale.py", 37, "patch.object", "vm.gone"),
    ]
    # patch.multiple's second name WAS bound: verified, not reported.
    assert stats.verified == 1


def test_bound_names_of_every_top_level_shape_are_clean(tmp_path):
    """Everything pkg/vm.py binds at module scope -- plain and from-imports,
    the try/except fallback, an assignment under ``if``, a ``with ... as``
    target, a class, a function -- plus module dunders and a submodule on
    disk, resolves as bound in every seam form."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_bound.py", """
        from unittest.mock import patch
        import pkg
        import pkg.vm as vm


        def test_all(monkeypatch):
            with patch.object(vm, "host_system", return_value="Linux"):
                pass
            with patch.object(vm, "shutil"), patch.object(vm, "optional_dep"):
                pass
            monkeypatch.setattr(vm, "CONFIG", {})
            monkeypatch.setattr(vm, "_fh", None)
            monkeypatch.setattr(vm, "Player", object)
            monkeypatch.setattr(vm, "play_audio_file", lambda p: True)
            monkeypatch.setattr(vm, "__file__", "x")
            monkeypatch.setattr(pkg, "vm", None)
            monkeypatch.setattr("pkg.vm.host_system", lambda: "Darwin")
            with patch("pkg.vm.subprocess.Popen"):
                pass
            with patch.object(vm.subprocess, "Popen"), patch.object(vm.Player, "play"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_bound.py")
    assert findings == []
    assert stats.verified == 10
    # vm.subprocess.Popen / vm.Player.play: the module seam was crossed and
    # verified; what lies beyond it is an object attribute, out of scope.
    assert stats.object_attr == 3


def test_shapes_the_model_declines_to_judge_are_counted_not_reported(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_skips.py", """
        import importlib
        import sys
        from unittest.mock import patch
        import pkg.vm as vm
        import pkg.vm as reloaded
        import pkg.star as star
        import pkg.hooked as hooked
        import pkg.shared as shared
        import ns.sub.adapter as adapter
        from pkg.vm import Player


        def test_dynamic_alias(monkeypatch, fixture_mod):
            reloaded = importlib.reload(reloaded)
            with patch.object(reloaded, "platform"):        # rebound: dynamic
                pass
            with patch.object(fixture_mod, "platform"):     # a parameter: dynamic
                pass
            with patch.object(type(vm), "platform"):        # not a Name chain
                pass
            with patch.object(sys.modules["pkg.vm"], "platform"):
                pass


        def test_external():
            with patch.object(sys, "platform", "linux"):    # outside the repo
                pass
            with patch("os.path.exists"):
                pass
            with patch.object(Player, "platform"):          # a class, not a module: object_attr
                pass


        def test_not_static():
            with patch.object(star, "platform"):            # wildcard import
                pass
            with patch.object(hooked, "platform"):          # PEP 562
                pass
            with patch.object(shared, "published"):         # namespace handed to a registrar
                pass


        def test_lenient(monkeypatch):
            with patch.object(vm, "platform", create=True):
                pass
            monkeypatch.setattr(vm, "platform", None, raising=False)
            monkeypatch.delattr(vm, "platform", raising=False)
            with patch("pkg.vm.input"):                     # mock creates builtins on modules
                pass


        def test_namespace_package():
            with patch("ns.sub.adapter.send"):
                pass
            with patch.object(adapter, "send"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_skips.py")
    assert findings == []
    assert stats.dynamic == 2
    assert stats.external == 2
    assert stats.object_attr == 1
    assert stats.not_static == 3
    assert stats.lenient == 4
    assert stats.verified == 2
    # type(vm) / sys.modules[...] never became seams at all.
    assert stats.seams == 14


def test_pep562_hook_names_are_read_from_its_body(tmp_path):
    """tools/voice_mode.py -- the incident module -- has a PLUGIN-COMPAT
    ``__getattr__``.  Treating every hooked module as opaque would have hidden
    the incident, so the hook's body is read: names it compares with, keys of
    the module-level literal it looks up in, across chained hooks.  A hook
    that looks ``name`` up in something the source does not spell out makes
    the module opaque again."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_lazy.py", """
        from unittest.mock import patch
        import pkg.lazy as lazy
        import pkg.lazy_opaque as opaque


        def test_it(monkeypatch):
            with patch.object(lazy, "platform"), patch.object(lazy, "legacy_helper"):
                pass
            monkeypatch.setattr(lazy, "requests", None)
            monkeypatch.setattr(lazy, "tick", None)
            monkeypatch.setattr(lazy, "_PLUGIN_COMPAT_LAZY", {})
            monkeypatch.setattr(lazy, "gone", None)
            monkeypatch.setattr(opaque, "HERMES_HOME", None)
            monkeypatch.setattr(opaque, "gone", None)
        """)
    findings, stats = _scan(repo, "tests/test_lazy.py")
    assert findings == [("tests/test_lazy.py", 12, "setattr", "lazy.gone")]
    assert stats.verified == 5
    assert stats.not_static == 2
    facts = cps.Repo(repo).facts("pkg.lazy")
    assert facts.lazy == {"platform", "legacy_helper", "requests", "tick", "tock"}
    assert cps.Repo(repo).facts("pkg.lazy_opaque").lazy is None


def test_pep562_hook_containers_built_from_calls_unions_and_unpacks_are_read(tmp_path):
    """tools/skills_hub.py looks ``name`` up in ``{"HERMES_HOME": f, **{...
    for r in (_skills_dir, _hub_dir)}}`` and tools/mcp_tool.py in
    ``frozenset({...} | {n for ... in _FAMILIES for n in names})`` then
    returns ``globals()[name]``: 63 + 16 seams skipped as not_static until
    the container was read as far as the source spells it.  A name the
    built container carries verifies; one it dropped is reported."""
    repo = _demo_repo(tmp_path)
    facts = cps.Repo(repo).facts("pkg.lazy_built")
    assert facts.static
    served = {
        "stdio_client", "StdioServerParameters",        # the literal half of the union
        "CreateMessageResult", "ErrorData", "ElicitResult",  # the comprehension over _FAMILIES
        "HERMES_HOME",                                  # the dict display's own key
        "SKILLS_DIR", "HUB_DIR",                        # re-keyed from the resolver tuple's values
        "INLINE_A",                                     # a comprehension over an inline display
        "extra",                                        # ``_ALSO = _SDK | {"extra"}``: a union by name
    }
    assert facts.lazy >= served
    # The documented over-approximation, and no more: every string in the
    # display a comprehension iterates, every identifier in a re-keyed value.
    assert facts.lazy - served == {"mcp.types", "sampling types not available", "elicitation types not available", "skills"}
    _write(repo, "tests/test_built.py", """
        from unittest.mock import patch
        import pkg.lazy_built as built


        def test_it(monkeypatch):
            with patch.object(built, "SKILLS_DIR"), patch.object(built, "HUB_DIR"):
                pass
            monkeypatch.setattr(built, "stdio_client", None)
            monkeypatch.setattr(built, "ErrorData", None)
            monkeypatch.setattr(built, "_skills_dir", None)
            monkeypatch.setattr(built, "gone", None)
        """)
    findings, stats = _scan(repo, "tests/test_built.py")
    assert findings == [("tests/test_built.py", 11, "setattr", "built.gone")]
    assert stats.verified == 5 and stats.not_static == 0
    # Drop one resolver (a rename of HUB_DIR) and the patch on it is the finding.
    source = (repo / "pkg/lazy_built.py").read_text(encoding="utf-8")
    _write(repo, "pkg/lazy_built.py", source.replace("for r in (_skills_dir, _hub_dir)", "for r in (_skills_dir,)"))
    findings, _ = _scan(repo, "tests/test_built.py")
    assert [f[3] for f in findings] == ["built.HUB_DIR", "built.gone"]
    # Every escape keeps the hook opaque: a comprehension over something the
    # source does not spell, a ``**`` of a call, a container built by a call
    # the scan does not follow, a union with an opaque side.
    for body in (
        "import os\n_C = {**{k: 1 for k in os.environ}}\n",
        "_C = {'A': 1, **_more()}\n",
        "_C = frozenset(_names())\n",
        "_C = {'A'} | _other()\n",
        "_T = (_f,)\n_C = {k: 1 for k in _T}\n",           # a tuple of names bound by nothing readable
    ):
        _write(repo, "pkg/opaque_c.py", body + "\n\ndef __getattr__(name):\n    if name in _C:\n        return 1\n    raise AttributeError(name)\n")
        assert cps.Repo(repo).facts("pkg.opaque_c").lazy is None, body


def test_instance_registrar_method_is_read_through_the_dict_protocol(tmp_path):
    """agent/*_registry.py: ``_registry = ProviderRegistry(...)`` then
    ``_registry.export(globals())`` -- 243 seams on seven modules skipped as
    not_static.  The registrar is the imported class's method, read past
    ``self``; the names it writes into the namespace dict (``update(x=v)``,
    ``update({...})``, ``ns["x"] = v``, ``setdefault``) verify, a name it
    dropped is reported, and the module's own PLUGIN-COMPAT hook still
    serves its keys."""
    repo = _demo_repo(tmp_path)
    facts = cps.Repo(repo).facts("pkg.image_registry")
    assert facts.static
    assert facts.registrars == (("pkg.provider_registry", "ProviderRegistry.export"),)
    assert facts.registered == {
        "_providers", "_lock", "register_provider", "_reset_for_tests",   # update(x=v)
        "registry_generation",                                           # update({"x": v})
        "snapshot_registration",                                         # ns["x"] = v
        "restore_registration",                                          # setdefault
    }
    assert facts.lazy == {"hermes_home_key"}
    # ``from pkg import provider_registry`` + ``provider_registry.ProviderRegistry(...)``
    # and a @staticmethod registrar (no ``self`` to skip) resolve the same way.
    assert cps.Repo(repo).facts("pkg.attr_registry").registered == facts.registered
    assert cps.Repo(repo).facts("pkg.static_registry").registered == {"STATIC_NAME"}
    _write(repo, "tests/test_registry.py", """
        from unittest.mock import patch
        import pkg.image_registry as image_gen_registry
        import pkg.attr_registry as attr_registry


        def test_it(monkeypatch):
            with patch.object(image_gen_registry, "register_provider"), patch.object(image_gen_registry, "_reset_for_tests"):
                pass
            monkeypatch.setattr(image_gen_registry, "_providers", {})
            monkeypatch.setattr(image_gen_registry, "snapshot_registration", None)
            monkeypatch.setattr(image_gen_registry, "restore_registration", None)
            monkeypatch.setattr(image_gen_registry, "registry_generation", 0)
            monkeypatch.setattr(image_gen_registry, "get_active_provider", None)
            monkeypatch.setattr(image_gen_registry, "hermes_home_key", None)
            monkeypatch.setattr(attr_registry, "_lock", None)
            monkeypatch.setattr(image_gen_registry, "list_providers", None)
            monkeypatch.setattr(image_gen_registry, "export", None)
            monkeypatch.setattr(image_gen_registry, "reset", None)
        """)
    findings, stats = _scan(repo, "tests/test_registry.py")
    assert [f[3] for f in findings] == [
        "image_gen_registry.list_providers",   # never exported
        "image_gen_registry.export",           # the registrar's own method, not a published name
        "image_gen_registry.reset",            # published as _reset_for_tests, not under its own name
    ]
    assert stats.verified == 9 and stats.not_static == 0
    # Drop ``register_provider`` from export (a rename) and the patch on it is the finding.
    source = (repo / "pkg/provider_registry.py").read_text(encoding="utf-8")
    _write(repo, "pkg/provider_registry.py", source.replace("register_provider=self.register, ", ""))
    findings, _ = _scan(repo, "tests/test_registry.py")
    assert [f[3] for f in findings][0] == "image_gen_registry.register_provider"
    # Every escape keeps the host non-static: ``update(**computed)``, a
    # positional the scan cannot read, ``pop``, an instance of a class from
    # outside the repo, a class the module defines itself, a rebound alias.
    cases = {
        "star": "from pkg.provider_registry import Opaque\n_r = Opaque()\n_r.export(globals())\n",
        "computed": "from pkg.provider_registry import Opaque\n_r = Opaque()\n_r.export_computed(globals())\n",
        "pop": "from pkg.provider_registry import Opaque\n_r = Opaque()\n_r.export_pop(globals())\n",
        "outside": "import third_party\n_r = third_party.Registry()\n_r.export(globals())\n",
        "own": "class R:\n    def export(self, ns):\n        ns.update(x=1)\n_r = R()\n_r.export(globals())\n",
        "rebound": "from pkg.provider_registry import ProviderRegistry\n_r = ProviderRegistry(label='x')\n_r = None\n_r.export(globals())\n",
        "no_method": "from pkg.provider_registry import ProviderRegistry\n_r = ProviderRegistry(label='x')\n_r.missing(globals())\n",
    }
    for name, body in cases.items():
        _write(repo, f"pkg/host_{name}.py", body)
        facts = cps.Repo(repo).facts(f"pkg.host_{name}")
        assert not facts.static, name
        assert facts.registered is None, name


def test_the_live_registry_modules_and_built_hooks_are_static():
    """Against the real tree: the seven ``agent.*_registry`` modules resolve
    through ProviderRegistry.export, tools.skills_hub through its resolver
    table and tools.mcp_tool through its SDK symbol set, so the 341 seams
    the 2026-09-18 breakdown counted as not_static verify, and a name none
    of them binds is a finding."""
    repo = cps.Repo(REPO_ROOT)
    for module in ("image_gen", "tts", "transcription", "web_search", "terminal_env", "video_gen", "browser"):
        facts = repo.facts(f"agent.{module}_registry")
        assert facts.static, module
        assert facts.registrars == (("agent.provider_registry", "ProviderRegistry.export"),), module
        assert facts.binds("register_provider") and facts.binds("_reset_for_tests") and facts.binds("_providers"), module
        assert not facts.binds("_this_name_is_exported_by_nothing"), module
    hub = repo.facts("tools.skills_hub")
    assert hub.static and hub.binds("SKILLS_DIR") and hub.binds("QUARANTINE_DIR") and hub.binds("HERMES_HOME")
    assert not hub.binds("_this_path_has_no_resolver")
    mcp = repo.facts("tools.mcp_tool")
    assert mcp.static and mcp.binds("stdio_client") and mcp.binds("StdioServerParameters") and mcp.binds("streamable_http_client")
    assert not mcp.binds("_this_symbol_is_not_lazy")


def test_names_written_through_globals_are_bound_by_key_or_pattern(tmp_path):
    """tools/browser_tool.py binds ``check_<tool>_requirements`` through
    ``globals()[f"..."]`` in a loop and hermes_cli/main.py serves a frozen
    surface through a comprehension-inverted dict: a constant key binds the
    name, an f-string key binds its literal shape, a comprehension over
    module-level displays serves every string in them, and handing the
    namespace something computed makes the module opaque."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_table.py", """
        import pkg.table as table
        import pkg.table_opaque as opaque


        def test_it(monkeypatch):
            monkeypatch.setattr(table, "check_browser_snapshot_requirements", lambda: True)
            monkeypatch.setattr(table, "ALIAS", 2)
            monkeypatch.setattr(table, "FROM_UPDATE", 3)
            monkeypatch.setattr(table, "_stash_changes", None)
            monkeypatch.setattr(table, "_kill_stale", None)
            monkeypatch.setattr(table, "check_anything_requirements", None)
            monkeypatch.setattr(table, "gone", None)
            monkeypatch.setattr(opaque, "PATH", None)
        """)
    findings, stats = _scan(repo, "tests/test_table.py")
    assert findings == [("tests/test_table.py", 12, "setattr", "table.gone")]
    assert stats.verified == 6  # check_anything_requirements fits the f-string shape: not judged
    assert stats.not_static == 1
    facts = cps.Repo(repo).facts("pkg.table")
    assert facts.static and [p.pattern for p in facts.patterns] == ["check_.*_requirements"]
    assert facts.lazy == {"pkg.updater", "_stash_changes", "_run_backup", "pkg.procs", "_kill_stale"}


def test_monkeypatch_setattr_does_not_get_mocks_builtin_leniency(tmp_path):
    """mock.patch quietly sets create=True for a builtin name on a module;
    monkeypatch.setattr raises.  The leniency follows the form."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_builtin.py", """
        import pkg.vm as vm


        def test_it(monkeypatch):
            monkeypatch.setattr(vm, "input", lambda *a: "y")
        """)
    findings, _ = _scan(repo, "tests/test_builtin.py")
    assert findings == [("tests/test_builtin.py", 5, "setattr", "vm.input")]


def test_relative_import_resolves_from_the_test_package(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/__init__.py", "")
    _write(repo, "tests/helpers.py", "SEEN = 1\n")
    _write(repo, "tests/test_rel.py", """
        from unittest.mock import patch
        from . import helpers
        from .helpers import SEEN


        def test_it():
            with patch.object(helpers, "SEEN", 2), patch.object(helpers, "gone"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_rel.py")
    assert findings == [("tests/test_rel.py", 7, "patch.object", "helpers.gone")]
    assert stats.verified == 1


def test_allowlist_suppresses_by_path_and_target(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_allow.py", """
        import pkg.vm as vm


        def test_it(monkeypatch):
            monkeypatch.setattr(vm, "platform", None)
        """)
    findings, _ = cps.scan(repo, ["tests/test_allow.py"], allow=frozenset({"tests/test_allow.py::vm.platform"}))
    assert findings == []


@pytest.mark.timeout(scaled(60))
def test_cli_exit_codes_and_report_lines(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_cli.py", """
        import pkg.vm as vm


        def test_it(monkeypatch):
            monkeypatch.setattr(vm, "platform", None)
            monkeypatch.setattr(vm, "host_system", None)
        """)
    red = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "tests/test_cli.py", "--no-reads"],
        capture_output=True, text=True, timeout=scaled(30), stdin=subprocess.DEVNULL,
    )
    assert red.returncode == 1, red.stderr
    assert red.stdout.splitlines() == [
        "tests/test_cli.py:5: setattr(vm.platform) -- pkg.vm binds no `platform` at top level (pkg/vm.py)",
    ]
    assert "1 stale seam(s)" in red.stderr

    (repo / "tests" / "test_cli.py").write_text(
        "import pkg.vm as vm\n\n\ndef test_it(monkeypatch):\n    monkeypatch.setattr(vm, 'host_system', None)\n",
        encoding="utf-8",
    )
    green = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "tests/test_cli.py", "--verbose", "--no-reads"],
        capture_output=True, text=True, timeout=scaled(30), stdin=subprocess.DEVNULL,
    )
    assert green.returncode == 0, green.stdout + green.stderr
    assert green.stdout == ""
    assert "seams=1 verified=1" in green.stderr

    outside = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo / "nope")],
        capture_output=True, text=True, timeout=scaled(30), stdin=subprocess.DEVNULL,
    )
    assert outside.returncode == 2


# ── Reads ───────────────────────────────────────────────────────────────────


def test_stale_read_reported_in_every_read_shape(tmp_path):
    """A plain ``alias.NAME`` load -- bare, called, in a comparison, as a
    decorator argument, deep in an expression -- is a seam; a chain that
    crosses a module boundary reports the first missing component once."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_reads.py", """
        import pkg
        import pkg.vm as vm
        from pkg import vm as vm2


        def test_it():
            assert vm.platform
            vm.platform.system()
            if vm2.platform == "x":
                pass
            x = [vm.host_system(), vm.CONFIG, pkg.vm.gone, pkg.vm.Player, vm.shutil.which]
            assert vm.Player.play
            assert vm.Player.missing_method   # beyond the seam: object attr, not judged
        """)
    findings, stats = _scan(repo, "tests/test_reads.py", reads=True)
    assert findings == [
        ("tests/test_reads.py", 7, "read", "vm.platform"),
        ("tests/test_reads.py", 8, "read", "vm.platform"),
        ("tests/test_reads.py", 9, "read", "vm2.platform"),
        ("tests/test_reads.py", 11, "read", "pkg.vm.gone"),
    ]
    assert stats.verified == 3  # host_system, CONFIG, Player; the three deeper chains are object attrs
    assert stats.object_attr == 3


def test_reads_of_attributes_the_test_tree_creates_are_not_judged(tmp_path):
    """The three creation shapes, in the file itself and in a conftest whose
    fixture reaches other files -- tests/tools/conftest.py's
    ``_find_cli_unpatched`` is the real case."""
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/conftest.py", """
        import pytest
        import pkg.vm as vm


        @pytest.fixture(autouse=True)
        def _pin_cli(monkeypatch):
            monkeypatch.setattr(vm, "_find_cli_unpatched", vm.play_audio_file, raising=False)
            vm.from_store = 1
            setattr(vm, "from_setattr", 2)
        """)
    _write(repo, "tests/sub/test_uses_conftest.py", """
        import pkg.vm as vm
        from unittest.mock import patch


        def test_it(monkeypatch):
            assert vm._find_cli_unpatched() and vm.from_store and vm.from_setattr
            monkeypatch.setattr(vm, "own_lenient", 1, raising=False)
            with patch.object(vm, "own_create", create=True):
                assert vm.own_lenient and vm.own_create
            vm.own_store = 3
            assert vm.own_store
            monkeypatch.setattr(vm, "_find_cli_unpatched", None)  # a patch of a created attr: fine too
            assert vm.never_created
        """)
    findings, stats = _scan(repo, "tests/sub/test_uses_conftest.py", reads=True)
    assert findings == [("tests/sub/test_uses_conftest.py", 13, "read", "vm.never_created")]
    assert stats.created == 7
    assert cps.conftest_created(repo) == {("pkg.vm", "_find_cli_unpatched"), ("pkg.vm", "from_store"), ("pkg.vm", "from_setattr")}


def test_guarded_reads_are_not_judged(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_guards.py", """
        import contextlib
        import pytest
        import pkg.vm as vm


        def test_it():
            if hasattr(vm, "maybe"):
                assert vm.maybe and vm.maybe.deeper
            assert getattr(vm, "maybe_default", None) is None or vm.maybe_default
            try:
                vm.in_try
            except AttributeError:
                pass
            try:
                vm.in_wide_try
            except (KeyError, Exception):
                pass
            try:
                vm.in_bare_try
            except:  # noqa: E722
                pass
            with pytest.raises(AttributeError):
                vm.in_raises
            with contextlib.suppress(AttributeError):
                vm.in_suppress
            try:
                vm.not_guarded_by_this_except
            except KeyError:
                vm.in_handler_not_guarded
            else:
                vm.in_else_not_guarded
        """)
    findings, stats = _scan(repo, "tests/test_guards.py", reads=True)
    assert [f[3] for f in findings] == ["vm.not_guarded_by_this_except", "vm.in_handler_not_guarded", "vm.in_else_not_guarded"]
    assert stats.guarded == 8


def test_reads_stay_out_of_the_patch_only_scan(tmp_path):
    repo = _demo_repo(tmp_path)
    _write(repo, "tests/test_patch_only.py", """
        import pkg.vm as vm


        def test_it():
            assert vm.platform
        """)
    assert _scan(repo, "tests/test_patch_only.py") == ([], cps.Stats(files=1))
    findings, _ = _scan(repo, "tests/test_patch_only.py", reads=True)
    assert findings == [("tests/test_patch_only.py", 5, "read", "vm.platform")]


# ── Split-module registrars (tui_gateway/server.py) ─────────────────────────


def test_split_module_registrars_are_read_so_the_host_stays_static(tmp_path):
    """``for _m in (...): _m.register(sys.modules[__name__])`` no longer makes
    the host non-static: what each registrar publishes is read from its body.
    A name a split module keeps verifies; a name it dropped (or never
    published: a plain import of a def, a module, the registry plumbing, a
    TYPE_CHECKING declaration, a handler installed into a table) is reported
    -- the head-only red a split-module rename would cause."""
    repo = _split_repo(tmp_path)
    facts = cps.Repo(repo).facts("pkg.gw.server")
    assert facts.static
    assert facts.registrars == ((".methods_a", "register"), (".methods_b", "register"))
    assert facts.registered == {
        # methods_a via bind_module: its defs, assignments, a constant imported
        # from the repo and a name imported from outside it (TYPE_CHECKING is a
        # bool, published as-is) -- not ``os``, ``methods_b``, ``host_system``.
        "LIMIT", "TYPE_CHECKING", "DISPATCH", "_run_prompt_submit", "Turn",
        "_LONG_HANDLERS", "_WORKER_UNAVAILABLE", "_profile_name",  # methods_b.register
        "_profile_execution_policy",                              # methods_c.bind_server
    }
    _write(repo, "tests/test_server.py", """
        from unittest.mock import patch
        import pkg.gw.server as server


        def test_kept():
            with patch.object(server, "_run_prompt_submit"), patch.object(server, "_emit"):
                pass
            with patch.object(server, "_WORKER_UNAVAILABLE"), patch.object(server, "_profile_execution_policy"):
                pass
            with patch.object(server, "LIMIT"), patch.object(server, "_LONG_HANDLERS"):
                pass


        def test_dropped():
            with patch.object(server, "_renamed_away"):        # server declares it, no split module binds it
                pass
            with patch.object(server, "host_system"):          # methods_a's plain import of a def
                pass
            with patch.object(server, "methods_b"):            # an imported module
                pass
            with patch.object(server, "_registry"):            # HandlerRegistry instance
                pass
            with patch.object(server, "bind_module"):          # plumbing
                pass
            with patch.object(server, "_"):                    # in skip=
                pass
            with patch.object(server, "_only_a_handler"):      # installed into _methods, never a name
                pass
            with patch("pkg.gw.server._sessions_declared"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_server.py")
    assert [f[3] for f in findings] == [
        "server._renamed_away", "server.host_system", "server.methods_b", "server._registry",
        "server.bind_module", "server._", "server._only_a_handler", "pkg.gw.server._sessions_declared",
    ]
    assert stats.verified == 6
    assert stats.not_static == 0


def test_registrar_the_scan_cannot_read_keeps_the_host_non_static(tmp_path):
    """Every escape from the readable shapes falls back to the old verdict:
    a registrar outside the repo, a body that hands the server to a call the
    scan does not follow, a computed setattr key, ``server.__dict__`` writes."""
    repo = _split_repo(tmp_path)
    cases = {
        "outside": "import sys\nimport third_party\nthird_party.register(sys.modules[__name__])\n",
        "handed_on": "import sys\nfrom . import opaque\nopaque.register(sys.modules[__name__])\n",
        "computed": "import sys\nfrom . import keyed\nkeyed.register(sys.modules[__name__])\n",
        "dunder": "import sys\nfrom . import dunder\ndunder.register(sys.modules[__name__])\n",
        "rebound": "import sys\nfrom . import methods_c\nmethods_c = None\nmethods_c.register(sys.modules[__name__])\n",
    }
    _write(repo, "pkg/gw/opaque.py", "import os\n\n\ndef register(server):\n    os.register(server)\n")
    _write(repo, "pkg/gw/keyed.py", "def register(server):\n    for name in _names():\n        setattr(server, name, 1)\n\n\ndef _names():\n    return ['x']\n")
    _write(repo, "pkg/gw/dunder.py", "def register(server):\n    server.__dict__['x'] = 1\n")
    for name, body in cases.items():
        _write(repo, f"pkg/gw/host_{name}.py", body)
        facts = cps.Repo(repo).facts(f"pkg.gw.host_{name}")
        assert not facts.static, name
        assert facts.registered is None, name
    # ...and the direct hand-off forms stay unknown as before.
    _write(repo, "pkg/gw/host_direct.py", "from .method_ctx import bind_module\nbind_module(globals(), object())\n")
    assert cps.Repo(repo).facts("pkg.gw.host_direct").shared_namespace


def test_the_live_server_split_is_static_and_binds_what_its_tests_patch():
    """The pattern this exists for, against the real tree: tui_gateway/server.py
    resolves through its ~34 registrars, so ``patch.object(server, "_run_prompt
    _submit")`` in tests/tui_gateway verifies instead of being skipped as
    not_static, and a name no split module binds is a finding."""
    facts = cps.Repo(REPO_ROOT).facts("tui_gateway.server")
    assert facts.static
    assert len(facts.registrars) >= 30 and all(spec.startswith(".") and fn == "register" for spec, fn in facts.registrars)
    assert facts.registered and len(facts.registered) > 500
    assert facts.binds("_run_prompt_submit") and facts.binds("_start_inflight_turn") and facts.binds("_apply_model_switch")
    assert facts.binds("_WORKER_UNAVAILABLE")  # methods_bot_relay.register's setattr loop over methods_groups
    assert not facts.binds("_this_name_is_bound_by_no_split_module")
    assert not facts.binds("bind_module")


def test_type_checking_only_imports_are_not_bound(tmp_path):
    """``if TYPE_CHECKING: import httpx`` never runs: a test patching through
    that name is the 8586e305a2 nous-provider red (eight tests, 2026-09-10 to
    2026-09-18, fixed alongside this rule).  ``if not TYPE_CHECKING:`` is the
    runtime branch and binds."""
    repo = _demo_repo(tmp_path)
    _write(repo, "pkg/typed.py", """
        from typing import TYPE_CHECKING
        import typing as t

        if TYPE_CHECKING:
            import httpx
        if t.TYPE_CHECKING:
            from pkg.vm import Player
        else:
            import json
        if not TYPE_CHECKING:
            import shutil
        else:
            import tomllib


        def post(url):
            import httpx
            return httpx.post(url)
        """)
    _write(repo, "tests/test_typed.py", """
        from unittest.mock import patch
        import pkg.typed as typed


        def test_it():
            with patch("pkg.typed.httpx.post"), patch.object(typed, "Player"), patch.object(typed, "tomllib"):
                pass
            with patch.object(typed, "json"), patch.object(typed, "shutil"), patch.object(typed, "post"):
                pass
        """)
    findings, stats = _scan(repo, "tests/test_typed.py")
    assert [f[3] for f in findings] == ["pkg.typed.httpx", "typed.Player", "typed.tomllib"]
    assert stats.verified == 3


_HTTPX_STALE_AT = "36d80d1d5f"  # trunk before the fix landed with this rule
_HTTPX_TEST = "tests/plugins/dashboard_auth/test_nous_provider.py"


def test_the_nous_httpx_seam_is_caught_before_and_clean_after():
    """Replay against the CURRENT plugins/dashboard_auth/_shared.py: the test
    file at 36d80d1d5f patched ``plugins.dashboard_auth._shared.httpx.post``
    while _shared had ``import httpx`` under TYPE_CHECKING only (eight
    AttributeErrors at run time); the tree's file patches ``httpx.post``."""
    before = _git_show(f"{_HTTPX_STALE_AT}:{_HTTPX_TEST}")
    if before is None:
        pytest.skip(f"{_HTTPX_STALE_AT} is not in this clone's history")
    repo = cps.Repo(REPO_ROOT)

    stats = cps.Stats()
    stale = cps.check_file(repo, _HTTPX_TEST, before.encode("utf-8"), stats)
    assert {(f.form, f.target) for f in stale} == {("patch", "plugins.dashboard_auth._shared.httpx")}
    assert len(stale) == 8
    assert "plugins.dashboard_auth._shared binds no `httpx`" in stale[0].reason

    stats = cps.Stats()
    assert cps.check_file(repo, _HTTPX_TEST, (REPO_ROOT / _HTTPX_TEST).read_bytes(), stats) == []


# ── Historical positive control ─────────────────────────────────────────────

_INCIDENT_FIX = "006faacb8b"
_INCIDENT_TEST = "tests/tools/test_voice_mode_playback_env_scrub.py"


def _git_show(spec: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", spec],
        capture_output=True, stdin=subprocess.DEVNULL,
    )
    return proc.stdout.decode("utf-8") if proc.returncode == 0 else None


def test_the_voice_mode_incident_is_caught_before_and_clean_after():
    """Replay the incident against the CURRENT tools/voice_mode.py: the test
    file as it was before 006faacb8b (``patch.object(vm, "platform")``) must be
    reported, the file after it (``patch.object(vm, "host_system", ...)``)
    must be clean.  Runs in place -- scan() reads only what it is given."""
    before = _git_show(f"{_INCIDENT_FIX}~1:{_INCIDENT_TEST}")
    after = _git_show(f"{_INCIDENT_FIX}:{_INCIDENT_TEST}")
    if before is None or after is None:
        pytest.skip(f"{_INCIDENT_FIX} is not in this clone's history")
    repo = cps.Repo(REPO_ROOT)

    stats = cps.Stats()
    stale = cps.check_file(repo, _INCIDENT_TEST, before.encode("utf-8"), stats)
    assert [(f.form, f.target) for f in stale] == [("patch.object", "vm.platform")]
    assert "tools.voice_mode binds no `platform`" in stale[0].reason

    stats = cps.Stats()
    fixed = cps.check_file(repo, _INCIDENT_TEST, after.encode("utf-8"), stats)
    assert fixed == []
    assert stats.verified >= 1


_READ_FIX = "5432bf59ce"
_READ_TEST = "tests/hermes_cli/test_host_platform_helpers.py"


def test_the_wmi_constant_read_is_caught_before_and_clean_after():
    """The reads class, replayed against the CURRENT hermes_cli/_subprocess_compat.py:
    the file before 5432bf59ce read ``compat.WMI_STRAY_THREAD_FIXED`` after
    3a392cdb87 had moved that import into function scope; the file after
    imports it from sqlite_runtime.  With the tree's conftest creations in
    force, as a real scan would have them."""
    before = _git_show(f"{_READ_FIX}~1:{_READ_TEST}")
    after = _git_show(f"{_READ_FIX}:{_READ_TEST}")
    if before is None or after is None:
        pytest.skip(f"{_READ_FIX} is not in this clone's history")
    repo = cps.Repo(REPO_ROOT)
    created = cps.conftest_created(REPO_ROOT)

    stats = cps.Stats()
    stale = cps.check_file(repo, _READ_TEST, before.encode("utf-8"), stats, created=created)
    assert [(f.form, f.target) for f in stale] == [("read", "compat.WMI_STRAY_THREAD_FIXED")]
    assert "hermes_cli._subprocess_compat binds no `WMI_STRAY_THREAD_FIXED`" in stale[0].reason

    stats = cps.Stats()
    assert cps.check_file(repo, _READ_TEST, after.encode("utf-8"), stats, created=created) == []
    assert stats.verified >= 1
