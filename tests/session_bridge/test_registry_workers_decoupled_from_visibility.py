"""The store-convergence workers must not ride on the sidebar's switch.

Regression pins for 2026-09-07: ``claude_visibility.enabled`` was set to
``false`` to stop sidebar spam, and that silently switched off the whole
desktop-registry reconciliation leg -- ``cliSessionId`` fill and
``lastActivityAt``/``completedTurns`` convergence alike -- for hours, while
``reconcile_desktop_registries`` still read ``true``.  Neither worker produces
a sidebar mirror, so neither belongs behind that flag.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from session_bridge.cli import (
    should_run_desktop_registry_sync,
    should_run_idle_chip_archiver,
)
from session_bridge.config import BridgeConfig, ClaudeVisibilityConfig


def _config(**visibility) -> BridgeConfig:
    return BridgeConfig(
        claude_visibility=dataclasses.replace(
            ClaudeVisibilityConfig(), **visibility
        )
    )


ROOTS = (Path("root-a"), Path("root-b"))


# --------------------------------------------------------------- registry sync

def test_registry_sync_runs_while_visibility_is_disabled() -> None:
    """The exact live regression: the sidebar off, convergence still on."""
    config = _config(enabled=False, reconcile_desktop_registries=True)
    assert should_run_desktop_registry_sync(
        config, catalog_only=False, roots=ROOTS
    )


def test_registry_sync_honours_its_own_switch() -> None:
    """The control: turning it off by its OWN key must still stop it.

    Without this the test above would pass on a predicate that returns True
    unconditionally, which is the shape of a guard that cannot fail.
    """
    config = _config(enabled=True, reconcile_desktop_registries=False)
    assert not should_run_desktop_registry_sync(
        config, catalog_only=False, roots=ROOTS
    )


def test_registry_sync_does_not_run_without_roots() -> None:
    config = _config(enabled=False, reconcile_desktop_registries=True)
    assert not should_run_desktop_registry_sync(
        config, catalog_only=False, roots=()
    )


def test_registry_sync_does_not_run_in_catalog_only_mode() -> None:
    config = _config(enabled=True, reconcile_desktop_registries=True)
    assert not should_run_desktop_registry_sync(
        config, catalog_only=True, roots=ROOTS
    )


def test_registry_sync_is_indifferent_to_the_visibility_flag() -> None:
    """Both values of ``enabled`` give the same answer -- that is the fix."""
    on = _config(enabled=True, reconcile_desktop_registries=True)
    off = _config(enabled=False, reconcile_desktop_registries=True)
    assert should_run_desktop_registry_sync(
        on, catalog_only=False, roots=ROOTS
    ) == should_run_desktop_registry_sync(off, catalog_only=False, roots=ROOTS)


# ---------------------------------------------------------- idle chip archiver

def test_idle_chip_archiver_runs_while_visibility_is_disabled() -> None:
    """Turning visibility off to reduce sidebar clutter must not stop the
    worker whose whole job is reducing sidebar clutter."""
    config = _config(enabled=False, archive_idle_chips=True)
    assert should_run_idle_chip_archiver(config, catalog_only=False)


def test_idle_chip_archiver_honours_its_own_switch() -> None:
    config = _config(enabled=True, archive_idle_chips=False)
    assert not should_run_idle_chip_archiver(config, catalog_only=False)


def test_idle_chip_archiver_does_not_run_in_catalog_only_mode() -> None:
    config = _config(enabled=True, archive_idle_chips=True)
    assert not should_run_idle_chip_archiver(config, catalog_only=True)


def test_idle_chip_archiver_is_indifferent_to_the_visibility_flag() -> None:
    on = _config(enabled=True, archive_idle_chips=True)
    off = _config(enabled=False, archive_idle_chips=True)
    assert should_run_idle_chip_archiver(
        on, catalog_only=False
    ) == should_run_idle_chip_archiver(off, catalog_only=False)
