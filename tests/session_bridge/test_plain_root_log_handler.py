from __future__ import annotations

import inspect
import io
import logging
from collections.abc import Iterator

import pytest

from session_bridge import cli


@pytest.fixture(autouse=True)
def _restore_root_logging() -> Iterator[None]:
    """Save and restore the root logger. These tests install and remove
    handlers on the GLOBAL tree, which outlives the test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _bare_root() -> logging.Logger:
    root = logging.getLogger()
    root.handlers[:] = []
    root.setLevel(logging.WARNING)
    return root


def test_installs_a_plain_stream_handler() -> None:
    root = _bare_root()
    cli._install_plain_root_log_handler()
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert type(handler) is logging.StreamHandler
    assert "rich" not in type(handler).__module__


def test_sets_the_root_level_to_info() -> None:
    """basicConfig would have set this. Its no-op skips the LEVEL too, so
    forgetting it would silently drop every INFO record the service emits."""
    root = _bare_root()
    cli._install_plain_root_log_handler()
    assert root.level == logging.INFO
    assert root.isEnabledFor(logging.INFO)


def test_fastmcp_basicconfig_cannot_replace_it() -> None:
    """The load-bearing assumption, asserted rather than trusted.

    FastMCP's configure_logging calls logging.basicConfig(handlers=[RichHandler])
    without force=. basicConfig is documented to do nothing when root already
    has handlers. If that ever changes, this fix silently stops working and the
    rich handler comes back -- so pin it here rather than in a comment.
    """
    root = _bare_root()
    cli._install_plain_root_log_handler()
    ours = root.handlers[0]

    # the shape fastmcp uses
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(io.StringIO())],
    )

    assert root.handlers == [ours], "basicConfig replaced our handler"


def test_does_not_stack_a_second_handler() -> None:
    """Called twice, or after something else configured logging, it must not
    double every line."""
    root = _bare_root()
    cli._install_plain_root_log_handler()
    cli._install_plain_root_log_handler()
    assert len(root.handlers) == 1


def test_defers_to_an_existing_configuration() -> None:
    root = _bare_root()
    pre_existing = logging.StreamHandler(io.StringIO())
    root.addHandler(pre_existing)

    cli._install_plain_root_log_handler()

    assert root.handlers == [pre_existing]


def test_records_still_carry_level_name_and_message() -> None:
    """Formatting changes; information does not."""
    root = _bare_root()
    cli._install_plain_root_log_handler()
    sink = io.StringIO()
    root.handlers[0].stream = sink  # type: ignore[attr-defined]

    logging.getLogger("some.library").info("a thing happened")

    written = sink.getvalue()
    assert "INFO" in written
    assert "some.library" in written
    assert "a thing happened" in written


def _serve_source_lines() -> list[str]:
    source = inspect.getsource(cli.ProductionBackend.serve)
    # Comments mention create_app() by name; a substring search over the raw
    # source finds the COMMENT before the call and reports the wrong order.
    # This bit the author's own manual check for exactly this fix.
    return [
        line.strip()
        for line in source.splitlines()
        if not line.strip().startswith("#")
    ]


def test_serve_installs_the_handler_before_building_the_app() -> None:
    """ORDERING IS THE WHOLE MECHANISM.

    The handler only pre-empts rich if it is installed before FastMCP is
    constructed, which happens inside create_app(). Called afterwards this
    function returns early -- root already has rich's handler -- and the fix
    becomes a silent no-op that every other test in this file still passes.
    """
    lines = _serve_source_lines()
    install = next(
        i for i, l in enumerate(lines) if "_install_plain_root_log_handler()" in l
    )
    create = next(i for i, l in enumerate(lines) if "create_app(" in l)
    assert install < create, (
        f"_install_plain_root_log_handler() appears at line {install} of serve() "
        f"but create_app( is at {create}; installed after FastMCP it is a no-op"
    )


def test_serve_still_quiets_the_noisy_loggers() -> None:
    """Guards the reorder: the earlier fix's call had to move, and moving a
    call is exactly when it gets dropped."""
    assert any(
        "_quiet_noisy_third_party_loggers()" in l for l in _serve_source_lines()
    )
