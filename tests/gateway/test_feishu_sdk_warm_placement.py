"""``tests/gateway/conftest.py`` must never load the Feishu SDK.

``lark_oapi``'s import costs far more than the repo's default ``--timeout``.
conftest is imported once per pytest process and the per-file runner starts one
process per test file, so an SDK load placed here is paid by all ~200 gateway
test files rather than the handful that need it — and, inside a fixture,
pytest-timeout bills it to whichever test requests that fixture, so the whole
directory errors with "Timeout ... at setup" naming tests unrelated to feishu.
That is exactly what upstream f84e3687d8 (2026-08-03) did, and what this file
exists to stop coming back.

The sanctioned placement is a MODULE-level
``tests.gateway._feishu_sdk_warm.bind_feishu_sdk_globals()`` call in the feishu
test files that need the adapter globals: collection is not covered by the
per-test timeout, and only those files pay.

These checks are pure AST over the conftest source — nothing here imports the
SDK.
"""

import ast
import textwrap
from pathlib import Path

import pytest

_CONFTEST = Path(__file__).with_name("conftest.py")

# Names whose *call* pulls the SDK in, and modules whose *import* does.
_SDK_CALLS = {"_load_lark_oapi", "bind_feishu_sdk_globals", "warm_feishu_sdk"}
_SDK_MODULES = {"lark_oapi"}


def _is_sdk_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] in _SDK_MODULES for a in node.names)
    if isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        return root in _SDK_MODULES
    return False


def _is_sdk_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return name in _SDK_CALLS


def _loads_sdk(node: ast.AST) -> bool:
    return any(
        _is_sdk_import(child) or _is_sdk_call(child) for child in ast.walk(node)
    )


def _is_fixture(node: ast.AST) -> bool:
    """True for a def decorated with anything spelled ``...fixture...``."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = (
            target.attr
            if isinstance(target, ast.Attribute)
            else getattr(target, "id", "")
        )
        if "fixture" in name:
            return True
    return False


def sdk_loading_fixtures(source: str) -> list[str]:
    """Names of fixtures in ``source`` that load the Feishu SDK."""
    tree = ast.parse(source)
    return [
        node.name
        for node in ast.walk(tree)
        if _is_fixture(node) and _loads_sdk(node)
    ]


def module_level_sdk_loads(source: str) -> list[int]:
    """Line numbers of top-level statements in ``source`` that load the SDK."""
    tree = ast.parse(source)
    hits = []
    for stmt in tree.body:
        if _is_fixture(stmt) or isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue  # a plain def/class only loads when something calls it
        if _loads_sdk(stmt):
            hits.append(stmt.lineno)
    return hits


def test_conftest_has_no_sdk_loading_fixture():
    offenders = sdk_loading_fixtures(_CONFTEST.read_text(encoding="utf-8"))
    assert offenders == [], (
        f"{_CONFTEST.name} fixtures load the Feishu SDK: {offenders}. "
        "Move the load to a module-level bind_feishu_sdk_globals() call in the "
        "feishu test files that need it — see this module's docstring."
    )


def test_conftest_has_no_module_level_sdk_load():
    offenders = module_level_sdk_loads(_CONFTEST.read_text(encoding="utf-8"))
    assert offenders == [], (
        f"{_CONFTEST.name} loads the Feishu SDK at module level on line(s) "
        f"{offenders}; every gateway test file would pay that import."
    )


# --- detector arming -------------------------------------------------------
# Without these, a detector broken into returning [] leaves both checks above
# green on a conftest that does load the SDK.

# The exact shape upstream f84e3687d8 introduced.
_F84E3687D8_SHAPE = textwrap.dedent(
    '''
    import pytest


    @pytest.fixture(scope="session", autouse=True)
    def _bind_lark_sdk_globals_when_installed():
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
            yield
            return
        try:
            from plugins.platforms.feishu.adapter import _load_lark_oapi

            _load_lark_oapi()
        except Exception:
            pass
        yield
    '''
)


@pytest.mark.parametrize(
    "source, expected",
    [
        pytest.param(_F84E3687D8_SHAPE, ["_bind_lark_sdk_globals_when_installed"],
                     id="f84e3687d8-shape"),
        pytest.param(
            "import pytest\n\n\n@pytest.fixture\ndef f():\n    import lark_oapi\n",
            ["f"],
            id="bare-import-in-fixture",
        ),
        pytest.param(
            "import pytest\n\n\n@pytest.fixture\ndef f():\n"
            "    from tests.gateway._feishu_sdk_warm import warm_feishu_sdk\n"
            "    warm_feishu_sdk()\n",
            ["f"],
            id="warm-call-in-fixture",
        ),
        pytest.param(
            "import pytest\n\n\n@pytest.fixture\ndef f():\n    return 1\n",
            [],
            id="clean-fixture",
        ),
        pytest.param(
            "def helper():\n    import lark_oapi\n",
            [],
            id="plain-function-is-not-a-fixture",
        ),
    ],
)
def test_fixture_detector_fires(source, expected):
    assert sdk_loading_fixtures(source) == expected


@pytest.mark.parametrize(
    "source, expected_lines",
    [
        pytest.param("import lark_oapi\n", [1], id="top-level-import"),
        pytest.param("from lark_oapi.api.im.v1 import X\n", [1], id="top-level-from"),
        pytest.param(
            "from tests.gateway._feishu_sdk_warm import bind_feishu_sdk_globals\n"
            "bind_feishu_sdk_globals()\n",
            [2],
            id="top-level-bind-call",
        ),
        pytest.param("import sys\n", [], id="clean-import"),
        pytest.param(
            "def helper():\n    import lark_oapi\n", [], id="deferred-inside-def"
        ),
    ],
)
def test_module_level_detector_fires(source, expected_lines):
    assert module_level_sdk_loads(source) == expected_lines
