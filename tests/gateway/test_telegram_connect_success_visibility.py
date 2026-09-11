"""Healthy first connect is INFO, retries warn, and success remains visible.

Combines local quiet boot progress with upstream terminal-visible completion.
"""

import ast
from pathlib import Path

ADAPTER = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "platforms"
    / "telegram"
    / "adapter.py"
)


def _logger_call_level(tree: ast.AST, needle: str) -> str:
    """Return the logger method name for the log call whose format string
    contains *needle*."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
            and node.args
        ):
            first = node.args[1] if node.func.attr == "log" else node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and needle in first.value
            ):
                return ast.unparse(node.args[0]) if node.func.attr == "log" else node.func.attr
    raise AssertionError(f"no logger call containing {needle!r} found")


def test_connect_success_line_matches_attempt_line_visibility():
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    attempt_level = _logger_call_level(tree, "Connecting to Telegram (attempt")
    success_level = _logger_call_level(tree, "Connected to Telegram")

    # Quiet initial progress preserves the local boot-noise fix; retries warn.
    assert attempt_level == "logging.INFO if _attempt == 0 else logging.WARNING"
    # Successful connection stays visible even after a warning-level retry.
    assert success_level == "warning"
