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
        _RESOLVERS = {"HERMES_HOME": str, **{k: str for k in ("A", "B")}}


        def __getattr__(name):
            resolver = _RESOLVERS.get(name)
            if resolver is not None:
                return resolver()
            raise AttributeError(name)
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
    _write(repo, "pkg/registrar.py", "def register(mod):\n    mod.published = 1\n")
    _write(repo, "ns/sub/adapter.py", "def send():\n    pass\n")
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
