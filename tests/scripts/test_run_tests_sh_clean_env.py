"""``scripts/run_tests.sh`` must not drop the Windows OS path vars.

The wrapper does ``cd "$REPO_ROOT"`` and then

    exec env -i "${CLEAN_ENV[@]}" "$PYTHON" "$SCRIPT_DIR/run_tests_parallel.py"

``env -i`` starts from an *empty* environment, so ``CLEAN_ENV`` is an
allowlist: anything not named there is gone for the runner and — because
``run_tests_parallel.py`` hands workers ``env=os.environ`` — for every
pytest worker it spawns as well.

When ``SYSTEMDRIVE`` is missing, a Windows child cannot expand the
``REG_EXPAND_SZ`` known-folder template ``%SystemDrive%\\ProgramData`` held
in ``HKLM\\...\\ProfileList``.  The literal string is then used as a
*relative* path and the known-folder cache is built under the process CWD
— which the ``cd "$REPO_ROOT"`` above pinned to the checkout root.  The
result is a stray ``%SystemDrive%/ProgramData/Microsoft/Windows/Caches/``
tree in the repo.

Observed on 2026-08-16 18:29:34 in the shared checkout and reproduced
directly: the same ``env -i`` allowlist plus the MSIX/WindowsApps python
writes the tree; adding ``SYSTEMDRIVE=C:`` and nothing else makes it stop.

This is the wrapper-side twin of
``tests/secret_sources/test_child_env_windows_essentials.py``, which
guards the same failure mode in the secret-helper allowlists.  The test is
a static read of the script so it passes on POSIX too — what is under
test is the allowlist, not the host OS.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_tests.sh"

# Absence of these is what produces the literal-%SystemDrive% tree.
_REQUIRED = ("SYSTEMDRIVE", "PROGRAMDATA")


def _clean_env_names() -> set[str]:
    """Names the script forwards through ``env -i``.

    The script forwards a name two ways, and both count:

    * literally, in the ``CLEAN_ENV=( ... )`` block or a ``CLEAN_ENV+=( ... )``
      append (``"PATH=$PATH"``, ``"USERPROFILE=$USERPROFILE"``);
    * indirectly, via a ``for _var in A B C; do ... CLEAN_ENV+=("$_var=$_val")``
      loop, where the names live in the loop header.

    A ``"$_var=..."`` entry is deliberately NOT counted as the literal name
    ``_var`` — the real names come from the loop header instead.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    names: set[str] = set()
    for block in re.findall(r"CLEAN_ENV\+?=\(\s*(.*?)\)", text, re.DOTALL):
        # (?<![$\w]) keeps `"$_var=..."` and `FOO_BAR=` tails out of the set.
        names.update(re.findall(r'(?<![$\w])([A-Za-z_][A-Za-z0-9_]*)=', block))
    for header, body in re.findall(r"for _var in\s+(.*?);?\s*do(.*?)done", text, re.DOTALL):
        if "CLEAN_ENV+=" in body:
            names.update(re.findall(r"\b([A-Z][A-Z0-9_]*)\b", header))
    return names


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_runner_is_launched_through_env_i() -> None:
    """Guard the premise: if ``env -i`` goes away, this test's subject does too."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'env -i "${CLEAN_ENV[@]}"' in text, (
        "run_tests.sh no longer launches the runner via `env -i \"${CLEAN_ENV[@]}\"`; "
        "re-derive what the child environment is before trusting this file's guarantees"
    )


@pytest.mark.parametrize("var", _REQUIRED)
def test_clean_env_forwards_windows_os_path_var(var: str) -> None:
    """Each var must be named in CLEAN_ENV, else the child can't expand the template."""
    names = _clean_env_names()
    assert var in names, (
        f"{var} is not forwarded through `env -i` in scripts/run_tests.sh. "
        f"Without it a Windows child writes a literal %SystemDrive% tree into "
        f"$REPO_ROOT. Forwarded names: {sorted(names)}"
    )


def test_clean_env_forwards_programfiles_for_docker_cli_plugins() -> None:
    """The Docker CLI finds buildx under %ProgramFiles%\Docker\cli-plugins. Without
    PROGRAMFILES it silently uses the legacy builder, and every ``COPY --chmod`` in
    the Dockerfile fails with "requires BuildKit" -- tests/docker's built_image
    fixture errored at both pins of the 2026-09-17 acceptance ceremonies this way."""
    names = _clean_env_names()
    assert "PROGRAMFILES" in names, (
        f"PROGRAMFILES is not forwarded through `env -i`; docker build under the runner "
        f"cannot find the buildx plugin. Forwarded names: {sorted(names)}"
    )


def test_clean_env_parse_found_the_block() -> None:
    """Falsifier for the parser: a regex that matches nothing would pass vacuously."""
    names = _clean_env_names()
    assert {"PATH", "HOME", "PYTHONUTF8"} <= names, (
        f"CLEAN_ENV parsing looks broken — expected the known baseline vars, got {sorted(names)}"
    )


def _timeout_scale_arms() -> "list[tuple[str, str]]":
    """The (guard, value) arms that decide HERMES_TEST_TIMEOUT_SCALE, in order.

    Parsed rather than pattern-matched as a whole so the ORDER is assertable:
    the explicit-value arm has to come first or a caller's
    HERMES_TEST_TIMEOUT_SCALE=1 would lose to the default.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    arms: "list[tuple[str, str]]" = []
    for guard, value in re.findall(
        r"(?:if|elif) (\[[^\n]*\]); then\n\s*CLEAN_ENV\+=\(\"HERMES_TEST_TIMEOUT_SCALE=([^\"]+)\"\)",
        text,
    ):
        arms.append((guard, value))
    return arms


def test_runner_defaults_the_timeout_scale_for_a_loaded_host() -> None:
    """Diego 2026-09-19: the runner sets HERMES_TEST_TIMEOUT_SCALE=4.

    Without it every ``scaled()`` bound written INSIDE a test is inert on this
    host (the module's own default is 1.0), so a safety net sized for an idle
    box trips under -j 12 and reads as a regression.
    """
    assert "HERMES_TEST_TIMEOUT_SCALE" in _clean_env_names(), (
        "the runner no longer forwards HERMES_TEST_TIMEOUT_SCALE, so every "
        "tests/timeout_budget rule-2 bound is back to its unscaled literal"
    )
    arms = _timeout_scale_arms()
    assert [value for _guard, value in arms] == ["$HERMES_TEST_TIMEOUT_SCALE", "4"], (
        f"expected an explicit-value arm then a default of 4, got {arms}"
    )


def test_timeout_scale_default_is_skipped_under_ci() -> None:
    """CI must keep the module default: timeout_budget.py promises that.

    Quadrupling every safety net on a CI runner would slow the kill of a
    genuinely wedged child without the load that justifies it here.
    """
    arms = _timeout_scale_arms()
    assert len(arms) == 2, f"expected two arms, got {arms}"
    default_guard = arms[1][0]
    assert "CI" in default_guard and "-z" in default_guard, (
        f"the default arm is no longer gated on CI being unset: {default_guard!r}"
    )


def test_timeout_scale_arm_parse_found_the_block() -> None:
    """Falsifier for the parser above: matching nothing would pass vacuously."""
    assert _timeout_scale_arms(), (
        "could not locate the HERMES_TEST_TIMEOUT_SCALE arms in run_tests.sh -- "
        "re-derive what the runner sets before trusting the two tests above"
    )
