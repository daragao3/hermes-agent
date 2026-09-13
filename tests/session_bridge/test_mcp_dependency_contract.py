"""The MCP SDK in the running interpreter must satisfy the pyproject pin.

Regression pins for 2026-09-13.  ``session_bridge/mcp_server.py`` wraps its SDK
imports in ``except ImportError`` and re-raises ``RuntimeError("session bridge
MCP dependencies are not installed")``.  That message names no version, no
import and no interpreter, so a wrong-SDK environment does not report itself --
it reports 40+ identical anonymous failures, one per test that builds the app.

Measured cost: on this box ``python -m pytest`` resolves to the Windows Store
CPython 3.11 whose USER site-packages carries mcp 1.26.0 (directory mtime
2026-05-29), while pyproject and uv.lock both pin mcp==2.2.0 and commit
d11a98e28e moved the code to the 2.x API.  1.26.0 exports ``Server`` /
``FastMCP`` and has no ``MCPServer``, so every MCP test in
``tests/session_bridge/test_end_to_end.py`` raised that RuntimeError.  The
pinned environment (``agent-src/.venv``) was correct the whole time and nothing
needed installing; only the interpreter was wrong.

The failure was doubly silent because the same suite was ALSO broken in the
correct environment, for the opposite reason: ``test_end_to_end.py`` imported
``mcp.shared.version``, a 1.x path deleted in 2.x.  So the wrong interpreter
failed at run time with the RuntimeError wall and the right interpreter failed
at COLLECTION with ``Interrupted: 4 errors``, zero tests run -- neither arm ever
named the SDK as the cause.  Directory collection went 4128 collected + 4
errors (interrupted) -> 4251 collected + 0 errors once the import was
corrected; the other three modules (``test_coordinator_hardening``,
``test_coordinator_safety``, ``test_fault_injection``) inherited it by importing
the harness out of ``test_end_to_end``.

This guard asserts the CONTRACT, never the Python version.  CI syncs
``--python 3.11`` (.github/workflows/tests.yml:83, 182; tests-os.yml:95) to
match ``.python-version``, while the local ``.venv`` is 3.12.13, so a guard
keyed on the interpreter version would fire on one of the two legitimately.  A
version assertion would also go stale on the next SDK bump; the pin in
pyproject is the single source of truth and is read from disk here rather than
duplicated.

Deliberately NOT ``importorskip``: a guard that skips when the dependency is
wrong reports green in exactly the situation it exists to catch, and the four
modules above spent that state looking like an unrelated collection error.
A missing or unparseable pin is a FAILURE here for the same reason -- a guard
that quietly cannot find its own source of truth is worse than no guard.

Record: loops agent-src-pytest-interpreter-mcp-pin-20260913; MemPalace
session-bridge/pytest-interpreter-and-mcp-pin-2026-09-13.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# (module, attribute, who imports it) -- the two import paths this repo's MCP
# surface actually depends on.  The first is production code, the second is the
# test harness; they broke independently, which is why both are pinned.
_REQUIRED_IMPORTS = (
    ("mcp.server", "MCPServer", "session_bridge/mcp_server.py"),
    ("mcp.types", "LATEST_PROTOCOL_VERSION", "tests/session_bridge/test_end_to_end.py"),
)


def _pinned_mcp_version() -> str:
    """The pinned mcp version from the ``mcp`` extra, read from disk.

    Raises rather than returning a sentinel: see the module docstring on why a
    guard that cannot find its own source of truth must fail, not pass.
    """
    if not _PYPROJECT.is_file():
        raise AssertionError(f"cannot read the mcp pin: {_PYPROJECT} does not exist")
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    extras = data.get("project", {}).get("optional-dependencies", {})
    for extra in ("mcp", "dev"):
        for spec in extras.get(extra, []):
            if spec.replace(" ", "").startswith("mcp=="):
                return spec.replace(" ", "").split("==", 1)[1]
    raise AssertionError(
        "no `mcp==<version>` pin found in the [mcp] or [dev] extras of "
        f"{_PYPROJECT}; this guard has lost its source of truth"
    )


def _where() -> str:
    """Interpreter provenance -- the fact the RuntimeError never carried."""
    try:
        installed = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        installed = "NOT INSTALLED"
    return (
        f"\n  interpreter: {sys.executable}"
        f"\n  python:      {sys.version.split()[0]}"
        f"\n  mcp:         {installed}"
        f"\n  pin:         {_pinned_mcp_version()} (from {_PYPROJECT})"
        "\n  remedy:      run tests through the project environment, e.g."
        "\n               agent-src/.venv/Scripts/python.exe -m pytest ..."
        "\n               or `uv run --no-sync python -m pytest ...`"
    )


def test_pyproject_still_pins_the_mcp_sdk() -> None:
    """The pin this guard reads must exist and be exact.

    Pinned separately so that losing the pin is reported as losing the pin,
    rather than as a mismatch against an empty string.
    """
    pinned = _pinned_mcp_version()
    assert pinned, "the mcp extra must pin an exact version"
    assert pinned[0].isdigit(), f"expected an exact version, got {pinned!r}"


def test_installed_mcp_matches_the_pin() -> None:
    """A wrong-SDK interpreter must say so once, naming itself."""
    pinned = _pinned_mcp_version()
    try:
        installed = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - env fault
        pytest.fail(
            "the `mcp` distribution is not installed in this interpreter, so "
            "every session_bridge MCP test will raise RuntimeError('session "
            f"bridge MCP dependencies are not installed').{_where()}"
        )
    assert installed == pinned, (
        f"mcp {installed} is installed but pyproject pins mcp=={pinned}. "
        "The session_bridge MCP tests will fail as a wall of identical "
        "RuntimeError('session bridge MCP dependencies are not installed') "
        f"that names neither the version nor this interpreter.{_where()}"
    )


@pytest.mark.parametrize(("module", "attribute", "importer"), _REQUIRED_IMPORTS)
def test_required_mcp_import_paths_resolve(module: str, attribute: str, importer: str) -> None:
    """Each SDK path this repo imports by name must exist in the installed SDK.

    Version equality is not sufficient on its own: these two paths moved
    between 1.x and 2.x, and a same-version SDK that lost one of them would
    still break the suite.  This is the assertion that would have named the
    real cause on 2026-09-13 in BOTH failing arms.
    """
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(
            f"{importer} imports `from {module} import {attribute}`, but "
            f"{module} cannot be imported: {exc!r}.{_where()}"
        )
    assert hasattr(mod, attribute), (
        f"{importer} imports `from {module} import {attribute}`, but the "
        f"installed SDK's {module} has no {attribute}. mcp 1.x exposed "
        "`Server`/`FastMCP` and `mcp.shared.version`; 2.x exposes `MCPServer` "
        f"and `mcp.types`.{_where()}"
    )
