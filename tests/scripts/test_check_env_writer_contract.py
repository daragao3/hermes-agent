"""Verify the .env read-modify-write encoding contract across the repo.

Pytest wrapper for ``scripts/check_env_writer_contract.py`` plus unit tests of
its discovery rules.  The contract itself (BOM tolerance, surrogateescape on
both sides, newline="\\n" on the write) is exercised behaviourally per writer
in tests/plugins/memory/test_{openviking_provider,mem0_setup,hindsight_setup_env}.py,
tests/hermes_cli/test_config_env_writer_contract.py,
tests/control_center/test_apply_env_writer_contract.py and
tests/skills/test_telephony_env_writer_contract.py.  This file pins that NEW
writers cannot arrive carrying two of the three, which is how the Hindsight
and Mem0 writers spent 2026-09-18/19.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.timeout_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_env_writer_contract.py"

# Same ordering rule as the other repo-scan wrappers: the subprocess bound must
# fire before pyproject's 30 s thread watchdog, so a slow scan names itself
# instead of surfacing as a bare pytest-timeout.  ~20-35 s on an idle box;
# 198 s measured under the runner at -j 12, which is what the first version of
# this test (relying on the global 30 s cap) failed on.  Both stay under the
# 1800 s per-file cap once the runner's x4 scale is applied.
_SCAN_TIMEOUT_S = scaled(300)
_TEST_TIMEOUT_S = scaled(360)


def _load_guard():
    spec = importlib.util.spec_from_file_location("_env_writer_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _kinds(source: str) -> list[tuple[str, str, int]]:
    """(kind, function, line) for each CHECKED site in ``source``."""
    checked, _ = _load_guard().scan_source(source, "x.py")
    return sorted((s.kind, s.func, s.lineno) for s in checked)


def _violations(source: str) -> list[tuple[str, str]]:
    """(function, failing keyword) for each contract failure in ``source``."""
    checked, _ = _load_guard().scan_source(source, "x.py")
    return sorted((s.func, kw) for s in checked for kw, _actual, _req in s.violations())


# --------------------------------------------------------------------------
# The wiring: the real tree must satisfy the contract.
# --------------------------------------------------------------------------

@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_repo_env_writers_carry_all_three_properties():
    """Every discovered .env read-modify-write passes, and every pinned writer
    is still discovered (the scan's own rot tripwire).

    A full scan is ~20-35 s: git grep narrows the tree, then ~480 files parse.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, timeout=_SCAN_TIMEOUT_S, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f".env writer contract check failed:\n{result.stdout}\n{result.stderr}"
    )


# --------------------------------------------------------------------------
# Each property is detected independently -- the whole point is catching a
# writer that carries TWO of the three.
# --------------------------------------------------------------------------

_RMW = '''
def _write_env(env_path, updates):
    existing = env_path.read_text({read_kw}).splitlines()
    env_path.write_text("\\n".join(existing), {write_kw})
'''

_FULL_READ = 'encoding="utf-8-sig", errors="surrogateescape"'
_FULL_WRITE = 'encoding="utf-8", errors="surrogateescape", newline="\\n"'


def test_a_compliant_writer_is_clean():
    assert _violations(_RMW.format(read_kw=_FULL_READ, write_kw=_FULL_WRITE)) == []


def test_missing_surrogateescape_on_the_write_is_caught():
    """The Hindsight/Mem0 shape on 2026-09-18: BOM + newline, no surrogateescape."""
    src = _RMW.format(read_kw='encoding="utf-8-sig"', write_kw='encoding="utf-8", newline="\\n"')
    assert ("_write_env", "errors") in _violations(src)


def test_missing_bom_tolerance_on_the_read_is_caught():
    src = _RMW.format(read_kw='encoding="utf-8", errors="surrogateescape"', write_kw=_FULL_WRITE)
    assert ("_write_env", "encoding") in _violations(src)


def test_missing_newline_on_the_write_is_caught():
    src = _RMW.format(read_kw=_FULL_READ, write_kw='encoding="utf-8", errors="surrogateescape"')
    assert ("_write_env", "newline") in _violations(src)


def test_errors_replace_is_not_accepted_for_surrogateescape():
    """``errors="replace"`` does not raise, so it looks safe; it still turns an
    undecodable byte into U+FFFD and writes the replacement back.  This was
    hermes_cli/config.py's shape until 2026-09-20."""
    src = _RMW.format(read_kw='encoding="utf-8-sig", errors="replace"', write_kw=_FULL_WRITE)
    assert ("_write_env", "errors") in _violations(src)


# --------------------------------------------------------------------------
# Scope: what is and is not a read-modify-write.
# --------------------------------------------------------------------------

def test_read_only_precheck_is_not_reported():
    """hermes_cli/profile_cmd.py::_env_file_has_key and friends: nothing they
    read is written back, so nothing they read can be corrupted."""
    src = '''
def _env_file_has_key(env_path, key):
    return any(l.startswith(key) for l in env_path.read_text(encoding="utf-8").splitlines())
'''
    assert _kinds(src) == []


def test_create_only_write_is_not_reported():
    """hermes_cli/profiles.py::backfill_profile_envs seeds a placeholder into a
    profile that has none: no pre-existing bytes, so nothing to round-trip."""
    src = '''
def backfill_profile_envs(entry):
    env_path = entry / ".env"
    if env_path.exists():
        return
    env_path.write_text(_PLACEHOLDER_ENV, encoding="utf-8", newline="\\n")
'''
    assert _kinds(src) == []


def test_split_writer_is_paired_through_a_shared_target():
    """hermes_cli/config.py's shape: the read and write halves live in separate
    helpers, paired by one caller handing both the SAME target."""
    src = '''
def _read_env_lines(env_path):
    with open(env_path, encoding="utf-8-sig", errors="replace") as f:
        return f.readlines()

def _write_env_lines(env_path, lines):
    with open(env_path, "w", encoding="utf-8", newline="\\n") as f:
        f.writelines(lines)

def save_env_value(key, value):
    env_path = get_env_path()
    lines = _read_env_lines(env_path)
    _write_env_lines(env_path, lines)
'''
    funcs = {func for _kind, func, _line in _kinds(src)}
    assert funcs == {"_read_env_lines", "_write_env_lines"}
    assert ("_read_env_lines", "errors") in _violations(src)
    assert ("_write_env_lines", "errors") in _violations(src)


def test_own_inline_read_pairs_with_a_helper_write():
    """hermes_cli/config.py::sanitize_env_file opens .env INLINE and writes it
    back through _write_env_lines(env_path, ...).  Matching only
    helper-call/helper-call classed that read as an unpaired pre-check and let
    its errors="replace" through -- the scan going GREEN on a site it exists to
    catch."""
    src = '''
def _write_env_lines(env_path, lines):
    with open(env_path, "w", encoding="utf-8", errors="surrogateescape", newline="\\n") as f:
        f.writelines(lines)

def sanitize_env_file(env_path):
    with open(env_path, encoding="utf-8-sig", errors="replace") as f:
        original = f.readlines()
    _write_env_lines(env_path, original)
'''
    assert "sanitize_env_file" in {func for _k, func, _l in _kinds(src)}
    assert ("sanitize_env_file", "errors") in _violations(src)


def test_unrelated_read_and_write_in_one_caller_do_not_pair():
    """mem0's wizard calls both _prompt_api_key(...) and _write_env(env_path,...).
    They share no target, so the prompt's read must stay an unpaired pre-check --
    pairing on 'same caller' alone would drag it in."""
    src = '''
def _prompt_api_key(label, env_var, hermes_home):
    env_path = Path(hermes_home) / ".env"
    return env_path.read_text(encoding="utf-8-sig", errors="replace")

def _write_env(env_path, updates):
    existing = env_path.read_text(encoding="utf-8-sig", errors="surrogateescape").splitlines()
    env_path.write_text("\\n".join(existing), encoding="utf-8",
                        errors="surrogateescape", newline="\\n")

def run_wizard(hermes_home):
    key = _prompt_api_key("Mem0", "MEM0_API_KEY", hermes_home)
    _write_env(Path(hermes_home) / ".env", {"MEM0_API_KEY": key})
'''
    assert "_prompt_api_key" not in {func for _k, func, _l in _kinds(src)}
    assert _violations(src) == []


def test_noqa_marker_exempts_a_site():
    src = _RMW.format(read_kw=_FULL_READ, write_kw='encoding="utf-8"')
    assert _violations(src) != []
    marked = src.replace(
        'env_path.write_text("\\n".join(existing), encoding="utf-8")',
        'env_path.write_text("\\n".join(existing), encoding="utf-8")  # noqa: env-writer-contract',
    )
    assert _violations(marked) == []


# --------------------------------------------------------------------------
# False positives that the first run of this scan actually produced.
# --------------------------------------------------------------------------

def test_an_environment_mapping_is_not_an_env_file():
    """``Path(env["HERMES_HOME"]) / "config.yaml"`` binds through a dict NAMED
    env.  Treating an env MAPPING as an env FILE flagged
    evals/desktop_bug_campaign/linux_launcher_probe.py writing config.yaml."""
    src = '''
def main(env):
    config = Path(env["HERMES_HOME"]) / "config.yaml"
    old = config.read_text(encoding="utf-8")
    config.write_text(old + "desktop:\\n", encoding="utf-8")
'''
    assert _kinds(src) == []


def test_a_local_env_binding_does_not_leak_across_functions():
    """openclaw_to_hermes.py binds ``destination = self.target_root / ".env"``
    inside ONE method.  A module binding table built by walking the whole tree
    put that on every other method's ``destination`` parameter and flagged a
    generic file copier."""
    src = '''
def merge_env_values(self):
    destination = self.target_root / ".env"
    return destination.read_text(encoding="utf-8-sig", errors="surrogateescape")

def copy_file(self, source, destination, transform):
    content = transform(source.read_text(encoding="utf-8"))
    destination.write_text(content, encoding="utf-8")
'''
    assert "copy_file" not in {func for _k, func, _l in _kinds(src)}


def test_module_scope_env_constant_is_still_resolved():
    """The leak fix must not cost the real case: control_center/apply.py binds
    ``HERMES_ENV = HERMES / ".env"`` at MODULE scope and writes it from a
    function."""
    src = '''
HERMES_ENV = HERMES / ".env"

def _apply_threshold_adjust(proposal):
    raw = HERMES_ENV.read_text(encoding="utf-8")
    HERMES_ENV.write_text(raw + "X=1\\n", encoding="utf-8")
'''
    funcs = {func for _k, func, _l in _kinds(src)}
    assert funcs == {"_apply_threshold_adjust"}


def test_tests_tree_is_out_of_scope():
    guard = _load_guard()
    assert "tests/" in guard.SKIP_PREFIXES


def test_known_writers_are_all_real_paths():
    """The rot tripwire is only meaningful if every pinned path exists."""
    guard = _load_guard()
    for pinned in guard.KNOWN_WRITERS:
        rel, _, func = pinned.partition("::")
        path = REPO_ROOT / rel
        assert path.is_file(), f"{pinned}: {rel} does not exist"
        assert f"def {func}(" in path.read_text(encoding="utf-8", errors="surrogateescape"), (
            f"{pinned}: {func} is not defined in {rel}"
        )
